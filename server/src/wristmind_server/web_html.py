"""Resource-bounded trafilatura subprocess. Emits only sizes/timing/RSS on stderr."""
from __future__ import annotations
import json
import logging
import sys
import time


def main() -> int:
    max_chars, memory_mb = map(int, sys.argv[1:3])
    measured = {'status': 'error'}
    try:
        import resource
        ceiling = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (ceiling, ceiling))
        logging.disable(logging.CRITICAL)
        import trafilatura
        import re
        html = sys.stdin.buffer.read().decode('utf-8')
        measured['chars_in'] = len(html)
        started = time.perf_counter()
        try:
            text = trafilatura.extract(html, include_comments=False, include_tables=True,
                                       include_formatting=True, output_format='txt', favor_recall=True) or ''
        finally:
            measured['duration_ms'] = round((time.perf_counter() - started)*1000, 3)
        text = re.sub(r'\n{3,}', '\n\n', text.replace('\x00', '')).strip()
        measured['chars_out'] = len(text)
        if len(text) > max_chars:
            measured['reason'] = 'text_limit'
            return 2
        if not text:
            measured['reason'] = 'empty_extraction'
            return 3
        sys.stdout.buffer.write(text.encode('utf-8'))
        measured['status'] = 'success'
        return 0
    except Exception as exc:
        measured['reason'] = type(exc).__name__
        return 3
    finally:
        try:
            import resource
            measured['child_peak_rss_bytes'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
            print('WM_HTML_METRIC ' + json.dumps(measured), file=sys.stderr)
        except Exception:
            pass


if __name__ == '__main__':
    raise SystemExit(main())
