"""Portable, pickle-free report material in one compressed NumPy archive."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile

import numpy as np


def save_report_data(record, target):
    """Save small display arrays and the processing record, never a Raw/model."""
    from .storage import _commit
    arrays = {}
    array_ids = {}

    def pack(value):
        if isinstance(value, np.ndarray):
            if value.dtype.hasobject:
                raise TypeError('Object arrays are not supported in report data')
            name = array_ids.get(id(value))
            if name is None:
                name = f'array_{len(arrays)}'
                arrays[name] = value
                array_ids[id(value)] = name
            return {'__report_array__': name}
        if isinstance(value, np.generic):
            return value.item()
        if isinstance(value, dict):
            items = {str(key): pack(item) for key, item in value.items()}
            if set(items) in ({'__report_array__'}, {'__report_mapping__'}):
                return {'__report_mapping__': list(items.items())}
            return items
        if isinstance(value, (list, tuple)):
            return [pack(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        return value

    saved = {key: value for key, value in record.items()
             if not (key in ('ica_materials', 'ica_display') and 'report_materials' in record)}
    payload = {'format': 'eegproc-report-data', 'record': pack(saved)}
    arrays['record_json'] = np.asarray(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.eeg-report-', dir=target.parent) as staging:
        staged = Path(staging) / target.name
        with staged.open('wb') as stream:
            np.savez_compressed(stream, **arrays)
        _commit([staged], target.parent)
    return target


def read_report_data(path):
    """Read only JSON and numeric arrays; no pickled Python objects."""
    with np.load(Path(path), allow_pickle=False) as archive:
        payload = json.loads(str(archive['record_json'].item()))
        if payload.get('format') != 'eegproc-report-data' or not isinstance(payload.get('record'), dict):
            raise ValueError('File is not an eegproc report-data archive')

        def unpack(value):
            if isinstance(value, dict):
                if set(value) == {'__report_array__'}:
                    return archive[value['__report_array__']].copy()
                if set(value) == {'__report_mapping__'}:
                    return {key: unpack(item) for key, item in value['__report_mapping__']}
                return {key: unpack(item) for key, item in value.items()}
            if isinstance(value, list):
                return [unpack(item) for item in value]
            return value

        return unpack(payload['record'])
