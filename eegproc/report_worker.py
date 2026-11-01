"""Internal one-report worker. Public callers use eegproc.render_report()."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'output', 'result', 'target', 'context'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args(argv)
    from .report_data import read_report_data, save_report_data
    record = read_report_data(args.source)
    context = json.loads(args.context.read_text(encoding='utf8'))
    context['worker_pid'] = os.getpid()
    # A report is committed only if this worker subsequently exits with zero.
    # Include the successful current attempt in its own HTML audit as well as
    # prior failed attempts, which were supplied by the parent.
    context['attempts'] = [*context.get('attempts', []),
        dict(attempt=context['attempt'], returncode=0, timed_out=False)]
    record['report_execution'] = context
    started = time.monotonic()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=context['n_threads']):
        from .quality_report import safe_report
        ok = safe_report(record, args.output, reuse_figures=context['reuse_figures'],
                         output_path=args.target)
    context['worker_elapsed_seconds'] = time.monotonic() - started
    print(json.dumps(dict(report_status=record.get('report_status'),
        plot_errors=record.get('visualizations',{}).get('errors',[]),
        error=record.get('report_error'))),flush=True)
    save_report_data(record, args.result)
    return 0 if ok else 2


if __name__ == '__main__':
    raise SystemExit(main())
