"""Read-only, deterministic diagnostic plots for human EEG review.

Comparisons share samples, channels and display reference. They measure change,
not signal recovery: no clean ground truth is available in a routine report.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import sys
import warnings
import numpy as np
import mne
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import rc_context, font_manager

PRE = '#226fbd'
POST = '#df7826'
BAD = '#bf3b49'
GOOD = '#27846e'
# Re-export the numeric helpers used by earlier internal integrations.
from .report_materials import (
    CLASS_NAMES, PLOT_OPTIONS, material_options, bad_spans, referenced,
    waveform_data, paired_psd, full_record_data, sensor_data, sensor_info,
    ica_data, retention_rows, collect_report_materials,
)


@contextmanager
def style(config=None):
    family = ['DejaVu Sans', 'Microsoft YaHei'] if Path('C:/Windows/Fonts/msyh.ttc').exists() else ['DejaVu Sans']
    with material_options(config):
        with rc_context({'font.family':family, 'font.size':10, 'axes.unicode_minus':False,
                         'svg.fonttype':'none', 'pdf.fonttype':42}):
            yield


def figure(*args, **kwargs):
    fig = Figure(*args, layout='constrained', **kwargs)
    FigureCanvasAgg(fig)
    return fig


def _progress(phase, key):
    """Leave a bounded last-stage marker in an isolated renderer's log."""
    if PLOT_OPTIONS.get().get('_report_progress'):
        print('EEGPROC_REPORT ' + json.dumps({'phase': phase, 'key': key}),
              file=sys.stderr, flush=True)


def asset(fig, folder, key, title, caption):
    import base64,io
    from PIL import Image
    options=PLOT_OPTIONS.get();maximum=options.get('report_max_width',1200)
    dpi=min(options.get('report_dpi',100),maximum/fig.get_size_inches()[0])
    _progress('figure_start', key)
    buffer=io.BytesIO()
    try:
        fig.savefig(buffer,format='png',dpi=dpi,bbox_inches='tight',pil_kwargs={'optimize':True})
    finally:
        fig.clear()
    with Image.open(io.BytesIO(buffer.getvalue())) as source:
        if source.width>maximum:source=source.resize((maximum,round(source.height*maximum/source.width)),Image.Resampling.LANCZOS)
        # Palette PNG reduces report size; numeric diagnostics retain full precision.
        source=source.convert('RGB').quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
        final=io.BytesIO();source.save(final,format='PNG',optimize=True);width,height=source.size
    data=final.getvalue()
    result=dict(key=key,title=title,caption=caption,sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),width_px=width,height_px=height)
    result['data_uri']='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
    _progress('figure_saved', key)
    return result


def draw_waveforms(data,folder):
    figs=[]
    for i,window in enumerate(data['windows']):
        start,width,sf,seconds=(window[k] for k in ('start','width','sfreq','seconds'))
        selected,bads,labels=(window[k] for k in ('selected','bads','labels'))
        before,after=(np.asarray(window[k]) for k in ('before','after'))
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
            for spans,color in [(window['input_spans'],'#e3c24c'),(window['output_spans'],'#dc6976')]:
                for lo,hi,_ in spans:
                    if hi>start and lo<start+width:ax.axvspan(max(lo,start)/sf,min(hi,start+width)/sf,color=color,alpha=.10)
            ax.set_ylabel(name+('*' if name in bads else '')+'\nµV');ax.grid(alpha=.15)
            ax.spines[['top','right']].set_visible(False)
        axes[0].legend(loc='upper right',ncol=2);axes[-1].set_xlabel('Time from recording start (s)')
        title=' / '.join(labels)+f': {start/sf:.2f}–{(start+width)/sf:.2f} s'
        fig.suptitle(title,fontsize=13)
        caption=f'Paired channels and samples; average reference over original good channels; median removed per display window. Windows selected from {seconds:g}-s blocks. Yellow: input BAD; red: output BAD; *: bad channel.'
        figs.append(asset(fig,folder,f'waveform_{i+1}',title,caption))
    return figs,data['records']


def waveform_figures(original,clean,good,bads,folder):
    return draw_waveforms(waveform_data(original,clean,good,bads),folder)


def psd_figure(original,clean,good,report,folder):
    options=PLOT_OPTIONS.get();hp=report.get('config',{}).get('highpass',.5)
    seconds=options.get('report_psd_window_seconds') or min(20.,max(4.,2./hp))
    f,a,b,meta=paired_psd(original,clean,good,max_windows=options.get('report_psd_windows',30),window_seconds=seconds)
    return draw_psd(dict(frequency=f,before=a,after=b,metadata=meta),report,folder)


def draw_psd(data,report,folder):
    f,a,b=(np.asarray(data[k]) for k in ('frequency','before','after'));meta=data['metadata']
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
    return draw_timeline(dict(sfreq=float(original.info['sfreq']),n_times=int(original.n_times),
        input_spans=bad_spans(original),output_spans=bad_spans(clean)),folder)


def draw_timeline(data,folder):
    sf=data['sfreq'];fig=figure(figsize=(13,2.8));ax=fig.subplots()
    for row,spans,color in [(1,data['input_spans'],'#bd9e30'),(0,data['output_spans'],BAD)]:
        ax.broken_barh([(lo/sf,(hi-lo)/sf) for lo,hi,_ in spans],(row-.18,.36),facecolors=color)
    ax.set(yticks=[0,1],yticklabels=['Output BAD / boundaries','Input BAD / boundaries'],xlim=(0,data['n_times']/sf),xlabel='Time from recording start (s)',ylim=(-.6,1.6))
    ax.grid(axis='x',alpha=.15)
    return asset(fig,folder,'bad_timeline','Annotation timeline','Input and output BAD annotations on the original sample grid.')


def draw_full_record(data,folder):
    from matplotlib.colors import LogNorm
    displays=[np.asarray(x) for x in data['displays']];edges=np.asarray(data['edges'])
    rows,eeg,bads=(data[k] for k in ('rows','eeg','bads'))
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
    sf=data['sfreq']
    for lo,hi,_ in data['output_spans']:axes[2].axvspan(lo/sf,hi/sf,color=BAD,alpha=.12)
    axes[2].set(yscale='log',ylabel='Peak-to-peak (uV; log scale)',xlabel='Time from recording start (s)',xlim=(0,data['duration']));axes[2].legend(fontsize=9);axes[2].grid(alpha=.15)
    caption='Non-overlapping 1-s windows with a shared log scale. Display bins use the maximum when compressed. Red: output BAD.'
    return asset(fig,folder,'whole_record_qc','Channel-by-time peak-to-peak',caption),rows,data['sampling']


def full_record_qc(original,clean,good,bads,folder):
    return draw_full_record(full_record_data(original,clean,good,bads),folder)


def ica_figures(report,folder,ica=None,training=None):
    """Small topomaps plus numeric detail data for an on-demand HTML dialog."""
    if 'ica_display' in report:
        display=report['ica_display']
        report['ica_diagnostics']=display['diagnostics']
        return display['figures'],display['notes']
    return draw_ica(ica_data(report,ica,training),report,folder)


def draw_ica(data,report,folder):
    if 'maps' not in data:return [],data.get('notes',[])
    maps=np.asarray(data['maps']);info=sensor_info(data['geometry']);figures=[]
    for idx in range(maps.shape[1]):
        topo=maps[:,idx];topo=topo/max(np.max(np.abs(topo)),1e-30)
        fig=figure(figsize=(2.,2.));ax=fig.subplots()
        mne.viz.plot_topomap(topo,info,axes=ax,show=False,contours=0,vlim=(-1,1),cmap='RdBu_r',sensors=False)
        figures.append(asset(fig,folder,f'ica_topomap_{idx}',f'IC {idx}','Normalized component topography.'))
    report['ica_diagnostics']=data['diagnostics']
    return figures,data.get('notes',[])


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


def build_material_figures(report,material,folder):
    """Plot previously collected numbers; no Raw/model reads or ICA calls."""
    from types import SimpleNamespace
    out=dict(version=1,figures=[],notes=list(material.get('notes',[])),errors=list(material.get('errors',[])),
        display_only=True,signal_data_modified=False)
    options=dict(report.get('config',{}))
    options['_report_progress']=report.get('report_execution',{}).get('mode')=='subprocess'
    with style(options):
        def attempt(name,fn):
            _progress('section_start', name)
            try:
                result=fn()
                _progress('section_completed', name)
                return result
            except Exception as exc:
                _progress('section_error', name)
                out['errors'].append(dict(section=name,type=type(exc).__name__,message=str(exc)))
                return None
        with warnings.catch_warnings(record=True) as caught:
            waves=attempt('waveforms',lambda:draw_waveforms(material['waveforms'],folder)) if 'waveforms' in material else None
            if waves:out['figures']+=waves[0];out['waveform_windows']=waves[1]
            psd=attempt('psd',lambda:draw_psd(material['psd'],report,folder)) if 'psd' in material else None
            if psd:out['figures'].append(psd[0]);out['psd_sampling']=psd[1]
            line=attempt('line_noise',lambda:line_noise_figure(report,folder))
            if line:out['figures'].append(line)
            if report.get('line_diagnostics',{}).get('error'):
                out['errors'].append(dict(section='line_noise',type=report['line_diagnostics']['error'],message=report['line_diagnostics']['reason']))
            whole=attempt('whole_record_qc',lambda:draw_full_record(material['whole_record_qc'],folder)) if 'whole_record_qc' in material else None
            if whole:out['figures'].append(whole[0]);report['qc_timeseries']=whole[1];out['whole_record_sampling']=whole[2]
            out['whole_record_heatmap_requested']=bool(report.get('config',{}).get('report_full_record_heatmap',False))
            sensors=attempt('bad_channels',lambda:sensors_figure(SimpleNamespace(info=sensor_info(material['sensors'])),report,folder)) if 'sensors' in material else None
            if sensors:out['figures'].append(sensors)
            timeline=attempt('bad_timeline',lambda:draw_timeline(material['timeline'],folder)) if 'timeline' in material else None
            if timeline:out['figures'].append(timeline)
            if 'ica_display' in material:
                display=material['ica_display'];report['ica_diagnostics']=display['diagnostics'];ic=(display['figures'],display['notes'])
            else:
                ic=attempt('ica',lambda:draw_ica(material.get('ica',{}),report,folder))
            if ic:out['figures']+=ic[0];out['notes']+=ic[1]
        out['plot_warnings']=sorted(set(material.get('warnings',[])+[str(w.message) for w in caught]))
    return out


def build_signal_figures(report,original,clean,folder,ica=None,training=None):
    return build_material_figures(report,collect_report_materials(report,original,clean,ica,training),folder)
