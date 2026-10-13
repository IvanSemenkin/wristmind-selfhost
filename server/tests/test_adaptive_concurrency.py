"""Local only: injected pressure, mocked URLs, bounded threads and subprocesses."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
import statistics
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from wristmind_server import resource_controller as rc, web_search, search_trace
from wristmind_server.resource_controller import AdaptiveResourceController, ResourceSample, ResourceUnavailable, MB, linux_sample
from wristmind_server.search_agent import run_search_agent
from wristmind_server.web_search import WebSearchResult, WebSearchUnavailable


@pytest.fixture(autouse=True)
def clean_database():
    yield  # pure tests; no database


def controller(mem=1100, cpu=.2, **kwargs):
    return AdaptiveResourceController(sampler=lambda: ResourceSample(mem * MB, cpu), **kwargs)


def test_pressure_modes_and_hysteresis_and_safe_fallback():
    now, value = [0.], [ResourceSample(1100*MB, .2)]
    c = AdaptiveResourceController(sampler=lambda: value[0], clock=lambda: now[0])
    def sample(mem, cpu=.2):
        now[0] += 2.1; value[0] = ResourceSample(mem * MB if mem is not None else None, cpu);c.refresh()
    sample(1100);assert c.mode == 'NORMAL' and c.limit('http') == 2
    sample(750);assert c.mode == 'BUSY' and c.limit('http') == 1 and c.limit('index') == 0
    sample(480);assert c.mode == 'CRITICAL' and c.limit('html') == 0
    for _ in range(8):
        sample(520);sample(490)
        assert c.mode == 'CRITICAL'
    sample(700);assert c.mode == 'CRITICAL'
    sample(700);assert c.mode == 'BUSY'
    sample(1100);sample(1100);assert c.mode == 'NORMAL'
    sample(1600);assert c.limit('http') == 3 and c.limit('search') == 2
    sample(None, None);assert c.limit('http') == 2 and c.limit('search') == 1
    sample(1200, 1.0);assert c.mode == 'BUSY'
    sample(1200, 1.6);assert c.mode == 'CRITICAL'


def test_cgroup_memory_parent_and_cpu_limits(tmp_path):
    proc, cg = tmp_path/'proc', tmp_path/'cgroup'
    (proc/'self').mkdir(parents=True);(cg/'container').mkdir(parents=True)
    (proc/'meminfo').write_text('MemAvailable: 2000000 kB\n')
    (proc/'loadavg').write_text('0.50 0 0 0\n')
    (proc/'self/cgroup').write_text('0::/container\n')
    (cg/'memory.max').write_text(str(1000*MB));(cg/'memory.current').write_text(str(700*MB))
    (cg/'container/memory.max').write_text('max');(cg/'cpu.max').write_text('100000 100000')
    sample=linux_sample(proc,cg)
    assert sample.available_bytes == 300*MB and sample.cpu_load == .5
    missing=linux_sample(tmp_path/'missing', tmp_path/'missingcg')
    assert missing.available_bytes is None and missing.cpu_load is None


def test_global_slot_limits_fairness_and_timeouts():
    async def scenario():
        c=controller(wait_seconds=.1, max_waiters=2)
        a=await c.acquire('http');b=await c.acquire('http')
        order=[]
        async def wait(index):
            async with c.slot('http'):
                order.append(index);await asyncio.sleep(.01)
        tasks=[asyncio.create_task(wait(i)) for i in range(2)]
        await asyncio.sleep(.01)
        with pytest.raises(ResourceUnavailable, match='очередь'):
            await c.acquire('http')
        a.release();await asyncio.gather(*tasks);b.release()
        assert order == [0,1] and c.peak['http'] == 2
        assert sum(c.active.values()) == 0 and not c.waiters
        a=await c.acquire('pdf')
        with pytest.raises(ResourceUnavailable):await c.acquire('pdf', timeout=.01)
        a.release();assert not c.waiters and c.active['pdf']==0
    asyncio.run(scenario())


def test_cancellation_in_wait_and_active_slot_no_leaks():
    async def scenario():
        c=controller();lease=await c.acquire('html')
        task=asyncio.create_task(c.acquire('html'));await asyncio.sleep(.01);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert c.active['html']==1 and not c.waiters
        lease.release()
        entered=asyncio.Event()
        async def active():
            async with c.slot('html'):
                entered.set();await asyncio.sleep(10)
        task=asyncio.create_task(active());await entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert sum(c.active.values())==0 and not c.waiters
    asyncio.run(scenario())


def test_cancelled_physical_thread_holds_slot_and_event_loop_responds():
    async def scenario():
        c=controller(wait_seconds=.03);start=threading.Event();finish=threading.Event()
        def physical():start.set();finish.wait(1);return 'done'
        task=asyncio.create_task(c.thread('pdf', physical))
        while not start.is_set():await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert c.active['pdf']==1 and len(c.detached)==1
        with pytest.raises(ResourceUnavailable):await c.acquire('pdf')
        finish.set()
        while c.detached:await asyncio.sleep(.001)
        assert c.active['pdf']==0 and not c.waiters
        async with c.slot('pdf'):pass
    asyncio.run(scenario())


def test_low_memory_fails_bounded_but_network_and_planner_still_work():
    async def scenario():
        c=controller(400, wait_seconds=.01)
        with pytest.raises(ResourceUnavailable):
            async with c.slot('html'):pytest.fail('critical HTML started')
        async with c.slot('http'):pass
        async with c.slot('planner'):pass
        assert c.mode=='CRITICAL' and not c.waiters and sum(c.active.values())==0
    asyncio.run(scenario())


def test_sampler_is_idle_and_at_most_once_per_two_seconds():
    async def scenario():
        calls=[];now=[0.]
        def sample():calls.append(1);return ResourceSample(1100*MB,.2)
        c=AdaptiveResourceController(sampler=sample, clock=lambda:now[0])
        assert not calls
        for _ in range(10):
            async with c.slot('http'):pass
        assert len(calls)==1
        now[0]=2.1
        async with c.slot('http'):pass
        assert len(calls)==2
    asyncio.run(scenario())


def test_parallel_http_releases_slots_before_extraction_and_preserves_ssrf(monkeypatch):
    original=httpx.AsyncClient
    original_resolve=web_search._resolve_public_host
    async def handler(request):
        await asyncio.sleep(.02)
        return httpx.Response(200,text='<article><p>Fixture</p></article>',headers={'content-type':'text/html'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(web_search,'_resolve_public_host',AsyncMock())
    async def scenario():
        c=controller();monkeypatch.setattr(web_search,'resources',lambda:c)
        active=0
        async def extract(html,**kw):
            nonlocal active
            async with c.slot('html'):
                assert c.active['http']<2
                active+=1;assert active==1;await asyncio.sleep(.01);active-=1
                return 'Extracted fixture'
        monkeypatch.setattr(web_search,'extract_web_html',extract)
        out=await asyncio.gather(*(web_search.open_web_page('https://example.org/'+str(n),
            timeout_seconds=1,max_download_bytes=2000,max_redirects=2) for n in range(2)))
        assert [url for url,_ in out]==['https://example.org/0','https://example.org/1']
        assert c.peak['http']==2 and c.peak['html']==1 and sum(c.active.values())==0
        monkeypatch.setattr(web_search, '_resolve_public_host', original_resolve)
        with pytest.raises(WebSearchUnavailable):
            await web_search.open_web_page('http://127.0.0.1/',timeout_seconds=1,max_download_bytes=2000,max_redirects=2)
    asyncio.run(scenario())


def test_comparison_batch_one_failure_and_single_source_early_stop():
    first=WebSearchResult('Отчёт о доходах','https://one.example/report','Доходы предприятия')
    second=WebSearchResult('Другой отчёт о доходах','https://two.example/report','Доходы предприятия')
    async def scenario():
        many=AsyncMock(return_value=[WebSearchUnavailable('HTTP 403'),(second.url,'Второй прочитанный отчёт')])
        common=dict(previous=[],deep=True,max_seconds=1,max_steps=3,max_searches=1,max_opens=2,
            optimise=True,search=AsyncMock(return_value=[first,second]),open_page=AsyncMock(),
            plan=AsyncMock(return_value=SimpleNamespace(action='open',result_id='r1')),
            save=AsyncMock(return_value=None),state=AsyncMock(),required_open=lambda *a:None)
        result=await run_search_agent(query='Сравни разные отчёты о доходах',open_pages=many,**common)
        assert many.await_count==1 and 'r2' in result.opened and result.errors
        assert result.completion!='success'
        many.reset_mock();common['save']=AsyncMock(return_value='saved')
        common['open_page']=AsyncMock(return_value=(first.url,'Подходящий первоисточник'))
        result=await run_search_agent(query='Отчёт о доходах',open_pages=many,**common)
        assert many.await_count==0 and common['open_page'].await_count==1 and len(result.opened)==1
    asyncio.run(scenario())


def test_resource_trace_fields_are_content_free(monkeypatch):
    events=[];monkeypatch.setattr(search_trace,'event',lambda name,**fields:events.append((name,fields)))
    async def scenario():
        c=controller(750)
        async with c.slot('http'):pass
    asyncio.run(scenario())
    assert any(name=='RESOURCE_MODE' for name,_ in events)
    assert any('slot_wait_ms' in fields for _,fields in events)
    assert all(not set(fields)&{'query','url','text','key'} for _,fields in events)


def test_controller_shared_by_worker_event_loop():
    async def scenario():assert rc.resources() is rc.resources()
    asyncio.run(scenario())


def test_download_cancellation_closes_slots_and_owned_tasks(monkeypatch):
    original=httpx.AsyncClient
    started=asyncio.Event()
    async def handler(request):started.set();await asyncio.sleep(10)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(web_search,'_resolve_public_host',AsyncMock())
    async def scenario():
        c=controller();monkeypatch.setattr(web_search,'resources',lambda:c)
        task=asyncio.create_task(web_search.open_web_page('https://example.org/slow',timeout_seconds=1,
            max_download_bytes=2000,max_redirects=2))
        await started.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert sum(c.active.values())==0 and not c.waiters
    asyncio.run(scenario())


def test_cancelled_html_child_is_reaped_before_slot_release(monkeypatch):
    async def scenario():
        c=controller();monkeypatch.setattr(web_search,'resources',lambda:c)
        started=asyncio.Event();reaped=asyncio.Event()
        class Child:
            returncode=None
            async def communicate(self,data=None):
                if data is not None:started.set();await asyncio.sleep(10)
                else:await asyncio.sleep(.01);self.returncode=-9;reaped.set()
                return b'fixture',b''
            def kill(self):assert c.active['html']==1
        monkeypatch.setattr(asyncio,'create_subprocess_exec',AsyncMock(return_value=Child()))
        task=asyncio.create_task(web_search.extract_web_html('fixture',max_chars=12000,memory_mb=256,timeout_seconds=1))
        await started.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert reaped.is_set() and c.active['html']==0
    asyncio.run(scenario())


def test_comparison_respects_common_deadline_and_cancels_both_reads():
    items=[WebSearchResult('Отчёт о доходах',f'https://{n}.example/report','Доходы') for n in range(2)]
    async def scenario():
        active=0
        async def one(item):
            nonlocal active
            active+=1
            try:await asyncio.sleep(1)
            finally:active-=1
        async def pair(items, *, completed=None):return await asyncio.gather(*(one(item) for item in items),return_exceptions=True)
        started=time.perf_counter()
        result=await run_search_agent(query='Сравни разные отчёты о доходах',previous=[],deep=True,
            max_seconds=.03,max_steps=3,max_searches=1,max_opens=2,optimise=True,
            search=AsyncMock(return_value=items),open_page=one,open_pages=pair,
            plan=AsyncMock(return_value=SimpleNamespace(action='open',result_id='r1')),
            save=AsyncMock(),state=AsyncMock(),required_open=lambda *a:None)
        assert result.timed_out and active==0 and time.perf_counter()-started < .2
    asyncio.run(scenario())


def test_v1_cgroup_memory_and_unavailable_probes(tmp_path):
    proc,cg=tmp_path/'proc',tmp_path/'cg'
    (proc/'self').mkdir(parents=True);(cg/'memory/container').mkdir(parents=True)
    (proc/'self/cgroup').write_text('5:memory:/container\n')
    (cg/'memory/container/memory.limit_in_bytes').write_text(str(800*MB))
    (cg/'memory/container/memory.usage_in_bytes').write_text(str(200*MB))
    assert linux_sample(proc,cg).available_bytes == 600*MB


def test_completed_page_survives_a_sibling_reaching_deadline():
    items=[WebSearchResult('Отчёт о доходах',f'https://{n}.example/report','Доходы') for n in range(2)]
    async def scenario():
        async def pair(items, *, completed=None):
            async def one(index,item):
                await asyncio.sleep(.001 if index==0 else 1)
                value=(item.url,'Прочитанный отчёт')
                completed[index]=value
                return value
            return await asyncio.gather(*(one(i,item) for i,item in enumerate(items)),return_exceptions=True)
        result=await run_search_agent(query='Сравни разные отчёты о доходах',previous=[],deep=True,
            max_seconds=.03,max_steps=3,max_searches=1,max_opens=2,optimise=True,
            search=AsyncMock(return_value=items),open_page=AsyncMock(),open_pages=pair,
            plan=AsyncMock(return_value=SimpleNamespace(action='open',result_id='r1')),
            save=AsyncMock(return_value=None),state=AsyncMock(),required_open=lambda *a:None)
        assert result.timed_out and len(result.opened)==1 and result.errors
    asyncio.run(scenario())


def test_bad_threshold_configuration_is_rejected():
    from pydantic import ValidationError
    from wristmind_server.config import Settings
    with pytest.raises(ValidationError, match='critical < busy'):
        Settings(resource_critical_memory_mb=1000,resource_busy_memory_mb=900)


def test_lightweight_metrics_aggregate_resource_events():
    from wristmind_server.search_metrics import aggregate
    result=aggregate([
        {'event':'SEARCH_RESOURCE_SLOT','status':'acquired','slot_wait_ms':10,'peak_concurrency':2},
        {'event':'SEARCH_RESOURCE_SLOT','status':'cancelled','cancellations':1},
        {'event':'SEARCH_RESOURCE_SLOT','status':'timeout'},
        {'event':'SEARCH_RESOURCE_MODE','mode':'BUSY'},
        {'event':'SEARCH_FIRST_SOURCE','first_source_ms':123},
        {'event':'SEARCH_AGENT_FINISHED','duration_ms':234}])
    assert result['resources']['peak_concurrency']==2
    assert result['resources']['slot_wait_p50_ms']==10
    assert result['resources']['wait_timeouts']==1 and result['resources']['cancellations']==1
    assert result['first_source_latency']['p50_ms']==123 and result['agent_latency']['p50_ms']==234


def test_cancelled_vision_render_keeps_physical_pdf_slot(monkeypatch):
    from wristmind_server import model_capabilities, providers
    from wristmind_server.config import get_settings
    c=controller();monkeypatch.setattr(rc,'resources',lambda:c)
    monkeypatch.setattr(providers,'resources',lambda:c)
    monkeypatch.setattr(model_capabilities,'selected',lambda *a:(object(),'fixture'))
    monkeypatch.setattr(providers,'PdfReader',lambda *a:SimpleNamespace(pages=[1]))
    router=providers.ProviderRouter(get_settings());entered=threading.Event();finished=threading.Event()
    def render(*args):entered.set();finished.wait(1);return b'fixture'
    monkeypatch.setattr(router,'_vision_pdf_page',render)
    async def scenario():
        task=asyncio.create_task(router.analyze_file(Path('fixture.pdf'),'application/pdf'))
        while not entered.is_set():await asyncio.sleep(.001)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert c.active['ocr']==0 and c.active['pdf']==1
        another=asyncio.create_task(router.analyze_file(Path('fixture.pdf'),'application/pdf'))
        await asyncio.sleep(.01)
        assert c.active['pdf']==1 and c.peak['pdf']==1
        another.cancel()
        with pytest.raises(asyncio.CancelledError):await another
        finished.set()
        while c.detached:await asyncio.sleep(.001)
        assert sum(c.active.values())==0 and not c.waiters
    asyncio.run(scenario())


def test_free_resource_boost_yields_to_active_heavy_work():
    async def scenario():
        c=controller(1600);c.refresh();assert c.limit('http')==3
        async with c.slot('html'):assert c.limit('http')==2 and c.limit('search')==1
        assert c.limit('http')==3
    asyncio.run(scenario())
