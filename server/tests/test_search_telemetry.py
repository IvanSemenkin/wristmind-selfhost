import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from wristmind_server import search_trace, latency_trace
from wristmind_server.config import Settings
from wristmind_server.providers import ProviderRouter, ProviderError
from wristmind_server.search_metrics import aggregate, recent_events
from wristmind_server.web_search import open_web_page, WebSearchUnavailable

@pytest.fixture(autouse=True)
def clean_database():
    yield  # Pure telemetry/transport fixtures; no DB use.

@pytest.fixture
def records(monkeypatch):
    rows=[]
    monkeypatch.setattr(latency_trace, 'record', lambda event, **fields: rows.append({'event':event, **fields}))
    return rows


def test_trace_rejects_sensitive_fields_and_error_body(records):
    secret='sk-' + 'test-secret-and-private-document'  # synthetic token for redaction test
    with search_trace.scope(secret) as trace:
        trace.event('STAGE', stage='searxng', duration_ms=12, query=secret, title=secret, api_key=secret,
                    url='https://example.org/?token='+secret, reason='HTTP '+secret, text=secret)
        with pytest.raises(ValueError):
            with search_trace.stage('html_extract', chars_in=999):
                raise ValueError(secret)
    assert secret not in json.dumps(records) and 'ValueError' in json.dumps(records)
    assert records[0]['job_id'] == search_trace.fingerprint(secret)
    assert records[-1]['status']=='error' and records[-1]['rss_bytes']>0


def test_provider_stream_records_usage_even_without_choices(records, monkeypatch):
    payload='data: {"choices":[{"delta":{"content":"ОК"}}]}\n\n' + \
            'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":3,"total_tokens":14}}\n\ndata: [DONE]\n\n'
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(
        lambda request: httpx.Response(200,text=payload)), **kw))
    async def run():
        provider=ProviderRouter(Settings(mock_providers=False,deepseek_api_key='private-api-key'))
        with search_trace.scope('usage-job') as trace:
            async def choose():
                return ''.join([part async for part in provider.stream_answer('deepseek:deepseek-chat',[{'role':'user','content':'private request'}])])
            answer=await search_trace.purpose('search_planner')(choose)()
            assert answer=='ОК' and trace.llm_calls==1
            assert trace.tokens=={'prompt_tokens':11,'completion_tokens':3,'total_tokens':14}
    asyncio.run(run())
    llm=next(row for row in records if row['event']=='SEARCH_LLM')
    assert llm['purpose']=='search_planner' and llm['total_tokens']==14
    assert 'private' not in json.dumps(records)


def test_missing_usage_is_unavailable_and_nested_call_counted_once(records):
    async def run():
        provider=ProviderRouter(Settings(mock_providers=True))
        with search_trace.scope('job') as trace:
            with search_trace.llm_call('vision_ocr'):
                parts=[part async for part in provider.stream_answer('deepseek:deepseek-chat',[{'role':'user','content':'secret'}])]
            assert parts and trace.llm_calls==1 and trace.tokens=={}
    asyncio.run(run())
    assert len(records)==1 and 'total_tokens' not in records[0]


def test_cancelled_llm_records_finish_and_propagates(records):
    async def run():
        @search_trace.observed_stream
        async def slow():
            await asyncio.sleep(60)
            yield 'unused'
        async def consume():
            with search_trace.scope('cancel-job'):
                async for _ in slow(): pass
        task=asyncio.create_task(consume())
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(run())
    assert records[-1]['event']=='SEARCH_LLM' and records[-1]['status']=='cancelled'


def test_traced_answer_summary_cancel_and_context_isolation(records):
    async def run():
        @search_trace.traced_answer
        async def answer(job_id):
            trace=search_trace.current(); trace.received_ms=1;trace.route='deep_web';trace.searches=1
            await asyncio.sleep(60)
        task=asyncio.create_task(answer('job'))
        await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert search_trace.current() is None
    asyncio.run(run())
    summary=records[-1]
    assert summary['event']=='SEARCH_SUMMARY' and summary['status']=='cancelled'
    assert summary['searches']==1 and summary['stop_reason']=='cancelled'


def test_metrics_percentiles_ratios_unknown_usage_and_bounded_file(tmp_path):
    events=[{'event':'SEARCH_SUMMARY','job_id':str(n),'route':'web' if n<3 else 'deep_web',
        'status':'complete','response_ms':100*n,'llm_calls':n,'opens':2,'successful_opens':1,
        'verified_sources':n%2,'cache_hits':1,'cache_misses':1} for n in range(1,5)]
    # Duplicate records don't inflate the population.
    info=aggregate(events+[events[0]])
    assert info['requests']==4 and info['response_latency']['web']=={'n':2,'p50_ms':100,'p95_ms':200}
    assert info['mean_llm_calls']==2.5 and info['successful_open_ratio']==.5
    assert info['without_confirmed_source_ratio']==.5 and info['cache_hit_ratio']==.5
    assert info['total_tokens_reported'] is None
    path=tmp_path/'trace.jsonl';path.write_text('invalid\n'+ '\n'.join(json.dumps(x) for x in events))
    assert len(recent_events(path,max_bytes=1_000_000,limit=2))==2
    assert len(recent_events(path,max_bytes=100,limit=2))<=1


def test_local_download_extraction_and_resource_trace(records,monkeypatch):
    original=httpx.AsyncClient
    html='<html><body><article><h1>Title</h1><p>'+'Original paragraph. '*70+'</p></article></body></html>'
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(
        lambda r:httpx.Response(200,text=html,headers={'content-type':'text/html'})),**kw))
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host',AsyncMock())
    async def run():
        with search_trace.scope('html-job'):
            return await open_web_page('https://example.org/long?private=query',timeout_seconds=1,max_download_bytes=10000,max_redirects=2)
    url,text=asyncio.run(run())
    stages={row['stage']:row for row in records if row['event']=='SEARCH_STAGE'}
    assert len(text)>1000 and {'download','trafilatura','html_extract'}<=stages.keys()
    assert stages['trafilatura']['chars_out']==len(text) and stages['trafilatura']['child_peak_rss_bytes']>0
    assert stages['download']['bytes_in']>len(text) and 'private=query' not in json.dumps(records)


def test_failed_download_still_records_duration(records,monkeypatch):
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw: original(transport=httpx.MockTransport(
        lambda r:httpx.Response(403)),**kw))
    monkeypatch.setattr('wristmind_server.web_search._resolve_public_host',AsyncMock())
    async def run():
        with search_trace.scope('job'):
            await open_web_page('https://example.org/fail',timeout_seconds=1,max_download_bytes=10000,max_redirects=2)
    with pytest.raises(WebSearchUnavailable,match='HTTP 403'):asyncio.run(run())
    stage = next(item for item in reversed(records) if item.get('stage') == 'download')
    assert stage['status']=='error'


def test_searxng_records_time_without_query(records, monkeypatch):
    from wristmind_server.web_search import search_web
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(
        lambda r: httpx.Response(200,json={'results':[{'title':'Original','url':'https://example.org/a','content':'Found'}]})), **kw))
    async def run():
        with search_trace.scope('search'):
            result = await search_web('http://searxng:8080', 'private user sentence', timeout_seconds=1, result_limit=3)
            assert len(result)==1
    asyncio.run(run())
    stage = next(item for item in reversed(records) if item.get('stage') == 'searxng')
    assert stage['duration_ms']>=0
    assert 'private user sentence' not in json.dumps(records)


def test_pdf_ordinary_large_and_limits_are_traced(records, monkeypatch):
    from test_web_pdf import make_pdf
    from wristmind_server.web_search import extract_web_pdf
    from wristmind_server.config import get_settings
    async def run():
        with search_trace.scope('pdf'):
            for count in (1,30):
                data=make_pdf(*['A long original page with real text. '*70]*count)
                text=await extract_web_pdf(data)
                assert text.count('## Страница ')==count
    asyncio.run(run())
    stages=[x for x in records if x.get('stage')=='pdf_extract']
    assert len(stages)==2 and stages[1]['chars_out']>stages[0]['chars_out']*25
    assert all(x['rss_bytes']>0 for x in stages)
    monkeypatch.setattr(get_settings(),'max_pdf_pages',1)
    async def reject():
        with search_trace.scope('pdf-limit'):
            await extract_web_pdf(make_pdf('Original page text '*10,'Second page text '*10))
    with pytest.raises(WebSearchUnavailable,match='число страниц'):asyncio.run(reject())
    assert records[-1]['stage']=='pdf_extract' and records[-1]['status']=='error'


def test_agent_cancellation_does_not_save_or_continue(records):
    from wristmind_server.search_agent import run_search_agent
    from wristmind_server.web_search import WebSearchResult
    item=WebSearchResult('Full original text','https://example.org/book','Original')
    saved=[]
    async def run():
        entered=asyncio.Event()
        async def search(q):return [item]
        async def open_page(r):entered.set();await asyncio.sleep(60)
        async def plan(*a):
            from types import SimpleNamespace
            return SimpleNamespace(action='open',result_id='r1')
        async def save(*a):saved.append(a)
        async def state(*a):pass
        with search_trace.scope('cancel') as trace:
            task=asyncio.create_task(run_search_agent(query='original',previous=[],deep=True,max_seconds=90,
                max_steps=4,max_searches=2,max_opens=1,search=search,open_page=open_page,plan=plan,save=save,
                state=state,required_open=lambda *a:'r1'))
            await asyncio.wait_for(entered.wait(),1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert trace.searches==1 and trace.opens==1 and trace.successful_opens==0
            assert saved==[]
    asyncio.run(run())
