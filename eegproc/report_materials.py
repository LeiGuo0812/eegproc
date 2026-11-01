"""Bounded, read-only numerical report material without plotting imports.

Sampling and diagnostics are shared by immediate and deferred reports.  This
module does not initialize Matplotlib, a canvas, fonts or global plot settings.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import warnings

import numpy as np
import mne
from scipy.signal import welch

CLASS_NAMES = ['Brain', 'Muscle', 'Eye', 'Heart', 'Line noise', 'Channel noise', 'Other']
PLOT_OPTIONS = ContextVar('eeg_plot_options', default={})


@contextmanager
def material_options(config=None):
    """Provide display sampling options without changing plotting runtime state."""
    token = PLOT_OPTIONS.set(config or {})
    try:
        yield
    finally:
        PLOT_OPTIONS.reset(token)


def bad_spans(raw):
    sf=raw.info['sfreq']; spans=[]
    for a in raw.annotations:
        if a['description'].lower().startswith(('bad','edge','boundary')):
            lo=max(0,int(np.floor((a['onset']-raw.first_time)*sf+1e-7)))
            hi=min(raw.n_times,max(lo+1,int(np.ceil((a['onset']-raw.first_time+a['duration'])*sf-1e-7))))
            if hi>lo:spans.append((lo,hi,str(a['description'])))
    return spans



def referenced(raw, selected, reference, start, stop):
    # get_data returns copies; never change input Raw or its annotations.
    ref=raw.get_data(picks=reference,start=start,stop=stop).mean(axis=0)
    return (raw.get_data(picks=selected,start=start,stop=stop)-ref)*1e6



def waveform_data(original, clean, good, bads):
    """Collect the existing representative windows without creating figures."""
    options=PLOT_OPTIONS.get();seconds=options.get('report_window_seconds',4.)
    limit=options.get('report_waveform_windows',3);max_channels=options.get('report_max_channels',6)
    sf=original.info['sfreq']; width=min(original.n_times,max(1,round(seconds*sf)))
    starts=list(range(0,max(1,original.n_times-width+1),width))
    if starts[-1]!=original.n_times-width:starts.append(original.n_times-width)
    scores=[]
    for start in starts:
        before=referenced(original,good,good,start,start+width)
        after=referenced(clean,good,good,start,start+width)
        scores.append((float(np.ptp(before,axis=1).max()),float(np.ptp(after,axis=1).max())))
    # Typical valid window, not an arbitrary unusually clean excerpt.
    eligible=[i for i,s in enumerate(starts) if not any(hi>s and lo<s+width for lo,hi,_ in bad_spans(original))]
    eligible=eligible or list(range(len(starts)))
    median=np.median([scores[i][0] for i in eligible]);typical=min(eligible,key=lambda i:abs(scores[i][0]-median))
    choices={}
    for start,label in [(starts[typical],'Representative amplitude'),
                        (starts[int(np.argmax(np.array(scores)[:,0]))],'Largest input peak-to-peak'),
                        (starts[int(np.argmax(np.array(scores)[:,1]))],'Largest output peak-to-peak')]:
        choices.setdefault(start,[]).append(label)
    # With a reduced budget prioritize residual problems over the typical window.
    if limit<len(choices):
        ordered=sorted(choices,key=lambda s:('Largest output peak-to-peak' not in choices[s], 'Largest input peak-to-peak' not in choices[s]))
        choices={s:choices[s] for s in ordered[:limit]}
    elif limit>len(choices):
        for i in np.unique(np.linspace(0,len(starts)-1,min(limit,len(starts)),dtype=int)):
            if len(choices)>=limit:break
            choices.setdefault(starts[i],['Additional window'])
    windows=[]; records=[]
    for i,(start,labels) in enumerate(choices.items()):
        before=referenced(original,good,good,start,start+width)
        after=referenced(clean,good,good,start,start+width)
        selected=[]
        candidates=[good[int(np.argmax(np.ptp(before,axis=1)))],good[int(np.argmax(np.ptp(after,axis=1)))]]
        candidates += [n for n in ['Fp1','Fz','Cz','Pz','Oz'] if n in good]
        candidates += [good[j] for j in np.linspace(0,len(good)-1,min(4,len(good)),dtype=int)]
        for name in candidates:
            if name not in selected:selected.append(name)
            if len(selected)>=min(4,max(2,max_channels-min(2,len(bads)))):break
        selected+=bads[:max_channels-len(selected)]
        before=referenced(original,selected,good,start,start+width)
        after=referenced(clean,selected,good,start,start+width)
        before-=np.median(before,axis=1,keepdims=True)
        after-=np.median(after,axis=1,keepdims=True)
        windows.append(dict(start=start,width=width,sfreq=sf,seconds=seconds,labels=labels,
            selected=selected,bads=bads,before=before,after=after,
            input_spans=bad_spans(original),output_spans=bad_spans(clean)))
        records.append(dict(start_sample=start,stop_sample=start+width,start_seconds=start/sf,stop_seconds=(start+width)/sf,reason=labels,channels=selected))
    return dict(windows=windows,records=records)



def paired_psd(original, clean, good, max_windows=60, window_seconds=4.):
    sf=original.info['sfreq'];width=min(round(window_seconds*sf),original.n_times)
    if width<max(8,round(sf)):raise ValueError('Less than one second of data for PSD comparison')
    spans=bad_spans(original)
    # Short recordings/segments need a shorter window, recorded explicitly.
    valid=np.ones(original.n_times,bool)
    for lo,hi,_ in spans:valid[lo:hi]=False
    edges=np.flatnonzero(np.diff(np.r_[False,valid,False].astype(int)))
    lengths=edges[1::2]-edges[::2]
    if len(lengths):width=min(width,int(max(lengths)))
    if width<max(8,round(sf)):raise ValueError('No sufficiently long non-BAD input segment')
    eligible=[s for s in range(0,original.n_times-width+1,width) if not any(hi>s and lo<s+width for lo,hi,_ in spans)]
    if not eligible:
        eligible=[int(a) for a,b in zip(edges[::2],edges[1::2]) if b-a>=width]
    if not eligible:raise ValueError('No paired PSD windows outside input BAD/boundaries')
    starts=[eligible[i] for i in np.unique(np.linspace(0,len(eligible)-1,min(max_windows,len(eligible)),dtype=int))]
    sums=[None,None]
    for start in starts:
        for i,raw in enumerate([original,clean]):
            x=referenced(raw,good,good,start,start+width)
            f,p=welch(x,fs=sf,nperseg=width,noverlap=0,window='hann',detrend='constant',scaling='density',axis=-1)
            sums[i]=p if sums[i] is None else sums[i]+p
    return f,sums[0]/len(starts),sums[1]/len(starts),dict(window_seconds=width/sf,window_count=len(starts),
        starts_samples=starts,channels=good,reference='mean of originally usable EEG channels',
        original_bad_excluded=True,output_bad_excluded=False,units='uV^2/Hz',
        requested_window_seconds=window_seconds,frequency_resolution_hz=sf/width)



def full_record_data(original,clean,good,bads):
    """EEG analogue of whole-run reportlets, not fMRI FD/DVARS or regressors."""
    eeg=[original.ch_names[i] for i in mne.pick_types(original.info,eeg=True,exclude=[])];sf=original.info['sfreq'];width=max(1,round(sf))
    masks=[]
    for raw in (original,clean):
        mask=np.zeros(raw.n_times,bool)
        for lo,hi,_ in bad_spans(raw):mask[lo:hi]=True
        masks.append(mask)
    matrices=[[],[]];rows=[];good_indices=[eeg.index(n) for n in good]
    for lo in range(0,original.n_times,width):
        hi=min(lo+width,original.n_times);signals=[]
        for i,raw in enumerate((original,clean)):
            x=referenced(raw,eeg,good,lo,hi);signals.append(x);matrices[i].append(np.ptp(x,axis=1))
        rms=np.sqrt(np.mean((signals[1][good_indices]-signals[1][good_indices].mean(axis=1,keepdims=True))**2,axis=1))
        rows.append(dict(start_sample=lo,stop_sample=hi,onset_seconds=lo/sf,duration_seconds=(hi-lo)/sf,
            input_bad_fraction=float(masks[0][lo:hi].mean()),output_bad_fraction=float(masks[1][lo:hi].mean()),
            input_max_ptp_uv=float(max(matrices[0][-1][good_indices])),output_max_ptp_uv=float(max(matrices[1][-1][good_indices])),
            output_median_rms_uv=float(np.median(rms))))
    matrices=[np.asarray(x).T for x in matrices]
    groups=np.array_split(np.arange(len(rows)),min(1200,len(rows)))
    displays=[np.column_stack([x[:,g].max(axis=1) for g in groups]) for x in matrices]
    edges=np.r_[[rows[g[0]]['onset_seconds'] for g in groups],original.n_times/sf]
    return dict(displays=displays,edges=edges,rows=rows,eeg=eeg,bads=bads,
        output_spans=bad_spans(clean),duration=original.n_times/sf,sfreq=sf,
        sampling=dict(window_samples=width,window_count=len(rows),display_columns=len(groups),
                      display_aggregation='max',channels=eeg,reference_channels=good))



def sensor_data(info):
    """Only geometry used by sensor plots; no full recording or model."""
    return dict(names=list(info['ch_names']),sfreq=float(info['sfreq']),
        locations=np.array([c['loc'] for c in info['chs']]),
        frames=[int(c['coord_frame']) for c in info['chs']],
        dig=[dict(kind=int(d['kind']),ident=int(d['ident']),r=np.asarray(d['r']),
                  coord_frame=int(d['coord_frame'])) for d in info.get('dig') or []],
        dev_head_t=None if info.get('dev_head_t') is None else dict(
            fro=int(info['dev_head_t']['from']),to=int(info['dev_head_t']['to']),
            trans=np.asarray(info['dev_head_t']['trans'])))



def sensor_info(data):
    from mne._fiff._digitization import _format_dig_points
    info=mne.create_info(data['names'],data['sfreq'],'eeg')
    for channel,loc,frame in zip(info['chs'],data['locations'],data['frames']):
        channel['loc']=np.asarray(loc).copy();channel['coord_frame']=frame
    with info._unlock():
        info['dig']=_format_dig_points([dict(d,r=np.asarray(d['r'])) for d in data['dig']])
        transform=data.get('dev_head_t')
        info['dev_head_t']=(None if transform is None else mne.transforms.Transform(
            transform['fro'],transform['to'],np.asarray(transform['trans'])))
    return info



def ica_data(report,ica=None,training=None):
    """Capture maps and bounded numeric diagnostics, without plotting."""
    ir=report.get('ica',{});p=np.asarray(ir.get('probabilities',[]),float)
    if p.ndim!=2 or p.shape[1]!=7:return dict(notes=[])
    if not isinstance(ica,mne.preprocessing.ICA) or training is None:
        return dict(notes=['ICA maps unavailable: model or training preview missing.'])
    origin=report.get('ica_preview',{}).get('original_start_seconds',0.)
    stop=min(training.n_times,round(60*training.info['sfreq']))
    src=ica.get_sources(training,start=0,stop=stop).get_data();maps=ica.get_components();sf=training.info['sfreq']
    details=[]
    for idx in range(len(p)):
        key=f'ica_topomap_{idx}'
        n=min(src.shape[1],round(10*sf));groups=np.array_split(np.arange(n),min(400,n))
        indices=np.unique(np.concatenate([[g[np.argmin(src[idx,g])],g[np.argmax(src[idx,g])]] for g in groups]))
        ff,pp=welch(src[idx],fs=sf,nperseg=min(round(4*sf),src.shape[1]),detrend='constant')
        keep=(ff>=0)&(ff<=min(100,sf/2))
        details.append(dict(component=idx,topomap_key=key,time_seconds=np.round(origin+indices/sf,5).tolist(),
            activation=np.round(src[idx,indices],6).tolist(),frequency_hz=np.round(ff[keep],5).tolist(),
            power_db=np.round(10*np.log10(np.maximum(pp[keep],1e-30)),4).tolist(),
            spectrum_duration_seconds=src.shape[1]/sf))
    return dict(maps=maps,geometry=sensor_data(ica.info),diagnostics=details,notes=[])



def retention_rows(report):
    ep=report.get('epochs',{}); names={str(v):k for k,v in (report.get('event_id') or {}).items()}
    result=[]
    for code,row in ep.get('condition_retention',{}).items():
        total=int(row.get('input',row.get('total',0))); kept=int(row.get('retained',0));eligible=row.get('eligible')
        if total<0 or kept<0 or kept>total:raise ValueError('Inconsistent epoch counts')
        if eligible is not None and not kept<=eligible<=total:raise ValueError('Inconsistent eligible epoch counts')
        result.append(dict(code=str(code),name=names.get(str(code),'Event code '+str(code)),input=total,retained=kept,
            eligible=eligible,annotation_rejected=None if eligible is None else total-int(eligible),
            qc_rejected=total-kept if eligible is None else int(eligible)-kept,
            retention_fraction=kept/total if total else None))
    return result



def collect_report_materials(report,original,clean,ica=None,training=None):
    """Read bounded diagnostic material now; defer every plotting operation."""
    if (original.n_times!=clean.n_times or original.first_samp!=clean.first_samp or
        original.info['sfreq']!=clean.info['sfreq'] or original.info['meas_date']!=clean.info['meas_date'] or original.ch_names!=clean.ch_names):
        raise ValueError('Input/output sample grids, clocks or channels do not match')
    eeg=[original.ch_names[i] for i in mne.pick_types(original.info,eeg=True,exclude=[])];bads=[n for n in report.get('bad_channels',[]) if n in eeg];good=[n for n in eeg if n not in bads]
    if len(good)<2:raise ValueError('At least two usable input EEG channels are required')
    out=dict(errors=[],notes=[],bads=bads)
    with material_options(report.get('config',{})):
        def collect(name,fn):
            try:out[name]=fn()
            except Exception as exc:out['errors'].append(dict(section=name,type=type(exc).__name__,message=str(exc)))
        with warnings.catch_warnings(record=True) as caught:
            collect('waveforms',lambda:waveform_data(original,clean,good,bads))
            def psd():
                options=PLOT_OPTIONS.get();hp=report.get('config',{}).get('highpass',.5)
                seconds=options.get('report_psd_window_seconds') or min(20.,max(4.,2./hp))
                f,a,b,meta=paired_psd(original,clean,good,max_windows=options.get('report_psd_windows',30),window_seconds=seconds)
                return dict(frequency=f,before=a,after=b,metadata=meta)
            collect('psd',psd)
            collect('sensors',lambda:sensor_data(mne.pick_info(clean.info,mne.pick_types(clean.info,eeg=True,exclude=[]),copy=True)))
            out['timeline']=dict(sfreq=float(original.info['sfreq']),n_times=int(original.n_times),
                input_spans=bad_spans(original),output_spans=bad_spans(clean))
            if report.get('config',{}).get('report_full_record_heatmap',False):
                collect('whole_record_qc',lambda:full_record_data(original,clean,good,bads))
            if 'ica_display' in report:
                out['ica_display']=report['ica_display']
            elif 'ica_materials' in report:
                out['ica']=report['ica_materials']
            else:
                collect('ica',lambda:ica_data(report,ica,training))
        out['warnings']=sorted(set(str(w.message) for w in caught))
    return out
