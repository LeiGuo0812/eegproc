"""Bounded copies and hashes without changing MNE clocks or annotation origins."""
import hashlib
import mne
import numpy as np


def raw_slice(raw, start=0, stop=None, picks=None):
    """Copy only requested channels/samples, preserving the absolute sample clock."""
    stop = raw.n_times if stop is None else stop
    if not 0 <= start < stop <= raw.n_times:
        raise ValueError('Invalid sample interval')
    indices = np.arange(len(raw.ch_names)) if picks is None else np.asarray(picks)
    info = mne.pick_info(raw.info, indices, copy=True)
    result = mne.io.RawArray(raw.get_data(picks=indices, start=start, stop=stop), info,
                             first_samp=raw.first_samp + start, copy='auto', verbose=False)
    annotations = raw.annotations.copy()
    if annotations.orig_time is None:
        annotations.onset -= result.first_time
    # Match Raw.pick(): MNE intersects scoped annotations with retained
    # channels and drops annotations whose scope becomes empty. In particular,
    # an excluded channel's BAD must never become a global BAD on this slice.
    result.set_annotations(annotations, emit_warning=False, on_missing='ignore')
    return result


def signal_hash(raw, block_samples=65536):
    """SHA256 of channel-major little-endian float64, matching the former full copy."""
    digest = hashlib.sha256()
    for channel in range(len(raw.ch_names)):
        for start in range(0, raw.n_times, block_samples):
            values = raw.get_data(picks=[channel], start=start, stop=min(start+block_samples,raw.n_times))
            digest.update(np.asarray(values, dtype='<f8').tobytes(order='C'))
    return digest.hexdigest()


def channel_is_finite_nonconstant(raw, channel, block_samples=65536):
    """Check an auxiliary channel without materializing its complete recording."""
    first = raw.get_data(picks=[channel], start=0, stop=1)[0, 0]
    nonconstant = False
    for start in range(0, raw.n_times, block_samples):
        values = raw.get_data(picks=[channel], start=start,
                              stop=min(start + block_samples, raw.n_times))
        if not np.isfinite(values).all():
            return False
        nonconstant |= bool(np.any(values != first))
    return nonconstant


def concatenate_samples(raw, spans, picks=None):
    """Copy selected intervals in their given order into one allocated array.

    This helper handles numeric auxiliary signals only. EEG training continues
    to use MNE concatenation, which also constructs boundary annotations.
    """
    indices = np.arange(len(raw.ch_names)) if picks is None else np.asarray(picks)
    result = np.empty((len(indices), sum(stop - start for start, stop in spans)), dtype=float)
    position = 0
    for start, stop in spans:
        length = stop - start
        result[:, position:position + length] = raw.get_data(
            picks=indices, start=start, stop=stop)
        position += length
    return result
