"""Run eegproc with generated MNE data, without datasets or network downloads.

After installing eegproc:
    python examples/synthetic_demo.py --output outputs/synthetic_demo
    python examples/synthetic_demo.py --output outputs/rest_demo --mode rest

Default mode runs rest, ERP, ICA review and continuation. These synthetic
signals demonstrate software use, not biological validity or cleaning accuracy.
The output directory must not already exist; inputs are never overwritten.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def make_raw():
    """Return a 60 s, 32 EEG + EOG/ECG/STIM Raw and explicit absolute events."""
    import mne
    import numpy as np
    from scipy.signal import lfilter

    sfreq, duration = 256., 60.
    samples = int(sfreq * duration)
    t = np.arange(samples) / sfreq
    names = ["Fp1", "Fp2", "F7", "F3", "Fz", "F4", "F8", "FC5", "FC1",
             "FC2", "FC6", "T7", "C3", "Cz", "C4", "T8", "CP5", "CP1",
             "CP2", "CP6", "P7", "P3", "Pz", "P4", "P8", "PO7", "PO3",
             "POz", "PO4", "PO8", "O1", "O2"]
    montage = mne.channels.make_standard_montage("standard_1020")
    positions = np.array([montage.get_positions()["ch_pos"][name] for name in names])
    positions /= np.linalg.norm(positions, axis=1, keepdims=True)
    x, y, z = positions.T
    spatial = np.column_stack([x, y, z, x*y, x*z, y*z, x*x-y*y, z*z])
    rng = np.random.default_rng(20261022)
    sources = lfilter([1.], [1., -.96], rng.normal(size=(spatial.shape[1], samples)))
    sources /= sources.std(axis=1, keepdims=True)
    sources[0] += np.sin(2*np.pi*10*t)
    sources[1] += .5*np.sin(2*np.pi*6*t)
    eeg = spatial @ sources * 7e-6 + rng.normal(scale=.5e-6, size=(len(names), samples))
    eeg += np.sin(2*np.pi*50*t)[None, :] * 1.5e-6
    eog = sum(np.exp(-.5*((t-onset)/.12)**2) for onset in (15., 35., 49.)) * 120e-6
    eeg += np.maximum(y, 0)[:, None] * eog * .15
    ecg = sum(np.exp(-.5*((t-onset)/.015)**2) for onset in np.arange(.6, duration, .85)) * 150e-6
    onsets = np.arange(5., 57., 3.)
    codes = np.resize([1, 2], len(onsets))
    stim = np.zeros(samples)
    for onset, code in zip(onsets, codes):
        stim[int(onset*sfreq):int(onset*sfreq)+3] = code
        # A small demonstration response, not a validated physiological model.
        eeg += z[:, None] * np.exp(-.5*((t-onset-.3)/.08)**2) * (3e-6 if code == 1 else 6e-6)
    info = mne.create_info(names + ["EOG", "ECG", "STI"], sfreq,
                           ["eeg"]*len(names) + ["eog", "ecg", "stim"])
    raw = mne.io.RawArray(np.vstack([eeg, eog, ecg, stim]), info,
                          first_samp=2048, verbose=False)
    raw.set_montage(montage, verbose=False)
    raw.set_meas_date(datetime(2020, 1, 2, tzinfo=timezone.utc))
    raw.info["description"] = "Generated eegproc tutorial data; not participant data"
    raw.set_annotations(mne.Annotations(
        [11., *onsets], [.35, *np.zeros(len(onsets))],
        ["BAD_manual", *["standard" if code == 1 else "target" for code in codes]],
        ch_names=[("F3",), *[() for _ in onsets]],
        extras=[{"source": "manual example"}, *[{"source": "generated stimulus"} for _ in onsets]]))
    events = np.column_stack([
        raw.first_samp + np.round(onsets*sfreq).astype(int),
        np.zeros(len(onsets), dtype=int), codes])
    return raw, events, {"standard": 1, "target": 2}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("all", "rest", "erp", "review"), default="all")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    output.mkdir(parents=True)
    import mne
    import numpy as np
    from eegproc import run, resume, render_report

    raw, events, event_id = make_raw()
    input_file = output / "synthetic_input_raw.fif"
    raw.save(input_file, fmt="double", overwrite=False, verbose=False)
    # Reading back gives the checkpoint a stable file-backed original reference.
    raw = mne.io.read_raw_fif(input_file, preload=False, verbose=False)
    before = raw.get_data()
    annotations_before = raw.annotations.copy()
    summaries = {}

    def record(name, result):
        summaries[name] = {
            "status": result.status, "outputs": result.outputs,
            "quality_flags": result.report.get("quality_flags", []),
            "removed_components_0based": result.report.get("ica", {}).get("removed_components_0based"),
            "trial_retention": result.report.get("epochs", {}).get("condition_retention"),
        }
        np.testing.assert_array_equal(raw.get_data(), before)
        assert raw.annotations == annotations_before
        (output / "example_summary.json").write_text(json.dumps(
            {"synthetic_only": True, "input_unchanged": True, "runs": summaries},
            indent=2), encoding="utf8")
        print(f"{name}: {result.status}; {result.outputs['quality_report']}")

    if args.mode in ("all", "rest"):
        result = run(raw, output / "rest", "synthetic", purpose="rest", task_name="eyes_closed")
        record("rest", result)
        del result
    if args.mode in ("all", "erp"):
        result = run(raw, output / "erp", "synthetic", purpose="erp", task_name="oddball",
                     epoch_mode="events", events=events, event_id=event_id)
        record("erp", result)
        del result
    if args.mode in ("all", "review"):
        review = run(raw, output / "review", "synthetic", purpose="erp",
                     task_name="oddball", epoch_mode="events", events=events,
                     event_id=event_id, ica_mode="review")
        record("review", review)
        # For actual manual use: inspect the HTML, then supply its downloaded
        # selection_json OR replace this complete zero-based list yourself.
        proposed = review.report["ica"]["automatic_proposal_0based"]
        revised = resume(review.outputs["checkpoint"], output / "resumed", "synthetic",
                         exclude=proposed, original_fif=input_file, reviewer="Tutorial",
                         reason="Demonstrate continuation using unchanged automatic proposal")
        record("resumed", revised)
        render_report(revised.outputs["quality_report"], output / "rebuilt_report.html")
    raw.close()


if __name__ == "__main__":
    main()
