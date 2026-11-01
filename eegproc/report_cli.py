"""Generate HTML from a processing result's compact report package or HTML."""
import argparse
import json


def parser():
    p = argparse.ArgumentParser(description='Render saved report material without running EEG preprocessing.')
    p.add_argument('--source', required=True, help='Report-data NPZ or existing HTML')
    p.add_argument('--output', required=True, help='New HTML file')
    return p


def main(argv=None):
    from .api import render_report
    from .reporting import read_report_source
    args = parser().parse_args(argv)
    target = render_report(args.source, args.output)
    record=read_report_source(target)
    print(json.dumps(dict(report=str(target), status=record['report_status'],
                          processing_status=record.get('processing_status',record.get('status'))), indent=2))


if __name__ == '__main__':
    main()
