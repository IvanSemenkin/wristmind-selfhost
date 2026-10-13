"""Identical local two-source scenarios; mocked network, no actual LLM."""
import asyncio,json,statistics,time
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
import httpx
from wristmind_server import web_search
from wristmind_server.resource_controller import AdaptiveResourceController,ResourceSample,MB
from wristmind_server.search_agent import run_search_agent
from wristmind_server.web_search import WebSearchResult
HTML='<article><h1>Отчёт о доходах</h1>'+''.join('<h2>Раздел %d</h2><p>'%i+('Доходы и расходы компании. '*100)+'</p>' for i in range(14))+'</article>'
ITEMS=[WebSearchResult('Отчёт о доходах',f'https://source{n}.example/report','Доходы компании') for n in range(2)]
CLIENT=httpx.AsyncClient
async def once(parallel,real):
 c=AdaptiveResourceController(sampler=lambda:ResourceSample(1100*MB,.2))
 async def handler(request):
  await asyncio.sleep(.08)
  return httpx.Response(200,text=HTML,headers={'content-type':'text/html'})
 async def synthetic(html,**kw):
  async with c.slot('html'):
   await asyncio.sleep(.025);return 'Прочитанный отчёт о доходах компании.'
 async def one(item):return await web_search.open_web_page(item.url,timeout_seconds=1,max_download_bytes=200000,max_redirects=2)
 async def pair(items, *, completed=None):return await asyncio.gather(*(one(item) for item in items),return_exceptions=True)
 async def plan(query,results,opened,evidence):return SimpleNamespace(action='answer') if opened else SimpleNamespace(action='open',result_id='r1')
 with patch.object(web_search,'resources',lambda:c),patch.object(web_search,'_resolve_public_host',AsyncMock()),patch.object(httpx,'AsyncClient',lambda **kw:CLIENT(transport=httpx.MockTransport(handler),**kw)):
  parser=patch.object(web_search,'extract_web_html',synthetic)
  if not real:parser.start()
  ticks=[0]
  async def heartbeat():
   while True:ticks[0]+=1;await asyncio.sleep(.005)
  beat=asyncio.create_task(heartbeat())
  try:
   start=time.perf_counter()
   result=await run_search_agent(query='Сравни разные отчёты о доходах компании',previous=[],deep=True,max_seconds=5,max_steps=6,max_searches=1,max_opens=2,optimise=True,search=AsyncMock(return_value=ITEMS),open_page=one,open_pages=pair if parallel else None,plan=plan,save=AsyncMock(return_value=None),state=AsyncMock(),required_open=lambda *a:None)
   assert len(result.opened)==2 and result.completion=='success'
   return (time.perf_counter()-start)*1000,result.planner_calls,c.peak['http'],c.peak['html'],ticks[0]
  finally:
   beat.cancel();await asyncio.gather(beat,return_exceptions=True)
   if not real:parser.stop()
async def main():
 report={}
 for real in [False,True]:
  values={}
  for parallel in [False,True]:
   rows=[await once(parallel,real) for _ in range(5)];ms=sorted(r[0] for r in rows)
   values['parallel' if parallel else 'sequential']={'samples':5,'p50_ms':round(statistics.median(ms),3),'p95_ms':round(ms[-1],3),'planner_calls':sorted(set(r[1] for r in rows)),'http_peak':max(r[2] for r in rows),'html_peak':max(r[3] for r in rows),'event_loop_ticks_min':min(r[4] for r in rows)}
  values['p50_reduction_percent']=round(100*(1-values['parallel']['p50_ms']/values['sequential']['p50_ms']),2)
  report['real_trafilatura' if real else 'mock_parser']=values
 print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':asyncio.run(main())
