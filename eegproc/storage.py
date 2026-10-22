"""Collision-checked output plans and staged writes for MNE result families."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from ._utils import _json_default


@dataclass(frozen=True)
class OutputPlan:
    directory: Path
    subject: str
    source_paths: tuple = ()

    def preflight(self):
        directory=Path(self.directory).resolve()
        targets=[directory/f'{self.subject}_cont_raw.fif', directory/f'{self.subject}-ica.fif',
                 directory/f'{self.subject}_clean-epo.fif', directory/f'{self.subject}_report.html',
                 directory/f'{self.subject}_ica_review']
        sources={Path(p).resolve() for p in self.source_paths if p}
        if any(p in sources for p in targets):
            raise ValueError('Output path overlaps an input file; choose a separate output directory')
        existing=[p for p in targets if p.exists()]
        if directory.exists():
            for pattern in (f'{self.subject}_cont_raw-*.fif',f'{self.subject}_clean-epo-*.fif'):
                existing.extend(directory.glob(pattern))
        if existing:
            raise FileExistsError('Output already exists; choose a fresh subject/output directory: '+str(existing[0]))
        return self


def _retry_windows_file_operation(operation):
    """Allow brief sync/antivirus locks, never retry other filesystem failures."""
    delays=(.05,.1,.2,.4,.8,1.)
    for attempt in range(len(delays)+1):
        try:return operation()
        except OSError as exc:
            if getattr(exc,'winerror',None) not in (5,32,33) or attempt==len(delays):
                raise
            time.sleep(delays[attempt])


def _file_identity(path):
    stat=Path(path).lstat()
    return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns


def _owned_file(path,identities):
    try:return _file_identity(path) in identities
    except FileNotFoundError:return False


def _commit(staged, target_directory):
    """Commit a validated family; roll back only newly created files on error."""
    pairs=[(Path(p),Path(target_directory)/Path(p).name) for p in staged]
    if any(dst.exists() for _,dst in pairs):
        raise FileExistsError('Output appeared while writing; existing data were not replaced')
    committed=[]
    try:
        for src,dst in pairs:
            source_identity=_file_identity(src)
            with dst.open('xb') as stream:
                stat=os.fstat(stream.fileno())
                reserved=(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
            # A rename on the same filesystem preserves the source identity.
            # Track both states so rollback remains safe even if replace succeeds
            # immediately before another operation raises.
            identities={reserved,source_identity}
            committed.append((dst,identities))
            def replace_owned():
                if not _owned_file(dst,{reserved}):
                    raise FileExistsError('Reserved output changed; external data were not replaced')
                os.replace(src,dst)
            _retry_windows_file_operation(replace_owned)
    except BaseException as exc:
        for dst,identities in reversed(committed):
            def remove_owned():
                if _owned_file(dst,identities):dst.unlink(missing_ok=True)
            try:_retry_windows_file_operation(remove_owned)
            except OSError as cleanup_error:
                exc.add_note(f'Could not remove newly created output {dst}: {cleanup_error}')
        raise
    return [dst for dst,_ in committed]


def atomic_save_raw(raw,target):
    import mne
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.eeg-write-',dir=target.parent) as staging:
        files=raw.save(Path(staging)/target.name,fmt='double',overwrite=False,verbose='warning')
        check=mne.io.read_raw_fif(Path(staging)/target.name,preload=False,verbose=False)
        if check.n_times!=raw.n_times or check.ch_names!=raw.ch_names:
            raise IOError('Saved Raw failed its sample/channel verification')
        check.close()
        return _commit(files,target.parent)


def atomic_save_ica(model,target):
    import mne
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.eeg-write-',dir=target.parent) as staging:
        staged=Path(staging)/target.name;model.save(staged,overwrite=False,verbose='warning')
        check=mne.preprocessing.read_ica(staged,verbose='warning')
        if check.ch_names!=model.ch_names or check.n_components_!=model.n_components_:
            raise IOError('Saved ICA failed verification')
        return _commit([staged],target.parent)[0]


def atomic_save_epochs(epochs,target):
    import mne
    target=Path(target).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.eeg-write-',dir=target.parent) as staging:
        staged=Path(staging)/target.name
        epochs.save(staged,fmt='double',overwrite=False,verbose=False)
        check=mne.read_epochs(staged,preload=False,verbose=False)
        if len(check.events)!=len(epochs.events) or check.ch_names!=epochs.ch_names:
            raise IOError('Saved Epochs failed verification')
        del check
        return _commit(sorted(Path(staging).glob('*.fif')),target.parent)


def atomic_write_text(path,text,*,overwrite=True):
    target=Path(path).resolve();target.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.eeg-write-',dir=target.parent) as staging:
        staged=Path(staging)/target.name
        with staged.open('w',encoding='utf8',newline='') as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        if overwrite:os.replace(staged,target)
        else:_commit([staged],target.parent)


def atomic_write_json(path,payload):
    atomic_write_text(path,json.dumps(payload,ensure_ascii=False,indent=2,default=_json_default),overwrite=False)


def file_receipt(path,kind):
    path=Path(path).resolve()
    with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(path=str(path),kind=kind,bytes=path.stat().st_size,sha256=digest,status='committed')


class OutputStore:
    def __init__(self,report):
        self.report=report;report.setdefault('stage_files',[]);report.setdefault('output_files',[])

    def record(self,files,kind):
        self.report['output_files'].extend(file_receipt(p,kind) for p in files)

    def save_final(self,raw,target):
        files=atomic_save_raw(raw,target)
        self.report['final_raw_files']=[str(p) for p in files];self.record(files,'raw')

    def save_ica(self,model,target):
        self.record([atomic_save_ica(model,target)],'ica')

    def save_epochs(self,epochs,target):
        files=atomic_save_epochs(epochs,target)
        self.report['epoch_files']=[str(p) for p in files];self.record(files,'epochs')

