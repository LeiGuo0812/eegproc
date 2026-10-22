from report_helpers import read_report
from datetime import datetime,timezone
import json
import mne
import numpy as np
import pytest
from eeg_pipeline.pipeline import config_for,choose_components,preprocess_raw
from eeg_pipeline.epochs import EpochConfig,repair_epochs,screen


def test_public_cli_defaults_enable_asr_for_both_purposes():
    from eeg_pipeline.cli import parser
    from eeg_pipeline import resolve_config
    for purpose in ('rest','erp'):
        args=parser().parse_args(['--input-fif','source_raw.fif','--save-path','out','--subject','demo','--purpose',purpose,'--line-frequency','60'])
        c=resolve_config(purpose=args.purpose,line_frequency=args.line_frequency)
        assert c.asr_cutoff==20 and c.line_frequency==60
        assert resolve_config(purpose=purpose,asr_cutoff=None).asr_cutoff is None


def test_strict_output_never_changes_retained_trials(tmp_path):
    from erp_outputs import make_strict_epochs
    raw=fixture();clean=raw.copy()
    clean._data[2,1536:1600]+=1e-3*np.sin(np.linspace(0,8*np.pi,64))
    events=np.column_stack([raw.first_samp+np.arange(3,37,3)*256,np.zeros(12,int),np.ones(12,int)])
    original=mne.Epochs(clean,events,{'target':1},tmin=-.2,tmax=1,baseline=(None,0),preload=True,verbose=False)
    ep,r=make_strict_epochs(clean,raw,events,{'target':1},save_path=tmp_path,subject='strict')
    expected=original[~screen(original.get_data(picks='eeg'),EpochConfig()).any(axis=1)]
    np.testing.assert_array_equal(ep.events,expected.events)
    np.testing.assert_array_equal(ep.get_data(),expected.get_data())
    assert r['repaired_epochs']==0 and not r['enabled']


def fixture(clock=True):
    names=['Fp1','Fp2','F3','F4','C3','C4','P3','P4','O1','O2','Fz','Pz']
    sf=256.;n=10240;t=np.arange(n)/sf;rng=np.random.default_rng(429)
    xyz=np.array([mne.channels.make_standard_montage('standard_1005').get_positions()['ch_pos'][c] for c in names])
    mixing=np.exp(-np.linalg.norm(xyz[:,None,:]-xyz[None,::3,:],axis=2)**2/.02)
    data=mixing@np.array([np.sin(2*np.pi*f*t+p) for f,p in zip([5,9,14,20],[0,.3,.6,.9])])*5e-6
    data+=rng.normal(size=data.shape)*.1e-6
    aux=rng.normal(size=(1,n))*10e-6;stim=np.zeros((1,n));stim[0,1024:1026]=7
    raw=mne.io.RawArray(np.vstack([data,aux,stim]),mne.create_info(names+['EOG','STI'],sf,['eeg']*12+['eog','stim']),first_samp=4096,verbose=False)
    if clock:raw.set_meas_date(datetime(2020,1,1,tzinfo=timezone.utc))
    raw.set_montage('standard_1005');raw.set_annotations(mne.Annotations([4,10,20],[0,1,0],['target','BAD_manual','target']))
    return raw


def test_heart_uses_same_probability_rule_without_ecg_gate():
    p=np.array([[.01,.01,.01,.94,.01,.01,.01],
                [.01,.01,.01,.89,.01,.01,.06],
                [.21,0,0,.79,0,0,0]])
    assert choose_components(p,config_for())==[0]
    assert choose_components(p,config_for(artifact_threshold=.7))==[0,1]


@pytest.mark.parametrize('clock',[True,False])
def test_epoch_repair_preserves_original_bad_clock_aux_and_noop(clock,tmp_path):
    raw=fixture(clock);before=raw.get_data().copy()
    clean=raw.copy();clean.annotations.append(clean.first_time+3,2,'BAD_residual')
    events=np.array([[raw.first_samp+1024,0,1],[raw.first_samp+2560,0,1],[raw.first_samp+5120,0,1]])
    epochs,report=repair_epochs(clean,raw,events,{'target':1},save_path=tmp_path,subject='safe')
    assert list(epochs.events[:,0])==list(events[[0,2],0])
    assert report['retained_epochs']==2 and report['repaired_epochs']==0
    expected=mne.Epochs(raw,events,{'target':1},tmin=-.2,tmax=1,baseline=(None,0),preload=True,verbose=False)
    np.testing.assert_array_equal(epochs.get_data(),expected.get_data())
    np.testing.assert_array_equal(raw.get_data(),before)
    reread=mne.read_epochs(tmp_path/'safe_clean-epo.fif',preload=True,verbose=False)
    np.testing.assert_array_equal(reread.events,epochs.events)
    assert 'BAD_manual' in report['original_drop_log'][1]


def test_native_end_to_end_roundtrip(tmp_path):
    raw=fixture();before=raw.get_data().copy()
    events,event_id=mne.events_from_annotations(raw,verbose=False)
    clean,report,_=preprocess_raw(raw,tmp_path,'native',config=config_for('erp',asr_cutoff=20.,detect_ransac=False),
        events=events,event_id=event_id)
    reread=mne.io.read_raw_fif(tmp_path/'native_cont_raw.fif',preload=True,verbose=False)
    np.testing.assert_array_equal(reread.get_data(picks=['EOG','STI']),before[-2:])
    np.testing.assert_array_equal(raw.get_data(),before)
    assert reread.first_samp==raw.first_samp and reread.info['meas_date']==raw.info['meas_date']
    np.testing.assert_allclose([c['loc'][:3] for c in reread.info['chs'][:12]], [c['loc'][:3] for c in raw.info['chs'][:12]],atol=1e-8)
    assert report['epochs']['retained_epochs']==2
    assert report['quality']['data_deleted'] is False
    assert report['asr']['existing_bad_and_boundary_samples_excluded']==256
    saved=read_report((tmp_path/'native_report.html').read_text(encoding='utf8'))
    assert saved['pipeline']=='eegproc' and saved['outputs']['epochs'].endswith('_clean-epo.fif')


def test_post_screen_still_rejects_unrepairable_large_epochs(tmp_path):
    raw=fixture();events=np.column_stack([raw.first_samp+np.arange(3,37,3)*256,np.zeros(12,int),np.ones(12,int)])
    raw.set_annotations(mne.Annotations([],[],[]));clean=raw.copy()
    # All electrodes affected: local repair must not turn this into a valid trial.
    clean._data[:12,1536:1600]+=1e-3*np.sin(np.linspace(0,8*np.pi,64))
    ep,r=repair_epochs(clean,raw,events,{'target':1},config=EpochConfig(),save_path=tmp_path,subject='large')
    assert r['failed_screen_before_repair']>=1
    assert not screen(ep.get_data(picks='eeg'),EpochConfig()).any()
    assert all(len(x['interpolated_channels'])<=1 for x in r['records'])
