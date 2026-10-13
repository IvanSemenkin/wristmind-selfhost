"""Search orchestration, independent of providers, persistence and the UI."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
import time
import re
from typing import Any, Awaitable, Callable
from types import SimpleNamespace
from .search_ranking import (rank_results, rank_candidate, obvious_source,
                             comparison_requested, completeness_requested, document_check, specific_section_requested,
                             additional_document_task, primary_document_requested, secondary_material)

from .search_documents import DocumentView
from . import search_trace
from .resource_controller import ResourceUnavailable
from .web_search import WebSearchResult, WebSearchUnavailable


class PlannerFailure(RuntimeError):
    """A planner response is unusable, not an assertion that evidence is absent."""


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
    completion: str = "partially_verified"
    stop_reason: str = "no_verified_document"
    planner_calls: int = 0
    planner_ms: int = 0
    deterministic_steps: int = 0
    warnings: list[str] = field(default_factory=list)
    checks: dict[str, dict] = field(default_factory=dict)
    ranking: dict[str, dict] = field(default_factory=dict)


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
    model_fragment_chars: int = 12_000,
    optimise: bool = False,
    verification_query: str | None = None,
    min_sources: int = 1,
    open_pages: Callable[..., Awaitable[list]] | None = None,
    require_saved_source: bool = False,
    additional_task_query: str | None = None,
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
    search_started = time.perf_counter()
    first_source_reported = False
    deadline = search_started + max_seconds
    attempted: set[str] = set()
    evidence = None
    request = verification_query or query
    compare = comparison_requested(request) or min_sources > 1
    complete = completeness_requested(request)
    section = specific_section_requested(request)
    additional_task = additional_document_task(request if additional_task_query is None else additional_task_query)
    analysis_read = False
    rejected_documents: set[str] = set()
    document_fragments: dict[str, list[str]] = {}
    seen_actions: set[tuple] = set()
    answered = False
    limited = False

    def pending_check():
        return (require_saved_source and outcome.source is None) or (compare and len({url for key, (_, url, _) in outcome.opened.items() if key not in rejected_documents}) < max(2, min_sources)) or (
            (complete or section) and not any(check.get("verified") for check in outcome.checks.values()))

    def save_allowed(result_id):
        check = outcome.checks.get(result_id, {})
        return result_id not in rejected_documents and not ((complete and check.get("expected") or section) and not check.get("verified"))

    def fallback():
        candidates = [(key, rank_candidate(request, item)) for key, item in outcome.results.items()
                      if key not in attempted]
        candidates.sort(key=lambda pair: pair[1].score, reverse=True)
        return next((key for key, rank in candidates if not rank.undesirable and rank.score >= 2
                     and (rank.exact or rank.query_coverage >= .2)), None)

    def diagnostic(reason, code="tool_warning"):
        search_trace.event("AGENT_WARNING", reason=code)
        outcome.warnings.append(reason)
        # The next model call sees a bounded tool diagnostic, not silent failure.
        outcome.inspected["tool_status"] = ("Диагностика инструментов", "", reason[:500])

    def add(results):
        urls = {item.url for item in outcome.results.values()}
        for item in rank_results(request, results) if optimise else results:
            if item.url not in urls:
                outcome.results[f"r{len(outcome.results) + 1}"] = item
                urls.add(item.url)
        for key, item in outcome.results.items():
            rank = rank_candidate(request, item)
            for reason in rank.reasons:
                search_trace.event("CANDIDATE", url_hash=search_trace.fingerprint(item.url), score=rank.score,
                                   reason=reason.split("=")[0], status="demoted" if rank.undesirable else "ranked")
        outcome.ranking = {key: {"score": rank_candidate(request, item).score,
                                "reasons": rank_candidate(request, item).reasons}
                           for key, item in outcome.results.items()}

    async def bounded(awaitable, floor: float = 0.0):
        budget = deadline - time.perf_counter()
        # Historical floor arguments remain accepted, but cannot extend the
        # total search deadline (including resource-slot waits).
        if budget <= 0:
            awaitable.close() if hasattr(awaitable, 'close') else None
            raise TimeoutError
        async with asyncio.timeout(budget):
            return await awaitable

    async def search_once(value):
        outcome.searches += 1
        trace = search_trace.current()
        if trace is not None: trace.searches = outcome.searches
        outcome.queries.append(value)
        await state({"state": "searching", "pass": outcome.searches})
        started = time.perf_counter()
        try:
            found = await bounded(search(value))
            outcome.warnings.extend(getattr(found, "warnings", []))
            add(found)
            if not found:
                diagnostic("Выдача пуста; отсутствие информации не установлено.", "empty_search")
            elif all(rank_candidate(request, item).undesirable or rank_candidate(request, item).query_coverage < .2 for item in found):
                diagnostic("В выдаче нет уверенного совпадения с запросом; уточни поиск, не утверждай отсутствие материала.", "weak_match")
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
            outcome.completion = "partially_verified" if outcome.results else "search_error"
            outcome.stop_reason = "snippets_only" if outcome.results else "empty_search"
            search_trace.event('AGENT_FINISHED', duration_ms=(time.perf_counter()-search_started)*1000,
                               completion=outcome.completion, stop_reason=outcome.stop_reason)
            return outcome
        while outcome.steps < max_steps and time.perf_counter() < deadline:
            await state({"state": "reviewing_sources", "step": outcome.steps + 1})
            automatic = None
            if optimise:
                if not outcome.opened:
                    automatic = obvious_source(request, outcome.results, attempted)
                    if require_saved_source:
                        automatic = automatic or fallback()
                    if automatic is None and outcome.errors:
                        automatic = fallback()
                elif pending_check():
                    automatic = required_open(outcome.results, attempted, outcome.opened) or fallback()
                if (require_saved_source and outcome.source is None and not automatic
                        and outcome.opened and fallback() is None and outcome.searches == 0
                        and outcome.searches < max_searches):
                    await search_once(query)
                    automatic = fallback()
            if automatic and len(attempted) < max_opens:
                action = SimpleNamespace(action="open", result_id=automatic)
                outcome.deterministic_steps += 1
            else:
                outcome.planner_calls += 1
                plan_started = time.perf_counter()
                try:
                    action = await bounded(plan(query, outcome.results, outcome.inspected, evidence))
                    evidence = action
                except PlannerFailure as exc:
                    diagnostic(str(exc), "planner_failure")
                    candidate = fallback()
                    if candidate is None or len(attempted) >= max_opens:
                        outcome.stop_reason = "planner_error"
                        break
                    action = SimpleNamespace(action="open", result_id=candidate)
                    outcome.deterministic_steps += 1
                finally:
                    outcome.planner_ms += round((time.perf_counter() - plan_started) * 1000)
            outcome.steps += 1
            fingerprint = (action.action, getattr(action, "result_id", None),
                           getattr(action, "query", None), getattr(action, "start_block", None),
                           getattr(action, "end_block", None))
            if action.action != "answer" and fingerprint in seen_actions:
                diagnostic("Планировщик повторил выполненное действие; пробуем другой источник.", "repeated_action")
                candidate = fallback()
                if candidate is None or len(attempted) >= max_opens:
                    limited = True
                    outcome.stop_reason = "repeated_action"
                    break
                action = SimpleNamespace(action="open", result_id=candidate)
                outcome.deterministic_steps += 1
            seen_actions.add(fingerprint)
            if action.action == "answer":
                if additional_task and not analysis_read:
                    candidate = next((key for key in outcome.opened if key not in rejected_documents
                                      and outcome.checks.get(key, {}).get('verified')), None)
                    if candidate:
                        focus = re.split(r'затем|после\s+(?:этого|проверки)', request, maxsplit=1, flags=re.I)[-1]
                        action = SimpleNamespace(action='find', result_id=candidate, query=focus)
                        outcome.deterministic_steps += 1
                if action.action == 'answer':
                    forced = required_open(outcome.results, attempted, outcome.opened)
                    if pending_check():
                        forced = forced or fallback()
                    if forced is None or len(attempted) >= max_opens:
                        answered = not pending_check()
                        limited = bool(forced) and len(attempted) >= max_opens
                        outcome.stop_reason = "verification_incomplete" if pending_check() else "planner_answer"
                        break
                    action = SimpleNamespace(action="open", result_id=forced)
                    outcome.deterministic_steps += 1
            if action.action == "search":
                if outcome.searches >= max_searches:
                    limited = True
                    outcome.stop_reason = "search_limit"
                    break
                if action.query in outcome.queries:
                    diagnostic("Этот поисковый запрос уже выполнен; сформулируй другой.", "repeated_query")
                    continue
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
                    selected = view.prompt(action.query, max_chars=model_fragment_chars)
                else:
                    try:
                        selected = view.read(action.start_block, action.end_block, max_chars=model_fragment_chars)
                    except (ValueError, TypeError) as exc:
                        diagnostic(f"Не удалось прочитать диапазон: {exc}", "invalid_read_range")
                        continue
                # Subsequent tool reads must not erase earlier episode/quote
                # evidence. Keep a small, bounded collection within one view.
                fragments = document_fragments.setdefault(result_id, [])
                if selected not in fragments:
                    fragments.append(selected)
                    del fragments[:-6]
                per_fragment = max(1, (model_fragment_chars - 2 * len(fragments)) // len(fragments))
                combined = '\n\n'.join(part[:per_fragment] for part in fragments)[:model_fragment_chars]
                outcome.inspected[result_id] = (title, url, combined)
                analysis_read = True
                saved = None
                if outcome.source is None and save_allowed(result_id):
                    saved = await bounded(save(outcome.results[result_id], text,
                        action.query if action.action == "find" else selected[:1000]), floor=save_floor_seconds)
                outcome.source = outcome.source or saved
                if not additional_task and outcome.source is not None and not pending_check() and required_open(outcome.results, attempted, outcome.opened) is None:
                    answered = True
                    outcome.stop_reason = "saved_source"
                    break
                continue
            if result_id not in outcome.results or result_id in attempted:
                diagnostic("Некорректный или уже открытый источник.", "invalid_open")
                continue
            if len(attempted) >= max_opens:
                limited = True
                outcome.stop_reason = "open_limit"
                break
            batch_ids = [result_id]
            if open_pages is not None and compare and not outcome.opened and len(attempted) + 2 <= max_opens:
                second = required_open(outcome.results, attempted | {result_id}, outcome.opened)
                if second is None:
                    candidates = sorted(((key, rank_candidate(request, item)) for key, item in outcome.results.items()
                        if key not in attempted and key != result_id), key=lambda pair: pair[1].score, reverse=True)
                    second = next((key for key, rank in candidates if not rank.undesirable and rank.score >= 2
                                   and (rank.exact or rank.query_coverage >= .2)), None)
                if second and second != result_id and second not in attempted:
                    batch_ids.append(second)
            attempted.update(batch_ids)
            trace = search_trace.current()
            if trace is not None: trace.opens = len(attempted)
            await state({"state": "opening_source", "page": len(attempted)})
            started = time.perf_counter()
            try:
                if len(batch_ids) > 1:
                    completed = {}
                    try:
                        pages = await bounded(open_pages([outcome.results[key] for key in batch_ids], completed=completed))
                    except TimeoutError:
                        # Reads completed before the deadline stay available;
                        # the owned batch cancels/drains unfinished siblings.
                        outcome.timed_out = True
                        pages = [completed.get(index, WebSearchUnavailable('Чтение не завершено за бюджет поиска'))
                                 for index in range(len(batch_ids))]
                else:
                    try:
                        pages = [await bounded(open_page(outcome.results[result_id]))]
                    except WebSearchUnavailable as exc:
                        pages = [exc]
            finally:
                outcome.open_ms += round((time.perf_counter() - started) * 1000)
            for result_id, page in zip(batch_ids, pages):
                if isinstance(page, BaseException):
                    if not isinstance(page, WebSearchUnavailable):
                        raise page
                    search_trace.event("SOURCE_ERROR", url_hash=search_trace.fingerprint(outcome.results[result_id].url),
                                       reason=type(page).__name__, status="error")
                    outcome.errors.append({"result_id": result_id, "reason": str(page)})
                    outcome.inspected[result_id] = (outcome.results[result_id].title,
                                                    outcome.results[result_id].url, f"Ошибка чтения: {page}")
                    continue
                url, text = page
                if not text or not text.strip():
                    outcome.errors.append({"result_id": result_id, "reason": "Источник не содержит извлечённого текста"})
                    outcome.inspected[result_id] = (outcome.results[result_id].title, outcome.results[result_id].url, "Пустой текст источника; это ошибка чтения, а не отсутствие информации.")
                    continue
                item = replace(outcome.results[result_id], url=url)
                outcome.results[result_id] = item
                outcome.opened[result_id] = (item.title, url, text)
                if trace is not None: trace.successful_opens = len(outcome.opened)
                outcome.inspected[result_id] = (item.title, url, DocumentView(text).prompt(query, max_chars=model_fragment_chars))
                outcome.checks[result_id] = document_check(request, item.title, text)
                if primary_document_requested(request) and secondary_material(item.title, text):
                    rejected_documents.add(result_id)
                    outcome.inspected[result_id] = (item.title, url,
                        'Отклонён: это комментарий/пересказ, а не запрошенный оригинал. Текст не является доказательством оригинала.')
                    diagnostic('Прочитан вторичный материал вместо оригинала; нужен другой источник.', 'secondary_not_original')
                    continue

            for result_id in batch_ids:
                if result_id not in outcome.opened or not save_allowed(result_id):
                    continue
                title, url, text = outcome.opened[result_id]
                if outcome.source is None:
                    outcome.source = await bounded(save(outcome.results[result_id], text), floor=save_floor_seconds)
                if not first_source_reported and (outcome.source is not None or outcome.checks[result_id].get('verified')):
                    first_source_reported = True
                    search_trace.event('FIRST_SOURCE', first_source_ms=(time.perf_counter() - search_started)*1000)
            structurally_checked = optimise and any(check.get('verified') for check in outcome.checks.values()) and (
                complete or any(rank_candidate(request, outcome.results[key]).exact for key in outcome.opened))
            if not additional_task and (outcome.source is not None or structurally_checked) and not pending_check() and required_open(outcome.results, attempted, outcome.opened) is None:
                answered = True
                outcome.stop_reason = "structure_checked" if structurally_checked else "saved_source"
                break
        if time.perf_counter() >= deadline:
            outcome.timed_out = True
    except TimeoutError:
        outcome.timed_out = True
    except (WebSearchUnavailable, ResourceUnavailable) as exc:
        outcome.errors.append({"result_id": "search", "reason": str(exc)})
        outcome.stop_reason = "search_failed"
    if outcome.timed_out:
        outcome.completion, outcome.stop_reason = "limits_exhausted", "time_limit"
    elif limited or (outcome.steps >= max_steps and not answered):
        outcome.completion = "limits_exhausted"
        if not limited:
            outcome.stop_reason = "step_limit"
    elif answered and outcome.opened and not outcome.errors and not outcome.warnings and not pending_check():
        outcome.completion = "success"
    elif outcome.opened:
        outcome.completion = "partially_verified"
    elif any(error["result_id"] != "search" for error in outcome.errors):
        outcome.completion = "source_error"
        outcome.stop_reason = "source_read_failed"
    elif outcome.errors or outcome.stop_reason == "planner_error" or not outcome.results:
        outcome.completion = "search_error"
        if not outcome.results and not outcome.errors:
            outcome.stop_reason = "empty_search"
    search_trace.event("AGENT_FINISHED", duration_ms=(time.perf_counter()-search_started)*1000,
                       completion=outcome.completion, stop_reason=outcome.stop_reason)
    return outcome
