"""Check report interactions in isolated headless Edge or Chrome sessions."""
from pathlib import Path
import argparse
import html
import json
import os
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROBE = r"""
<script>
window.addEventListener('load',async()=>{
 document.body.dataset.probeStage='images';
 const checks={};
 const check=(name,value)=>{document.body.dataset.probeStage=name;checks[name]=Boolean(value);if(!value)throw Error(name);};
 try{
  const maps=Array.from(document.querySelectorAll('[data-component]'));
  document.querySelectorAll('img').forEach(x=>x.loading='eager');
  await Promise.all(Array.from(document.images).filter(x=>x.hasAttribute('src')).map(x=>x.decode()));
  check('all_images_decode',true);
  const audit=JSON.parse(document.getElementById('run-record').textContent);
  const taskRow=Array.from(document.querySelectorAll('#summary tr')).find(r=>r.cells[0]?.textContent==='Task name');
  check('task_name',audit.task_name===audit.config.task_name&&taskRow?.cells[1].textContent===(audit.task_name||'Not specified'));
  check('four_second_waveforms',audit.visualizations.waveform_windows.every(w=>Math.abs(w.stop_seconds-w.start_seconds-4)<1e-8));
  check('line_noise_plot',Boolean(document.querySelector('img[alt="Line-noise removal"]')));
  check('line_stage_diagnostics',audit.line_diagnostics.status==='available'&&audit.line_diagnostics.targets_hz.length>0);
  const data=JSON.parse(document.getElementById('component-data').textContent);
  check('component_count',maps.length===data.components.length&&maps.length>1);
  check('spectra_visible_without_click',!document.getElementById('component-dialog').open&&maps.every(map=>{
   const preview=map.parentElement.querySelector('.ic-spectrum-preview');
   return preview&&preview.getBoundingClientRect().height>50&&preview.getBoundingClientRect().top>=map.getBoundingClientRect().bottom&&preview.querySelector('svg path')?.getAttribute('d').length>20;
  }));
  maps[0].focus();maps[0].click();
  const modal=document.getElementById('component-dialog');
  check('detail_opens',modal.open);
  check('activation_present',document.querySelector('#ic-activation svg path').getAttribute('d').length>20);
  check('spectrum_present',document.querySelector('#ic-spectrum svg path').getAttribute('d').length>20);
  check('probabilities_present',document.querySelectorAll('#ic-probabilities td').length===7);
  check('probabilities_full_width',document.getElementById('ic-probabilities').parentElement.getBoundingClientRect().width>modal.clientWidth*.8);
  document.getElementById('ic-next').click();
  check('next_component',document.getElementById('ic-title').textContent.startsWith('IC 1 '));
  modal.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft'}));
  check('keyboard_navigation',document.getElementById('ic-title').textContent.startsWith('IC 0 '));
  document.getElementById('ic-close').click();
  await Promise.resolve();
  check('close_restores_focus',!modal.open&&document.activeElement===maps[0]);
  const excluded=data.components.findIndex(c=>c.decision==='Excluded');
  if(excluded>=0){
   check('excluded_label_red',getComputedStyle(maps[excluded].querySelector('.ic-name')).color==='rgb(189, 36, 54)');
   maps[excluded].click();
   check('excluded_detail_red',getComputedStyle(document.getElementById('ic-title')).color==='rgb(189, 36, 54)');
   document.getElementById('ic-close').click();
  }
  if(data.selection){
   const boxes=Array.from(document.querySelectorAll('[data-exclude]'));
   const detail=document.getElementById('ic-detail-exclude');
   const selectionStatus=document.getElementById('ic-detail-selection-status');
   check('initial_selection',JSON.stringify(boxes.filter(x=>x.checked).map(x=>Number(x.dataset.exclude)))===JSON.stringify(data.selection.exclude));
   maps[0].click();
   check('detail_selection_initial',Boolean(detail)&&detail.checked===boxes[0].checked);
   const initial=boxes[0].checked;
   detail.click();
   check('detail_to_card',boxes[0].checked===!initial&&detail.checked===boxes[0].checked);
   check('detail_selection_status',selectionStatus.textContent===(detail.checked?'Exclude':'Retain'));
   check('detail_saved_result_unchanged',document.getElementById('ic-title').textContent===`IC 0 — ${data.components[0].decision}`);
   document.getElementById('ic-next').click();
   check('detail_navigation_selection',detail.checked===boxes[1].checked&&detail.getAttribute('aria-label')==='Exclude IC 1');
   const secondInitial=boxes[1].checked;
   detail.click();
   document.getElementById('ic-prev').click();
   check('detail_choices_persist_on_navigation',detail.checked===!initial&&boxes[1].checked===!secondInitial);
   document.getElementById('ic-close').click();
   boxes[0].click();maps[0].click();
   check('card_to_detail_after_reopen',detail.checked===initial&&boxes[0].checked===initial);
   document.getElementById('ic-close').click();
   document.getElementById('keep-all').click();check('keep_all',boxes.every(x=>!x.checked)&&!detail.checked);
   maps[0].click();check('detail_keep_all',!detail.checked&&selectionStatus.textContent==='Retain');
   document.getElementById('ic-close').click();
   document.getElementById('restore-proposal').click();
   check('restore_proposal',JSON.stringify(boxes.filter(x=>x.checked).map(x=>Number(x.dataset.exclude)))===JSON.stringify(data.automatic_proposal));
   maps[0].click();check('detail_restore_proposal',detail.checked===data.automatic_proposal.includes(0));
   document.getElementById('ic-close').click();
   document.getElementById('keep-all').click();maps[1].click();detail.click();
   check('detail_exclusion_red',getComputedStyle(selectionStatus).color==='rgb(189, 36, 54)');
   document.getElementById('ic-close').click();maps[1].click();
   check('detail_exclusion_survives_reopen',detail.checked&&boxes[1].checked);
   document.getElementById('ic-close').click();
   document.getElementById('reviewer').value='Browser validation';
   document.getElementById('review-reason').value='Single-component override';
   let downloaded;
   // Capture the actual JSON string passed to the native Blob constructor.
   // Blob.text() uses asynchronous file work that may outlive --dump-dom's
   // virtual deadline; no report behavior or selection payload is substituted.
   const NativeBlob=window.Blob;
   window.Blob=class extends NativeBlob{constructor(parts,options){super(parts,options);if(parts.every(x=>typeof x==='string'))downloaded=parts.join('');}};
   URL.createObjectURL=blob=>{check('download_is_json_blob',blob instanceof NativeBlob&&blob.type==='application/json');return 'blob:validation';};
   HTMLAnchorElement.prototype.click=function(){};
   document.getElementById('save-selection').click();
   const choice=JSON.parse(downloaded);
   check('confirmed_download',choice.reviewed===true&&choice.exclude.length===1&&choice.exclude[0]===1);
   check('detail_selection_exported_once',JSON.stringify(choice.exclude)===JSON.stringify(boxes.filter(x=>x.checked).map(x=>Number(x.dataset.exclude))));
   check('checkpoint_identity',choice.checkpoint_id===data.selection.checkpoint_id&&choice.model_sha256===data.selection.model_sha256);
   check('review_fields',choice.reviewer==='Browser validation'&&choice.reason==='Single-component override');
  }
  document.body.dataset.validation='passed';
 }catch(e){checks.error=String(e);document.body.dataset.validation='failed';}
 const result=document.createElement('pre');result.id='browser-validation';result.textContent=JSON.stringify(checks);document.body.append(result);
});
</script>
"""


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser','--edge',dest='edge',type=Path,
        default=Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
        help='Preferred Chromium executable; Chrome is tried if its headless smoke probe fails')
    parser.add_argument('--root',type=Path,default=ROOT/'results/eegproc',help='Read reports from this pipeline-validation directory')
    parser.add_argument('--output',type=Path,help='New or empty browser-validation directory; defaults to a temporary directory')
    args=parser.parse_args(argv)
    root=args.root.expanduser().resolve()
    for name in ['rest','erp','review','reselected']:
        if not (root/name/f'{name}_report.html').is_file():parser.error('Report not found: '+str(root/name/f'{name}_report.html'))
    output=args.output.expanduser().resolve() if args.output else Path(tempfile.mkdtemp(prefix='eeg-browser-validation-'))
    if output.exists() and any(output.iterdir()):parser.error('Output directory must be new or empty: '+str(output))
    output.mkdir(parents=True,exist_ok=True)
    print('OUTPUT',output,flush=True)
    scratch=output/'work'
    scratch.mkdir(parents=True,exist_ok=True)
    preview=output/'preview';preview.mkdir(exist_ok=True)
    base=['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
          '--disable-extensions',
          '--window-size=1440,1320','--virtual-time-budget=10000','--hide-scrollbars']
    def launch(browser,flags,url):
        # A fresh profile avoids delegating to any user session. System temporary
        # storage also keeps browser caches out of the synchronized project tree.
        with tempfile.TemporaryDirectory(prefix='eeg-headless-',ignore_cleanup_errors=True) as profile:
            return subprocess.run([str(browser),*base,'--user-data-dir='+profile,*flags,url],
                capture_output=True,timeout=55,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    candidates=list(dict.fromkeys([args.edge,
        Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe']))
    runtime=dict(attempts=[]);browser=None
    for candidate in candidates:
        if not candidate.is_file():continue
        try:
            smoke=launch(candidate,['--dump-dom'],'data:text/html,<title>EEG headless smoke</title><body>EEG_SMOKE_READY</body>')
            item=dict(executable=str(candidate),returncode=smoke.returncode,
                      stdout_bytes=len(smoke.stdout),stderr=smoke.stderr.decode('utf8',errors='replace')[-2000:])
            runtime['attempts'].append(item)
            if smoke.returncode==0 and b'EEG_SMOKE_READY' in smoke.stdout:
                browser=candidate;break
        except (OSError,subprocess.TimeoutExpired) as exc:
            runtime['attempts'].append(dict(executable=str(candidate),error=str(exc)))
    runtime['selected_executable']=str(browser) if browser else None
    (output/'browser_runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf8')
    if browser is None:raise RuntimeError('No browser completed the isolated headless smoke test; see browser_runtime.json')
    print('BROWSER',browser,flush=True)
    def execute(flags,page):
        run=launch(browser,flags,page.as_uri())
        if run.returncode:raise RuntimeError(run.stderr.decode('utf8',errors='replace')[-2000:])
        text=run.stdout.decode('utf8',errors='replace')
        if '--dump-dom' in flags and not text.strip():
            raise RuntimeError('Headless browser returned empty DOM: '+str(page))
        return text
    summary={}
    for name in ['rest','erp','review','reselected']:
        source=(root/name/f'{name}_report.html').read_text(encoding='utf8').replace('loading="lazy"','loading="eager"')
        probe=scratch/f'{name}_probe.html';probe.write_text(source.replace('</body>',PROBE+'</body>'),encoding='utf8')
        dom=execute(['--dump-dom'],probe)
        match=re.search(r'<pre id="browser-validation">(.*?)</pre>',dom,re.S)
        if not match:
            # Large embedded images can finish decoding near the initial virtual
            # deadline. Retry only an incomplete probe, never a failed assertion.
            runtime.setdefault('probe_retries',[]).append(dict(report=name,virtual_time_budget_ms=30000))
            (output/'browser_runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf8')
            dom=execute(['--dump-dom','--virtual-time-budget=30000'],probe)
            match=re.search(r'<pre id="browser-validation">(.*?)</pre>',dom,re.S)
        if not match:
            (scratch/'failed_dom.html').write_text(dom,encoding='utf8')
            raise RuntimeError('Browser did not complete the interaction probe: '+name)
        checks=json.loads(html.unescape(match.group(1)))
        summary[name]=checks
        assert 'error' not in checks,checks
        print(name,checks,flush=True)
    source=(root/'rest/rest_report.html').read_text(encoding='utf8').replace('loading="lazy"','loading="eager"')
    for name,action in [('eeg_waveforms',"document.querySelectorAll('main>section').forEach(x=>x.hidden=x.id!=='eeg');"),
                        ('line_noise',"document.querySelectorAll('main>section').forEach(x=>x.hidden=x.id!=='eeg');const line=document.getElementById('line-noise');for(const child of line.parentElement.children){if(child===line)break;child.hidden=true;}"),
                        ('ica_overview',"document.querySelectorAll('main>section').forEach(x=>x.hidden=x.id!=='ica');"),
                        ('ica_detail',"document.querySelector('[data-component]').click();")]:
        action="window.addEventListener('load',async()=>{await Promise.all(Array.from(document.images).filter(x=>x.hasAttribute('src')).map(x=>x.decode()));"+action+"});"
        page=scratch/f'{name}.html';page.write_text(source.replace('</body>','<script>'+action+'</script></body>'),encoding='utf8')
        execute([f'--screenshot={preview/(name+".png")}'],page)
        if not (preview/(name+'.png')).is_file():raise RuntimeError('Browser did not save screenshot: '+name)
        from PIL import Image
        with Image.open(preview/(name+'.png')) as shot:
            if not any(low!=high for low,high in shot.convert('RGB').getextrema()):
                raise RuntimeError('Browser saved a blank screenshot: '+name)
            runtime.setdefault('screenshots',[]).append(dict(name=name,pixels=list(shot.size),
                bytes=(preview/(name+'.png')).stat().st_size,nonblank=True))
    (output/'browser_runtime.json').write_text(json.dumps(runtime,indent=2),encoding='utf8')
    (output/'browser_validation.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print('VALIDATED',output/'browser_validation.json',flush=True)


if __name__=='__main__':main()
