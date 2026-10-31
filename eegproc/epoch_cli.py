"""Command-line adapter for epoching processed FIF data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import warnings

from .cli import integer, number, option, optional_number


def parser():
    p = argparse.ArgumentParser(description=(
        'Epoch preprocessed MNE FIF data without repeating filtering, ASR or ICA. '
        'Parameters may be supplied in Python, JSON, explicit flags or --set KEY=JSON.'))
    p.add_argument('--input-fif', required=True)
    p.add_argument('--save-path', required=True)
    p.add_argument('--subject', help='Output prefix; otherwise inherited from processed Raw')
    p.add_argument('--config')
    p.add_argument('--task-name')
    p.add_argument('--events-json', help='Explicit {events, event_id}, with absolute MNE sample indices')
    option(p, 'epoch-mode', ['events', 'fixed'])
    option(p, 'event-source', ['auto', 'annotations', 'stim'])
    p.add_argument('--event-names', nargs='+')
    p.add_argument('--stim-channel')
    p.add_argument('--tmin', type=number)
    p.add_argument('--tmax', type=number)
    p.add_argument('--baseline', nargs='+', help='Two endpoints, or off')
    p.add_argument('--fixed-epochs', dest='fixed_epoch_duration', type=number)
    p.add_argument('--fixed-overlap', dest='fixed_epoch_overlap', type=number)
    option(p, 'epoch-qc', ['auto', 'event-window', 'annotations'])
    p.add_argument('--repair-epochs', action=argparse.BooleanOptionalAction, default=None)
    for name in ('residual-peak-uv', 'residual-ptp-uv', 'residual-robust-z', 'residual-relative-min-ptp-uv'):
        p.add_argument('--'+name, type=number)
    p.add_argument('--seed', type=integer)
    p.add_argument('--n-threads', type=integer)
    p.add_argument('--source-report', help='Previous HTML or report-data NPZ; otherwise discovered automatically')
    p.add_argument('--keep-source-report', action=argparse.BooleanOptionalAction, default=True,
                   help='Keep the source HTML (default); deletion requires a successfully written merged HTML')
    p.add_argument('--report', action=argparse.BooleanOptionalAction, default=True,
                   help='Write HTML now; --no-report saves one deferred report package')
    p.add_argument('--set', dest='settings', action='append', default=[], metavar='KEY=JSON',
                   help='Advanced epoch/QC controls; continuous-cleaning settings are ignored and reported')
    return p


def main(argv=None):
    import mne
    from .api import epoch
    p = parser()
    args = p.parse_args(argv)
    io = {'input_fif', 'save_path', 'subject', 'config', 'events_json', 'baseline',
          'source_report', 'keep_source_report', 'report', 'settings'}
    parameters = {key:value for key,value in vars(args).items() if key not in io and value is not None}
    if args.fixed_epoch_duration is not None:
        parameters['epoch_mode'] = 'fixed'
    if args.baseline is not None:
        parameters['baseline'] = None if args.baseline == ['off'] else tuple(optional_number(v) for v in args.baseline)
    for setting in args.settings:
        try:
            key, value = setting.split('=', 1)
            value = json.loads(value)
        except (ValueError, json.JSONDecodeError):
            p.error('--set requires KEY=JSON')
        if key in parameters or key in io:
            p.error('Duplicate or non-scientific --set override: '+key)
        parameters[key] = value
    events = event_id = None
    if args.events_json:
        try:
            payload = json.loads(Path(args.events_json).read_text(encoding='utf-8-sig'))
            if not isinstance(payload, dict) or not payload.get('events'):
                raise ValueError('Event JSON must contain a nonempty events array')
            events, event_id = payload['events'], payload.get('event_id')
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            warnings.warn('Optional event input unavailable; epoch export will be skipped: '+str(exc),
                          RuntimeWarning, stacklevel=2)
            events = []
    with mne.io.read_raw_fif(args.input_fif, preload=False, verbose=False) as raw:
        result = epoch(raw, args.save_path, args.subject, config_file=args.config,
            events=events, event_id=event_id, source_report=args.source_report,
            keep_source_report=args.keep_source_report, report=args.report, **parameters)
    print(json.dumps(dict(status=result.status, outputs=result.outputs,
                         report_status=result.report.get('report_status'),
                         epochs_retained=result.report.get('epochs', {}).get('retained_epochs')), indent=2))


if __name__ == '__main__':
    main()
