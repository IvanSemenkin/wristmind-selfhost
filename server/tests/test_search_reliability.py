"""Local search scenarios: no live SearXNG, providers, or production traffic."""
import asyncio
import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest

from wristmind_server.search_agent import run_search_agent, PlannerFailure
from wristmind_server.search_ranking import rank_results, obvious_source, document_check
from wristmind_server.web_search import WebSearchResult, WebSearchResults, WebSearchUnavailable, search_web
from wristmind_server.worker import choose_web_action, RequestAnchor, providers

@pytest.fixture(autouse=True)
def clean_database():
    # These scenarios use only pure callbacks; no DB or API persistence.
    yield


QUERY = 'Найди полный оригинальный текст повести А. С. Пушкина "Капитанская дочка" и проверь наличие всех 14 глав'
BOOK = WebSearchResult('Пушкин — Капитанская дочка, полный текст', 'https://library.example/book', 'Оригинальный текст повести')
SUMMARY = WebSearchResult('Капитанская дочка — краткое содержание', 'https://study.example/summary', 'Пересказ по главам')
TEXT = 'Капитанская дочка\n' + '\n'.join(f'## Глава {n}\n' + f'Оригинальный текст главы {n}. ' * 40 for n in range(1, 15))


def options(**overrides):
    defaults = dict(query=QUERY, previous=[], deep=True, max_seconds=1, max_steps=6,
                    max_searches=3, max_opens=2, optimise=True,
                    search=AsyncMock(return_value=[SUMMARY, BOOK]),
                    open_page=AsyncMock(return_value=(BOOK.url, TEXT)),
                    plan=AsyncMock(return_value=SimpleNamespace(action='answer')),
                    save=AsyncMock(return_value=None), state=AsyncMock(), required_open=lambda *args: None)
    defaults.update(overrides)
    return defaults


def run(**overrides):
    return asyncio.run(run_search_agent(**options(**overrides)))


def test_full_original_ranking_and_zero_planner_calls():
    result = run()
    assert result.completion == 'success' and result.planner_calls == 0
    assert result.checks['r1']['found'] == list(range(1, 15))
    assert result.checks['r1']['scope'] == 'section_headings_and_body_presence_only'
    assert result.results['r1'] == BOOK
    assert result.ranking['r2']['score'] < result.ranking['r1']['score']


def test_missing_chapter_and_contents_list_are_not_complete():
    partial = TEXT[:TEXT.index('## Глава 14')]
    result = run(open_page=AsyncMock(return_value=(BOOK.url, partial)))
    assert result.completion == 'partially_verified'
    assert result.checks['r1']['missing'] == [14]
    contents = '\n'.join(f'Глава {n}\n' for n in range(1, 15))
    assert not document_check(QUERY, BOOK.title, contents)['verified']


def test_concrete_section_read_far_beyond_initial_fragment():
    query = 'Найди раздел 14 документа "Регламент"'
    item = WebSearchResult('Регламент — полный текст', 'https://agency.example/regulation', 'Оригинал документа')
    text = 'Регламент\nРаздел 1\n' + 'Введение. ' * 4000 + '\nРаздел 14\nНужное правило.'
    result = run(query=query, search=AsyncMock(return_value=[item]), open_page=AsyncMock(return_value=(item.url, text)))
    assert result.completion == 'success' and result.planner_calls == 0
    assert 'Нужное правило' in result.inspected['r1'][2]
    assert len(result.inspected['r1'][2]) <= 12000


def test_conflicting_sources_do_not_stop_on_first_save():
    first = WebSearchResult('Отчёт о численности', 'https://first.example/report', '10 человек')
    second = WebSearchResult('Другой отчёт о численности', 'https://second.example/report', '20 человек')
    saved = object()
    save = AsyncMock(return_value=saved)
    async def plan(query, results, inspected, previous):
        return SimpleNamespace(action='open', result_id='r1') if not inspected else SimpleNamespace(action='answer')
    async def open_page(item):
        return item.url, item.snippet
    result = run(query='Сравни противоречивые отчёты о численности из разных источников',
                 search=AsyncMock(return_value=[first, second]), plan=plan, open_page=open_page,
                 save=save)
    assert len(result.opened) == 2 and result.source is saved
    assert result.completion == 'success' and save.await_count == 1
    assert {page[2] for page in result.opened.values()} == {'10 человек', '20 человек'}


@pytest.mark.parametrize('failure', ['HTTP 403', 'empty'])
def test_dead_site_or_empty_extraction_is_source_error(failure):
    async def open_page(item):
        if failure == 'empty':
            return item.url, ''
        raise WebSearchUnavailable(failure)
    result = run(search=AsyncMock(return_value=[BOOK]), open_page=open_page)
    assert result.completion == 'source_error' and result.errors
    assert not result.opened


def test_invalid_planner_json_recovers_without_asserting_absence(monkeypatch):
    async def invalid(*args, **kwargs):
        yield 'not JSON'
    monkeypatch.setattr(providers, 'stream_answer', invalid)
    item = WebSearchResult('Правила документа', 'https://agency.example/doc', 'Документ правила')
    async def plan(query, results, inspected, previous):
        return await choose_web_action('mock:test', RequestAnchor(original_request=query, main_subject=query, task_type='other'), query, results, inspected, previous)
    result = run(query='Найди правила документа', search=AsyncMock(return_value=[item]), plan=plan,
                 open_page=AsyncMock(return_value=(item.url, 'Прочитанные правила документа')))
    assert result.opened and result.completion == 'partially_verified'
    assert result.stop_reason == 'planner_error' and result.warnings


def test_partial_searxng_response_and_ranking_before_limit(monkeypatch):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'results': [{'title': x.title, 'url': x.url, 'content': x.snippet} for x in [SUMMARY, BOOK]],
        'unresponsive_engines': [['engine', 'timeout']]}))
    class Client(original):
        def __init__(self, **kwargs):
            super().__init__(transport=transport, **kwargs)
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    results = asyncio.run(search_web('http://searxng:8080', QUERY, timeout_seconds=1, result_limit=1))
    assert results == [BOOK] and results.warnings
    outcome = run(search=AsyncMock(return_value=results))
    assert outcome.completion == 'partially_verified' and outcome.warnings
    assert outcome.checks['r1']['verified']


def test_repeated_action_moves_to_other_source_within_budget():
    first = WebSearchResult('Правила', 'https://one.example/doc', 'Правила')
    second = WebSearchResult('Правила 2026', 'https://two.example/doc', 'Правила')
    result = run(query='Правила', search=AsyncMock(return_value=[first, second]),
                 plan=AsyncMock(return_value=SimpleNamespace(action='open', result_id='r1')),
                 open_page=AsyncMock(side_effect=lambda item: (item.url, 'Правила документа')))
    assert len(result.opened) == 2 and result.planner_calls <= 6
    assert result.completion == 'limits_exhausted' and result.stop_reason == 'repeated_action'


def test_time_limit_and_comparison_with_only_one_source():
    async def slow(*args):
        await asyncio.sleep(1)
    result = run(max_seconds=.01, search=slow)
    assert result.completion == 'limits_exhausted' and result.timed_out
    partial = run(query='Сравни разные источники о Капитанской дочке',
                  search=AsyncMock(return_value=[BOOK]), save=AsyncMock(return_value='saved'),
                  plan=AsyncMock(return_value=SimpleNamespace(action='open', result_id='r1')), max_steps=2)
    assert partial.completion != 'success' and len(partial.opened) == 1


def test_ambiguous_candidates_still_use_planner():
    alternative = WebSearchResult(BOOK.title, 'https://another.example/book', BOOK.snippet)
    assert obvious_source(QUERY, {'r1': BOOK, 'r2': alternative}, set()) is None
    result = run(search=AsyncMock(return_value=[BOOK, alternative]),
                 plan=AsyncMock(return_value=SimpleNamespace(action='open', result_id='r2')))
    assert result.planner_calls == 1 and result.opened['r2'][1] == BOOK.url


def test_wrong_author_and_mention_only_are_not_structural_success():
    wrong = WebSearchResult('Гоголь — Капитанская дочка, полный текст', 'https://wrong.example/book', 'Оригинал')
    assert obvious_source(QUERY, {'r1': wrong}, set()) is None
    assert not document_check(QUERY, wrong.title, TEXT)['verified']
    assert not document_check('Найди раздел 14 документа "Регламент"', 'Регламент',
                              'В разделе 14 описаны правила.')['verified']


def test_explicit_title_can_skip_query_rewrite_but_followup_cannot():
    from wristmind_server.search_ranking import self_contained_source_query
    assert self_contained_source_query(QUERY)
    assert self_contained_source_query('Найди раздел 14 документа "Регламент"')
    assert not self_contained_source_query('Найди другое издание "Капитанской дочки", полный текст')
    assert not self_contained_source_query('Найди полный текст той повести')


def test_fenced_planner_json_needs_no_retry(monkeypatch):
    async def fenced(*args, **kwargs):
        yield '```json\n{"action":"open","result_id":"r1"}\n```'
    monkeypatch.setattr(providers, 'stream_answer', fenced)
    action = asyncio.run(choose_web_action('mock:test', RequestAnchor(original_request=QUERY, main_subject=QUERY, task_type='other'),
                                          QUERY, {'r1': BOOK}, {}, None))
    assert action.action == 'open' and action.result_id == 'r1'


def test_irrelevant_search_is_partial_not_absence():
    wrong = WebSearchResult('Кулинария — полный текст', 'https://food.example/book', 'Рецепты')
    result = run(search=AsyncMock(return_value=[wrong]))
    assert result.completion != 'success' and result.warnings
    assert not result.opened and result.stop_reason == 'verification_incomplete'


def test_incomplete_first_book_is_not_saved_as_full_original():
    other = WebSearchResult(BOOK.title, 'https://other.example/book', BOOK.snippet)
    partial = TEXT[:TEXT.index('## Глава 14')]
    async def open_page(item):
        return item.url, partial if item.url == BOOK.url else TEXT
    save = AsyncMock(return_value='saved-full')
    result = run(search=AsyncMock(return_value=[BOOK, other]), open_page=open_page, save=save,
                 plan=AsyncMock(return_value=SimpleNamespace(action='open', result_id='r1')))
    assert len(result.opened) == 2 and result.completion == 'success'
    assert result.source == 'saved-full' and save.await_count == 1
    assert save.call_args.args[0].url == other.url


def test_missing_specific_section_is_partial_and_not_saved():
    item = WebSearchResult('Регламент — полный текст', 'https://agency.example/regulation', 'Оригинал')
    save = AsyncMock(return_value='wrong-section')
    result = run(query='Найди раздел 14 документа "Регламент"', search=AsyncMock(return_value=[item]),
                 open_page=AsyncMock(return_value=(item.url, 'Регламент\nРаздел 1\nТекст первого раздела.')), save=save)
    assert result.completion == 'partially_verified' and not result.checks['r1']['verified']
    assert result.source is None and save.await_count == 0


def test_commentary_with_fourteen_chapters_cannot_confirm_original():
    commentary = WebSearchResult('Повесть А. С. Пушкина "Капитанская дочка"', 'https://library.example/commentary', 'Пособие для учителя. Комментарий')
    commentary_text = 'КОММЕНТАРИЙ\nПособие для учителя\n' + TEXT
    check = document_check(QUERY, commentary.title, commentary_text)
    assert not check['verified'] and check['reason'] == 'secondary_not_original'
    assert rank_results(QUERY, [commentary, BOOK])[0] == BOOK
    result = run(search=AsyncMock(return_value=[commentary]),
                 open_page=AsyncMock(return_value=(commentary.url, commentary_text)),
                 plan=AsyncMock(return_value=SimpleNamespace(action='open', result_id='r1')))
    assert result.completion != 'success'
    assert result.stop_reason != 'structure_checked'
    assert 'Отклонён' in result.inspected['r1'][2]


def test_composite_request_reads_beyond_chapter_verification():
    query = QUERY + ', затем выдели 6 эпизодов, опираясь строго на найденный текст'
    plan = AsyncMock(return_value=SimpleNamespace(action='answer'))
    result = run(query=query, plan=plan)
    assert result.stop_reason == 'planner_answer'
    assert result.planner_calls >= 2
    assert result.deterministic_steps >= 2  # open + focused document read
    assert 'block' in result.inspected['r1'][2]


def test_rejected_save_does_not_stop_on_structure_checked():
    alternative = WebSearchResult('Пушкин Капитанская дочка оригинальный текст', 'https://other.example/book', 'Полный текст')
    save = AsyncMock(side_effect=[None, 'verified-saved-source'])
    result = run(require_saved_source=True, search=AsyncMock(return_value=[BOOK, alternative]), save=save,
                 open_page=AsyncMock(side_effect=lambda item: (item.url, TEXT)))
    assert save.await_count == 2 and result.source == 'verified-saved-source'
    assert len(result.opened) == 2
    assert result.stop_reason == 'structure_checked'  # only after actual save succeeds


def test_original_with_notes_after_front_matter_is_not_commentary():
    assert document_check(QUERY, BOOK.title, TEXT + '\nКомментарий\nПояснения редактора')['verified']


def test_foundational_source_accepts_fenced_json_without_false_rejection(monkeypatch):
    from wristmind_server import worker
    async def fenced(*args, **kwargs):
        yield '```json\n{"foundation":true}\n```'
    monkeypatch.setattr(worker.providers, 'stream_answer', fenced)
    assert asyncio.run(worker.is_foundational_source('mock:test', QUERY, [], BOOK.title, BOOK.url, TEXT, True))


def test_current_planner_contract_overrides_old_prompt_and_disables_thinking(monkeypatch):
    from wristmind_server import worker
    monkeypatch.setattr(worker, 'render_prompt', lambda *args: 'Старый формат планировщика')
    async def valid(model, messages, **kwargs):
        assert 'Единственный актуальный формат JSON' in messages[0]['content']
        assert 'сначала find/read' in messages[0]['content']
        assert kwargs['thinking'] is False
        yield '{"action":"open","result_id":"r1"}'
    monkeypatch.setattr(worker.providers, 'stream_answer', valid)
    action = asyncio.run(worker.choose_web_action('deepseek:deepseek-flash',
        RequestAnchor(original_request=QUERY, main_subject=QUERY, task_type='find_source'),
        QUERY, {'r1': BOOK}, {}, None))
    assert action.action == 'open'


def test_multiple_document_reads_keep_evidence_within_fragment_budget():
    text = TEXT.replace('Оригинальный текст главы 1. ', 'УникальныйЭпизодА. ', 1)
    text = text.replace('Оригинальный текст главы 14. ', 'УникальныйЭпизодБ. ', 1)
    plan = AsyncMock(side_effect=[
        SimpleNamespace(action='find', result_id='r1', query='УникальныйЭпизодА'),
        SimpleNamespace(action='find', result_id='r1', query='УникальныйЭпизодБ'),
        SimpleNamespace(action='answer')])
    result = run(query=QUERY + ', затем выдели эпизоды', plan=plan,
                 open_page=AsyncMock(return_value=(BOOK.url, text)))
    evidence = result.inspected['r1'][2]
    assert 'УникальныйЭпизодА' in evidence and 'УникальныйЭпизодБ' in evidence
    assert len(evidence) <= 12000
