"""Five-run simulation: planner=25ms, document network=3ms; not server latency."""
import argparse
import asyncio, importlib.util, sys, time, statistics, json
from types import SimpleNamespace
from wristmind_server.search_agent import run_search_agent
from wristmind_server.web_search import WebSearchResult
parser = argparse.ArgumentParser(description='Local synthetic benchmark; no network, models or database calls.')
parser.add_argument('--baseline', help='Trusted pre-change search_agent.py; omit to compare current heuristic switch.')
args = parser.parse_args()
old_run = run_search_agent
if args.baseline:
    spec = importlib.util.spec_from_file_location('wristmind_server._baseline', args.baseline)
    before = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = before
    spec.loader.exec_module(before)
    old_run = before.run_search_agent
book = WebSearchResult('Пушкин Капитанская дочка — полный текст', 'https://library.example/book', 'Оригинал')
query = 'Найди полный оригинальный текст А. С. Пушкина "Капитанская дочка" и проверь наличие всех 14 глав'
text = 'Капитанская дочка\n' + '\n'.join(f'Глава {n}\n' + 'Текст произведения. ' * 40 for n in range(1, 15))
async def measure(fn, optimised):
    calls = 0
    async def search(q): return [book]
    async def open_page(item):
        await asyncio.sleep(.003)
        return item.url, text
    async def plan(query, results, opened, previous):
        nonlocal calls
        calls += 1
        await asyncio.sleep(.025)
        return SimpleNamespace(action='answer') if opened else SimpleNamespace(action='open', result_id='r1')
    async def save(*a): return None
    async def state(*a): pass
    opts = dict(query=query, previous=[], deep=True, max_seconds=1, max_steps=6, max_searches=3,
                max_opens=2, search=search, open_page=open_page, plan=plan, save=save, state=state,
                required_open=lambda *a: None)
    if optimised or not args.baseline: opts['optimise'] = optimised
    start=time.perf_counter(); outcome=await fn(**opts)
    return {'ms': (time.perf_counter()-start)*1000, 'planner_calls':calls, 'searches':outcome.searches, 'opens':len(outcome.opened)}
async def main():
    data={}
    for label, fn, opt in [('before' if args.baseline else 'heuristics_off', old_run, False), ('after', run_search_agent, True)]:
        samples=[await measure(fn,opt) for _ in range(5)]
        data[label]={'median_ms':round(statistics.median(x['ms'] for x in samples),2), 'samples':samples}
    print(json.dumps(data,indent=2))
asyncio.run(main())
