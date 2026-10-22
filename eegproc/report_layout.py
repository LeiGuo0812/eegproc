"""Offline report presentation and component-detail interactions."""

CSS = r'''
:root{--ink:#292d32;--muted:#65707b;--line:#dce0e4;--blue:#17659d;--red:#bd2436}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:white;font:15px/1.55 Arial,Helvetica,sans-serif}
header{background:#27313c;color:white;padding:17px 30px}header strong{font-size:22px;font-weight:500}header span{margin-left:18px;color:#cad2db}
aside{position:fixed;top:68px;bottom:0;width:220px;overflow:auto;padding:24px 18px;background:#f6f7f8;border-right:1px solid var(--line)}
aside a{display:block;padding:7px 12px;color:#425466}aside a:hover{background:#e8edf1;text-decoration:none}
main{margin-left:220px;padding:22px 38px 65px;max-width:1520px}section{padding:10px 0 26px;border-bottom:1px solid var(--line);scroll-margin-top:16px}
h1{font-size:27px;font-weight:500;margin:8px 0 20px}h2{font-size:21px;font-weight:500;margin:25px 0 10px}h3{font-size:17px;font-weight:600;margin:15px 0 8px}
a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}p{margin:9px 0}.caption,.muted{color:var(--muted);font-size:13px}
ul{padding-left:24px}li{margin:4px 0}table{border-collapse:collapse;font-size:13px;width:100%;margin:12px 0}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid #e5e8eb;vertical-align:top}th{background:#f1f3f5;font-weight:600}
.summary{max-width:850px}.summary th{width:220px}.summary td{font-size:14px}figure{margin:16px 0 24px}figure img{display:block;max-width:100%;height:auto}figcaption{color:var(--muted);font-size:13px;padding:7px 0}
details{margin:12px 0}summary{cursor:pointer;color:var(--blue);padding:8px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f7f8;padding:15px;font:12px/1.55 Consolas,monospace;max-height:500px;overflow:auto}.table-scroll{overflow:auto;max-height:450px}
.status{font-weight:600}.warning{border-left:3px solid #b77f22;padding:8px 15px;background:#fffaf0;margin:12px 0}.excluded{color:var(--red)!important;font-weight:600}.retained{color:#343c45}.pending{color:#997020}
.ic-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:6px;margin:16px 0 22px}
.ic-spectrum-preview{border-top:1px solid #edf0f2;padding-top:4px}.ic-spectrum-preview svg{display:block;width:100%;height:auto}.ic-spectrum-preview p{font-size:11px;text-align:center;color:var(--muted)}
.ic-tile{border:1px solid #e6e8eb;padding:4px;background:#fff;min-width:0}.ic-map{display:block;border:0;background:white;padding:0;width:100%;cursor:pointer;font:inherit}.ic-map:hover{background:#f0f5fa;outline:1px solid #8cb0cc}.ic-map img{display:block;width:100%;height:auto;aspect-ratio:1;object-fit:contain}.ic-name{display:block;font-size:13px}.ic-class{display:block;font-size:11px;color:#65707b;padding:2px 0 5px}.ic-select{font-size:12px;display:block;text-align:center;padding:4px}.ic-select input{vertical-align:middle}
button{font:inherit;cursor:pointer}.button{border:1px solid #b8c5d1;border-radius:3px;background:#f5f7f9;padding:7px 12px;color:#264b68}.primary{background:#17659d;color:#fff;border-color:#17659d}.review-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:12px 0}.review-controls input[type=text]{border:1px solid #b8c5d1;padding:8px;min-width:180px;font:inherit}.review-controls label{font-size:13px}
dialog{border:1px solid #aebbc7;border-radius:5px;max-width:1100px;width:94vw;max-height:92vh;padding:22px 25px;overflow:auto;color:var(--ink)}dialog::backdrop{background:#17253499}.dialog-header{display:flex;justify-content:space-between;align-items:center;gap:12px}.dialog-header h2{margin:0}.component-detail{display:grid;grid-template-columns:240px 1fr;gap:20px;margin-top:12px}.component-detail img{width:100%}.component-detail svg{display:block;width:100%;height:auto}.dialog-controls{display:flex;gap:8px}.component-detail .charts{min-width:0}#ic-probabilities td{white-space:nowrap}#ic-dialog-note{font-size:13px;color:var(--muted)}.methods p{max-width:1050px}.references{padding-left:24px;font-size:14px}.references li{margin:9px 0}
.detail-selection{display:flex;align-items:center;flex-wrap:wrap;gap:10px 20px;padding:10px 12px;margin:12px 0;background:#f6f7f8;border:1px solid var(--line)}.detail-selection label{cursor:pointer}.detail-selection input{vertical-align:middle;margin-right:6px}.detail-selection .caption{margin:0}
@media(max-width:900px){aside{position:static;width:100%;display:flex;flex-wrap:wrap;padding:8px;border-right:0;border-bottom:1px solid var(--line)}aside a{padding:5px 10px}main{margin-left:0;padding:18px}header{padding:14px 18px}.component-detail{grid-template-columns:1fr}.component-detail img{max-width:220px;margin:auto}.ic-grid{grid-template-columns:repeat(auto-fill,minmax(145px,1fr))}}
@media print{aside{display:none}header{color:black;background:white}main{margin:0;padding:0}details>summary{color:black}.ic-tile{break-inside:avoid}.review-controls{display:none}}
'''

JS = r'''
const reportData=JSON.parse(document.getElementById('component-data').textContent);
const records=reportData.components, modal=document.getElementById('component-dialog');
let activeIndex=0,previousFocus=null;
const detailExclude=document.getElementById('ic-detail-exclude');
function syncDetailSelection(){
 if(!detailExclude)return;
 const c=records[activeIndex];if(!c)return;
 const box=document.querySelector(`[data-exclude="${c.component}"]`);
 detailExclude.checked=Boolean(box?.checked);
 detailExclude.setAttribute('aria-label',`Exclude IC ${c.component}`);
 const status=document.getElementById('ic-detail-selection-status');
 status.textContent=detailExclude.checked?'Exclude':'Retain';
 status.className=detailExclude.checked?'excluded':'retained';
}
const escapeText=x=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function lineChart(x,y,xLabel,yLabel,color,compact=false){
 if(!x.length||!y.length)return '<p>No preview available.</p>';
 const W=compact?240:720,H=compact?160:220,L=compact?48:62,R=15,T=compact?24:15,B=compact?38:46,x0=x[0],x1=x[x.length-1];let lo=Math.min(...y),hi=Math.max(...y);if(lo===hi){lo-=1;hi+=1;}
 const px=v=>L+(v-x0)/(x1-x0||1)*(W-L-R),py=v=>H-B-(v-lo)/(hi-lo)*(H-T-B);
 const fmt=v=>Math.abs(v)>=10000||Math.abs(v)>0&&Math.abs(v)<.001?v.toExponential(1):Number(v.toPrecision(compact?3:4)).toString();
 const xTicks=compact?3:5,yTicks=compact?3:4;
 let axes='';for(let i=0;i<xTicks;i++){const v=x0+(x1-x0)*i/(xTicks-1),xx=px(v);axes+=`<line x1="${xx}" y1="${T}" x2="${xx}" y2="${H-B}" stroke="#edf0f2"/><text x="${xx}" y="${H-B+19}" text-anchor="middle">${fmt(v)}</text>`;}
 for(let i=0;i<yTicks;i++){const v=lo+(hi-lo)*i/(yTicks-1),yy=py(v);axes+=`<line x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}" stroke="#edf0f2"/><text x="${L-7}" y="${yy+4}" text-anchor="end">${fmt(v)}</text>`;}
 const path=x.map((v,i)=>(i?'L':'M')+px(v).toFixed(2)+','+py(y[i]).toFixed(2)).join(' ');
 const yTitle=compact?`<text x="${L}" y="13">${escapeText(yLabel)}</text>`:`<text transform="translate(13 ${H/2}) rotate(-90)" text-anchor="middle">${escapeText(yLabel)}</text>`;
 return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeText(yLabel)}" style="font:${compact?13:11}px Arial;fill:#55616c">${axes}<path d="${path}" fill="none" stroke="${color}" stroke-width="1.2"/><text x="${(L+W-R)/2}" y="${H-6}" text-anchor="middle">${escapeText(xLabel)}</text>${yTitle}</svg>`;
}
function showComponent(index){
 activeIndex=index;const c=records[index];if(!c)return;
 const tile=document.querySelector(`[data-component="${c.component}"]`),label=document.getElementById('ic-title');
 label.textContent=`IC ${c.component} — ${c.decision}`;label.className=c.decision==='Excluded'?'excluded':'';
 const image=tile?.querySelector('img'), target=document.getElementById('ic-dialog-map');target.src=image?.src||'';target.alt=`IC ${c.component} topography`;
 document.getElementById('ic-proposal').textContent=`Automatic proposal: ${c.proposal}. Decision source: ${reportData.decision_source}.`;
 document.getElementById('ic-probabilities').innerHTML='<tr>'+reportData.classes.map(x=>`<th>${escapeText(x)}</th>`).join('')+'</tr><tr>'+c.probabilities.map(x=>`<td>${x.toFixed(4)}</td>`).join('')+'</tr>';
 const color=c.decision==='Excluded'?'#bd2436':'#17659d';
 document.getElementById('ic-activation').innerHTML=lineChart(c.time_seconds||[],c.activation||[],'Recording time (s)','Activation (a.u.)',color);
 document.getElementById('ic-spectrum').innerHTML=lineChart(c.frequency_hz||[],c.power_db||[],'Frequency (Hz)','PSD (dB, a.u.²/Hz)',color);
 document.getElementById('ic-dialog-note').textContent=c.spectrum_duration_seconds?`Training preview: ${c.spectrum_duration_seconds.toFixed(1)} s; topography normalized per component.`:'Training preview unavailable.';
 syncDetailSelection();
 if(!modal.open){previousFocus=document.activeElement;modal.showModal();}
}
document.querySelectorAll('[data-component]').forEach((button,i)=>button.addEventListener('click',()=>showComponent(i)));
records.forEach(c=>{
 const preview=document.querySelector(`[data-spectrum="${c.component}"]`);
 if(preview)preview.innerHTML=lineChart(c.frequency_hz||[],c.power_db||[],'Hz','PSD (dB)',c.decision==='Excluded'?'#bd2436':'#17659d',true);
});
document.getElementById('ic-close').onclick=()=>modal.close();
document.getElementById('ic-prev').onclick=()=>showComponent((activeIndex+records.length-1)%records.length);
document.getElementById('ic-next').onclick=()=>showComponent((activeIndex+1)%records.length);
modal.addEventListener('close',()=>previousFocus?.focus());
modal.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'){e.preventDefault();showComponent((activeIndex+records.length-1)%records.length);}if(e.key==='ArrowRight'){e.preventDefault();showComponent((activeIndex+1)%records.length);}});
if(reportData.selection){
 const boxes=()=>Array.from(document.querySelectorAll('[data-exclude]'));
 boxes().forEach(box=>box.addEventListener('change',syncDetailSelection));
 detailExclude.addEventListener('change',()=>{
  const c=records[activeIndex],box=document.querySelector(`[data-exclude="${c.component}"]`);
  if(box){box.checked=detailExclude.checked;box.dispatchEvent(new Event('change',{bubbles:true}));}
 });
 document.getElementById('keep-all').onclick=()=>{boxes().forEach(x=>x.checked=false);syncDetailSelection();};
 document.getElementById('restore-proposal').onclick=()=>{boxes().forEach(x=>x.checked=reportData.automatic_proposal.includes(Number(x.dataset.exclude)));syncDetailSelection();};
 document.getElementById('save-selection').onclick=()=>{const decision={...reportData.selection,reviewed:true,exclude:boxes().filter(x=>x.checked).map(x=>Number(x.dataset.exclude)),reviewer:document.getElementById('reviewer').value,reason:document.getElementById('review-reason').value};
 const uri=URL.createObjectURL(new Blob([JSON.stringify(decision,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=uri;link.download='selection.json';link.click();setTimeout(()=>URL.revokeObjectURL(uri),1000);};
}
'''
