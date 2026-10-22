"""MNE-only downstream examples: resting PSD, ERP and time-frequency power.

Only run after inspecting preprocessing QC. No additional packages or data
downloads are needed beyond eegproc's normal dependencies.

python examples/analyze_outputs.py --raw outputs/rest/sub01_cont_raw.fif --output analysis/rest
python examples/analyze_outputs.py --epochs outputs/erp/sub01_clean-epo.fif --output analysis/erp

Use the exported epochs rather than re-epoching continuous Raw if you want to
retain the pipeline's event-window QC selection. All data are in SI units.
Outputs are exploratory summaries, not subject/group inferential statistics.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def analyze_rest(path, output):
    import mne
    import numpy as np
    import matplotlib.pyplot as plt

    raw = mne.io.read_raw_fif(path, preload=False, verbose=False)
    upper = min(45., raw.info["lowpass"], raw.info["sfreq"]/2 - 1.)
    lower = max(1., raw.info["highpass"])
    if upper <= lower:
        raise ValueError("Input does not contain the requested PSD analysis range")
    n_fft = min(int(round(4*raw.info["sfreq"])), raw.n_times)
    spectrum = raw.compute_psd(method="welch", fmin=lower, fmax=upper,
                               picks="eeg", exclude="bads", reject_by_annotation=True,
                               n_fft=n_fft, n_per_seg=n_fft, n_overlap=n_fft//2,
                               verbose=False)
    psd, frequencies = spectrum.get_data(return_freqs=True)
    np.savez_compressed(output / "rest_psd.npz", psd_v2_hz=psd,
                        frequencies_hz=frequencies, channels=np.asarray(spectrum.ch_names))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(frequencies, 10*np.log10(np.maximum(psd*1e12, np.finfo(float).tiny)).T,
            alpha=.25, linewidth=.7)
    ax.plot(frequencies, 10*np.log10(np.maximum(psd.mean(0)*1e12, np.finfo(float).tiny)),
            color="black", label="Mean channel power")
    ax.set(xlabel="Frequency (Hz)", ylabel="Power (dB µV²/Hz)",
           title="Resting EEG: Welch PSD, BAD excluded")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "rest_psd.png", dpi=150)
    plt.close(fig)
    raw.close()
    return {"channels": spectrum.ch_names, "frequency_range_hz": [lower, upper],
            "reject_by_annotation": True, "units": "V²/Hz", "n_fft": n_fft}


def analyze_epochs(path, output):
    import mne
    import numpy as np
    import matplotlib.pyplot as plt

    epochs = mne.read_epochs(path, preload=True, verbose=False)
    if not len(epochs):
        raise ValueError("No retained epochs")
    epochs.pick("eeg", exclude="bads")
    if not len(epochs.ch_names):
        raise ValueError("No usable EEG channels")
    conditions = list(epochs.event_id)
    evokeds = [epochs[name].average() for name in conditions if len(epochs[name])]
    mne.write_evokeds(output / "conditions-ave.fif", evokeds, overwrite=False, verbose=False)
    channel = "Pz" if "Pz" in epochs.ch_names else epochs.ch_names[0]
    fig, ax = plt.subplots(figsize=(8, 4))
    for evoked in evokeds:
        ax.plot(evoked.times, evoked.get_data(picks=[channel])[0]*1e6,
                label=f"{evoked.comment} (n={evoked.nave})")
    ax.axvline(0, color="black", linestyle=":", linewidth=.8)
    ax.axhline(0, color="gray", linewidth=.6)
    ax.set(xlabel="Time (s)", ylabel="Amplitude (µV)", title=f"Condition averages: {channel}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output / "condition_erp.png", dpi=150)
    plt.close(fig)

    # Deliberately use frequencies whose finite wavelets fit the available
    # window. For a scientific study, epoch with additional padding beforehand.
    duration = epochs.times[-1] - epochs.times[0]
    available = np.geomspace(max(8., epochs.info["highpass"]), min(25., epochs.info["lowpass"]), 12)
    frequencies = available[(available < epochs.info["sfreq"]/2) & (5*3/(np.pi*available) < duration)]
    tfr_summary = {"computed": False}
    if len(frequencies) >= 2 and frequencies[-1] > frequencies[0]:
        # Average=True returns power averaged across all retained trials.
        # For condition contrasts, compute the same expression per condition.
        power = epochs.compute_tfr(method="morlet", freqs=frequencies, n_cycles=3.,
                                   use_fft=True, return_itc=False, average=True,
                                   picks=[channel], decim=2, n_jobs=1, verbose=False)
        baseline = (max(-.2, float(power.times[0])), 0.)
        baseline_used = power.times[0] < 0 and baseline[0] < 0
        if baseline_used:
            power.apply_baseline(baseline, mode="logratio", verbose=False)
        np.savez_compressed(output / "time_frequency.npz", power=power.data,
                            frequencies_hz=power.freqs, times_s=power.times,
                            channels=np.asarray(power.ch_names))
        fig, ax = plt.subplots(figsize=(8, 4))
        mesh = ax.pcolormesh(power.times, power.freqs, power.data[0], shading="auto", cmap="RdBu_r")
        ax.axvline(0, color="black", linestyle=":", linewidth=.8)
        ax.set(xlabel="Time (s)", ylabel="Frequency (Hz)", title=f"{channel}: all retained trials")
        fig.colorbar(mesh, ax=ax, label="log10(power / baseline)" if baseline_used else "Power (V²)")
        fig.tight_layout()
        fig.savefig(output / "time_frequency.png", dpi=150)
        plt.close(fig)
        tfr_summary = {"computed": True, "channel": channel, "n_cycles": 3.,
                       "baseline": baseline if baseline_used else None,
                       "power_unit": "log10 ratio" if baseline_used else "V²",
                       "edge_effects_require_review": True,
                       "note": "ERP-filtered input limits available frequencies; use a prespecified broader analysis band for broadband TFR."}
    return {"retained_epochs": len(epochs), "per_condition": {name: len(epochs[name]) for name in conditions},
            "erp_channel": channel, "baseline_already_in_epochs": epochs.baseline,
            "tfr": tfr_summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--raw", type=Path)
    sources.add_argument("--epochs", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    import matplotlib
    matplotlib.use("Agg")
    output.mkdir(parents=True)
    summary = analyze_rest(args.raw, output) if args.raw else analyze_epochs(args.epochs, output)
    (output / "analysis_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf8")
    print(f"Saved exploratory analysis to {output}")


if __name__ == "__main__":
    main()
