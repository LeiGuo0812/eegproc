"""Code-first EEG examples; importing this file does not read or process data.

Examples after local installation:
    python examples/code_first.py rest prepared/sub01_raw.fif outputs/rest --subject sub01
    python examples/code_first.py erp prepared/sub01_raw.fif outputs/erp --subject sub01 --events-json events.json
    python examples/code_first.py review prepared/sub01_raw.fif outputs/review --subject sub01
    python examples/code_first.py resume outputs/review/sub01_ica_review/checkpoint.json outputs/revised --exclude 1 4
    python examples/code_first.py render outputs/rest/sub01_report.html outputs/rest/updated_report.html

Every processing output family must be new. All exclusion lists are zero-based
and complete: [] explicitly keeps all components. No algorithm defaults change.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def resting_state(raw, output, subject, *, task_name="eyes_closed"):
    """Direct keyword parameters: existing rest defaults and descriptive task."""
    from eegproc import run
    return run(raw, output, subject, purpose="rest", task_name=task_name)


def event_related(raw, output, subject, *, events=None, event_id=None, task_name="oddball"):
    """An immutable config; omitted events are extracted from annotations."""
    from eegproc import PipelineConfig, run
    config = PipelineConfig(purpose="erp", task_name=task_name, epoch_mode="events")
    return run(raw, output, subject, config=config, events=events, event_id=event_id)


def review_ica(raw, output, subject, *, purpose="rest", task_name="rest"):
    """Pause before component subtraction; result.raw is None while pending."""
    from eegproc import run
    return run(raw, output, subject, purpose=purpose, task_name=task_name, ica_mode="review")


def manual_ica(raw, output, subject, exclude, *, purpose="rest", task_name="rest"):
    """A mapping sets a complete manual list for an initial full run."""
    from eegproc import run
    parameters = dict(purpose=purpose, task_name=task_name, ica_mode="manual", ica_exclude=exclude)
    return run(raw, output, subject, config=parameters)


def optional_file(raw, output, subject, config_file, **parameters):
    """The optional file is below direct Python values in the merge order."""
    from eegproc import run
    return run(raw, output, subject, config_file=config_file, **parameters)


def revise_ica(checkpoint, output, *, exclude=None, selection_json=None,
               original_raw=None, original_fif=None):
    """Reuse the fitted model; select a new output directory."""
    from eegproc import resume
    return resume(checkpoint, output, exclude=exclude, selection_json=selection_json,
                  original_raw=original_raw, original_fif=original_fif,
                  reviewer="Researcher", reason="Manual component review")


def prepare_device(source, *, output_fif=None, montage=None, channel_types=None):
    """Return raw/events/event_id/provenance/outputs without EEG cleaning."""
    from eegproc.preparation import prepare_data
    return prepare_data(source, output_fif=output_fif, montage=montage,
                        channel_types=channel_types, return_result=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for mode in ("rest", "erp", "review", "manual", "config"):
        command = commands.add_parser(mode)
        command.add_argument("input_fif", type=Path)
        command.add_argument("output", type=Path)
        command.add_argument("--subject", required=True)
        command.add_argument("--task-name", default=None)
        if mode == "erp":command.add_argument("--events-json", type=Path)
        if mode in ("review", "manual"):command.add_argument("--purpose", choices=("rest", "erp"), default="rest")
        if mode == "manual":command.add_argument("--exclude", type=int, nargs="*", required=True)
        if mode == "config":command.add_argument("--config-file", type=Path, required=True)
    continuation = commands.add_parser("resume")
    continuation.add_argument("checkpoint", type=Path)
    continuation.add_argument("output", type=Path)
    selection = continuation.add_mutually_exclusive_group(required=True)
    selection.add_argument("--exclude", type=int, nargs="*")
    selection.add_argument("--selection-json", type=Path)
    continuation.add_argument("--original-fif", type=Path)
    rendering = commands.add_parser("render")
    rendering.add_argument("source_html", type=Path)
    rendering.add_argument("output_html", type=Path)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("source", type=Path)
    preparation.add_argument("--output-fif", type=Path)
    preparation.add_argument("--montage")
    args = parser.parse_args(argv)
    if args.command == "render":
        from eegproc import render_report
        print(render_report(args.source_html, args.output_html))
        return
    if args.command == "prepare":
        prepared = prepare_device(args.source, output_fif=args.output_fif, montage=args.montage)
        print(json.dumps(dict(event_id=prepared.event_id, events=len(prepared.events),
                              outputs=prepared.outputs), indent=2, default=str))
        return
    if args.command == "resume":
        result = revise_ica(args.checkpoint, args.output, exclude=args.exclude,
                            selection_json=args.selection_json, original_fif=args.original_fif)
    else:
        import mne
        raw = mne.io.read_raw_fif(args.input_fif, preload=False, verbose=False)
        if args.command == "rest":
            result = resting_state(raw, args.output, args.subject, task_name=args.task_name or "eyes_closed")
        elif args.command == "erp":
            payload = json.loads(args.events_json.read_text(encoding="utf-8-sig")) if args.events_json else {}
            result = event_related(raw, args.output, args.subject, events=payload.get("events"),
                                   event_id=payload.get("event_id"), task_name=args.task_name or "oddball")
        elif args.command == "review":
            result = review_ica(raw, args.output, args.subject, purpose=args.purpose,
                                task_name=args.task_name or args.purpose)
        elif args.command == "manual":
            result = manual_ica(raw, args.output, args.subject, args.exclude, purpose=args.purpose,
                                task_name=args.task_name or args.purpose)
        else:
            overrides = {} if args.task_name is None else {"task_name": args.task_name}
            result = optional_file(raw, args.output, args.subject, args.config_file, **overrides)
    print(json.dumps(dict(status=result.status, outputs=result.outputs), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
