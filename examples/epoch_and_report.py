"""Preprocess once, epoch a saved cleaned FIF, and render both reports later.

After installing eegproc, run from the repository checkout:
    python examples/epoch_and_report.py --output outputs/epoch_demo

The input is generated locally. No dataset downloads or original-Raw snapshot
are needed. Each output family must be new. Numerical and QC defaults are the
normal ERP defaults; report=False postpones figures and HTML only.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")

    import mne
    import numpy as np
    from eegproc import run, epoch, render_report
    from synthetic_demo import make_raw

    raw, events, event_id = make_raw()
    before = raw.get_data().copy()
    annotations = raw.annotations.copy()
    prep = run(raw, output / "preprocessing", "synthetic", purpose="erp",
               task_name="oddball", report=False)
    np.testing.assert_array_equal(raw.get_data(), before)
    assert raw.annotations == annotations
    raw.close()
    del raw, before

    # This is the only continuous data required for standalone epoching.
    # The same-directory report-data package is discovered automatically.
    with mne.io.read_raw_fif(prep.outputs["raw"], preload=False, verbose=False) as clean:
        seg = epoch(
            clean, output / "epochs", "synthetic",
            events=events, event_id=event_id,
            tmin=-0.2, tmax=1.0, baseline=(None, 0.0), report=False,
        )

    # Either result objects or saved *_report_data.npz paths can be used.
    prep_html = render_report(prep, output / "preprocessing" / "synthetic_report.html")
    epoch_html = render_report(seg, output / "epochs" / "synthetic_report.html")
    print(f"Preprocessing: {prep.status}; {prep_html}")
    print(f"Epoching: {seg.status}; {epoch_html}")
    epochs = seg.epochs
    if epochs is not None:
        print({name: len(epochs[name]) for name in epochs.event_id})
    else:
        print(seg.report.get("epoch_resolution"))


if __name__ == "__main__":
    main()
