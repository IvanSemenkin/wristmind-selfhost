"""Bounded, on-demand aggregates of content-free JSONL; no daemon or metrics DB."""
from collections import deque
import json
import math
from pathlib import Path


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered)*quantile)-1)]


def recent_events(path: Path, *, max_bytes=4_000_000, limit=5000):
    events = deque(maxlen=limit)
    try:
        with path.open('rb') as handle:
            size = handle.seek(0, 2)
            start = max(0, size-max_bytes)
            handle.seek(start)
            if start: handle.readline()  # partial first line
            for raw in handle:
                try:
                    row = json.loads(raw)
                    if isinstance(row, dict): events.append(row)
                except (ValueError, UnicodeDecodeError):
                    continue
    except OSError:
        pass
    return events


def aggregate(events):
    requests = {}
    timings = {}
    child_memory = []
    process_memory = []
    waits, first_sources, agent_times, concurrency = [], [], [], []
    modes = {}
    resource_timeouts = cancellations = 0
    for row in events:
        event = row.get('event')
        if event == 'SEARCH_RESOURCE_SLOT':
            if isinstance(row.get('peak_concurrency'), (int, float)):
                concurrency.append(row['peak_concurrency'])
            if row.get('status') == 'acquired' and isinstance(row.get('slot_wait_ms'), (int, float)):
                waits.append(row['slot_wait_ms'])
            resource_timeouts += row.get('status') == 'timeout'
            cancellations += row.get('cancellations', 0)
        if event == 'SEARCH_RESOURCE_MODE':
            mode = row.get('mode')
            modes[mode] = modes.get(mode, 0) + 1
        if event == 'SEARCH_FIRST_SOURCE' and isinstance(row.get('first_source_ms'), (int, float)):
            first_sources.append(row['first_source_ms'])
        if event == 'SEARCH_AGENT_FINISHED' and isinstance(row.get('duration_ms'), (int, float)):
            agent_times.append(row['duration_ms'])
        if row.get('event') == 'SEARCH_SUMMARY' and row.get('job_id'):
            requests[row['job_id']] = row  # no duplicate summary weights
        if row.get('event') == 'SEARCH_STAGE':
            name = row.get('stage')
            value = row.get('duration_ms')
            if row.get('status') == 'success' and isinstance(value, (int, float)):
                timings.setdefault(name, []).append(value)
            if isinstance(row.get('child_peak_rss_bytes'), (int, float)):
                child_memory.append(row['child_peak_rss_bytes'])
            if name in {'html_extract','pdf_extract'} and isinstance(row.get('rss_bytes'), (int, float)):
                process_memory.append(row['rss_bytes'])
    rows = [row for row in requests.values() if row.get('route') in {'web','deep_web'}]
    complete = [row for row in rows if row.get('status') == 'complete']
    latency = {}
    for route in ('web','deep_web'):
        sample = [row['response_ms'] for row in complete if row.get('route') == route and isinstance(row.get('response_ms'), (int, float))]
        latency[route] = {'n': len(sample), 'p50_ms': percentile(sample,.5), 'p95_ms': percentile(sample,.95)}
    opens = sum(row.get('opens',0) for row in rows)
    hits = sum(row.get('cache_hits',0) for row in rows)
    misses = sum(row.get('cache_misses',0) for row in rows)
    return {'requests': len(rows), 'completed': len(complete), 'cancelled': sum(row.get('status')=='cancelled' for row in rows),
            'response_latency': latency,
            'mean_llm_calls': sum(row.get('llm_calls',0) for row in rows)/len(rows) if rows else None,
            'successful_open_ratio': sum(row.get('successful_opens',0) for row in rows)/opens if opens else None,
            'without_confirmed_source_ratio': sum(not row.get('verified_sources',0) for row in complete)/len(complete) if complete else None,
            'cache_hit_ratio': hits/(hits+misses) if hits+misses else None,
            'cache_admission_skipped': sum(row.get('cache_skipped',0) for row in rows),
            'resources': {'peak_concurrency': max(concurrency) if concurrency else None,
                          'slot_wait_p50_ms': percentile(waits, .5), 'slot_wait_p95_ms': percentile(waits, .95),
                          'wait_timeouts': resource_timeouts, 'cancellations': cancellations, 'mode_changes': modes},
            'first_source_latency': {'n': len(first_sources), 'p50_ms': percentile(first_sources, .5), 'p95_ms': percentile(first_sources, .95)},
            'agent_latency': {'n': len(agent_times), 'p50_ms': percentile(agent_times, .5), 'p95_ms': percentile(agent_times, .95)},
            'stages': {name: {'n':len(sample),'p50_ms':percentile(sample,.5),'p95_ms':percentile(sample,.95)} for name,sample in timings.items()},
            'document_process_rss_max_bytes': max(process_memory) if process_memory else None,
            'html_child_peak_rss_max_bytes': max(child_memory) if child_memory else None,
            'total_tokens_reported': sum(row.get('total_tokens',0) for row in rows) if any('total_tokens' in row for row in rows) else None,
            'requests_with_usage': sum('total_tokens' in row for row in rows)}


def main():
    import argparse
    from .latency_trace import trace_path
    parser = argparse.ArgumentParser(description='Summarize recent WristMind search JSONL. Read-only, bounded.')
    parser.add_argument('--path', type=Path)
    parser.add_argument('--max-bytes', type=int, default=4_000_000)
    parser.add_argument('--limit', type=int, default=5000)
    args = parser.parse_args()
    if not 0 < args.max_bytes <= 16_000_000 or not 0 < args.limit <= 20000:
        parser.error('Use --max-bytes 1..16000000 and --limit 1..20000')
    print(json.dumps(aggregate(recent_events(args.path or trace_path(), max_bytes=args.max_bytes,limit=args.limit)), indent=2))


if __name__ == '__main__': main()
