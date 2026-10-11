"""Durable state of a material search in one chat.

A search for a whole material is rarely one message: the user asks for a
сборник, then corrects which one, then asks about a detail inside it. Without
remembered state each message is judged alone, so a short follow-up stops
looking like a source request and a rejected document can be offered again.

Two things live here:

* what the task is, so the router can recognise a continuation;
* which documents the user rejected, so they stay out of this task's candidates.

The state never starts a search on its own. The router still decides every
single turn, and a task that has been idle for several turns stops being shown
to it — a stale task must not pull every later question onto the web.
"""
from __future__ import annotations

from typing import Any

# How many turns without material activity the task is still offered to the
# router. Six turns is long enough for the corrections a source hunt needs and
# short enough that a conversation which moved on is not dragged back.
SEARCH_TASK_IDLE_LIMIT = 6


def task_is_alive(task: Any | None) -> bool:
    """True while the task may still describe what the user is working on."""
    if task is None:
        return False
    if not str(getattr(task, "statement", "") or "").strip():
        return False
    return int(getattr(task, "idle_turns", 0) or 0) <= SEARCH_TASK_IDLE_LIMIT


def rejected_source_ids(task: Any | None) -> set[str]:
    """Source ids the user rejected for this chat, as a plain set."""
    if task is None:
        return set()
    stored = getattr(task, "rejected", None)
    if not isinstance(stored, (list, tuple)):
        return set()
    return {str(item) for item in stored if item}


def search_task_block(task: Any | None, titles: dict[str, str] | None = None) -> str:
    """Router-facing description of the unfinished task, or an empty string.

    Empty whenever there is nothing to continue, so an ordinary question is
    never given a reason to search.
    """
    if not task_is_alive(task):
        return ""
    titles = titles or {}
    lines = [f"Задача поиска материала в этом чате (данные): {str(task.statement).strip()[:400]}"]
    rejected = [
        titles.get(source_id, source_id) for source_id in sorted(rejected_source_ids(task))
    ]
    if rejected:
        lines.append("Пользователь уже отклонил: " + "; ".join(rejected[:5]))
    return "\n".join(lines)


def with_rejection(task_rejected: Any, source_id: str | None) -> list[str]:
    """Rejection list with ``source_id`` added once, newest last."""
    current = [str(item) for item in task_rejected or [] if item] if isinstance(
        task_rejected, (list, tuple)
    ) else []
    if source_id and str(source_id) not in current:
        current.append(str(source_id))
    return current
