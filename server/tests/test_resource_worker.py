import asyncio
from wristmind_server import worker
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Job
from wristmind_server.resource_controller import AdaptiveResourceController, ResourceSample, MB


def test_busy_worker_keeps_ingest_queued_and_claims_answers(admin, monkeypatch):
    c=AdaptiveResourceController(sampler=lambda:ResourceSample(750*MB,.2))
    monkeypatch.setattr(worker,'resources',lambda:c)
    async def scenario():
        async with SessionFactory() as session:
            ingest=Job(kind='INGEST',device_id=admin['device_id'],client_request_id='deferred-index',payload={})
            answer=Job(kind='ANSWER',device_id=admin['device_id'],client_request_id='priority-answer',payload={})
            session.add_all([ingest,answer]);await session.commit()
            ingest_id,answer_id=ingest.id,answer.id
        assert await worker.claim_job()==answer_id
        assert await worker.claim_job() is None
        async with SessionFactory() as session:assert (await session.get(Job,ingest_id)).status=='queued'
        c.mode='NORMAL';c.last_sample=float('inf')
        assert await worker.claim_job()==ingest_id
    asyncio.run(scenario())


def test_pressure_during_ingest_requeues_job_and_preserves_source(admin, mode):
    from wristmind_server.db_models import KnowledgeSource
    from wristmind_server.resource_controller import ResourceUnavailable
    async def scenario():
        async with SessionFactory() as session:
            source=KnowledgeSource(mode_id=mode['id'],title='Fixture',filename='fixture.txt',
                media_type='text/plain',processing_mode='WEB',status='processing',storage_path='fixture.txt')
            session.add(source);await session.flush()
            job=Job(kind='INGEST',status='running',device_id=admin['device_id'],client_request_id='pressure-retry',payload={'source_id':source.id})
            session.add(job);await session.commit();source_id,job_id=source.id,job.id
        await worker.fail_job(job_id,ResourceUnavailable('Temporary resource pressure'))
        async with SessionFactory() as session:
            source=await session.get(KnowledgeSource,source_id);job=await session.get(Job,job_id)
            assert source.status=='queued' and source.title=='Fixture'
            assert job.status=='queued' and job.payload['retry_count']==1 and job.payload['retry_after']
    asyncio.run(scenario())


def test_worker_comparison_reads_in_parallel_preserves_cache_and_rag(client,admin_headers,mode,monkeypatch):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from pathlib import Path
    from wristmind_server.db_models import RawWebSource,KnowledgeSource
    from wristmind_server.web_search import WebSearchResult
    from wristmind_server.knowledge import knowledge_context
    from wristmind_server.config import get_settings
    route=worker.RetrievalRoute(retrieval='deep_web',reasoning='low',verification=True,freshness_required=False,
        task_type='comparison',intents=worker.WriteIntents(wants_source_saved_for_chat=True,wants_multi_source_check=True))
    monkeypatch.setattr(worker,'choose_retrieval_route',AsyncMock(return_value=route))
    monkeypatch.setattr(worker,'build_request_anchor',AsyncMock(return_value=worker.lightweight_request_anchor('Доходы по отчётам')))
    monkeypatch.setattr(worker,'choose_contextual_search_query',AsyncMock(return_value='Отчёты о доходах'))
    monkeypatch.setattr(worker,'choose_web_action',AsyncMock(return_value=worker.WebAgentAction(action='open',result_id='r1')))
    monkeypatch.setattr(worker,'is_foundational_source',AsyncMock(return_value=True))
    items=[WebSearchResult('Отчёт о доходах',f'https://source{n}.example/report','Доходы компании') for n in range(2)]
    monkeypatch.setattr(worker,'search_web',AsyncMock(return_value=items))
    text='Доходы компании составили 100 рублей. '*80
    active=peak=0
    async def open_page(url,**kw):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        try:await asyncio.sleep(.02);return url,text
        finally:active-=1
    monkeypatch.setattr(worker,'open_web_page',open_page)
    chat=client.post('/v1/chats',headers=admin_headers,json={'mode_id':mode['id']}).json()
    job=client.post(f"/v1/chats/{chat['id']}/messages",headers=admin_headers,json={
        'client_request_id':'parallel-worker','text':'Найди и сравни доходы по разным отчётам и сохрани текст в рабочий источник'}).json()
    async def run():
        async with SessionFactory() as session:
            pending=await session.get(Job,job['id']);pending.status='running';await session.commit()
        await worker.process_answer(job['id'])
        assert peak==2 and active==0
        async with SessionFactory() as session:
            raws=list(await session.scalars(select(RawWebSource).where(RawWebSource.chat_id==chat['id'])))
            sources=list(await session.scalars(select(KnowledgeSource).where(KnowledgeSource.chat_id==chat['id'])))
            assert len(raws)==2 and len(sources)==1
            source=sources[0];assert Path(source.storage_path).read_text()==text
            ingest=await session.scalar(select(Job).where(Job.client_request_id==f'working-source:{source.id}'))
            source_id,ingest_id=source.id,ingest.id
        await worker.process_ingest(ingest_id)
        async with SessionFactory() as session:
            source=await session.get(KnowledgeSource,source_id)
            assert source.status=='ready' and source.chunk_count>0
            context,meta=await knowledge_context(session,mode['id'],'Доходы компании',worker.providers,get_settings(),chat_id=chat['id'])
            assert context and '100 рублей' in context
    asyncio.run(run())
    message=client.get(f"/v1/chats/{chat['id']}/messages",headers=admin_headers).json()[-1]
    assert message['timings']['web_search']['opened_pages']==2 and message['timings']['web_search']['saved']
