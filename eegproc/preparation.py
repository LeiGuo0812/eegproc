"""Device I/O and metadata preparation, separate from preprocessing."""
from dataclasses import dataclass
from pathlib import Path
import re
import mne
import numpy as np
from .report_provenance import file_hash
from .storage import atomic_save_raw,atomic_write_json


@dataclass
class PreparationResult:
    """Prepared recording and events, available without writing any files."""
    raw: mne.io.BaseRaw
    events: np.ndarray
    event_id: dict
    provenance: dict
    outputs: dict


def _brainvision_references(header):
    """Read actual header references; associated files need not share a stem."""
    content=header.read_bytes()
    try:text=content.decode('utf-8-sig')
    except UnicodeDecodeError:text=content.decode('cp1252')
    references=[];section=None
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('['):section=line.lower()
        if section!='[common infos]':continue
        match=re.match(r'(DataFile|MarkerFile)\s*=\s*(.+)',line,re.IGNORECASE)
        if match:
            name=match.group(2).strip().replace('\\','/')
            references.append((header.parent/name).resolve())
    return references


def _preparation_targets(out,sources):
    """Check every known output and split-file family before writing anything."""
    targets=[out,out.with_suffix('.preparation.json'),out.with_suffix('.events.json')]
    source_paths={Path(p).resolve() for p in sources}
    if any(p in source_paths for p in targets):
        raise ValueError('Prepared output must not overwrite an original input file')
    existing=[p for p in targets if p.exists()]
    suffix='.fif.gz' if out.name.lower().endswith('.fif.gz') else '.fif'
    if not out.name.lower().endswith(suffix):raise ValueError('Prepared output must end in .fif or .fif.gz')
    stem=out.name[:-len(suffix)]
    if out.parent.exists():
        split=re.compile(re.escape(stem)+r'-\d+\.fif(?:\.gz)?$',re.IGNORECASE)
        existing.extend(p for p in out.parent.iterdir() if split.fullmatch(p.name))
    if existing:
        raise FileExistsError('Prepared output already exists; choose a fresh output: '+str(existing[0]))
    return targets


def prepare_data(source, *, output_fif=None, channel_types=None, rename=None, drop=(),
                 montage=None, event_id=None, allow_legacy_uv_per_mm=False,return_result=False):
    """Return MNE Raw without filtering, rereferencing, or artifact cleaning.

    Generic formats use MNE's calibrated SI readers. Neuracle uses the explicit
    vendor calibration, never amplitude-based unit guessing. Preserve clocks/BAD.
    ``return_result=True`` also returns events, provenance and output paths.
    """
    path=Path(source).resolve()
    if path.is_dir():
        from .io.neuracle import import_neuracle
        from .io.bridge import eeg_to_raw
        raw=eeg_to_raw(import_neuracle(path,allow_legacy_uv_per_mm=allow_legacy_uv_per_mm))
        sources=[path/'data.bdf',path/'evt.bdf'];reader='Neuracle vendor-calibrated importer'
    else:
        if allow_legacy_uv_per_mm:raise ValueError('Legacy calibration requires a Neuracle directory')
        readers={'.fif':mne.io.read_raw_fif,'.edf':mne.io.read_raw_edf,'.bdf':mne.io.read_raw_bdf,
                 '.vhdr':mne.io.read_raw_brainvision,'.set':mne.io.read_raw_eeglab}
        suffix='.fif' if path.name.lower().endswith('.fif.gz') else path.suffix.lower()
        if suffix not in readers:raise ValueError('Supported inputs: Neuracle directory, FIF, EDF, BDF, VHDR, SET')
        raw=readers[suffix](path,preload=False,verbose=False);sources=[path];reader=readers[suffix].__name__
        sources += [Path(p) for p in raw.filenames if p and Path(p)!=path]
        if suffix=='.vhdr':sources += _brainvision_references(path)
        # EEGLAB's resolved external .fdt (or embedded .set) is raw.filenames;
        # a same-stem .fdt guess may refer to an unrelated recording.
    sources=list(dict.fromkeys(Path(p).resolve() for p in sources))
    out=Path(output_fif).resolve() if output_fif is not None else None
    targets=_preparation_targets(out,sources) if out is not None else None
    if rename:raw.rename_channels(rename)
    if channel_types:raw.set_channel_types(channel_types)
    if drop:raw.drop_channels(list(drop))
    if montage is not None:raw.set_montage(montage,on_missing='raise',verbose=False)
    events,mapping=mne.events_from_annotations(raw,event_id=event_id,verbose=False)
    provenance=dict(schema_version=1,reader=reader,
        sources=[dict(path=str(p),bytes=p.stat().st_size,sha256=file_hash(p)) for p in dict.fromkeys(sources) if p.is_file()],
        units='SI (EEG/EOG/ECG in volts)',legacy_neuracle_uv_per_mm=allow_legacy_uv_per_mm,
        rename=rename or {},channel_types=channel_types or {},dropped_channels=list(drop),
        montage=str(montage) if montage is not None else None,first_samp=raw.first_samp,
        sfreq=raw.info['sfreq'],n_times=raw.n_times,meas_date=str(raw.info['meas_date']),
        input_highpass=raw.info['highpass'],input_lowpass=raw.info['lowpass'],
        filtering_applied=False,rereferencing_applied=False,artifact_cleaning_applied=False,
        event_sample_convention='absolute MNE samples including first_samp')
    outputs={}
    if out is not None:
        created=[]
        try:
            files=atomic_save_raw(raw,out);created.extend(files)
            provenance['saved_raw_files']=[str(p) for p in files]
            atomic_write_json(targets[1],provenance);created.append(targets[1])
            atomic_write_json(targets[2],dict(events=events.tolist(),event_id=mapping));created.append(targets[2])
            outputs=dict(raw=str(out),raw_files=[str(p) for p in files],
                         provenance=str(targets[1]),events=str(targets[2]))
        except BaseException:
            # Atomic writers roll back their own failing file family. Remove
            # only successfully committed files from this preparation attempt.
            for written in reversed(created):
                written=Path(written).resolve()
                if written.parent!=out.parent or written in sources:
                    raise RuntimeError('Refusing cleanup outside prepared output folder')
                written.unlink(missing_ok=True)
            raise
    return PreparationResult(raw,events,mapping,provenance,outputs) if return_result else raw
