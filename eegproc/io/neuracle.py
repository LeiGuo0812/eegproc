"""Read the two-file Neuracle recording used by ``Preproc_EEGLAB_new.m``.

Signal decoding and BDF+ annotation parsing use pyEDFlib.  The adapter deliberately
preserves two unusual details of Neuracle's MATLAB importer:

* ``read_bdf.m`` multiplies digital values by the header gain, without adding the
  header's physical offset.  ``calibration='neuracle'`` reproduces that operation.
* ``pop_importNeuracle.m`` assigns ``round(onset_seconds * srate)`` to an EEGLAB
  latency, without adding one.  Events outside [1, pnts], including onset zero,
  are discarded.  ``round`` uses MATLAB's half-away-from-zero rule.

Consequently these are EEGLAB's 1-based *latency fields*, but the legacy importer
places annotations one sample earlier than the usual ``onset * srate + 1`` rule.
The convention is recorded in ``EEG['etc']['neuracle_import']``.  Changing it would
be a change to the original processing pipeline.

References:
https://github.com/neuracle/neuracle-eegfile-reader/blob/master/pop_importNeuracle.m
https://github.com/neuracle/neuracle-eegfile-reader/blob/master/read_bdf.m
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Literal

import numpy as np


def matlab_round(values: float | np.ndarray) -> np.ndarray:
    """Round finite numbers with ties away from zero, unlike Python/NumPy round."""
    array = np.asarray(values, dtype=np.float64)
    if not np.all(np.isfinite(array)):
        raise ValueError("Event onset/sample values must be finite.")
    return np.copysign(np.floor(np.abs(array) + 0.5), array).astype(np.int64)


def _microvolt_scale(dimension: str, allow_unit_conversion: bool,
                     allow_legacy_uv_per_mm: bool = False) -> float:
    unit = dimension.strip().replace("µ", "u").replace("μ", "u").casefold()
    if unit == "uv/mm" and allow_legacy_uv_per_mm:
        # Explicit vendor compatibility, NOT a voltage/length unit conversion.
        # The unmodified source header remains in import provenance.
        return 1.0
    scales = {"v": 1e6, "mv": 1e3, "uv": 1.0, "nv": 1e-3}
    if unit not in scales:
        raise ValueError(
            f"Unsupported BDF physical dimension {dimension!r}; a voltage unit "
            "(V, mV, uV, or nV) is required to produce unambiguous microvolts."
        )
    if scales[unit] != 1.0 and not allow_unit_conversion:
        raise ValueError(
            f"BDF physical dimension is {dimension!r}, not uV. The original "
            "MATLAB importer does not convert header units. Set "
            "allow_unit_conversion=True only if explicit conversion to uV is intended."
        )
    return scales[unit]


def _recording_paths(data_path: str | Path) -> tuple[Path, Path]:
    directory = Path(data_path).expanduser().resolve()
    if not directory.is_dir():
        raise NotADirectoryError(f"Neuracle input must be a recording folder: {directory}")
    files = {path.name.casefold(): path for path in directory.iterdir() if path.is_file()}
    # Original MATLAB supports pauses/multiple data segments, while this script's
    # input contract is explicitly data.bdf + evt.bdf.  Never silently omit them.
    segments = [name for name in files if name.startswith("data.") and name.endswith(".bdf") and name != "data.bdf"]
    nested_segments = [path for path in directory.iterdir() if path.is_dir() and any(path.glob("*.bdf"))]
    extra_events = [name for name in files if name.startswith("evt.") and name.endswith(".bdf") and name != "evt.bdf"]
    if segments or nested_segments or extra_events:
        raise NotImplementedError(
            "Multi-segment/HEEG Neuracle recordings are not supported by this "
            "two-file adapter. Additional files/folders: "
            + ", ".join(segments + extra_events + [p.name for p in nested_segments])
        )
    missing = [name for name in ("data.bdf", "evt.bdf") if name not in files]
    if missing:
        raise FileNotFoundError(f"Missing Neuracle file(s) in {directory}: {', '.join(missing)}")
    return files["data.bdf"], files["evt.bdf"]


def read_neuracle_bdf(
    data_path: str | Path,
    *,
    calibration: Literal["neuracle", "physical"] = "neuracle",
    allow_unit_conversion: bool = False,
    allow_legacy_uv_per_mm: bool = False,
) -> dict:
    """Return signals (channels × samples, µV), events, and import provenance.

    The default matches the gain-only calibration of the original MATLAB reader.
    ``calibration='physical'`` opts into standard BDF gain + offset calibration;
    it is useful for other exporters, but is explicitly not a faithful migration.
    All signal channels must have a common rate and sample count, as required by
    the original importer. Non-uV voltage units are rejected unless explicit
    conversion is requested with ``allow_unit_conversion=True``; the MATLAB
    importer does not convert header units. Annotation timing uses evt.bdf TAL onsets,
    without adjusting for differences between the two files' clock headers.

    ``allow_legacy_uv_per_mm=True`` explicitly interprets the literal legacy
    Neuracle label uV/mm as uV, using the vendor reader's unchanged gain-only
    numbers. This is an audited compatibility assumption, not a dimensional
    conversion or a physical calibration validation. It is off by default.
    """
    import pyedflib

    if calibration not in {"neuracle", "physical"}:
        raise ValueError("calibration must be 'neuracle' or 'physical'.")
    if allow_legacy_uv_per_mm and calibration != "neuracle":
        raise ValueError("Legacy uV/mm interpretation requires calibration='neuracle'.")
    data_file, event_file = _recording_paths(data_path)
    with pyedflib.EdfReader(str(data_file)) as reader:
        if not reader.signals_in_file:
            raise ValueError("data.bdf contains no signal channels.")
        rates = np.asarray(reader.getSampleFrequencies(), dtype=float)
        counts = np.asarray(reader.getNSamples(), dtype=np.int64)
        if np.any(rates != rates[0]) or np.any(counts != counts[0]):
            raise ValueError("All non-annotation channels must share sample rate and length.")
        if rates[0] <= 0 or counts[0] < 1:
            raise ValueError("data.bdf has an invalid sample rate or no data.")
        headers = reader.getSignalHeaders()
        labels = [header["label"] for header in headers]
        signal_rows = []
        calibration_info = []
        for index, header in enumerate(headers):
            digital_span = float(header["digital_max"] - header["digital_min"])
            physical_span = float(header["physical_max"] - header["physical_min"])
            if digital_span <= 0 or physical_span <= 0:
                raise ValueError(f"Invalid BDF calibration for channel {labels[index]!r}.")
            gain = physical_span / digital_span
            offset = float(header["physical_min"]) - gain * float(header["digital_min"])
            scale = _microvolt_scale(str(header["dimension"]), allow_unit_conversion,
                                     allow_legacy_uv_per_mm)
            digital = reader.readSignal(index, digital=True).astype(np.float64)
            physical = digital * gain
            if calibration == "physical":
                physical += offset
            signal_rows.append(physical * scale)
            calibration_info.append({
                "label": labels[index], "source_unit": str(header["dimension"]),
                "gain": gain, "physical_offset": offset, "scale_to_uV": scale,
            })
        data = np.stack(signal_rows)
        recording_header = reader.getHeader()

    with pyedflib.EdfReader(str(event_file)) as reader:
        onsets, durations, descriptions = reader.readAnnotations()
        event_header = reader.getHeader()
    latencies = matlab_round(np.asarray(onsets) * rates[0])
    n_samples = int(counts[0])
    events = [
        {"type": str(description), "latency": float(latency)}
        for latency, description in zip(latencies, descriptions)
        if 1 <= latency <= n_samples
    ]
    events.sort(key=lambda event: event["latency"])
    provenance = {
        "reader": "pyedflib",
        "data_file": str(data_file), "event_file": str(event_file),
        "signal_unit": "uV", "calibration": calibration,
        "unit_conversion_enabled": bool(allow_unit_conversion),
        "legacy_uv_per_mm_interpreted_as_uV": bool(allow_legacy_uv_per_mm),
        "unit_interpretation_note": ("Explicit Neuracle gain-only compatibility; uV/mm interpreted as uV, not a dimensional conversion"
                                     if allow_legacy_uv_per_mm else "Voltage units required; no legacy unit override"),
        "calibration_info": calibration_info,
        "event_latency_convention": "MATLAB round(onset_seconds*srate), no +1; keep 1..pnts",
        "event_count_in_file": len(onsets),
        "event_count_retained": len(events),
        "event_count_outside_data": len(onsets) - len(events),
        "annotation_durations_discarded": True,
        "source_annotation_onsets_seconds": np.asarray(onsets, dtype=float),
        "source_annotation_durations_seconds": np.asarray(durations, dtype=float),
        "data_start_datetime": recording_header["startdate"].isoformat(),
        "event_start_datetime": event_header["startdate"].isoformat(),
        "clock_header_adjustment": False,
    }
    return {
        "data": data, "srate": float(rates[0]), "labels": labels,
        "events": events, "metadata": provenance,
    }


def import_neuracle(
    data_path: str | Path,
    *,
    calibration: Literal["neuracle", "physical"] = "neuracle",
    allow_unit_conversion: bool = False,
    allow_legacy_uv_per_mm: bool = False,
) -> dict:
    """Import data.bdf + evt.bdf into the validated dictionary consumed by MNE."""

    recording = read_neuracle_bdf(
        data_path, calibration=calibration, allow_unit_conversion=allow_unit_conversion,
        allow_legacy_uv_per_mm=allow_legacy_uv_per_mm,
    )
    data = recording["data"]
    eeg = {"etc": {}}
    eeg.update({
        "setname": Path(data_path).resolve().name,
        "filepath": str(Path(data_path).resolve()),
        "data": data, "srate": recording["srate"],
        "nbchan": data.shape[0], "pnts": data.shape[1], "trials": 1,
        "xmin": 0.0, "xmax": (data.shape[1] - 1) / recording["srate"],
        "times": np.arange(data.shape[1], dtype=float) * 1000 / recording["srate"],
        "ref": "common",
        "event": np.asarray(recording["events"], dtype=object),
        "chanlocs": np.asarray([
            {"labels": label, "ref": "", "type": "", "urchan": index,
             **{field: np.array([], dtype=float) for field in
                ("theta", "radius", "X", "Y", "Z", "sph_theta", "sph_phi", "sph_radius")}}
            for index, label in enumerate(recording["labels"])
        ], dtype=object),
        "comments": "\n".join([recording["metadata"]["data_file"], recording["metadata"]["event_file"]]),
        "chaninfo": {"plotrad": [], "shrink": [], "nosedir": "+X", "icachansind": []},
    })
    eeg["urevent"] = deepcopy(eeg["event"])
    # EEGPrep's foreign-key indices are 0-based internally; its .set writer
    # converts them to MATLAB's 1-based representation. Latencies remain 1-based.
    for index, event in enumerate(eeg["event"]):
        event["urevent"] = index
    eeg["etc"]["neuracle_import"] = recording["metadata"]
    return eeg
