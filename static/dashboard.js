'use strict';
const config = JSON.parse(document.getElementById('app-config').textContent);
const $ = id => document.getElementById(id);
const labels = {high:'Alto riesgo', medium:'En observación', low:'Buen camino'};
const colors = {high:'#c43c50', medium:'#ac7014', low:'#147b65'};
let data = null, selectedStudent = null, loading = false;
const fmtT = n => Number(n).toLocaleString('es-MX', {maximumFractionDigits:1});
const reasonText = {failing_average:'Promedio reprobatorio', high_predicted_risk:'Riesgo estimado alto'};
const reasonsOf = s => (s.alert_reasons||[]).map(r=>reasonText[r]||r).join(' y ');
const alertFlag = s => s.risk_label==='high' ? `<span class="alert-flag" title="${esc(reasonsOf(s))}">⚠ Alerta</span>` : '';
const fmt = n => Number(n).toLocaleString('es-MX', {maximumFractionDigits:1, minimumFractionDigits:1});
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function groupPath(){return `/reports/groups/${encodeURIComponent(data.group_id)}`;}
function studentPath(s){return `${groupPath()}/students/${encodeURIComponent(s.student_id)}.pdf`;}
function error(message){$('error').textContent=message; $('error').hidden=!message;}
async function load(group){
  if(loading) return;
  loading=true; data=null; $('student-dialog').close(); selectedStudent=null;
  $('students').replaceChildren(); $('metrics').replaceChildren(); $('distribution').replaceChildren(); $('grade-chart').replaceChildren();
  $('result-count').textContent=''; $('group-tag').textContent=''; $('empty').hidden=true;
  $('dashboard').setAttribute('aria-busy','true');
  $('group-report').disabled=true; $('refresh').disabled=true; $('load-group').disabled=true;
  error(''); $('notice').textContent='Cargando información del grupo…'; $('notice').hidden=false;
  try{
    const response=await fetch(`/api/groups/${encodeURIComponent(group)}`);
    const payload=await response.json();
    if(!response.ok) throw new Error(payload.error || 'No se pudo cargar el grupo.');
    data=payload; $('group').value=data.group_id; $('risk').value='all'; $('search').value='';
    history.replaceState(null,'',`/?group=${encodeURIComponent(data.group_id)}`);
    renderOverview(); renderStudents(); $('group-report').disabled=false;
    $('notice').textContent=`Grupo ${data.group_id} actualizado · ${new Date().toLocaleTimeString('es-MX')}`;
  }catch(e){error(e.message || 'No se pudo conectar con el servidor.'); $('notice').hidden=true;}
  finally{loading=false; $('refresh').disabled=false; $('load-group').disabled=false; $('dashboard').setAttribute('aria-busy','false');}
}
function renderOverview(){
 const s=data.summary;
 const metrics=[['Alumnos del grupo',s.total,'Vista completa del grupo'],['Promedio de calificaciones',fmt(s.average_grade),'Escala de 0 a 100'],['Asistencia promedio',`${fmt(s.attendance_pct)}%`,'Media de todos los alumnos'],['Alumnos en alerta',s.counts.high,`Promedio < ${fmtT(data.passing_grade/10)} o riesgo ≥ ${fmtT(data.risk_threshold)} · requieren revisión`]];
 $('metrics').innerHTML=metrics.map(([label,value,note])=>`<div class="metric"><p>${label}</p><strong>${value}</strong><small>${note}</small></div>`).join('');
 $('group-tag').textContent=data.group_id;
 $('risk-legend').textContent=`Riesgo estimado: ${data.risk_levels}.`;
 $('threshold-tag').textContent=`Alerta: promedio < ${fmtT(data.passing_grade/10)} o riesgo ≥ ${fmtT(data.risk_threshold)}`;
 $('distribution').innerHTML=Object.entries(labels).map(([tier,label])=>`<button class="distribution-row" data-tier="${tier}" aria-pressed="false"><span>${label}</span><span class="track"><span class="fill" style="display:block;width:${s.total?100*s.counts[tier]/s.total:0}%;background:${colors[tier]}"></span></span><b>${s.counts[tier]} <small>/${s.total}</small></b></button>`).join('');
 $('grade-chart').innerHTML=s.period_averages.map((g,i)=>`<div class="grade-col"><strong>${fmt(g)}</strong><div class="column" style="height:${g}px" title="Registro ${i+1}: ${fmt(g)}"></div><span>Registro ${i+1}</span></div>`).join('');
}
function renderStudents(){
 if(!data) return;
 const query=$('search').value.trim().toLocaleLowerCase('es');
 const risk=$('risk').value;
 const rows=data.students.filter(s=>(risk==='all'||s.risk_label===risk)&&`${s.name} ${s.student_id}`.toLocaleLowerCase('es').includes(query));
 rows.sort((a,b)=>({'risk':()=>b.risk_score-a.risk_score,'grade-desc':()=>b.average_grade-a.average_grade,'grade-asc':()=>a.average_grade-b.average_grade,'name':()=>a.name.localeCompare(b.name,'es',{numeric:true})}[$('sort').value])());
 $('students').innerHTML=rows.map(s=>`<tr><td><strong>${esc(s.name)}</strong>${alertFlag(s)}<small>${esc(s.student_id)}</small></td><td>${fmt(s.average_grade)}</td><td>${fmt(s.attendance_pct)}%</td><td><span class="score">${fmt(s.risk_score)}</span><span class="badge ${s.risk_label}">${labels[s.risk_label]}</span></td><td><button data-detail="${esc(s.student_id)}" aria-label="Ver detalle de ${esc(s.name)}">Ver detalle</button><button class="pdf-button" data-pdf="${esc(s.student_id)}" aria-label="Descargar PDF de ${esc(s.name)}">↓ PDF</button></td></tr>`).join('');
 $('result-count').textContent=`${rows.length} de ${data.students.length}`;
 $('empty').hidden=rows.length>0;
 document.querySelectorAll('[data-tier]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tier===risk)));
}
function showStudent(s){
 selectedStudent=s;
 $('student-name').textContent=s.name; $('student-id').textContent=s.student_id;
 $('student-detail').innerHTML=`<span class="badge ${s.risk_label}">${labels[s.risk_label]}</span> <b>Riesgo estimado: ${fmt(s.risk_score)}/100</b>${s.risk_label==='high'?` · <b class="alert-text">En alerta: ${esc(reasonsOf(s))}</b>`:''}<div class="detail-metrics"><div><span>Promedio /100</span><strong>${fmt(s.average_grade)}</strong></div><div><span>Asistencia</span><strong>${fmt(s.attendance_pct)}%</strong></div><div><span>Participación /100</span><strong>${fmt(s.participation_score)}</strong></div></div><h2>Calificaciones registradas</h2><div class="detail-grades">${s.grades.map((g,i)=>`<span>Registro ${i+1}<br><b>${fmt(g)}</b></span>`).join('')}</div><p>Cambio del primer al último registro: <b>${s.grade_trend>0?'+':''}${fmt(s.grade_trend)} puntos</b>.</p><p class="detail-note">Modelo de demostración. El riesgo es una estimación del modelo; la interpretación final corresponde al docente. El PDF incluye una comparación con el grupo y sugerencias de seguimiento.</p>`;
 $('student-dialog').showModal();
}
async function download(url, button){
 const previous=button.textContent;
 button.disabled=true; button.textContent='Preparando PDF…'; error('');
 try{
  const response=await fetch(url);
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(body.error||'No se pudo generar el PDF.');}
  if(!response.headers.get('content-type')?.includes('application/pdf')) throw new Error('El servidor no devolvió un PDF válido.');
  const blob=await response.blob(), objectUrl=URL.createObjectURL(blob), link=document.createElement('a');
  link.href=objectUrl; link.download=url.split('/').pop(); document.body.appendChild(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(objectUrl),10000);
  $('notice').textContent='PDF listo. Revisa las descargas de tu navegador.'; $('notice').hidden=false;
 }catch(e){error(e.message); $('notice').textContent=e.message; $('notice').hidden=false;}
 finally{button.disabled=false;button.textContent=previous;}
}
async function loadGroups(){
  const response=await fetch('/api/groups');
  const payload=await response.json();
  if(!response.ok) throw new Error(payload.error || 'No se pudo obtener la lista de grupos.');
  const current=$('group').value;
  $('group').innerHTML=payload.groups.map(g=>`<option value="${esc(g.group_id)}">${esc(g.group_id)}${g.name?` · ${esc(g.name)}`:''} (${g.student_count} alumnos)</option>`).join('');
  if(payload.groups.some(g=>g.group_id===current)) $('group').value=current;
  $('demo-banner').hidden=payload.mode!=='demo';
  $('no-groups').hidden=payload.groups.length>0;
  $('load-group').disabled=$('refresh').disabled=payload.groups.length===0;
  return payload.groups;
}
async function init(){
  if(config.error){error(config.error);$('dashboard').setAttribute('aria-busy','false');return;}
  try{
    const groups=await loadGroups();
    if(!groups.length){$('dashboard').setAttribute('aria-busy','false');return;}
    const known=groups.some(g=>g.group_id===config.group);
    await load(known?config.group:groups[0].group_id);
    if(config.group && !known) error(`El grupo '${config.group}' no existe.`);
  }catch(e){error(e.message || 'No se pudo conectar con el servidor.');$('dashboard').setAttribute('aria-busy','false');}
}
$('group-form').addEventListener('submit',e=>{e.preventDefault();load($('group').value);});
$('group').addEventListener('change',()=>load($('group').value));
$('refresh').addEventListener('click',async()=>{try{await loadGroups();}catch(e){error(e.message);}load($('group').value);});
document.addEventListener('visibilitychange',()=>{if(!document.hidden && !loading) loadGroups().catch(()=>{});});
['search','risk','sort'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',renderStudents));
$('clear').addEventListener('click',()=>{$('search').value='';$('risk').value='all';$('sort').value='risk';renderStudents();});
$('distribution').addEventListener('click',e=>{const b=e.target.closest('[data-tier]');if(b){$('risk').value=$('risk').value===b.dataset.tier?'all':b.dataset.tier;renderStudents();}});
$('students').addEventListener('click',e=>{const b=e.target.closest('button');if(!b||!data)return;const id=b.dataset.detail||b.dataset.pdf;const s=data.students.find(s=>s.student_id===id);if(!s)return;if(b.dataset.detail)showStudent(s);else download(studentPath(s),b);});
$('close-dialog').addEventListener('click',()=>$('student-dialog').close());
$('student-dialog').addEventListener('click',e=>{if(e.target===$('student-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
$('group-report').addEventListener('click',()=>{if(data)download(`${groupPath()}.pdf`,$('group-report'));});
$('student-report').addEventListener('click',()=>{if(selectedStudent)download(studentPath(selectedStudent),$('student-report'));});
init();
