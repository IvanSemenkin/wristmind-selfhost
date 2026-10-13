import asyncio
import hashlib
import json
import pytest
from wristmind_server.search_agent import PlannerFailure
from types import SimpleNamespace

from sqlalchemy import select

from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Chat, Job, JobEvent, KnowledgeSource
from wristmind_server.web_search import WebSearchResult
from wristmind_server.worker import (
    ResearchReview,
    RequestAnchor,
    RetrievalRoute,
    SOURCE_MATERIAL_REQUEST,
    WORKING_SOURCE_PREVIEW_CEILING,
    WORKING_SOURCE_PREVIEW_FLOOR,
    WriteIntents,
    apply_intent_safeguards,
    build_request_anchor,
    build_working_source_preview,
    choose_contextual_search_query,
    choose_retrieval_route,
    choose_web_action,
    create_source_candidate,
    deep_web_open_requirement,
    deterministic_route_fallback,
    exact_source_open_requirement,
    is_foundational_source,
    is_simple_fresh_fact,
    is_trivial_research_request,
    lightweight_request_anchor,
    local_first_snapshot,
    material_rejected_now,
    needs_fresh_search,
    task_statement_from_history,
    present_working_source,
    primary_source_results,
    providers,
    read_working_source_text,
    request_anchor_summary,
    requests_full_source_text,
    route_uses_web,
    should_seek_working_source,
    task_needs_exact_text,
)


def anchor(question: str) -> RequestAnchor:
    return RequestAnchor(
        original_request=question,
        main_subject=question,
        task_type="other",
    )


def test_planner_accepts_only_exact_schema_and_known_result_id(monkeypatch):
    async def stream(_model_id, _messages):
        yield '{"action":"open","result_id":"r1"}'

    monkeypatch.setattr(providers, "stream_answer", stream)
    results = {"r1": WebSearchResult("Источник", "https://example.org", "Факт")}
    action = asyncio.run(choose_web_action("mock:test", anchor("Вопрос"), "Вопрос", results, {}, None))
    assert action.action == "open"
    assert action.result_id == "r1"

    async def bad_stream(_model_id, _messages):
        yield '{"action":"open","url":"https://attacker.example"}'

    monkeypatch.setattr(providers, "stream_answer", bad_stream)
    with pytest.raises(PlannerFailure):
        asyncio.run(choose_web_action("mock:test", anchor("Вопрос"), "Вопрос", results, {}, None))


def test_planner_receives_opened_page_and_updated_evidence(monkeypatch):
    seen = ""

    async def stream(_model_id, messages):
        nonlocal seen
        seen = messages[0]["content"]
        yield (
            '{"action":"search","query":"Newton official release",'
            '"result_id":null,"purpose":"clarify_entity","confirmed":["Название Newton"],'
            '"missing":[{"field":"release_date","status":"unknown"}]}'
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    results = {"r1": WebSearchResult("Newton", "https://example.org", "Новый продукт")}
    action = asyncio.run(choose_web_action(
        "mock:test",
        anchor("Вышел ли старый продукт?"),
        "старый продукт выпуск",
        results,
        {"r1": ("Newton", "https://example.org", "Официальное название Newton")},
        None,
    ))

    assert action.query == "Newton official release"
    assert action.purpose == "clarify_entity"
    assert action.missing[0].field == "release_date"
    assert "Официальное название Newton" in seen
    assert "Исходный запрос: Вышел ли старый продукт?" in seen


def test_deep_search_builds_initial_query_from_conversation(monkeypatch):
    async def stream(_model_id, messages):
        assert "user: А про Россию?" in messages[0]["content"]
        yield '{"query":"часовые пояса России причины 11"}'

    monkeypatch.setattr(providers, "stream_answer", stream)
    query = asyncio.run(choose_contextual_search_query(
        "mock:test", anchor("Почему их столько?"), [
            type("Message", (), {"role": "user", "content": "А про Россию?"})(),
        ]
    ))
    assert query == "часовые пояса России причины 11"


def test_request_anchor_rejects_invented_subject_or_constraint(monkeypatch):
    question = "Когда выйдет обновление WristMind для часов?"

    async def stream(_model_id, _messages):
        yield (
            '{"original_request":"Когда выйдет обновление WristMind для часов?",'
            '"main_subject":"WristMind версии 9",'
            '"task_type":"fact_question","explicit_constraints":["только для Android 16"],'
            '"unknowns":[{"field":"release_date","status":"unknown"}]}'
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    result = asyncio.run(build_request_anchor("mock:test", question))

    assert result.original_request == question
    assert result.main_subject == question
    assert result.task_type == "other"
    assert result.explicit_constraints == []


def test_planner_refuses_a_second_search_without_retrieval_purpose(monkeypatch):
    async def stream(_model_id, _messages):
        yield '{"action":"search","query":"совсем другая тема","result_id":null,"confirmed":[],"missing":[]}'

    monkeypatch.setattr(providers, "stream_answer", stream)
    results = {"r1": WebSearchResult("Источник", "https://example.org", "Факт")}
    with pytest.raises(PlannerFailure):
        asyncio.run(choose_web_action(
            "mock:test", anchor("Сравни две версии WristMind"), "версии WristMind", results, {}, None,
        ))


def test_router_uses_current_chat_source_before_the_internet(monkeypatch):
    seen = ""

    async def stream(_model_id, messages):
        nonlocal seen
        seen = messages[0]["content"]
        yield (
            '{"retrieval":"chat_sources","reasoning":"medium","verification":false,'
            '"freshness_required":false,"task_type":"write_from_source"}'
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test",
        "Напиши по нему сочинение",
        "1. Последние сообщения текущего чата:\nuser: Найди текст для ОГЭ\n\n"
        "2. Источники, сохранённые именно в текущем чате:\nТекст Нагибина\n\n"
        "3. База знаний режима:\nдоступна для ответа\n\n"
        "4. Уже использованные веб-ссылки текущего чата:\nhttps://example.org/text",
        requested_web_search=True,
        requested_deep_research=True,
    ))

    assert route.retrieval == "chat_sources"
    assert route_uses_web(route) == (False, False)
    assert "Источники, сохранённые именно в текущем чате" in seen


def test_router_routes_fresh_fact_to_web_and_comparison_to_deep_web(monkeypatch):
    responses = iter([
        '{"retrieval":"web","reasoning":"low","verification":true,"freshness_required":true,"task_type":"current_fact"}',
        '{"retrieval":"deep_web","reasoning":"high","verification":true,"freshness_required":false,"task_type":"comparison"}',
    ])

    async def stream(_model_id, _messages):
        yield next(responses)

    monkeypatch.setattr(providers, "stream_answer", stream)
    fresh = asyncio.run(choose_retrieval_route(
        "mock:test", "Какая сегодня цена?", "Локальных данных нет", requested_web_search=False, requested_deep_research=False,
    ))
    comparison = asyncio.run(choose_retrieval_route(
        "mock:test", "Сравни два стандарта", "Локальных данных нет", requested_web_search=False, requested_deep_research=False,
    ))

    assert route_uses_web(fresh) == (True, False)
    assert route_uses_web(comparison) == (True, True)


def test_router_falls_back_to_local_answer_when_decision_is_invalid(monkeypatch):
    async def stream(_model_id, _messages):
        yield '{"retrieval":"internet","reasoning":"high"}'

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Что это?", "Локальных данных нет", requested_web_search=True, requested_deep_research=False,
    ))

    assert route.retrieval == "none"
    assert route_uses_web(route) == (False, False)


def test_router_retries_once_when_the_stream_ends_early(monkeypatch):
    replies = iter([
        "```",
        '{"retrieval":"chat_sources","reasoning":"high","verification":false,'
        '"freshness_required":false,"task_type":"write_from_source"}',
    ])
    calls = {"count": 0}

    async def stream(_model_id, _messages):
        calls["count"] += 1
        yield next(replies)

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Напиши по этому тексту сочинение", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
        chat_source_titles=["Текст Нагибина"],
    ))

    assert calls["count"] == 2
    assert route.retrieval == "chat_sources"


def test_router_falls_back_after_a_failed_retry(monkeypatch):
    calls = {"count": 0}

    async def stream(_model_id, _messages):
        calls["count"] += 1
        yield "```"

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Что такое биссектриса?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
    ))

    assert calls["count"] == 2
    assert route.retrieval == "none"


def test_deterministic_fallback_preserves_explicit_intent():
    assert deterministic_route_fallback(
        "Сравни последние версии Android и HyperOS", has_chat_material=False,
    ).retrieval == "deep_web"
    assert deterministic_route_fallback(
        "Используй несколько источников и проверь противоречия", has_chat_material=False,
    ).retrieval == "deep_web"
    assert deterministic_route_fallback(
        "Найди оригинальный текст Колобка", has_chat_material=False,
    ).retrieval == "deep_web"
    assert deterministic_route_fallback(
        "Напиши по этому тексту сочинение", has_chat_material=True,
    ).retrieval == "chat_sources"
    assert deterministic_route_fallback(
        "Напиши по этому тексту сочинение", has_chat_material=False,
    ).retrieval != "chat_sources"
    assert deterministic_route_fallback(
        "Какая сейчас последняя версия Android?", has_chat_material=False,
    ).retrieval == "web"
    assert deterministic_route_fallback(
        "Что такое биссектриса треугольника?", has_chat_material=False,
    ).retrieval == "none"


def test_router_failure_keeps_a_comparison_on_deep_web(monkeypatch):
    async def stream(_model_id, _messages):
        yield ""

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test",
        "Сравни последние стабильные версии Android и HyperOS и используй несколько источников",
        "Локальных данных нет",
        requested_web_search=True,
        requested_deep_research=True,
    ))

    assert route.retrieval == "deep_web"
    assert route_uses_web(route) == (True, True)


def test_router_accepts_json_wrapped_in_markdown_fence(monkeypatch):
    async def stream(_model_id, _messages):
        yield (
            "```json\n"
            '{"retrieval":"deep_web","reasoning":"high","verification":true,'
            '"freshness_required":false,"task_type":"write_from_source"}\n'
            "```"
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test",
        "Найди оригинальный текст",
        "Локальных данных нет",
        requested_web_search=False,
        requested_deep_research=False,
    ))

    assert route.retrieval == "deep_web"
    assert route.task_type == "write_from_source"
    assert route_uses_web(route) == (True, True)


def test_router_extracts_json_object_from_surrounding_text(monkeypatch):
    async def stream(_model_id, _messages):
        yield (
            "Решение: "
            '{"retrieval":"web","reasoning":"low","verification":true,'
            '"freshness_required":true,"task_type":"current_fact"}'
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test",
        "Какая последняя версия?",
        "Локальных данных нет",
        requested_web_search=False,
        requested_deep_research=False,
    ))

    assert route.retrieval == "web"
    assert route_uses_web(route) == (True, False)


def test_research_review_contract_and_trivial_request_gate():
    review = ResearchReview.model_validate({"verdict": "accept", "issues": ["не сохраняется"]})

    assert review.issues == []
    assert is_trivial_research_request("Привет!") is True
    assert is_trivial_research_request("Объясни причины промышленной революции") is False


def test_orange_search_recognizes_primary_source_request_and_demotes_answer_keys():
    results = {
        "r1": WebSearchResult("Сочинение ОГЭ по тексту Нагибина", "https://answers.example/1", "Готовый ответ"),
        "r2": WebSearchResult("Текст Ю. М. Нагибина о Гагарине", "https://texts.example/2", "Оригинальный текст для ОГЭ"),
    }

    assert SOURCE_MATERIAL_REQUEST.search("Найди оригинальный текст Нагибина для ОГЭ")
    assert [result_id for result_id, _ in primary_source_results(results, set())] == ["r2", "r1"]


def test_semantic_working_source_intent_does_not_depend_on_fixed_phrases(monkeypatch):
    async def stream_answer(*_args, **_kwargs):
        yield '{"requested":true}'

    monkeypatch.setattr(providers, "stream_answer", stream_answer)

    assert asyncio.run(should_seek_working_source(
        "deepseek:deepseek-flash",
        "Найди материал о первом полёте в космос; потом подготовим по нему работу",
        [],
    ))


def test_explicit_intent_never_bypasses_candidate_relevance_check(monkeypatch):
    seen_prompt = ""

    async def stream_answer(_model_id, messages, **_kwargs):
        nonlocal seen_prompt
        seen_prompt = messages[0]["content"]
        yield '{"foundation":false}'

    monkeypatch.setattr(providers, "stream_answer", stream_answer)

    accepted = asyncio.run(is_foundational_source(
        "deepseek:deepseek-flash",
        "Найди текст Нагибина о Гагарине, дальше напишем по нему сочинение",
        [],
        "Биография Гагарина",
        "https://example.test/gagarin",
        "Биографическая справка о Юрии Гагарине. " * 20,
        explicitly_requested=True,
        system_prompt="ПРОВЕРЬ ТОЧНОЕ СООТВЕТСТВИЕ МАТЕРИАЛА ЗАПРОСУ.",
    ))

    assert accepted is False
    assert "ПРОВЕРЬ ТОЧНОЕ СООТВЕТСТВИЕ" in seen_prompt
    assert "Предварительное намерение найти опорный материал: да" in seen_prompt


ROUTER_CASES = [
    # request, route the model would return, expected final route, chat source titles
    ("Что такое биссектриса треугольника?", "none", "none", None),
    ("Какая сейчас последняя стабильная версия Android?", "none", "web", None),
    ("Какая актуальная версия Python вышла последней?", "none", "web", None),
    (
        "Найди оригинальный текст Колобка, дальше я буду выполнять по нему задания",
        "none",
        "deep_web",
        None,
    ),
    (
        "Найди текст задания №13 из актуальной демоверсии ОГЭ по русскому языку",
        "web",
        "deep_web",
        None,
    ),
    # A non-empty but unrelated mode knowledge base must not win over freshness.
    ("Какая сейчас последняя стабильная версия Android?", "chat_sources", "web", None),
    # A request that really builds on the current chat material stays local.
    ("Напиши по этому тексту сочинение", "chat_sources", "chat_sources", ["Текст Нагибина"]),
    ("Объясни, что значит слово новый", "none", "none", None),
    ("Что такое текст как единица речи?", "none", "none", None),
]


def test_router_routes_the_required_intents(monkeypatch):
    for request, model_route, expected, titles in ROUTER_CASES:
        async def stream(_model_id, _messages, _route=model_route):
            yield (
                '{"retrieval":"%s","reasoning":"low","verification":false,'
                '"freshness_required":false,"task_type":"other"}' % _route
            )

        monkeypatch.setattr(providers, "stream_answer", stream)

        async def run():
            return await choose_retrieval_route(
                "mock:test",
                request,
                "Локальных данных нет",
                requested_web_search=False,
                requested_deep_research=False,
                chat_source_titles=titles,
            )

        route = asyncio.run(run())
        assert route.retrieval == expected, (request, route.retrieval)


def test_router_prompt_states_model_knowledge_is_not_local_material(monkeypatch):
    seen = ""

    async def stream(_model_id, messages):
        nonlocal seen
        seen = messages[0]["content"]
        yield '{"retrieval":"none","reasoning":"low","verification":false,"freshness_required":false,"task_type":"other"}'

    monkeypatch.setattr(providers, "stream_answer", stream)
    asyncio.run(choose_retrieval_route(
        "mock:test", "Что такое биссектриса?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
    ))

    assert "Собственные знания модели — это НЕ локальный контекст" in seen
    assert "выбирай минимум web" in seen
    assert "выбирай deep_web, даже если ты знаешь его содержание" in seen


def test_local_snapshot_reports_material_instead_of_a_bare_flag():
    snapshot = local_first_snapshot([], "context", {
        "strategy": "full",
        "source_tokens": 900,
        "context_tokens": 900,
        "chat_source_titles": ["Текст Нагибина"],
    })

    assert "Текст Нагибина" in snapshot
    assert "без отбора по релевантности" in snapshot
    assert "доступна для ответа" not in snapshot


def _comparison_route(retrieval="deep_web", task_type="comparison"):
    from wristmind_server.worker import RetrievalRoute

    return RetrievalRoute(
        retrieval=retrieval, reasoning="high", verification=True,
        freshness_required=False, task_type=task_type,
    )


def _results():
    return {
        "r1": WebSearchResult("Android 16", "https://a.example/android", "свежий релиз"),
        "r2": WebSearchResult("HyperOS", "https://b.example/hyperos", "новая оболочка"),
    }


def test_comparison_deep_web_must_open_a_page_before_answering():
    request = "Сравни последние стабильные версии Android и HyperOS по новым функциям"
    route = _comparison_route()
    results = _results()

    # No page opened yet: the next answer must become an open.
    assert deep_web_open_requirement(route, request, results, set(), {}) == "r1"
    # One page opened: a comparison still wants a second independent source.
    opened = {"r1": ("Android 16", "https://a.example/android", "текст")}
    assert deep_web_open_requirement(route, request, results, {"r1"}, opened) == "r2"
    # Depth reached: answering from snippets is now allowed.
    both = {
        "r1": ("Android 16", "https://a.example/android", "текст"),
        "r2": ("HyperOS", "https://b.example/hyperos", "текст"),
    }
    assert deep_web_open_requirement(route, request, results, {"r1", "r2"}, both) is None


def test_deep_web_evidence_gate_is_scoped_and_degrades_gracefully():
    # A cross-check with a single required source opens once, not twice.
    cross = _comparison_route(task_type="other")
    cross_request = "Используй несколько источников"
    results = _results()
    assert deep_web_open_requirement(cross, cross_request, results, set(), {}) == "r1"
    opened = {"r1": ("Android 16", "https://a.example/android", "текст")}
    assert deep_web_open_requirement(cross, cross_request, results, {"r1"}, opened) is None

    # Plain deep_web without cross-evidence intent is never forced open.
    plain = _comparison_route(task_type="other")
    assert deep_web_open_requirement(plain, "Найди что-нибудь интересное", results, set(), {}) is None
    # No suitable results -> no forced open, graceful snippet answer.
    assert deep_web_open_requirement(_comparison_route(), "Сравни два стандарта", {}, set(), {}) is None
    # A non-deep route is never affected.
    assert deep_web_open_requirement(_comparison_route("web", "current_fact"), "Сравни", results, set(), {}) is None


def _excerpt_route(retrieval="web", *, excerpt=True, primary=False, fast=False):
    from wristmind_server.worker import RetrievalRoute, WriteIntents

    return RetrievalRoute(
        retrieval=retrieval, reasoning="low", verification=False,
        freshness_required=False, task_type="other",
        intents=WriteIntents(
            wants_source_excerpt=excerpt, wants_primary_source=primary, wants_fast_answer=fast,
        ),
    )


def test_exact_text_task_is_recognized_by_intent_or_phrasing():
    assert task_needs_exact_text(_excerpt_route(), "просто вопрос") is True
    assert task_needs_exact_text(_excerpt_route(excerpt=False), "Какая сейчас погода") is False
    # Deterministic fallback for turns where the router reported no intent.
    assert task_needs_exact_text(
        _excerpt_route(excerpt=False), "Пришли оригинальный текст главы"
    ) is True


def test_exact_text_request_must_read_a_document_before_answering():
    """A "give me the exact text" task is not a deep_web comparison.

    The deep_web gate deliberately declines every other route, so nothing forced
    a read on this path: an answer could be assembled from snippets and then
    presented as a checked result. An exact-text task now reads one candidate
    before it is allowed to conclude anything about the document.
    """
    request = "Дай точный текст задачи 7.13 из сборника"
    route = _excerpt_route()
    results = _results()

    # The deep gate keeps excluding this route — that is exactly the hole filled.
    assert deep_web_open_requirement(route, request, results, set(), {}) is None
    # Nothing read yet: the next step must be an open, not an answer.
    assert exact_source_open_requirement(route, request, results, set(), {}) == "r1"
    # A document was read: the gate stops blocking the answer.
    opened = {"r1": ("Сборник", "https://a.example/sbornik", "текст")}
    assert exact_source_open_requirement(route, request, results, {"r1"}, opened) is None
    # Nothing readable left to try: degrade gracefully instead of looping.
    assert exact_source_open_requirement(route, request, {}, set(), {}) is None
    assert exact_source_open_requirement(route, request, results, {"r1", "r2"}, {}) is None
    # An ordinary question is never forced to read anything.
    assert exact_source_open_requirement(
        _excerpt_route(excerpt=False), "Какая сейчас погода в Москве", results, set(), {}
    ) is None
    # An explicit request for speed keeps the snippet answer the user chose.
    assert exact_source_open_requirement(_excerpt_route(fast=True), request, results, set(), {}) is None


def test_simple_fresh_fact_uses_a_deterministic_anchor():
    request = "Какая сейчас последняя стабильная версия Android?"
    route = _comparison_route("web", "current_fact")
    assert is_simple_fresh_fact(route, request) is True

    # Anything ambiguous or evidence-heavy keeps the model-built anchor.
    assert is_simple_fresh_fact(_comparison_route("deep_web", "comparison"), request) is False
    assert is_simple_fresh_fact(_comparison_route("web", "current_fact"), "Версия A или версия B?") is False
    assert is_simple_fresh_fact(
        _comparison_route("web", "current_fact"), "Найди официальный текст задания", 
    ) is False
    assert is_simple_fresh_fact(
        _comparison_route("web", "current_fact"), "Какая версия лучше? А какая стабильнее?"
    ) is False


def test_request_anchor_summary_is_structured_and_safe():
    anchor = lightweight_request_anchor("Какая сейчас последняя стабильная версия Android?")
    summary = request_anchor_summary(anchor, "deterministic")

    assert summary == {
        "mode": "deterministic",
        "subject": "Какая сейчас последняя стабильная версия Android?",
        "task": "fact_question",
        "constraints": [],
        "unknowns": [],
    }
    # Diagnostics must stay JSON-serializable for message.timings.
    assert json.loads(json.dumps(summary)) == summary


# --- Working Source presentation -------------------------------------------------
#
# A Working Source is durable chat material, not a screenful of text. The whole
# document is always stored and none of it is shown by default; only an explicit
# request reveals a fragment or the whole document. Nothing here may change
# extraction, provenance or storage.

LONG_SOURCE = (
    ("Колобок по сусекам скребён, по амбару метён, на сметане мешён. " * 30).strip()
    + "\n\n"
    + ("Я от бабушки ушёл, я от дедушки ушёл, и от тебя подавно уйду. " * 30).strip()
)

FIND_SOURCE_REQUEST = (
    "Найди оригинальный текст Колобка, дальше я буду выполнять по нему задания"
)


def test_finding_a_source_shows_a_bounded_verbatim_preview():
    """A: finding the text shows its opening, without dumping a long document."""
    assert len(LONG_SOURCE) > WORKING_SOURCE_PREVIEW_CEILING
    assert not requests_full_source_text(FIND_SOURCE_REQUEST)

    message = present_working_source("Колобок", LONG_SOURCE)

    preview = build_working_source_preview(LONG_SOURCE)
    assert message.startswith("Нашёл подходящий текст и сохранил его как рабочий источник текущего чата: «Колобок».\n\n")
    assert WORKING_SOURCE_PREVIEW_FLOOR <= len(preview) <= WORKING_SOURCE_PREVIEW_CEILING
    assert LONG_SOURCE.startswith(preview)
    assert preview in message
    assert LONG_SOURCE not in message
    assert "Показано начало" in message


def test_short_working_source_is_shown_entirely_without_misleading_preview_note():
    content = "Колобок от бабушки ушёл, от дедушки ушёл."
    message = present_working_source("Колобок", content)
    assert content in message
    assert "Показано начало" not in message


def test_explicit_full_text_requests_print_the_whole_source():
    """C: an explicit full-text request prints everything."""
    for phrase in (
        "покажи весь текст",
        "выведи полностью",
        "пришли целиком",
        "дай полный текст",
        "покажи полностью",
        "покажи его целиком, хочу прочитать",
        "дай всё содержание",
    ):
        assert requests_full_source_text(phrase), phrase

    message = present_working_source("Колобок", LONG_SOURCE, full_text=True)

    assert LONG_SOURCE in message
    assert "Показано начало" not in message


def test_ordinary_source_requests_do_not_dump_long_material():
    """E: plain find/save wording shows at most a bounded opening."""
    for phrase in (
        FIND_SOURCE_REQUEST,
        "Найди текст сказки Колобок",
        "Найди текст задания №13 из актуальной демоверсии ОГЭ по русскому языку",
        "Найди первоисточник и сохрани его",
        "Найди отрывок из поэмы",
        "Сохрани текст, будем дальше по нему работать",
        "Выведи список источников",
    ):
        assert not requests_full_source_text(phrase), phrase

        for content in (LONG_SOURCE, "Колобок от бабушки ушёл, от дедушки ушёл."):
            message = present_working_source("Колобок", content)
            assert content[:30] in message, (phrase, content[:30])
            if len(content) > WORKING_SOURCE_PREVIEW_CEILING:
                assert content not in message
                assert len(build_working_source_preview(content)) <= WORKING_SOURCE_PREVIEW_CEILING
            assert "рабочий источник текущего" in message


def test_named_text_is_treated_as_working_material_without_a_future_task(monkeypatch):
    prompts = []

    async def stream_answer(_model_id, messages, **_kwargs):
        prompts.append(messages[0]["content"])
        yield '{"requested":true}' if len(prompts) == 1 else '{"foundation":true}'

    monkeypatch.setattr(providers, "stream_answer", stream_answer)
    question = "Найди текст сказки Колобок"
    assert asyncio.run(should_seek_working_source("mock:test", question, []))
    assert asyncio.run(is_foundational_source(
        "mock:test", question, [], "Колобок", "https://example.test/kolobok",
        "Текст сказки Колобок. " * 30, explicitly_requested=True,
    ))
    assert all("Правило WristMind" in prompt for prompt in prompts)


def test_follow_up_answers_from_the_saved_material_without_web(monkeypatch):
    """D: later work runs locally on the stored material, with no new search."""
    async def stream(_model_id, _messages):
        yield (
            '{"retrieval":"chat_sources","reasoning":"low","verification":false,'
            '"freshness_required":false,"task_type":"write_from_source"}'
        )

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test",
        "Назови главную мысль этого текста",
        "Локальных данных нет",
        requested_web_search=False,
        requested_deep_research=False,
        chat_source_titles=["Колобок"],
    ))

    assert route.retrieval == "chat_sources"
    assert route_uses_web(route) == (False, False)


def test_saved_working_source_stays_complete_for_follow_ups(
    client, admin_headers, mode, monkeypatch
):
    request = "Найди оригинальный текст Колобка, дальше я буду выполнять по нему задания"
    chat = client.post("/v1/chats", headers=admin_headers, json={"mode_id": mode["id"]}).json()
    job = client.post(
        f"/v1/chats/{chat['id']}/messages",
        headers=admin_headers,
        json={"client_request_id": "working-source-1", "text": request},
    ).json()

    page = LONG_SOURCE + "\n\nХвост страницы, который в материал не входит."
    replies = iter([
        '{"foundation":true}',
        json.dumps({"title": "Колобок", "excerpt": LONG_SOURCE}),
    ])

    async def stream_answer(*_args, **_kwargs):
        yield next(replies)

    monkeypatch.setattr(providers, "stream_answer", stream_answer)

    async def run() -> tuple[str, int, str, str, str, int, list[str]]:
        async with SessionFactory() as session:
            saved_chat = await session.get(Chat, chat["id"])
            source = await create_source_candidate(
                session, job["id"], saved_chat, request, [], "mock:test",
                "Колобок", "https://example.test/kolobok", page,
                explicitly_requested=True,
            )
            assert source is not None
            stored = read_working_source_text(source)
            # The finding turn shows a bounded opening of the saved material.
            presented = present_working_source(source.title, stored)
            # Presenting the turn must not create another Working Source.
            total = len(list(await session.scalars(select(KnowledgeSource.id))))
            saved = await session.get(KnowledgeSource, source.id)
            progress = (await session.scalars(
                select(JobEvent)
                .where(JobEvent.job_id == job["id"], JobEvent.event == "state")
                .order_by(JobEvent.id)
            )).all()
            return source.id, total, stored, presented, saved.content_hash, (
                (saved.extraction_end or 0) - (saved.extraction_start or 0)
            ), [event.data["state"] for event in progress]

    source_id, total, stored, presented, saved_hash, saved_length, states = asyncio.run(run())

    # Preserve the entire extracted HTML document, including its trailing text.
    # Model-selected excerpts must not silently truncate a whole-original request.
    assert stored == page
    assert saved_hash == hashlib.sha256(page.encode("utf-8")).hexdigest()
    assert saved_length == len(page)
    assert total == 1
    assert states[-3:] == ["evaluating_source", "extracting_source", "saving_source"]

    # The finding turn shows the actual opening, not the entire long source.
    assert LONG_SOURCE[:40] in presented
    assert LONG_SOURCE not in presented

    # ...while a follow-up still has the whole material available.
    follow_up = present_working_source("Колобок", stored, full_text=True)
    assert LONG_SOURCE in follow_up
    assert present_working_source("Колобок", stored) != follow_up


# --- Semantic user instructions ---------------------------------------------------
#
# Explicit instructions are read from the MEANING of the request, never from a
# phrase list: the same intent must work for any wording, and the required
# priority rules must hold no matter how it was phrased.

INSTRUCTION_PHRASINGS = {
    "wants_deep_search": [
        "сделай глубокий поиск",
        "копни поглубже",
        "поищи это нормально",
        "не отвечай по памяти, проверь в интернете",
        "разберись подробно по источникам",
    ],
    "wants_multi_source_check": [
        "проверь по нескольким источникам",
        "сверь несколько сайтов",
        "посмотри, что пишут разные источники",
    ],
    "wants_primary_source": [
        "найди первоисточник",
        "нужен оригинальный текст, а не пересказ",
        "дай официальный документ",
    ],
    "wants_more_reasoning": [
        "подумай глубже",
        "обдумай это нормально",
        "не спеши, рассуди тщательно",
        "хочу максимально продуманный ответ",
    ],
    "wants_no_web": [
        "без интернета",
        "не ищи это",
        "ответь только из того, что уже есть",
        "веб не используй",
    ],
    "wants_fast_answer": [
        "ответь быстро",
        "коротко, без подробностей",
        "мне нужен быстрый ответ",
    ],
    "wants_source_saved_for_chat": [
        "сохрани это в источники",
        "оставь этот текст для дальнейшей работы",
        "будем дальше работать по этому материалу",
        "запомни этот источник в этом чате",
    ],
    "wants_existing_source_reused": [
        "используй то, что уже сохранено",
        "опирайся на материал этого чата",
        "работай по уже найденному",
    ],
    "wants_verification": [
        "проверь факты",
        "перепроверь по источникам",
        "убедись, что это правда",
    ],
}

# Instructions that must strengthen retrieval into a deep web pass.
STRENGTHENING_INTENTS = {
    "wants_deep_search",
    "wants_multi_source_check",
    "wants_primary_source",
    "wants_verification",
}


def _route_reply(**intents: bool) -> str:
    return json.dumps({
        "retrieval": "none",
        "reasoning": "low",
        "verification": False,
        "freshness_required": False,
        "task_type": "other",
        "intents": intents,
    })


def _run_router(monkeypatch, request: str, reply: str, *_, titles=None):
    async def stream(_model_id, _messages):
        yield reply

    monkeypatch.setattr(providers, "stream_answer", stream)

    async def run():
        return await choose_retrieval_route(
            "mock:test",
            request,
            "Локальных данных нет",
            requested_web_search=False,
            requested_deep_research=False,
            chat_source_titles=titles,
        )

    return asyncio.run(run())


def test_any_wording_of_the_same_instruction_gets_the_same_behaviour(monkeypatch):
    for intent, phrasings in INSTRUCTION_PHRASINGS.items():
        expected = "deep_web" if intent in STRENGTHENING_INTENTS else "none"
        for phrasing in phrasings:
            route = _run_router(monkeypatch, phrasing, _route_reply(**{intent: True}))

            assert getattr(route.intents, intent) is True, (intent, phrasing)
            assert route.retrieval == expected, (intent, phrasing, route.retrieval)


def test_a_phrase_list_would_not_have_been_enough():
    """The same intent is expressed with no shared wording at all."""
    for intent, phrasings in INSTRUCTION_PHRASINGS.items():
        assert len(phrasings) >= 3, intent


def test_explicit_no_web_beats_an_explicit_request_for_the_web(monkeypatch):
    route = _run_router(
        monkeypatch,
        "копни поглубже, но без интернета",
        json.dumps({
            "retrieval": "deep_web",
            "reasoning": "high",
            "verification": True,
            "freshness_required": False,
            "task_type": "comparison",
            "intents": {"wants_deep_search": True, "wants_no_web": True},
        }),
    )

    assert route.retrieval == "none"
    assert route_uses_web(route) == (False, False)


def test_no_web_falls_back_to_saved_material_instead_of_the_web(monkeypatch):
    # The user banned the web after the router had already chosen a web route:
    # the saved chat material is the only honest local replacement for it.
    route = _run_router(
        monkeypatch,
        "ответь без интернета",
        json.dumps({
            "retrieval": "web",
            "reasoning": "low",
            "verification": False,
            "freshness_required": True,
            "task_type": "current_fact",
            "intents": {"wants_no_web": True},
        }),
        titles=["Колобок"],
    )

    assert route.retrieval == "chat_sources"
    assert route_uses_web(route) == (False, False)


def test_no_web_leaves_a_plain_local_answer_alone(monkeypatch):
    # A ban is not an instruction to use chat material that the router did not ask for.
    route = _run_router(
        monkeypatch, "ответь без интернета", _route_reply(wants_no_web=True),
        titles=["Колобок"],
    )

    assert route.retrieval == "none"
    assert route_uses_web(route) == (False, False)


def test_primary_source_request_strengthens_retrieval(monkeypatch):
    route = _run_router(
        monkeypatch, "нужен оригинальный текст, а не пересказ",
        _route_reply(wants_primary_source=True),
    )

    assert route_uses_web(route) == (True, True)
    assert route.task_type == "write_from_source"


def test_asking_to_think_harder_does_not_switch_the_web_on(monkeypatch):
    route = _run_router(
        monkeypatch, "не спеши, рассуди тщательно", _route_reply(wants_more_reasoning=True)
    )

    assert route.retrieval == "none"
    assert route_uses_web(route) == (False, False)


def test_a_rejection_is_not_reported_again_on_every_later_turn():
    """One correction must not make every later turn reject the material again."""
    route = SimpleNamespace(intents=WriteIntents(rejects_previous_material=True))

    assert material_rejected_now(route, "попробуй еще раз", {"src"}) is False
    assert material_rejected_now(route, "это не тот сборник", {"src"}) is True
    # Nothing recorded yet: the model's semantic reading still counts.
    assert material_rejected_now(route, "попробуй еще раз", set()) is True


def test_the_task_label_comes_from_the_informative_request():
    history = [
        SimpleNamespace(role="user", content="попробуй еще раз"),
        SimpleNamespace(
            role="user",
            content="8 класс год неизвестно, попробуй поискать другие источники они идут почти последовательно",
        ),
    ]

    assert task_statement_from_history(history, "попробуй еще раз").startswith("8 класс год неизвестно")
    assert task_statement_from_history([], "попробуй еще раз") == "попробуй еще раз"


def test_a_requested_search_is_not_replaced_by_known_links():
    from wristmind_server.worker import RetrievalRoute, WriteIntents

    def route(**intents):
        return RetrievalRoute(
            retrieval="deep_web", reasoning="high", verification=False,
            freshness_required=False, task_type="other", intents=WriteIntents(**intents),
        )

    # The exact wordings the owner used in production.
    assert needs_fresh_search(route(), "найди эту задачу в интернете по моему описанию выше") is True
    assert needs_fresh_search(route(), "попробуй поискать другие источники они идут почти последовательно") is True
    assert needs_fresh_search(route(rejects_previous_material=True), "попробуй еще раз") is True
    assert needs_fresh_search(route(), "поищи в интернете глубже по этому описанию") is True
    # An ordinary comparison keeps the cheap reuse of links already found.
    assert needs_fresh_search(route(), "Сравни две последние версии по функциям") is False
    # "Тот PDF" points at material already known: no new query is needed.
    assert needs_fresh_search(route(wants_primary_source=True), "Найди тот PDF и выведи задачу про бревна") is False


def test_rejecting_the_material_used_here_returns_to_searching(monkeypatch):
    """«Это не тот сборник» must not be answered from the same wrong document."""
    route = _run_router(
        monkeypatch, "Это не тот сборник", _route_reply(rejects_previous_material=True),
        titles=["Стратегии"],
    )

    assert route.intents.rejects_previous_material is True
    assert route.retrieval == "deep_web"
    assert route.verification is True and route.safeguarded is True


def test_no_web_still_beats_a_rejected_material(monkeypatch):
    route = _run_router(
        monkeypatch, "Не тот сборник, но в интернет не лезь",
        _route_reply(rejects_previous_material=True, wants_no_web=True),
        titles=["Стратегии"],
    )

    assert route.retrieval == "none"


def test_a_rejected_material_does_not_force_a_search_when_speed_was_requested(monkeypatch):
    route = _run_router(
        monkeypatch, "Не тот, ответь быстро", 
        _route_reply(rejects_previous_material=True, wants_fast_answer=True),
        titles=["Стратегии"],
    )

    assert route.retrieval == "none"
    assert route.safeguarded is False


def test_router_prompt_carries_the_continuation_rule(monkeypatch):
    """A short follow-up must be recognisable as the same source hunt."""
    seen = ""

    async def stream(_model_id, messages):
        nonlocal seen
        seen = messages[0]["content"]
        yield _route_reply()

    monkeypatch.setattr(providers, "stream_answer", stream)
    asyncio.run(choose_retrieval_route(
        "mock:test", "А муниципальный этап?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
    ))

    assert "Продолжение задачи поиска материала" in seen
    assert "rejects_previous_material" in seen
    assert "сменил тему" in seen


def test_reusing_saved_material_avoids_a_new_search(monkeypatch):
    route = _run_router(
        monkeypatch, "опирайся на материал этого чата",
        _route_reply(wants_existing_source_reused=True),
        titles=["Колобок"],
    )

    assert route.retrieval == "chat_sources"
    assert route_uses_web(route) == (False, False)


def test_saving_material_affects_the_working_source_not_the_route():
    route = apply_intent_safeguards(
        RetrievalRoute(
            retrieval="none", reasoning="low", verification=False,
            freshness_required=False, task_type="other",
            intents=WriteIntents(wants_source_saved_for_chat=True),
        ),
        has_chat_material=False,
    )

    # The instruction is carried through for the Working Source decision and
    # never turns into permanent or global storage behaviour.
    assert route.intents.wants_source_saved_for_chat is True
    assert route.retrieval == "none"


def test_fast_answer_request_relaxes_the_evidence_gate():
    results = {"r1": WebSearchResult("Текст", "https://example.test/text", "фрагмент")}
    researched = RetrievalRoute(
        retrieval="deep_web", reasoning="high", verification=True,
        freshness_required=False, task_type="comparison",
        intents=WriteIntents(wants_deep_search=True),
    )
    quick = researched.model_copy(update={"intents": WriteIntents(wants_fast_answer=True)})

    assert deep_web_open_requirement(researched, "сравни", results, set(), {}) == "r1"
    assert deep_web_open_requirement(quick, "сравни", results, set(), {}) is None


def test_router_reports_where_its_decision_came_from(monkeypatch):
    answered = _run_router(monkeypatch, "Что такое биссектриса?", _route_reply())
    assert answered.router_source == "model"

    async def broken(_model_id, _messages):
        yield "```"

    monkeypatch.setattr(providers, "stream_answer", broken)
    fallback = asyncio.run(choose_retrieval_route(
        "mock:test", "Что такое биссектриса?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
    ))
    assert fallback.router_source == "fallback"


def test_router_is_asked_for_meaning_based_intents(monkeypatch):
    seen = ""

    async def stream(_model_id, messages):
        nonlocal seen
        seen = messages[0]["content"]
        yield _route_reply()

    monkeypatch.setattr(providers, "stream_answer", stream)
    asyncio.run(choose_retrieval_route(
        "mock:test", "привет", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
    ))

    for intent in WriteIntents.model_fields:
        assert intent in seen, intent
    assert "Оценивай смысл, а не отдельные слова" in seen


def test_router_diagnostics_describe_a_single_valid_attempt(monkeypatch):
    events = []

    async def stream(_model_id, _messages):
        yield _route_reply()

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Что такое биссектриса?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
        diagnostic=events.append,
    ))

    assert route.attempts_count == 1
    assert route.total_router_ms is not None
    assert [event["phase"] for event in events] == ["start", "finish"]
    assert [event["attempt"] for event in events] == [1, 1]
    assert events[1]["result_status"] == "valid"
    assert events[1]["retry_reason"] is None
    assert events[1]["duration_ms"] >= 0


def test_official_deepseek_router_disables_thinking_and_reuses_connection(monkeypatch):
    from wristmind_server.config import DEEPSEEK_MODEL_ID, Settings
    from wristmind_server.providers import ProviderRouter
    import wristmind_server.worker as worker

    assert Settings().router_model_id == DEEPSEEK_MODEL_ID
    provider = ProviderRouter(Settings(mock_providers=False, deepseek_api_key="test-key"))
    seen = []

    async def stream(_url, _headers, _model, _messages, **kwargs):
        seen.append((kwargs["extra_payload"], kwargs["client"]))
        yield _route_reply()

    monkeypatch.setattr(provider, "_stream_openai_compatible", stream)
    monkeypatch.setattr(worker, "providers", provider)

    async def run():
        for _ in range(2):
            route = await choose_retrieval_route(
                DEEPSEEK_MODEL_ID,
                "Что такое биссектриса?",
                "Локальных данных нет",
                requested_web_search=False,
                requested_deep_research=False,
            )
            assert route.retrieval == "none"
        await provider.aclose()

    asyncio.run(run())
    assert [payload for payload, _ in seen] == [
        {"thinking": {"type": "disabled"}},
        {"thinking": {"type": "disabled"}},
    ]
    assert seen[0][1] is seen[1][1]


def test_router_diagnostics_mark_a_truncated_reply_and_its_retry(monkeypatch):
    replies = iter(['{"retrieval":"web","reasoning":"lo', _route_reply()])
    events = []

    async def stream(_model_id, _messages):
        yield next(replies)

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Что такое биссектриса?", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
        diagnostic=events.append,
    ))

    assert route.attempts_count == 2
    assert route.router_source == "retry"
    finished = [event for event in events if event["phase"] == "finish"]
    assert [event["attempt"] for event in finished] == [1, 2]
    assert finished[0]["result_status"] == "truncated"
    assert finished[0]["retry_reason"] == "truncated"
    assert finished[1]["result_status"] == "valid"
    assert finished[0]["received_chars"] > 0


def test_router_diagnostics_report_a_network_error(monkeypatch):
    from wristmind_server.providers import ProviderError

    events = []

    async def stream(_model_id, _messages):
        raise ProviderError("Не удалось подключиться к провайдеру") from ConnectionError("reset")
        yield  # pragma: no cover

    monkeypatch.setattr(providers, "stream_answer", stream)
    route = asyncio.run(choose_retrieval_route(
        "mock:test", "Сравни два стандарта", "Локальных данных нет",
        requested_web_search=False, requested_deep_research=False,
        diagnostic=events.append,
    ))

    finished = [event for event in events if event["phase"] == "finish"]
    assert [event["result_status"] for event in finished] == ["network_error", "network_error"]
    assert route.router_source == "fallback"
    assert route.attempts_count == 2
