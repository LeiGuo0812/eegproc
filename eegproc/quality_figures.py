"""Read-only, deterministic diagnostic plots for human EEG review.

Comparisons share samples, channels and display reference. They measure change,
not signal recovery: no clean ground truth is available in a routine report.
"""
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import warnings
import numpy as np
import mne
from scipy.signal import welch
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import rc_context, font_manager

PRE = '#226fbd'
POST = '#df7826'
BAD = '#bf3b49'
GOOD = '#27846e'
CLASS_NAMES = ['Brain', 'Muscle', 'Eye', 'Heart', 'Line noise', 'Channel noise', 'Other']
PLOT_OPTIONS = ContextVar('eeg_plot_options', default={})


@contextmanager
def style(config=None):
    family = ['DejaVu Sans', 'Microsoft YaHei'] if Path('C:/Windows/Fonts/msyh.ttc').exists() else ['DejaVu Sans']
    token=PLOT_OPTIONS.set(config or {})
    try:
        with rc_context({'font.family':family, 'font.size':10, 'axes.unicode_minus':False,
                         'svg.fonttype':'none', 'pdf.fonttype':42}):
            yield
    finally:
        PLOT_OPTIONS.reset(token)


def figure(*args, **kwargs):
    fig = Figure(*args, layout='constrained', **kwargs)
    FigureCanvasAgg(fig)
    return fig


def asset(fig, folder, key, title, caption):
    import base64,io
    from PIL import Image
    options=PLOT_OPTIONS.get();maximum=options.get('report_max_width',1200)
    dpi=min(options.get('report_dpi',100),maximum/fig.get_size_inches()[0])
    buffer=io.BytesIO();fig.savefig(buffer,format='png',dpi=dpi,bbox_inches='tight',pil_kwargs={'optimize':True});fig.clear()
    with Image.open(io.BytesIO(buffer.getvalue())) as source:
        if source.width>maximum:source=source.resize((maximum,round(source.height*maximum/source.width)),Image.Resampling.LANCZOS)
        # Palette PNG reduces report size; numeric diagnostics retain full precision.
        source=source.convert('RGB').quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
        final=io.BytesIO();source.save(final,format='PNG',optimize=True);width,height=source.size
    data=final.getvalue()
    result=dict(key=key,title=title,caption=caption,sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),width_px=width,height_px=height)
    result['data_uri']='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
    return result


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


def waveform_figures(original, clean, good, bads, folder):
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
    figs=[]; records=[]
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
        fig=figure(figsize=(12,1.25*len(selected)+1.0));axes=fig.subplots(len(selected),1,sharex=True,squeeze=False)[:,0]
        tt=(start+np.arange(width))/sf
        # Envelope-preserving extrema thinning for very high sample rates.
        for j,(name,ax) in enumerate(zip(selected,axes)):
            inds=np.arange(width)
            if width>2400:
                chunks=np.array_split(inds,600)
                inds=np.unique(np.concatenate([[c[np.argmin(before[j,c])],c[np.argmax(before[j,c])],c[np.argmin(after[j,c])],c[np.argmax(after[j,c])]] for c in chunks]))
            ax.plot(tt[inds],before[j,inds],color=PRE,lw=.8,label='Before')
            ax.plot(tt[inds],after[j,inds],color=POST,lw=.8,label='After')
            for raw,color in [(original,'#e3c24c'),(clean,'#dc6976')]:
                for lo,hi,_ in bad_spans(raw):
                    if hi>start and lo<start+width:ax.axvspan(max(lo,start)/sf,min(hi,start+width)/sf,color=color,alpha=.10)
            ax.set_ylabel(name+('*' if name in bads else '')+'\nµV');ax.grid(alpha=.15)
            ax.spines[['top','right']].set_visible(False)
        axes[0].legend(loc='upper right',ncol=2);axes[-1].set_xlabel('Time from recording start (s)')
        title=' / '.join(labels)+f': {start/sf:.2f}–{(start+width)/sf:.2f} s'
        fig.suptitle(title,fontsize=13)
        caption=f'Paired channels and samples; average reference over original good channels; median removed per display window. Windows selected from {seconds:g}-s blocks. Yellow: input BAD; red: output BAD; *: bad channel.'
        figs.append(asset(fig,folder,f'waveform_{i+1}',title,caption))
        records.append(dict(start_sample=start,stop_sample=start+width,start_seconds=start/sf,stop_seconds=(start+width)/sf,reason=labels,channels=selected))
    return figs,records


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


def psd_figure(original,clean,good,report,folder):
    options=PLOT_OPTIONS.get();hp=report.get('config',{}).get('highpass',.5)
    seconds=options.get('report_psd_window_seconds') or min(20.,max(4.,2./hp))
    f,a,b,meta=paired_psd(original,clean,good,max_windows=options.get('report_psd_windows',30),window_seconds=seconds)
    fig=figure(figsize=(13,5));axes=fig.subplots(1,2)
    positive=f>0; upper=min(120.,f[-1])
    for ax,xlim in zip(axes,[(max(.1,float(f[1])),upper),(1,min(45,upper))]):
        visible=(f>=xlim[0]) & (f<=xlim[1]);limits=[]
        for p,label,color in [(a,'Before',PRE),(b,'After',POST)]:
            q=np.maximum(np.percentile(p,[25,50,75],axis=0),1e-30)
            limits.extend((10*np.log10(q[:,visible])).ravel())
            ax.plot(f[positive],10*np.log10(q[1,positive]),label=label,color=color,lw=1.6)
            ax.fill_between(f[positive],10*np.log10(q[0,positive]),10*np.log10(q[2,positive]),color=color,alpha=.13)
        for edge in [report.get('config',{}).get('highpass'),report.get('config',{}).get('lowpass')]:
            if edge is not None and xlim[0]<=edge<=xlim[1]:ax.axvline(edge,color='grey',ls='--',lw=1)
        line=report.get('config',{}).get('line_frequency')
        if line:
            for hz in np.arange(line,upper+1,line):ax.axvline(hz,color=BAD,ls=':',lw=.8)
        ax.set(xlim=xlim,xlabel='Frequency (Hz)',ylabel='PSD (dB, uV²/Hz)');ax.grid(alpha=.15);ax.legend()
        if limits:
            lo,hi=min(limits),max(limits);pad=max(2,(hi-lo)*.06);ax.set_ylim(lo-pad,hi+pad)
    axes[0].set_title('Broadband spectrum')
    axes[1].set_title('1–45 Hz; shaded channel interquartile range')
    caption=f"Paired input-good channels; {meta['window_count']} windows of {meta['window_seconds']:g} s, excluding input BAD. Median and interquartile range across channels. Dashed lines: analysis band; dotted lines: line frequencies."
    return asset(fig,folder,'psd','Power spectral density',caption),meta


def line_noise_figure(report,folder):
    """Render the measured intermediate spectra, independent of final filtering."""
    data=report.get('line_diagnostics',{})
    if data.get('status')!='available':return None
    freq=np.asarray(data['frequency_hz'])
    before=np.asarray(data['before_psd_quartiles']);after=np.asarray(data['after_psd_quartiles'])
    metrics=data['metrics'];ncols=min(2,len(metrics));nrows=int(np.ceil(len(metrics)/ncols))
    fig=figure(figsize=(12,4.2*nrows));axes=fig.subplots(nrows,ncols,squeeze=False).ravel()
    for ax,row in zip(axes,metrics):
        hz=row['frequency_hz'];visible=np.abs(freq-hz)<=5.
        for values,label,color in [(before,'Before line cleaning',PRE),(after,'After line cleaning',POST)]:
            db=10*np.log10(np.maximum(values[:,visible],1e-30))
            ax.plot(freq[visible],db[1],color=color,lw=1.5,label=label)
            ax.fill_between(freq[visible],db[0],db[2],color=color,alpha=.13)
        ax.axvspan(row['band_low_hz'],row['band_high_hz'],color='#697580',alpha=.07)
        ax.axvline(hz,color='#697580',ls=':',lw=1)
        reduction=row['median_reduction_db']
        change=f'{reduction:.1f} dB' if reduction is not None else 'unavailable'
        ax.set(title=f'{hz:g} Hz · band-power reduction: {change}',
            xlabel='Frequency (Hz)',ylabel='PSD (dB, µV²/Hz)',xlim=(freq[visible][0],freq[visible][-1]))
        ax.grid(alpha=.15);ax.legend(fontsize=9)
        ax.spines[['top','right']].set_visible(False)
    for ax in axes[len(metrics):]:ax.set_visible(False)
    caption=(f"Line-cleaning stage only, before band filtering, ASR and ICA. "
        f"{data['window_count']} paired {data['window_seconds']:g}-s windows; "
        f"{data['frequency_resolution_hz']:g} Hz resolution. Recorded reference; input BAD intervals "
        f"and input-bad channels excluded. Curves: median channel PSD; shading: channel interquartile range. "
        "Reduction: median paired channel power change in bins within ±1 Hz; positive values indicate lower power.")
    return asset(fig,folder,'line_noise','Line-noise removal',caption)


def sensors_figure(original,report,folder):
    info=mne.pick_info(original.info,mne.pick_types(original.info,eeg=True,exclude=[]),copy=True);bads=report.get('bad_channels',[])
    info['bads']=[n for n in bads if n in info['ch_names']]
    fig=figure(figsize=(10,7));ax=fig.subplots()
    mne.viz.plot_sensors(info,kind='topomap',ch_type='eeg',show_names=info['bads'],axes=ax,show=False,
        title=f'Bad channels: {len(info["bads"])} / {len(info["ch_names"])} (red)',pointsize=65,verbose=False)
    ax.set_title(f'Bad channels: {len(info["bads"])} / {len(info["ch_names"])} (red)',pad=20)
    return asset(fig,folder,'bad_channels','Channel locations','Bad channels are shown in red.')


def timeline_figure(original,clean,folder):
    sf=original.info['sfreq'];fig=figure(figsize=(13,2.8));ax=fig.subplots()
    for row,raw,color in [(1,original,'#bd9e30'),(0,clean,BAD)]:
        ax.broken_barh([(lo/sf,(hi-lo)/sf) for lo,hi,_ in bad_spans(raw)],(row-.18,.36),facecolors=color)
    ax.set(yticks=[0,1],yticklabels=['Output BAD / boundaries','Input BAD / boundaries'],xlim=(0,original.n_times/sf),xlabel='Time from recording start (s)',ylim=(-.6,1.6))
    ax.grid(axis='x',alpha=.15)
    return asset(fig,folder,'bad_timeline','Annotation timeline','Input and output BAD annotations on the original sample grid.')


def full_record_qc(original,clean,good,bads,folder):
    """EEG analogue of whole-run reportlets, not fMRI FD/DVARS or regressors."""
    from matplotlib.colors import LogNorm
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
    vmax=max(1.,float(max(x.max() for x in displays)));norm=LogNorm(vmin=.1,vmax=max(1.,vmax))
    fig=figure(figsize=(14,10));axes=fig.subplots(3,1,sharex=True,gridspec_kw={'height_ratios':[1.2,1.2,1]})
    ticks=np.arange(0,len(eeg),max(1,int(np.ceil(len(eeg)/32))))
    for ax,x,label in zip(axes[:2],displays,['Before','After']):
        im=ax.pcolormesh(edges,np.arange(len(eeg)+1),np.maximum(x,.1),norm=norm,cmap='magma',shading='flat')
        ax.set_yticks(ticks+.5,[eeg[j]+('*' if eeg[j] in bads else '') for j in ticks],fontsize=8)
        ax.invert_yaxis();ax.set_ylabel('EEG channels');ax.set_title(label+': channel peak-to-peak (* interpolated)',loc='left')
    fig.colorbar(im,ax=list(axes[:2]),label='Peak-to-peak (uV; shared log scale)',pad=.02)
    tt=np.array([r['onset_seconds'] for r in rows])
    for key,label,color in [('input_max_ptp_uv','Input maximum peak-to-peak',PRE),('output_max_ptp_uv','Output maximum peak-to-peak',POST)]:
        axes[2].plot(tt,np.maximum([r[key] for r in rows],.1),lw=.8,color=color,label=label)
    for lo,hi,_ in bad_spans(clean):axes[2].axvspan(lo/sf,hi/sf,color=BAD,alpha=.12)
    axes[2].set(yscale='log',ylabel='Peak-to-peak (uV; log scale)',xlabel='Time from recording start (s)',xlim=(0,original.n_times/sf));axes[2].legend(fontsize=9);axes[2].grid(alpha=.15)
    caption='Non-overlapping 1-s windows with a shared log scale. Display bins use the maximum when compressed. Red: output BAD.'
    return asset(fig,folder,'whole_record_qc','Channel-by-time peak-to-peak',caption),rows,dict(window_samples=width,window_count=len(rows),display_columns=len(groups),display_aggregation='max',channels=eeg,reference_channels=good)


def ica_figures(report,folder,ica=None,training=None):
    """Small topomaps plus numeric detail data for an on-demand HTML dialog."""
    if 'ica_display' in report:
        display=report['ica_display']
        report['ica_diagnostics']=display['diagnostics']
        return display['figures'],display['notes']
    ir=report.get('ica',{});p=np.asarray(ir.get('probabilities',[]),float)
    if p.ndim!=2 or p.shape[1]!=7:return [],[]
    if not isinstance(ica,mne.preprocessing.ICA) or training is None:
        return [],['ICA maps unavailable: model or training preview missing.']
    origin=report.get('ica_preview',{}).get('original_start_seconds',0.)
    stop=min(training.n_times,round(60*training.info['sfreq']))
    src=ica.get_sources(training,start=0,stop=stop).get_data();maps=ica.get_components();sf=training.info['sfreq']
    figures=[];details=[]
    for idx in range(len(p)):
        topo=maps[:,idx];topo=topo/max(np.max(np.abs(topo)),1e-30)
        fig=figure(figsize=(2.,2.));ax=fig.subplots()
        mne.viz.plot_topomap(topo,ica.info,axes=ax,show=False,contours=0,vlim=(-1,1),cmap='RdBu_r',sensors=False)
        key=f'ica_topomap_{idx}'
        figures.append(asset(fig,folder,key,f'IC {idx}','Normalized component topography.'))
        n=min(src.shape[1],round(10*sf));groups=np.array_split(np.arange(n),min(400,n))
        indices=np.unique(np.concatenate([[g[np.argmin(src[idx,g])],g[np.argmax(src[idx,g])]] for g in groups]))
        ff,pp=welch(src[idx],fs=sf,nperseg=min(round(4*sf),src.shape[1]),detrend='constant')
        keep=(ff>=0)&(ff<=min(100,sf/2))
        details.append(dict(component=idx,topomap_key=key,time_seconds=np.round(origin+indices/sf,5).tolist(),
            activation=np.round(src[idx,indices],6).tolist(),frequency_hz=np.round(ff[keep],5).tolist(),
            power_db=np.round(10*np.log10(np.maximum(pp[keep],1e-30)),4).tolist(),
            spectrum_duration_seconds=src.shape[1]/sf))
    report['ica_diagnostics']=details
    return figures,[]


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


def retention_figure(report,folder):
    rows=retention_rows(report)
    if not rows:return None,rows
    fig=figure(figsize=(12,max(3.5,.55*len(rows)+1.6)));axes=fig.subplots(1,2,gridspec_kw={'width_ratios':[1.6,1]})
    y=np.arange(len(rows));kept=np.array([r['retained'] for r in rows]);qc=np.array([r['qc_rejected'] for r in rows]);ann=np.array([r['annotation_rejected'] or 0 for r in rows])
    axes[0].barh(y,kept,label='Retained',color=GOOD);axes[0].barh(y,qc,left=kept,label='QC rejected',color=POST);axes[0].barh(y,ann,left=kept+qc,label='Annotations / boundaries',color=BAD)
    axes[0].set_yticks(y,[r['name']+f" [code{r['code']}]" for r in rows]);axes[0].invert_yaxis();axes[0].set_xlabel('Epochs');axes[0].legend(loc='upper center',bbox_to_anchor=(.5,1.2),fontsize=8,ncol=2)
    for i,r in enumerate(rows):axes[0].text(r['input']+.2,i,f"{r['retained']}/{r['input']}",va='center')
    axes[0].set_xlim(0,max(r['input'] for r in rows)*1.22+1)
    values=[100*r['retention_fraction'] if r['retention_fraction'] is not None else 0 for r in rows]
    axes[1].barh(y,values,color=GOOD);axes[1].set_yticks(y,[r['name'] for r in rows]);axes[1].invert_yaxis();axes[1].set(xlim=(0,115),xlabel='Retention (%)')
    for i,r in enumerate(rows):axes[1].text(values[i]+1,i,f'{values[i]:.1f}%' if r['input'] else 'No input',va='center')
    return asset(fig,folder,'epoch_retention','Epoch retention by condition','Input, annotation-rejected, QC-rejected and retained epochs by condition.'),rows


def build_signal_figures(report,original,clean,folder,ica=None,training=None):
    if (original.n_times!=clean.n_times or original.first_samp!=clean.first_samp or
        original.info['sfreq']!=clean.info['sfreq'] or original.info['meas_date']!=clean.info['meas_date'] or original.ch_names!=clean.ch_names):
        raise ValueError('Input/output sample grids, clocks or channels do not match')
    eeg=[original.ch_names[i] for i in mne.pick_types(original.info,eeg=True,exclude=[])];bads=[n for n in report.get('bad_channels',[]) if n in eeg];good=[n for n in eeg if n not in bads]
    if len(good)<2:raise ValueError('At least two usable input EEG channels are required')
    out=dict(version=1,figures=[],notes=[],errors=[],display_only=True,signal_data_modified=False)
    with style(report.get('config',{})):
        def attempt(name,fn):
            try:return fn()
            except Exception as exc:out['errors'].append(dict(section=name,type=type(exc).__name__,message=str(exc)));return None
        with warnings.catch_warnings(record=True) as caught:
            waves=attempt('waveforms',lambda:waveform_figures(original,clean,good,bads,folder))
            if waves:out['figures']+=waves[0];out['waveform_windows']=waves[1]
            psd=attempt('psd',lambda:psd_figure(original,clean,good,report,folder))
            if psd:out['figures'].append(psd[0]);out['psd_sampling']=psd[1]
            line=attempt('line_noise',lambda:line_noise_figure(report,folder))
            if line:out['figures'].append(line)
            if report.get('line_diagnostics',{}).get('error'):
                out['errors'].append(dict(section='line_noise',type=report['line_diagnostics']['error'],
                    message=report['line_diagnostics']['reason']))
            whole=(attempt('whole_record_qc',lambda:full_record_qc(original,clean,good,bads,folder))
                   if report.get('config',{}).get('report_full_record_heatmap',False) else None)
            if whole:
                out['figures'].append(whole[0]);report['qc_timeseries']=whole[1];out['whole_record_sampling']=whole[2]
            out['whole_record_heatmap_requested']=bool(report.get('config',{}).get('report_full_record_heatmap',False))
            # The output also has an explicitly supplied montage if input lacked one.
            for name,fn in [('bad_channels',lambda:sensors_figure(clean,report,folder)),('bad_timeline',lambda:timeline_figure(original,clean,folder))]:
                f=attempt(name,fn)
                if f:out['figures'].append(f)
            ic=attempt('ica',lambda:ica_figures(report,folder,ica,training))
            if ic:out['figures']+=ic[0];out['notes']+=ic[1]
        out['plot_warnings']=sorted(set(str(w.message) for w in caught))
    return out
