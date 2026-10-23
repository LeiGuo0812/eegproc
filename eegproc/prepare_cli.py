"""Prepare device recordings as MNE Raw/FIF before preprocessing."""
from eegproc.preparation import prepare_data


def main(argv=None):
    import argparse,json
    from pathlib import Path
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,help='Neuracle directory or supported EEG file')
    p.add_argument('--output-fif',required=True)
    p.add_argument('--montage',help='Actual cap geometry name, e.g. standard_1005; do not guess')
    p.add_argument('--eog',nargs='*',default=[]);p.add_argument('--ecg',nargs='*',default=[])
    p.add_argument('--stim',nargs='*',default=[]);p.add_argument('--drop',nargs='*',default=[])
    p.add_argument('--rename-json',help='JSON object mapping old to new channel names')
    p.add_argument('--event-id-json',help='JSON object mapping annotation descriptions to codes')
    p.add_argument('--neuracle-uv-per-mm',action='store_true')
    a=p.parse_args(argv)
    mapping=lambda name:json.loads(Path(name).read_text(encoding='utf-8-sig')) if name else None
    types={n:t for t,names in [('eog',a.eog),('ecg',a.ecg),('stim',a.stim)] for n in names}
    raw=prepare_data(a.input,output_fif=a.output_fif,montage=a.montage,channel_types=types,drop=a.drop,
        rename=mapping(a.rename_json),event_id=mapping(a.event_id_json),allow_legacy_uv_per_mm=a.neuracle_uv_per_mm)
    print(json.dumps(dict(output_fif=str(Path(a.output_fif).resolve()),channels=len(raw.ch_names),
        sfreq=raw.info['sfreq'],samples=int(raw.n_times),first_samp=int(raw.first_samp)),ensure_ascii=False))


if __name__=='__main__':main()
