"""Editable internal prompt templates. The answer identity stays code-owned."""

from __future__ import annotations

import re
from contextvars import ContextVar

from .prompt_templates import DEFAULT_TEMPLATES
PROMPT_LABELS = {
    "chat_title": "Название чата",
    "quick_chat_mode": "Универсальный быстрый чат",
    "extract_working_excerpt": "Извлечение рабочего источника",
    "should_seek_working_source": "Нужен ли рабочий источник",
    "is_foundational_source": "Проверка опорного источника",
    "choose_retrieval_route": "LLM Router",
    "build_request_anchor": "Рамка исходного запроса",
    "request_anchor_prompt": "Инструкция по рамке запроса",
    "review_research_answer": "Проверка ответа RESEARCH",
    "revise_research_answer": "Исправление ответа RESEARCH",
    "choose_contextual_search_query": "Поисковый запрос с контекстом",
    "choose_web_action": "Шаг веб-исследования",
    "web_search_prompt": "Результаты веб-поиска",
    "web_page_prompt": "Открытая веб-страница",
    "process_chat_memory": "Сжатая память чата",
    "working_source_context": "Рабочий источник в ответе",
    "knowledge_context": "Материалы базы знаний в ответе",
    "source_status": "Статус источников чата",
    "chat_memory_context": "Память чата в ответе",
    "conversation_focus": "Контекст текущего вопроса",
    "search_summary": "Сводка веб-исследования",
}

_overrides: ContextVar[dict[str, str]] = ContextVar("prompt_overrides", default={})


def set_prompt_overrides(values: dict[str, str]):
    return _overrides.set(values)


def reset_prompt_overrides(token) -> None:
    _overrides.reset(token)


def render_prompt(key: str, default: str, values: dict[str, str] | None = None) -> str:
    """Keep the existing production prompt unless an editor saved a template."""
    template = _overrides.get().get(key)
    if template is None:
        return default
    return re.sub(
        r"\{\{([^{}]+)\}\}",
        lambda match: (values or {}).get(match.group(1), match.group(0)),
        template,
    )


def required_markers(key: str) -> set[str]:
    return set(re.findall(r"\{\{([^{}]+)\}\}", DEFAULT_TEMPLATES[key]))
