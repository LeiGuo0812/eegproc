"""Continuous EEGPrep/EEGLAB (microvolts) <-> MNE Raw (volts).

This project's EEGLAB positions have +X anterior, +Y left, +Z superior and
explicit millimetre units. The bundled standard_1005 template is first rotated
to MNE axes, then rigidly transformed using its LPA/RPA/nasion fiducials to the
MNE head frame. This is template geometry, not individual digitization or an
individual MRI registration. Specify position_unit for other coordinate units.
"""
from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import as_file, files

import numpy as np

_PREFIX = "EEGLAB_MNE_BRIDGE_V1\n"
_SCALES = {"mm": 1e-3, "cm": 1e-2, "m": 1.0}
_TYPE_MAP = {"eeg": "eeg", "eog": "eog", "ecg": "ecg", "ekg": "ecg",
             "emg": "emg", "stim": "stim", "misc": "misc", "bio": "bio"}


def _json_default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _metadata(raw):
    description = raw.info.get("description") or ""
    if description.startswith(_PREFIX):
        try:
            return json.loads(description[len(_PREFIX):])
        except (TypeError, ValueError):
            pass
    return {}


def _template_geometry(template_path=None):
    import mne

    if template_path:
        montage = mne.channels.read_custom_montage(Path(template_path), head_size=None)
    else:
        resource = files('eegproc.resources').joinpath('standard_1005.elc')
        with as_file(resource) as path:
            montage = mne.channels.read_custom_montage(path, head_size=None)
    transform = mne.channels.compute_native_head_t(montage, on_missing="raise")
    matrix = np.asarray(transform["trans"], dtype=float)
    native = montage.get_positions()
    fiducials = {name: (matrix @ np.r_[native[name], 1.0])[:3]
                 for name in ("nasion", "lpa", "rpa")}
    return matrix, fiducials


def _position(channel):
    values = [np.asarray(channel.get(axis, [])) for axis in ("X", "Y", "Z")]
    if not all(value.size == 1 for value in values):
        return None
    xyz = np.array([float(value.reshape(-1)[0]) for value in values])
    return xyz if np.isfinite(xyz).all() else None


def _description(value):
    if isinstance(value, (int, float, np.number)) and np.isfinite(value):
        return str(int(value)) if float(value).is_integer() else str(float(value))
    return str(value)


def eeg_to_raw(eeg, *, position_unit="mm", coordinate_mode=None, template_path=None,
               highpass=None, lowpass=None):
    """Convert a finite continuous dict without filtering or re-referencing.

    position_unit is an explicit fixed convention, never estimated from radii.
    coordinate_mode='template' uses bundled fiducials; 'head' means the EEG axes
    already share the MNE head origin. Metadata from raw_to_eeg selects the
    appropriate mode automatically on a round trip. Events use 1-based latency
    and durations in samples; MNE annotations use seconds. Scalar event types
    survive FIF through annotation extras; descriptions remain plain labels.
    """
    import mne

    if position_unit not in _SCALES:
        raise ValueError("position_unit must be 'mm', 'cm', or 'm'.")
    if int(eeg.get("trials", 1)) != 1:
        raise ValueError("Only continuous, single-trial EEG is supported.")
    data = np.asarray(eeg["data"], dtype=float)
    locations = list(eeg.get("chanlocs", []))
    if data.ndim != 2 or not np.isfinite(data).all() or data.shape[1] < 1:
        raise ValueError("EEG data must be finite channels-by-samples microvolts.")
    if len(locations) != data.shape[0]:
        raise ValueError("chanlocs must contain one entry per data channel.")
    labels = [str(channel["labels"]) for channel in locations]
    if len(set(labels)) != len(labels):
        raise ValueError("Channel labels must be unique.")
    sfreq = float(eeg["srate"])
    if not np.isfinite(sfreq) or sfreq <= 0:
        raise ValueError("srate must be finite and positive.")
    previous = eeg.get("etc", {}).get("mne_bridge", {})
    if previous.get("position_unit", position_unit) != position_unit:
        raise ValueError("position_unit disagrees with saved EEG coordinate units; pass the matching unit explicitly.")
    mode = coordinate_mode or previous.get("coordinate_mode", "template")
    if mode not in {"template", "head"}:
        raise ValueError("coordinate_mode must be 'template' or 'head'.")
    nose = eeg.get("chaninfo", {}).get("nosedir", "+X")
    if isinstance(nose, str) and nose and nose != "+X":
        raise ValueError("Expected EEGLAB +X nose coordinates; normalize the electrode axes first.")
    if mode == "template" and template_path is None and previous.get("template_native_to_head") is not None:
        transform = np.asarray(previous["template_native_to_head"], dtype=float)
        if transform.shape != (4, 4) or not np.isfinite(transform).all():
            raise ValueError("Saved template_native_to_head must be a finite 4x4 transform.")
        fiducials = {key: np.asarray(value, dtype=float) for key, value in
                     previous.get("template_fiducials_head", {}).items()}
    else:
        transform, fiducials = _template_geometry(template_path) if mode == "template" else (np.eye(4), {})
    types = [_TYPE_MAP.get(str(channel.get("type", "EEG")).casefold(), "eeg") for channel in locations]
    if any(kind == "stim" for kind in types):
        raise ValueError("Stim channels are counts, not microvolts; exclude them before conversion.")
    info = mne.create_info(labels, sfreq, types)
    raw = mne.io.RawArray(data * 1e-6, info, verbose="ERROR")
    positions = {}
    for name, channel in zip(labels, locations):
        xyz = _position(channel)
        if xyz is not None:
            native = np.array([-xyz[1], xyz[0], xyz[2]]) * _SCALES[position_unit]
            positions[name] = (transform @ np.r_[native, 1.0])[:3]
    if positions:
        eeg_positions = {name: positions[name] for name, kind in zip(labels, types)
                         if kind == "eeg" and name in positions}
        if eeg_positions:
            montage = mne.channels.make_dig_montage(ch_pos=eeg_positions, coord_frame="head", **fiducials)
            raw.set_montage(montage, on_missing="ignore", verbose="ERROR")
        # set_montage intentionally ignores auxiliary EOG/ECG/EMG channels.
        # Their supplied coordinates still belong in FIF's channel metadata.
        from mne._fiff.constants import FIFF
        for index, name in enumerate(labels):
            if name in positions:
                raw.info["chs"][index]["loc"][:3] = positions[name]
                raw.info["chs"][index]["coord_frame"] = FIFF.FIFFV_COORD_HEAD
    ref = eeg.get("ref", "common")
    inherited = eeg.get("etc", {}).get("mne_info", {})
    applied = bool(inherited.get("custom_ref_applied", False)) or str(ref).casefold() in {
        "averef", "average", "car", "average reference"}
    if applied and "eeg" in types:
        # Public MNE operation: [] marks the existing reference, subtracting nothing.
        raw.set_eeg_reference(ref_channels=[], projection=False, verbose="ERROR")
    hp = highpass if highpass is not None else inherited.get("highpass")
    lp = lowpass if lowpass is not None else inherited.get("lowpass")
    if hp is not None or lp is not None:
        hp = float(raw.info["highpass"] if hp is None else hp)
        lp = float(raw.info["lowpass"] if lp is None else lp)
        if not 0 <= hp < lp <= sfreq / 2:
            raise ValueError("Filter metadata must satisfy 0 <= highpass < lowpass <= Nyquist.")
        with raw.info._unlock():
            raw.info["highpass"], raw.info["lowpass"] = hp, lp
    metadata = {"position_unit": position_unit, "coordinate_mode": mode,
                "template_native_to_head": transform.tolist(), "eeglab_ref": ref,
                "template_fiducials_head": {key: value.tolist() for key, value in fiducials.items()},
                "custom_ref_applied": applied,
                "channel_types_original": {name: channel.get("type", "EEG") for name, channel in zip(labels, locations)},
                "coordinate_note": "Standard template fiducial head transform; no individual digitization/MRI registration."}
    raw.info["description"] = _PREFIX + json.dumps(metadata, ensure_ascii=False, default=_json_default)
    onsets, durations, descriptions, extras = [], [], [], []
    for event in eeg.get("event", []):
        latency = float(event["latency"])
        duration = float(event.get("duration", 0) or 0)
        if not np.isfinite(latency) or not np.isfinite(duration) or duration < 0:
            raise ValueError("Events require finite latency and nonnegative duration in samples.")
        is_boundary = str(event.get("type", "")).casefold() == "boundary"
        minimum, maximum = (0.5, data.shape[1] + 0.5) if is_boundary else (1, data.shape[1])
        if not minimum <= latency <= maximum:
            raise ValueError("Event latency must lie within 1..pnts.")
        description = "BAD boundary" if is_boundary else _description(event.get("type", ""))
        onset = (latency - 1) / sfreq
        extra = {"eeglab_type_json": json.dumps(event.get("type", ""), default=_json_default),
                 "eeglab_description": description}
        if is_boundary:
            # A boundary duration counts removed samples, not time occupying
            # this Raw. Preserve that number only in metadata, and put edge
            # boundaries exactly at the acquisition's start/end.
            if latency == 0.5:
                onset = 0.0
            elif latency == data.shape[1] + 0.5:
                onset = data.shape[1] / sfreq
            extra.update(eeglab_boundary=1,
                         eeglab_boundary_latency_offset=latency - (onset * sfreq + 1),
                         eeglab_boundary_removed_samples=duration)
        extra.update(eeglab_onset_seconds=onset,
                     eeglab_duration_seconds=0.0 if is_boundary else duration / sfreq)
        onsets.append(onset)
        durations.append(0.0 if is_boundary else duration / sfreq)
        descriptions.append(description)
        extras.append(extra)
    raw.set_annotations(mne.Annotations(onsets, durations, descriptions, extras=extras), verbose="ERROR")
    return raw


def export_mne_fif(eeg, path, *, position_unit="mm", coordinate_mode=None,
                   template_path=None, highpass=None, lowpass=None, overwrite=False):
    """Save a double-precision MNE Raw FIF; metadata parameters never filter data."""
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = eeg_to_raw(eeg, position_unit=position_unit, coordinate_mode=coordinate_mode,
                     template_path=template_path, highpass=highpass, lowpass=lowpass)
    raw.save(destination, fmt="double", overwrite=overwrite, verbose="ERROR")
    return str(destination)
