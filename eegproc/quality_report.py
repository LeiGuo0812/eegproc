"""English single-file EEG report, with compact component maps and inline audit."""
from pathlib import Path
import html
import json
import time
from ._utils import _json_default
from .report_layout import CSS,JS


def esc(value):return html.escape(str(value),quote=True)


def value_text(value):
    if value is None:return 'n/a'
    if isinstance(value,bool):return 'Yes' if value else 'No'
    if isinstance(value,(dict,list,tuple)):return json.dumps(value,ensure_ascii=False,default=_json_default)
    if isinstance(value,float):return f'{value:.6g}'
    return str(value)


def table(rows,headers=None,classes=''):
    head='<thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr></thead>' if headers else ''
    return '<table class="'+classes+'">'+head+'<tbody>'+''.join('<tr>'+''.join('<td>'+esc(value_text(v))+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def records_table(records):
    if not records:return '<p class="muted">None.</p>'
    columns=list(dict.fromkeys(k for row in records for k in row))
    return '<div class="table-scroll">'+table([[r.get(k) for k in columns] for r in records],columns)+'</div>'


def disclosure(title,content):return '<details><summary>'+esc(title)+'</summary>'+content+'</details>'


def json_block(value):return '<pre>'+esc(json.dumps(value,ensure_ascii=False,indent=2,default=_json_default))+'</pre>'


def review_items(report, rows):
    # Kept as a structured API; the HTML shows concise observations only.
    notes=[str(v) for v in report.get('quality_flags',[])]
    if report.get('error'):notes.append(str(report['error']))
    for e in report.get('visualizations',{}).get('errors',[]):notes.append(e['section']+': '+e['message'])
    checks=report.get('metadata_audit',{}).get('checks',{})
    for name,value in checks.items():
        if value is False and not (name=='electrode_locations' and report['metadata_audit'].get('coordinate_change_expected')):notes.append('Metadata mismatch: '+name)
    return [dict(priority='Review',title='Observation',evidence=n,action='') for n in notes]


def save_quality_report(report, report_path, *, original=None, clean=None, ica=None, training=None, reuse_figures=False):
    from .quality_figures import build_signal_figures,retention_figure,style,CLASS_NAMES
    from .report_provenance import capture_signal_audit,methods_text,references,data_inventory,utc_now
    started=time.perf_counter();page=Path(report_path).resolve();page.parent.mkdir(parents=True,exist_ok=True)
    if page.suffix.lower()!='.html':raise ValueError('report_path must end in .html')
    base=page.name.removesuffix('_report.html')
    folder=page.parent;cfg=report.get('config',{});outputs=report.setdefault('outputs',{})
    outputs.update(quality_report=str(page))
    if original is not None and clean is not None:
        try:report['visualizations']=build_signal_figures(report,original,clean,folder,ica,training)
        except Exception as exc:report['visualizations']=dict(figures=[],notes=[],errors=[dict(section='paired_signals',message=str(exc),type=type(exc).__name__)])
        try:capture_signal_audit(report,original,clean)
        except Exception as exc:report['visualizations']['errors'].append(dict(section='metadata_audit',message=str(exc),type=type(exc).__name__))
    viz=report.setdefault('visualizations',dict(figures=[],notes=[],errors=[]))
    rows=[]
    if reuse_figures:
        from .quality_figures import retention_rows
        rows=retention_rows(report)
    else:
        viz['figures']=[f for f in viz['figures'] if f['key']!='epoch_retention']
        try:
            with style(cfg):f,rows=retention_figure(report,folder)
            if f:viz['figures'].append(f)
        except Exception as exc:viz['errors'].append(dict(section='epochs',message=str(exc),type=type(exc).__name__))
    images={}
    for f in viz['figures']:
        if f.get('data_uri'):images[f['key']]=f['data_uri']
    report['report_audit']=dict(schema_version='1.0',updated_utc=utc_now(),tables={},data_files=data_inventory(report,page.parent))
    status=report.get('status','unknown');ic=report.get('ica',{});ep=report.get('epochs',{});quality=report.get('quality',{})
    observations=review_items(report,rows)
    report['human_review']=dict(processing_completed=status in ('completed','review_required'),decision='pending',
        automatic_acceptance=False,quality_warning_requires_review=bool(observations) or status in ('failed','review_required','awaiting_ica_review'),checklist=observations)
    labels={'completed':'Completed','review_required':'Completed with observations','awaiting_ica_review':'Awaiting ICA selection','failed':'Failed','running':'Running'}
    def plots(prefix):
        fs=[f for f in viz['figures'] if f['key'].startswith(prefix) and f['key'] in images]
        return ''.join('<figure><img loading="lazy" data-figure-key="'+esc(f['key'])+'" src="'+esc(images[f['key']])+'" alt="'+esc(f['title'])+'" width="'+str(f.get('width_px',1200))+'" height="'+str(f.get('height_px',600))+'"><figcaption>'+esc(f['caption'])+'</figcaption></figure>' for f in fs)
    def section(key,title,body):return '<section id="'+key+'"><h1>'+esc(title)+'</h1>'+body+'</section>'
    summary=report.get('input_summary',{});gate=report.get('bad_channel_qc',{})
    adjustments=report.get('parameter_adjustments',[])
    epoch_resolution=report.get('epoch_resolution',{})
    total=ep.get('input_events',ep.get('events_total'));kept=ep.get('retained_epochs')
    summaries=[('Subject',report.get('provenance',{}).get('subject_label',base)),('Task name',cfg.get('task_name') or 'Not specified'),('Workflow','EEG preprocessing'),('Parameter preset',cfg.get('preset','standard')),('Status',labels.get(status,status)),
        ('Analysis',cfg.get('purpose','not recorded')),('Input duration',str(summary.get('duration_seconds','n/a'))+' s'),
        ('Sampling frequency',str(summary.get('sfreq','n/a'))+' Hz'),('EEG channels',gate.get('total_eeg_channels')),
        ('Analysis / ICA band',f"{cfg.get('highpass')}–{cfg.get('lowpass')} Hz / {cfg.get('training_highpass')}–{cfg.get('training_lowpass')} Hz"),
        ('Bad channels',', '.join(report.get('bad_channels',[])) or 'None'),
        ('Output BAD fraction',f"{quality['bad_sample_fraction']:.1%}" if 'bad_sample_fraction' in quality else 'Not evaluated'),
        ('ICA excluded',len(ic.get('removed_components_0based',[])) if ic else 'Disabled / unavailable'),
        ('Epochs retained','Skipped' if epoch_resolution.get('status')=='skipped' else f'{kept} / {total}' if total is not None else 'Not requested'),
        ('Parameter adjustments',len(adjustments))]
    adjustment_body=''
    if adjustments:
        def parameter_value(value):return 'None' if value is None else value
        adjustment_body='<h2>Parameter adjustments</h2><p>'+str(len(adjustments))+' recorded adjustment'+('s' if len(adjustments)!=1 else '')+'.</p><div class="table-scroll">'+table([
            (r.get('field'),parameter_value(r.get('requested')),parameter_value(r.get('effective')),r.get('reason')) for r in adjustments],
            ['Parameter','Requested','Effective','Reason'])+'</div>'
    content=section('summary','Summary',table(summaries,classes='summary')+adjustment_body+
        (('<div class="warning"><strong>Observations</strong><ul>'+''.join('<li>'+esc(x['evidence'])+'</li>' for x in observations)+'</ul></div>') if observations else ''))
    pre='<h2>Signals before and after preprocessing</h2>'
    if status=='awaiting_ica_review':pre+='<p class="caption">After: pre-ICA stage. Component subtraction is pending.</p>'
    pre+=plots('waveform_')+'<h2>Power spectral density</h2>'+plots('psd')
    line=report.get('line_diagnostics',{})
    pre+='<h2 id="line-noise">Line-noise removal</h2>'+plots('line_noise')
    if line.get('status')=='available':
        pre+=table([(r['frequency_hz'],r['before_median_power_uv2'],r['after_median_power_uv2'],
            r['median_reduction_db']) for r in line['metrics']],
            ['Frequency (Hz)','Before band power (µV², channel median)','After band power (µV², channel median)',
             'Reduction (dB, paired channel median)'])
        pre+=disclosure('Line-noise sampling and method',json_block(dict(
            method=report.get('line_cleaning'),sampling={k:v for k,v in line.items()
            if k not in ('before_psd_quartiles','after_psd_quartiles','frequency_hz','metrics')})))
    else:
        pre+='<p class="muted">'+esc(line.get('reason','Stage-specific spectra were not recorded.'))+'</p>'
    pre+='<h2>Channels</h2>'+plots('bad_channels')
    pre+=disclosure('Channel table',records_table(report.get('qc_channels',[])))+'<h2>Annotations</h2>'+plots('bad_timeline')+plots('whole_record_qc')
    pre+=disclosure('Annotation table',records_table(report.get('qc_annotations',[])))
    pre+=disclosure('Signal sampling',json_block({k:viz.get(k) for k in ['waveform_windows','psd_sampling','whole_record_sampling'] if k in viz}))
    pre+=disclosure('ASR and channel detection',json_block({k:report.get(k) for k in ['asr','channel_detection','continuous_segments'] if k in report}))
    content+=section('eeg','EEG preprocessing',pre)
    probs=ic.get('probabilities',[]);removed=ic.get('removed_components_0based',[]);proposed=ic.get('automatic_proposal_0based',removed)
    pending=ic.get('decision_status')=='pending';detail_by={d['component']:d for d in report.get('ica_diagnostics',[])}
    records=[];tiles=[];table_rows=[]
    selection=None
    initial_selection=proposed if pending else removed
    if report.get('ica_checkpoint'):
        checkpoint=report['ica_checkpoint'];selection=dict(schema='eeg-ica-selection-v1',checkpoint_id=checkpoint['checkpoint_id'],
            model_sha256=checkpoint['model_sha256'],reviewed=False,exclude=initial_selection,reviewer='',reason='')
    for idx,p in enumerate(probs):
        decision='Pending' if pending else 'Excluded' if idx in removed else 'Retained';proposal='Exclude' if idx in proposed else 'Retain'
        color='pending' if pending else 'excluded' if idx in removed else 'retained';cls=max(range(7),key=lambda j:p[j])
        d=detail_by.get(idx,dict(component=idx));records.append(dict(d,decision=decision,proposal=proposal,probabilities=p))
        uri=images.get(d.get('topomap_key',''));image='<img data-figure-key="'+esc(d.get('topomap_key',''))+'" src="'+esc(uri)+'" alt="IC '+str(idx)+' topography" loading="lazy">' if uri else '<p>Map unavailable</p>'
        button='<button type="button" class="ic-map" data-component="'+str(idx)+'" aria-label="Inspect IC '+str(idx)+'">'+image+'<span class="ic-name '+color+'">IC '+str(idx)+' · '+decision+'</span><span class="ic-class">'+esc(CLASS_NAMES[cls])+f' {p[cls]:.2f}</span></button>'
        check='<label class="ic-select"><input type="checkbox" data-exclude="'+str(idx)+'"'+(' checked' if idx in initial_selection else '')+'> Exclude</label>' if selection else ''
        spectrum='<div class="ic-spectrum-preview" data-spectrum="'+str(idx)+'"></div>'
        tiles.append('<div class="ic-tile">'+button+spectrum+check+'</div>')
        table_rows.append('<tr class="'+color+'"><td>'+str(idx)+'</td><td>'+proposal+'</td><td>'+decision+'</td>'+''.join(f'<td>{v:.4f}</td>' for v in p)+'</tr>')
    controls=''
    if selection:
        controls='<div class="review-controls"><label>Reviewer <input type="text" id="reviewer"></label><label>Reason <input type="text" id="review-reason"></label><button class="button" id="keep-all">Keep all</button><button class="button" id="restore-proposal">Restore automatic proposal</button><button class="button primary" id="save-selection">Download confirmed selection</button></div><p class="caption">Checked components define the next exclusion list. Download selection.json and resume from the pre-ICA checkpoint. Labels and plots describe the saved result.</p><p class="caption">Checkpoint: <code>'+esc(outputs.get('checkpoint',''))+'</code></p>'
    ic_body=table([('Method',cfg.get('ica_method')),('Selection rule',cfg.get('ica_rule')),('Rank / iterations',f"{ic.get('rank','n/a')} / {ic.get('iterations','n/a')}"),('Decision source',ic.get('decision_status','n/a')),('Reviewer',ic.get('review_author')),('Reason',ic.get('review_reason'))],classes='summary')
    if records:
        ic_body+='<p class="caption">Spectra: ICA training preview, dB (a.u.²/Hz). Select a topography for activation and class probabilities. <span class="excluded">Red labels: excluded components.</span></p>'+controls+'<div class="ic-grid">'+''.join(tiles)+'</div>'
        ic_body+=disclosure('Component probabilities and decisions','<div class="table-scroll"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in ['IC','Automatic','Final',*CLASS_NAMES])+'</tr></thead><tbody>'+''.join(table_rows)+'</tbody></table></div>')
    else:ic_body+='<p>No ICA decomposition available.</p>'
    ic_body+=disclosure('ICA diagnostics',json_block({k:v for k,v in ic.items() if k not in ('probabilities','log')}))
    content+=section('ica','ICA',ic_body)
    epoch_body=plots('epoch_retention')
    if epoch_resolution.get('status')=='skipped':
        epoch_body='<p><strong>Epoching skipped.</strong> '+esc(epoch_resolution.get('reason','No eligible event input was available.'))+'</p>'
    elif ep:
        epoch_body+=table([(r['name'],r['input'],r['annotation_rejected'],r['qc_rejected'],r['retained'],f"{r['retention_fraction']:.1%}" if r['retention_fraction'] is not None else 'n/a') for r in rows],['Condition','Input','Annotations','QC','Retained','Retention'])
        epoch_body+=disclosure('Epoch decisions',records_table(ep.get('records',[])))+disclosure('Epoch settings',json_block({k:v for k,v in ep.items() if k not in ('records','original_drop_log')}))
    else:epoch_body='<p>Epoching was not requested or has not been reached.</p>'
    content+=section('epochs','Epochs',epoch_body)
    methods=methods_text(report)
    content+=section('methods','Methods','<div class="methods">'+''.join('<p>'+esc(p)+'</p>' for p in methods.split('\n\n') if not p.startswith('#'))+'</div>')
    content+=section('references','References','<ol class="references">'+''.join('<li><a href="'+esc(url)+'">'+esc(title)+'</a></li>' for title,url in references(report))+'</ol>')
    provenance=report.get('provenance',{});software=provenance.get('software',{})
    about=table([('Version',report.get('workflow_revision','local')),('Run ID',provenance.get('run_uuid')),('Started (UTC)',provenance.get('started_utc')),('Finished (UTC)',provenance.get('processing_finished_utc')),('Elapsed',f"{report.get('elapsed_seconds',0):.2f} s"),('Source hash',software.get('source_bundle_sha256'))],classes='summary')
    about+=disclosure('Execution',records_table(report.get('execution',[])))+disclosure('Effective parameters',json_block(cfg))
    about+=disclosure('Metadata checks',table(report.get('metadata_audit',{}).get('checks',{}).items(),['Field','Preserved']))
    about+=disclosure('Output inventory',records_table(report['report_audit']['data_files']))
    about+=disclosure('Software and provenance',json_block(provenance))
    if report.get('report_generation'):
        about+=disclosure('Report rendering',json_block(report['report_generation']))
    about+=disclosure('Warnings and logs',json_block(dict(warnings=report.get('warnings',[]),plot_warnings=viz.get('plot_warnings',[]),plot_errors=viz.get('errors',[]),ica_log=ic.get('log',''))))
    content+=section('about','About',about)
    detail_selection='<div class="detail-selection"><label><input type="checkbox" id="ic-detail-exclude"> Exclude this component</label><p class="caption">Next exclusion list: <strong id="ic-detail-selection-status" aria-live="polite"></strong></p></div>' if selection else ''
    modal='<dialog id="component-dialog"><div class="dialog-header"><h2 id="ic-title"></h2><div class="dialog-controls"><button class="button" id="ic-prev">Previous</button><button class="button" id="ic-next">Next</button><button class="button" id="ic-close">Close</button></div></div>'+detail_selection+'<p id="ic-proposal"></p><div class="component-detail"><img id="ic-dialog-map" alt="Component topography"><div class="charts"><h3>Activation</h3><div id="ic-activation"></div><h3>Power spectrum</h3><div id="ic-spectrum"></div></div></div><div class="table-scroll"><table id="ic-probabilities"></table></div><p id="ic-dialog-note"></p></dialog>'
    payload=json.dumps(dict(components=records,classes=CLASS_NAMES,selection=selection,automatic_proposal=proposed,decision_source=ic.get('decision_status','recorded')),ensure_ascii=False,separators=(',',':'),default=_json_default).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
    nav=''.join('<a href="#'+key+'">'+name+'</a>' for key,name in [('summary','Summary'),('eeg','EEG preprocessing'),('ica','ICA'),('epochs','Epochs'),('methods','Methods'),('references','References'),('about','About')])
    viz['last_render_seconds']=time.perf_counter()-started
    def serialized():
        saved=dict(report);saved['visualizations']=dict(viz,figures=[{k:v for k,v in f.items() if k!='data_uri'} for f in viz['figures']])
        saved.pop('ica_diagnostics',None)  # Numeric previews are embedded once, in HTML.
        saved.pop('ica_display',None)  # Maps and component data are already embedded.
        return saved
    # Machine-readable provenance stays inside the same HTML as the visible report.
    # Resolve the byte-count field before writing, so stored and returned records agree.
    report['report_storage']=dict(total_bytes=0,html_bytes=0,image_bytes=sum(f.get('bytes',0) for f in viz['figures']),
        image_count=len(viz['figures']),self_contained=True,target_bytes=2*1024**2,over_target=False,
        excludes_analysis_fif_and_ica_model=True)
    prefix='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(base)+' · EEG report</title><style>'+CSS+'</style></head><body><header><strong>EEG preprocessing</strong><span>'+esc(base)+'</span></header><aside>'+nav+'</aside><main>'+content+'</main>'+modal+'<script id="component-data" type="application/json">'+payload+'</script>'
    for _ in range(10):
        audit=json.dumps(serialized(),ensure_ascii=False,separators=(',',':'),default=_json_default).replace('<',r'\u003c').replace('>',r'\u003e').replace('&',r'\u0026')
        document=prefix+'<script id="run-record" type="application/json">'+audit+'</script><script>'+JS+'</script></body></html>'
        size=len(document.encode('utf8'))
        if report['report_storage']['total_bytes']==size:break
        report['report_storage'].update(total_bytes=size,html_bytes=size,over_target=size>2*1024**2)
    from .storage import atomic_write_text
    atomic_write_text(page,document)


def safe_report(report,report_path,*,original=None,clean=None,ica=None,training=None,reuse_figures=False):
    """Reporting failure never replaces a processing exception or loses results."""
    report['processing_status']=report.get('status','unknown')
    report['delivery_status']='completed' if report.get('status') in ('completed','review_required','awaiting_ica_review') else 'incomplete'
    report['report_status']='completed'
    try:
        save_quality_report(report,report_path,original=original,clean=clean,ica=ica,training=training,reuse_figures=reuse_figures)
        return True
    except Exception as exc:
        report['report_status']='failed'
        report['report_error']=dict(type=type(exc).__name__,message=str(exc))
        try:
            from .storage import atomic_write_text
            minimal={k:report.get(k) for k in ('status','processing_status','delivery_status','report_status','report_error','error','outputs','config')}
            record=json.dumps(minimal,default=_json_default).replace('<',r'\u003c')
            atomic_write_text(report_path,'<!doctype html><html lang="en"><title>EEG report</title><h1>Report unavailable</h1><p>'+esc(str(exc))+'</p><script id="run-record" type="application/json">'+record+'</script></html>')
        except Exception:
            pass
        return False
