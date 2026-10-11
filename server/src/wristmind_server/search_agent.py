"""Search orchestration, independent of providers, persistence and the UI."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import time
from typing import Any, Awaitable, Callable

from .search_documents import DocumentView
from .web_search import WebSearchResult, WebSearchUnavailable


@dataclass
class SearchOutcome:
    results: dict[str, WebSearchResult] = field(default_factory=dict)
    opened: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    inspected: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    errors: list[dict[str, str]] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)
    searches: int = 0
    steps: int = 0
    search_ms: int = 0
    open_ms: int = 0
    timed_out: bool = False
    source: Any = None


async def run_search_agent(
    *, query: str, previous: list[WebSearchResult], deep: bool,
    max_seconds: float, max_steps: int, max_searches: int, max_opens: int,
    search: Callable[[str], Awaitable[list[WebSearchResult]]],
    open_page: Callable[[WebSearchResult], Awaitable[tuple[str, str]]],
    plan: Callable[..., Awaitable[Any]],
    save: Callable[..., Awaitable[Any]],
    state: Callable[[dict], Awaitable[None]],
    required_open: Callable[..., str | None],
    force_search: bool = False,
    open_floor_seconds: float = 0.0,
    save_floor_seconds: float = 0.0,
) -> SearchOutcome:
    """Run the bounded search loop.

    ``force_search`` makes this turn issue a new query even when earlier links
    are already known. Reusing known links is the cheap default; the caller sets
    this when the user asked to search, asked for other sources, or rejected the
    material already used — in those cases planning over the old list silently
    answers a different question than the one that was asked.

    ``open_floor_seconds`` and ``save_floor_seconds`` are floors, not extra
    budgets: while the loop clock has time left they change nothing. They only
    matter once the clock is exhausted, where cancelling work that has already
    been paid for throws away a downloaded page or a completed read. Reading and
    extraction on a slow host can take longer than the whole decision loop, so
    these steps keep a guaranteed minimum of their own.
    """
    outcome = SearchOutcome()
    deadline = time.perf_counter() + max_seconds
    attempted: set[str] = set()
    evidence = None

    def add(results):
        urls = {item.url for item in outcome.results.values()}
        for item in results:
            if item.url not in urls:
                outcome.results[f"r{len(outcome.results) + 1}"] = item
                urls.add(item.url)

    async def bounded(awaitable, floor: float = 0.0):
        budget = deadline - time.perf_counter()
        if floor:
            budget = max(budget, floor)
        async with asyncio.timeout(max(0.1, budget)):
            return await awaitable

    async def search_once(value):
        outcome.searches += 1
        outcome.queries.append(value)
        await state({"state": "searching", "pass": outcome.searches})
        started = time.perf_counter()
        try:
            add(await bounded(search(value)))
        finally:
            outcome.search_ms += round((time.perf_counter() - started) * 1000)

    try:
        # The planner sees previously discovered URLs even if the old assistant
        # failed to print them. It decides whether reuse fits this request.
        add(previous if deep else [])
        # Known links stay available as candidates, but they must not replace a
        # search the user actually asked for.
        if not outcome.results or force_search:
            await search_once(query)
        if not deep:
            return outcome
        while outcome.steps < max_steps and time.perf_counter() < deadline:
            await state({"state": "reviewing_sources", "step": outcome.steps + 1})
            action = await bounded(plan(query, outcome.results, outcome.inspected, evidence))
            evidence = action
            outcome.steps += 1
            if action.action == "answer":
                forced = required_open(outcome.results, attempted, outcome.opened)
                if forced is None or len(attempted) >= max_opens:
                    break
                action = type(action)(action="open", result_id=forced)
            if action.action == "search":
                if outcome.searches >= max_searches:
                    break
                query = action.query
                await search_once(query)
                continue
            result_id = action.result_id
            if action.action in {"find", "read"}:
                if result_id not in outcome.opened:
                    continue
                title, url, text = outcome.opened[result_id]
                view = DocumentView(text)
                if action.action == "find":
                    selected = view.prompt(action.query)
                else:
                    try:
                        selected = view.read(action.start_block, action.end_block)
                    except (ValueError, TypeError):
                        continue
                    if len(selected) > 14_000:
                        continue
                outcome.inspected[result_id] = (title, url, selected)
                outcome.source = await bounded(save(outcome.results[result_id], text,
                                                    action.query if action.action == "find" else selected[:1000]),
                                               floor=save_floor_seconds)
                if outcome.source is not None:
                    break
                continue
            if result_id not in outcome.results or result_id in attempted:
                break
            if len(attempted) >= max_opens:
                break
            attempted.add(result_id)
            await state({"state": "opening_source", "page": len(attempted)})
            started = time.perf_counter()
            try:
                url, text = await bounded(
                    open_page(outcome.results[result_id]), floor=open_floor_seconds,
                )
            except WebSearchUnavailable as exc:
                outcome.errors.append({"result_id": result_id, "reason": str(exc)})
                # Hide failed candidates from the planner to avoid retry loops.
                outcome.inspected[result_id] = (outcome.results[result_id].title,
                                                outcome.results[result_id].url, f"Ошибка чтения: {exc}")
                continue
            finally:
                outcome.open_ms += round((time.perf_counter() - started) * 1000)
            if not text:
                continue
            item = replace(outcome.results[result_id], url=url)
            outcome.results[result_id] = item
            outcome.opened[result_id] = (item.title, url, text)
            outcome.inspected[result_id] = (item.title, url, DocumentView(text).prompt(query))
            outcome.source = await bounded(save(item, text), floor=save_floor_seconds)
            if outcome.source is not None:
                break
        if time.perf_counter() >= deadline:
            outcome.timed_out = True
    except TimeoutError:
        outcome.timed_out = True
    except WebSearchUnavailable as exc:
        outcome.errors.append({"result_id": "search", "reason": str(exc)})
    return outcome
