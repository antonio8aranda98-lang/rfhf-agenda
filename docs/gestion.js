import {managementRequest,issueURL,REPOSITORY} from './gestion-model.mjs';
import {escapeHTML as e} from './model.mjs';
const $=s=>document.querySelector(s), form=$('#management-form');let players=[],loadNotice='';
const help={madrid:'Abre la ficha del equipo en RFFM y copia su enlace /fichaequipo/…',catalunya:'Abre el equipo de la categoría en FCF y copia su enlace /ca/clubs/…/categories/…',murcia:'Copia la ficha de equipo FFRM que contiene NFG_VisEquipos y Codigo_Equipo.',valencia:'Copia la ficha FFCV del equipo que contiene /equipos/equipo.php?cod_equipo=…'};
function update(){
  const action=$('#action').value,add=action==='add',reactivate=action==='reactivate';
  $('#add-fields').hidden=!add;$('#existing-fields').hidden=add;$('#collaborator-fields').hidden=!['add','assign'].includes(action);
  for(const el of $('#add-fields').querySelectorAll('input,select'))el.disabled=!add;
  $('#name').required=add;$('#source').required=add;$('#player_id').required=!add;$('#player_id').disabled=add;$('#collaborator-name').disabled=!['add','assign'].includes(action);$('#collaborator-name').required=['add','assign'].includes(action);
  const available=players.filter(p=>reactivate?p.active===false:p.active!==false);
  $('#player_id').innerHTML='<option value="">Selecciona un jugador</option>'+available.map(p=>`<option value="${e(p.id)}">${e(p.name)} · ${e(p.team)} · ${e(p.collaborator)}</option>`).join('');
  $('#existing-note').textContent=!available.length?'No hay jugadores disponibles para esta operación.':action==='deactivate'?'Se retirará de todas las vistas y avisos cuando termine la publicación.':reactivate?'Se comprobará de nuevo la plantilla y el calendario antes de reactivarlo.':'El cambio se aplicará en la próxima publicación.';
  sourceHelp();$('#form-status').hidden=!loadNotice;$('#form-status').textContent=loadNotice;
}
function sourceHelp(){const fid=$('#federation').value;$('#source-help').textContent=help[fid];$('#murcia-fields').hidden=fid!=='murcia';$('#competition_source').disabled=fid!=='murcia'||$('#action').value!=='add';$('#federation-note').hidden=fid!=='valencia';$('#federation-note').textContent='FFCV: la actualización automática todavía no está validada. Las altas de Valencia quedarán pendientes de comprobación y no se incorporarán automáticamente por ahora.'}
$('#action').addEventListener('change',update);$('#federation').addEventListener('change',sourceHelp);
form.addEventListener('submit',event=>{event.preventDefault();try{
  const request=managementRequest(Object.fromEntries(new FormData(form))),p=players.find(p=>p.id===request.player_id);
  const url=issueURL(request,p?.name);$('#form-status').hidden=false;$('#form-status').textContent='Solicitud preparada. Completa el envío en GitHub; todavía no se ha cambiado la cartera.';
  window.location.assign(url);
}catch(error){$('#form-status').hidden=false;$('#form-status').textContent=error.message}});
update();
try{
  let response=await fetch(`https://raw.githubusercontent.com/${REPOSITORY}/main/data/roster.json`,{cache:'no-store',signal:AbortSignal.timeout(10000)});
  if(!response.ok)throw new Error();players=(await response.json()).players;
}catch{
  try{const r=await fetch('data/feed.json',{cache:'no-cache'});if(!r.ok)throw new Error();players=(await r.json()).players;loadNotice='No se pudo cargar el registro completo. Las reactivaciones no estarán disponibles hasta recargar.'}catch{loadNotice='No se pudo cargar la cartera. Recarga la página antes de tramitar cambios.'}
}
$('#collaborator-list').innerHTML=[...new Set(players.map(p=>p.collaborator))].sort().map(name=>`<option value="${e(name)}"></option>`).join('');update();
