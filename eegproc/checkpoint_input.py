"""Reference the existing input instead of saving another original Raw file."""
from pathlib import Path
import json
import mne
import numpy as np
from ._utils import _json_default
from .raw_helpers import signal_hash
from .report_provenance import file_hash
from .compatibility import INPUT_IDENTITY_VERSION


def _plain(value):
    """Convert MNE metadata to portable JSON values without losing fields."""
    if isinstance(value, np.ndarray):return value.tolist()
    if isinstance(value, np.generic):return value.item()
    if isinstance(value, dict):return {str(k):_plain(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):return [_plain(v) for v in value]
    if hasattr(value,'isoformat'):return value.isoformat()
    return value


def metadata_identity(raw):
    """Metadata sufficient to reject a different baseline without reading data."""
    return dict(
        ch_names=list(raw.ch_names), channel_types=raw.get_channel_types(),
        n_times=int(raw.n_times), sfreq=float(raw.info['sfreq']),
        first_samp=int(raw.first_samp), meas_date=str(raw.info['meas_date']),
        annotation_orig_time=str(raw.annotations.orig_time),
        annotations=[dict(onset=float(a['onset']),duration=float(a['duration']),
                          description=a['description'],ch_names=list(a.get('ch_names',())),
                          extras=dict(a.get('extras',{}))) for a in raw.annotations],
        bads=list(raw.info['bads']),
        units=[[int(c['unit']),int(c['unit_mul'])] for c in raw.info['chs']],
        locations=np.array([c['loc'] for c in raw.info['chs']]).tolist(),
        coordinate_frames=[int(c['coord_frame']) for c in raw.info['chs']],
        digitization=_plain(raw.info.get('dig')),
        transforms={key:_plain(raw.info.get(key)) for key in ('dev_head_t','ctf_head_t','dev_ctf_t')},
        projections=_plain(raw.info['projs']),
        custom_ref_applied=int(raw.info['custom_ref_applied']),
        highpass=float(raw.info['highpass']),lowpass=float(raw.info['lowpass']),
    )


def input_identity(raw, data_hash=None):
    """Record the signal and metadata needed to verify a report's baseline."""
    return dict(identity_version=INPUT_IDENTITY_VERSION,
                signal_sha256=data_hash or signal_hash(raw), **metadata_identity(raw))


def metadata_equal(expected, actual, *, tolerant=False):
    """Use FIF float precision only for coordinate/projector numeric metadata."""
    if isinstance(expected,dict):
        return (isinstance(actual,dict) and expected.keys()==actual.keys()
                and all(metadata_equal(v,actual[k],tolerant=tolerant) for k,v in expected.items()))
    if isinstance(expected,(list,tuple)):
        return (isinstance(actual,(list,tuple)) and len(expected)==len(actual)
                and all(metadata_equal(a,b,tolerant=tolerant) for a,b in zip(expected,actual)))
    if isinstance(expected,(float,np.floating)) and isinstance(actual,(float,int,np.number)):
        if tolerant:return bool(np.isclose(expected,actual,rtol=1e-6,atol=1e-8,equal_nan=True))
        if np.isnan(expected):return bool(np.isnan(actual))
    return expected==actual


def identity_matches(expected, actual):
    """Old v2 identities validate every field they recorded; new ones add checks."""
    tolerant={'locations','digitization','transforms','projections'}
    return all(k in actual and metadata_equal(v,actual[k],tolerant=k in tolerant)
               for k,v in expected.items())


def input_reference(raw, data_hash=None):
    paths=[Path(p).resolve() for p in raw.filenames if p]
    first=paths[0] if paths else None
    is_fif=first is not None and first.name.lower().endswith(('.fif','.fif.gz'))
    return dict(identity=input_identity(raw,data_hash),
                fif_path=str(first) if is_fif else None,
                files=[dict(path=str(p),sha256=file_hash(p)) for p in paths] if is_fif else [])


def load_original(reference, *, original_raw=None, original_fif=None):
    if original_raw is not None and original_fif is not None:
        raise ValueError('Supply original_raw or original_fif, not both')
    if original_raw is None:
        path=original_fif or reference.get('fif_path')
        if not path or not Path(path).is_file():
            raise ValueError('Original input is required for resume: pass original_raw=raw '
                             'or --original-fif prepared/input_raw.fif')
        if original_fif is None:
            for item in reference.get('files',[]):
                p=Path(item['path'])
                if not p.is_file() or file_hash(p)!=item['sha256']:
                    raise ValueError('Original input file changed or is missing: '+str(p))
        original_raw=mne.io.read_raw_fif(path,preload=False,verbose=False)
    if not isinstance(original_raw,mne.io.BaseRaw):
        raise TypeError('original_raw must be a continuous MNE Raw object')
    actual=input_identity(original_raw)
    expected=reference['identity']
    if not identity_matches(expected,actual):
        raise ValueError('Original input does not match the checkpoint signal or metadata')
    return original_raw
