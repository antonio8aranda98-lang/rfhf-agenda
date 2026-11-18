import { madridToday, shiftDate, weekend, filterMatches, overlaps, matchups, applyPublicRegistry, displayStat, statEvidence, escapeHTML as e, safeURL, calendarICS } from './model.mjs';
const $ = s => document.querySelector(s);
let data, rawData, registryData, settings, region = 'madrid', collaborator = '', view = 'agenda', offset = 0, query = '', planOnly = false, sort = 'name';
let planned = new Set();
try { planned = new Set(JSON.parse(localStorage.getItem('rfhf-visits') || '[]')); } catch {}
const dialog = $('#player-dialog');
const statNames = { team_played:'Partidos del equipo', called_up:'Convocado', starts:'Titular', bench:'Suplente', minutes:'Minutos', goals:'Goles' };
const categoryNames={senior:'Sénior',juvenil:'Juvenil',cadete:'Cadete',infantil:'Infantil'};
const fedIcons = { madrid:'MAD', catalunya:'CAT', murcia:'MUR', valencia:'VAL' };
const dateText = (iso, opts = {}) => new Intl.DateTimeFormat('es-ES', { timeZone:'Europe/Madrid', day:'numeric', month:'long', ...opts }).format(new Date(`${iso}T12:00:00Z`));
const timestamp = iso => iso ? new Intl.DateTimeFormat('es-ES', { timeZone:'Europe/Madrid', day:'2-digit', month:'2-digit', ...(iso.length>10?{hour:'2-digit',minute:'2-digit'}:{}) }).format(new Date(iso)) : 'sin actualización';
function urlLink(url, text, cls = '') { const href = safeURL(url); return href ? `<a class="${cls}" href="${e(href)}" target="_blank" rel="noopener noreferrer">${text}</a>` : `<span>${text}</span>`; }
function initials(name) { return name.split(/\s+/).filter(Boolean).slice(0,2).map(s=>s[0]).join(''); }
function logo(src, name) { const url = safeURL(src); return url ? `<img class="club-logo" src="${e(url)}" alt="Escudo de ${e(name)}" loading="lazy" referrerpolicy="no-referrer">` : `<span class="logo-fallback" aria-hidden="true">${e(initials(name))}</span>`; }
function maps(m) {
  if (m.latitude && m.longitude && Number.isFinite(Number(m.latitude)) && Number.isFinite(Number(m.longitude))) return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(m.latitude + ',' + m.longitude)}`;
  return m.venue ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent([m.venue,m.locality,m.address].filter(Boolean).join(', '))}` : '';
}
function playerStat(player,key) {
  const evidence=statEvidence(player,key);
  return `${displayStat(evidence.value)}${evidence.partial?`<span class="partial-stat" title="Suma confirmada de las actas con este dato; faltan partidos por comprobar">${evidence.calendarIncomplete?'Calendario en carga':`Parcial · ${evidence.checked}/${evidence.total} actas`}</span>`:''}`;
}
function selectedPlayers() { return data.players.filter(p => p.federation === region && (!collaborator || p.collaborator === collaborator)); }
function portfolioPlayers() { const rows=registryData?.initialized===true&&registryData?.season===data.season&&Array.isArray(registryData.players)?registryData.players:data.players; return rows.filter(p=>p.active!==false&&p.federation===region); }
function visiblePlayers() { const q = query.normalize('NFD').replace(/\p{Diacritic}/gu,'').toLowerCase(); return selectedPlayers().filter(p=>[p.name,p.team].join(' ').normalize('NFD').replace(/\p{Diacritic}/gu,'').toLowerCase().includes(q)); }
function matches(dates=null) { return filterMatches(data.matches, selectedPlayers().map(p=>p.id), dates, query, planOnly ? planned : null); }
function toast(text) { $('#toast').textContent=text; $('#toast').hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$('#toast').hidden=true,4500); }
function setupCollaborators() {
  const people = [...new Set(portfolioPlayers().map(p=>p.collaborator))].sort((a,b)=>a.localeCompare(b,'es'));
  if ((collaborator && !people.includes(collaborator)) || people.length===1) collaborator=people[0]||'';
  $('#collaborator').innerHTML=(people.length>1 ? `<option value="" ${!collaborator?'selected':''}>Todos los colaboradores</option>` : '') + people.map(name=>`<option value="${e(name)}" ${name===collaborator?'selected':''}>${e(name)}</option>`).join('');
}
function render() {
  const days=weekend(madridToday(),offset), people=selectedPlayers(), games=matches(days);
  $('#federations').innerHTML=data.federations.map(f=>`<button class="fed-button ${f.id===region?'active':''}" data-region="${e(f.id)}" ${f.id===region?'aria-current="page"':''}><span class="fed-icon">${fedIcons[f.id]}</span><span>${e(f.id==='valencia'?'C. Valenciana':f.label)}</span><span class="fed-count">${String(data.players.filter(p=>p.federation===f.id).length).padStart(2,'0')}</span></button>`).join('');
  $('#region-title').textContent=data.federations.find(f=>f.id===region).label;
  const crosses=matchups(data.matches.filter(m=>m.federation===region),data.players,days);
  $('#matchups').hidden=!crosses.length;
  $('#matchups').innerHTML=crosses.length?`<p class="eyebrow">CRUCE ENTRE JUGADORES DE LA CARTERA</p><h2>¡Nuestros jugadores se enfrentan!</h2><p>Detectado en toda la federación, incluidos otros colaboradores. Cruces entre sus equipos; consulta el acta para confirmar la participación.</p>${crosses.map(m=>`<div class="matchup-row"><div>${m.home_players.map(p=>`<button data-player="${e(p.id)}">${e(p.name)}</button><small>${e(p.collaborator)}</small>`).join('')}<b>vs</b>${m.away_players.map(p=>`<button data-player="${e(p.id)}">${e(p.name)}</button><small>${e(p.collaborator)}</small>`).join('')}</div><span>${dateText(m.date)} · ${e(m.time||'Hora pendiente')}</span><button class="secondary" data-jump="${e(m.id)}">Ver partido →</button></div>`).join('')}`:'';
  const fed=data.federations.find(f=>f.id===region);
  const assigned=portfolioPlayers().filter(p=>!collaborator||p.collaborator===collaborator);
  const published=new Set(people.filter(p=>p.updated_at).map(p=>p.id));
  const waiting=assigned.filter(p=>!published.has(p.id)).length;
  const pause=[fed.retry_after,settings.source_pauses?.[region]].filter(Boolean).sort().at(-1);
  const cooling=pause&&new Date(pause).getTime()>Date.now();
  const stale=!fed.last_success || Date.now()-new Date(fed.last_success).getTime()>12*3600*1000;
  const partialStats=people.filter(p=>Object.keys(statNames).some(k=>p.stats?.[k]==null));
  const detail=partialStats.length===1&&partialStats[0].coverage?.acts_checked<(partialStats[0].stats?.team_played||0)?`Participación verificada en ${partialStats[0].coverage.acts_checked}/${partialStats[0].stats.team_played} partidos.`:'Algunos datos individuales siguen pendientes.';
  const providers=[...new Set(people.map(p=>p.source_acronym||(p.provider==='besoccer'?'BeSoccer':fed.acronym)))].join(', ');
  let sourceText=cooling?`Consultas a la FFCV pausadas hasta ${timestamp(pause)} para respetar su límite. Las consultas se retomarán automáticamente después; se conserva el último dato válido.`:!people.length?'No hay jugadores publicados con este filtro.':fed.status==='ok'&&!stale?`Calendario de ${providers} · Actualizado el ${timestamp(fed.last_success)}${partialStats.length?' · '+detail:''}`:`${fed.status==='ok'?'Datos antiguos':'Consulta automática incompleta'} · Último dato válido: ${timestamp(fed.last_success)}. Comprueba la fuente.`;
  if(waiting)sourceText+=` ${waiting} ${waiting===1?'jugador de tu cartera está pendiente':'jugadores de tu cartera están pendientes'} de ficha deportiva publicada.`;
  $('#source-status').classList.toggle('warning',!!cooling||!!waiting||!!people.length&&(fed.status!=='ok'||stale||!!partialStats.length));
  $('#source-status').innerHTML=`<span class="dot"></span><span>${e(sourceText)} ${people.some(p=>p.source_acronym)?'Consulta la fuente en cada jugador.':urlLink(fed.source,'Fuente oficial ↗')}</span>`;
  const countPending=games.filter(m=>m.status==='time_pending').length;
  const metric=(label,val,small='',highlight=false)=>`<div class="metric ${highlight?'highlight':''}"><div class="metric-label">${label}</div><div class="metric-value">${val}${small?`<small>${small}</small>`:''}</div></div>`;
  $('#metrics').innerHTML=metric('JUGADORES ASIGNADOS',String(assigned.length).padStart(2,'0'))+metric('PARTIDOS ESTE FINDE',String(games.length).padStart(2,'0'),'',true)+metric('VISITAS PLANIFICADAS',String(games.filter(m=>planned.has(m.id)).length).padStart(2,'0'))+metric('HORARIOS PENDIENTES',String(countPending).padStart(2,'0'));
  $('#plan-count').textContent=planned.size;
  $('#plan-filter').setAttribute('aria-pressed',String(planOnly));
  $('#agenda-count').textContent=games.length;
  document.querySelectorAll('[data-view]').forEach(b=>{const on=b.dataset.view===view;b.classList.toggle('active',on);if(on)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});
  for(const v of ['agenda','players','compare'])$(`#${v}-view`).hidden=v!==view;
  if(view==='agenda')renderAgenda(days,games);
  if(view==='players')renderPlayers();
  if(view==='compare')renderComparison();
}
function matchTeam(p,m){
  return [p,...(p.additional_teams||[])].find(t=>[m.home_team_id,m.away_team_id].map(String).includes(String(t.team_id)))||p;
}
function dualLabel(p,m=null){
  if(!p.additional_teams?.length)return '';
  if(!m)return '<span class="dual-badge">Dos equipos</span>';
  const t=matchTeam(p,m);
  return `<small class="dual-match-label">${e(t.team)} · ${['registration','additional'].includes(t.role)?'Equipo adicional':'Equipo seguido'} · Convocatoria por confirmar</small>`;
}
function additionalTeamSummary(p){
  return (p.additional_teams||[]).map(t=>`<section class="source-summary"><h3 class="mini-heading">Equipo adicional · ${e(t.team)}</h3><p class="stat-note">${e(t.competition_label)}. Estadísticas de este equipo, separadas del equipo seguido. ${t.calendar_status==='pending'?'Consulta incompleta: comprueba la fuente y la fecha de lectura.':''}</p><div class="mini-stats">${Object.keys(statNames).map(k=>`<div class="mini-stat">${playerStat(t,k)}<small>${statNames[k]}</small></div>`).join('')}</div><p class="stat-note">Actas verificadas: ${t.coverage?.acts_checked??0}/${t.stats?.team_played??'—'} · Lectura: ${e(timestamp(t.updated_at))} · ${urlLink(t.team_source,'Consultar equipo ↗')}</p></section>`).join('');
}
function matchCard(m, games) {
  const selected = new Set(selectedPlayers().map(p=>p.id));
  const players=data.players.filter(p=>m.player_ids.includes(p.id)&&selected.has(p.id));
  const conflict=games.some(other=>overlaps(m,other));
  const score=m.status==='finished'?`${m.score_home} – ${m.score_away}`:null;
  const location=m.venue?[m.venue,m.locality].filter(Boolean).join(' · '):'Campo pendiente de publicación';
  const dayStatus=m.date_precision==='round'?'Fecha de jornada · día y hora por confirmar':({scheduled:'Horario publicado',time_pending:'Horario pendiente',finished:'Finalizado',postponed:'Aplazado',cancelled:'Cancelado'}[m.status]||'Pendiente');
  return `<article class="match ${planned.has(m.id)?'planned':''}" data-match="${e(m.id)}"><div class="match-time"><strong class="clock ${!m.time?'pending':''}">${e(score||m.time||'Por confirmar')}</strong><small>${score?'RESULTADO':m.time?'HORA LOCAL':'JORNADA'}</small></div><div class="match-body"><div class="opponents"><span class="team">${logo(m.home_logo,m.home)}${e(m.home)}</span><span class="versus">vs</span><span class="team">${logo(m.away_logo,m.away)}${e(m.away)}</span></div><div class="venue"><svg viewBox="0 0 16 20" aria-hidden="true"><path d="M14 7c0 5-6 11-6 11S2 12 2 7a6 6 0 0 1 12 0Z"/><circle cx="8" cy="7" r="2"/></svg>${maps(m)?urlLink(maps(m),e(location)):e(location)}</div><div class="match-players">${players.map(p=>`<button class="player-chip" data-player="${e(p.id)}">↗ ${e(p.name)}${dualLabel(p,m)}</button>`).join('')}</div>${conflict?'<div class="conflict">↔ Se solapa con otro partido de esta agenda</div>':''}</div><div class="match-actions"><span class="match-badge">${e(dayStatus)}${m.round?' · J'+m.round:''}</span><button class="star-button" data-plan="${e(m.id)}" aria-pressed="${planned.has(m.id)}">${planned.has(m.id)?'★ Visita guardada':'☆ Planificar visita'}</button><div class="links">${maps(m)?urlLink(maps(m),'Cómo llegar ↗'):''}${urlLink(m.source,'Fuente ↗')}</div></div></article>`;
}
function renderAgenda(days,games) {
  $('#week-title').textContent=`${dateText(days[0],{month:undefined})}–${dateText(days.at(-1))}`;
  $('#agenda').innerHTML=days.map((day,i)=>{const list=games.filter(m=>m.date===day).sort((a,b)=>(a.time||'99:99').localeCompare(b.time||'99:99'));return `<section class="day"><div class="day-header"><h3>${['Sábado','Domingo'][i]}</h3><span class="date">${dateText(day,{month:'short'})}</span><span class="day-count">${list.length} ${list.length===1?'partido':'partidos'}</span></div>${list.length?list.map(m=>matchCard(m,games)).join(''):`<div class="empty-day"><span>—</span> ${query||planOnly?'No hay partidos con estos filtros.':'Sin partidos publicados de tus jugadores para este día.'}</div>`}</section>`}).join('');
  // Rearranged fixtures on weekdays stay discoverable, especially when a weekend game moves.
  const monday=shiftDate(days[0],-5); const weekdays=[0,1,2,3,4].map(n=>shiftDate(monday,n)); const other=matches(weekdays);
  $('#midweek').innerHTML=other.length?`<h3 class="mini-heading">También entre semana</h3><p class="subtle">Partidos de la misma semana fuera del sábado y domingo.</p>${other.map(m=>`<p class="subtle">${dateText(m.date,{weekday:'long'})}</p>${matchCard(m,other)}`).join('')}`:'';
}
function renderPlayers() {
  const people=visiblePlayers();
  $('#players').innerHTML=people.length?people.map(p=>`<button class="player-card" data-player="${e(p.id)}"><span class="profile-mark">${e(initials(p.name))}</span><span class="card-arrow">↗</span><h3>${e(p.name)}</h3>${dualLabel(p)}<div class="club">${e(p.team)}</div><div class="competition">${e(p.competition_label)}${p.age_category?' · '+e(categoryNames[p.age_category]||p.age_category):''}</div><div class="mini-stats">${['called_up','minutes','goals'].map(k=>`<div class="mini-stat">${playerStat(p,k)}<small>${statNames[k]}</small></div>`).join('')}</div></button>`).join(''):'<div class="empty"><strong>No hay jugadores con esa búsqueda</strong>Prueba otro nombre o borra el filtro.</div>';
}
function renderComparison() {
  const people=visiblePlayers().sort((a,b)=>sort==='name'?a.name.localeCompare(b.name,'es'):(b.stats?.[sort]??-1)-(a.stats?.[sort]??-1));
  $('#comparison').innerHTML=`<div class="table-wrap"><table><thead><tr><th><button data-sort="name">Jugador ${sort==='name'?'↓':''}</button></th>${Object.entries(statNames).map(([k,name])=>`<th><button data-sort="${k}">${name} ${sort===k?'↓':''}</button></th>`).join('')}</tr></thead><tbody>${people.map(p=>`<tr><td><button class="table-player" data-player="${e(p.id)}">${e(p.name)}</button><small>${e(p.team)}${p.additional_teams?.length?' · Dos equipos · datos del equipo seguido':''}</small></td>${Object.keys(statNames).map(k=>`<td>${playerStat(p,k)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="comparison-note">${people.length<2?'Actualmente hay un jugador en esta cartera; la comparación se ampliará al incorporar más. ':''}Los datos marcados «Parcial» suman únicamente las actas verificadas e indican su cobertura; pueden aumentar al recuperar las restantes. La ordenación por estadísticas utiliza los totales completos y deja los parciales al final. Un dato ausente no es un cero. Para valorar rendimiento, ten en cuenta posición, categoría y cobertura de las actas.</p>`;
}
function secondarySummary(source) {
  const labels={played:'Partidos jugados',starts:'Titular',minutes:'Minutos',goals:'Goles'};
  return `<section class="source-summary"><h3 class="mini-heading">Resumen complementario · BeSoccer</h3><p class="stat-note">${e(source.team)} · ${e(source.competition)} · ${e(source.season)}. Se muestra por separado para respetar el ámbito de cada fuente.</p><div class="mini-stats">${Object.entries(labels).map(([key,label])=>`<div class="mini-stat">${displayStat(source.stats?.[key])}<small>${label}</small></div>`).join('')}</div><p class="stat-note">Leído el ${e(timestamp(source.checked_at))} · ${urlLink(source.source,'Consultar BeSoccer ↗')}</p></section>`;
}
function showPlayer(id) {
  const p=data.players.find(p=>p.id===id);if(!p)return;
  const games=data.matches.filter(m=>m.player_ids.includes(id));
  const upcoming=games.filter(m=>m.status!=='finished'&&m.date>=madridToday()).slice(0,p.additional_teams?.length?10:5);
  const history=games.filter(m=>m.status==='finished').sort((a,b)=>b.date.localeCompare(a.date));
  $('#player-detail').innerHTML=`<header class="detail-header"><button class="close-dialog" aria-label="Cerrar ficha" data-close>×</button><p class="eyebrow">FICHA DE SEGUIMIENTO · ${e(data.season)}</p><h2 id="player-title">${e(p.name)}</h2>${dualLabel(p)}<p class="subtle">${e(p.team)} · ${e(p.competition_label)}</p>${p.official_display_name?`<p class="subtle">Nombre en la federación: ${e(p.official_display_name)}</p>`:''}<p class="subtle">Seguimiento: ${e(p.collaborator)}${p.age_category?' · Categoría por edad: '+e(categoryNames[p.age_category]||p.age_category):''}</p>${urlLink(p.source,p.provider==='besoccer'?'Consultar BeSoccer ↗':'Consultar federación ↗')}${p.team_source?' · '+urlLink(p.team_source,'Equipo seguido ↗'):''}${p.provider!=='besoccer'&&p.besoccer_player_source?' · '+urlLink(p.besoccer_player_source,'BeSoccer ↗'):''}</header><div class="detail-body">${p.additional_teams?.length?`<p class="dual-notice">DOS EQUIPOS · Equipo seguido: ${e(p.team)}. Equipo adicional: ${p.additional_teams.map(t=>e(t.team)).join(', ')}. Ambos calendarios son de equipo: la convocatoria del jugador está por confirmar. Los totales principales y la comparativa corresponden al equipo seguido.</p>`:''}<div class="metrics player-metrics">${Object.keys(statNames).map(k=>`<div class="metric"><div class="metric-label">${statNames[k]}</div><div class="metric-value">${playerStat(p,k)}</div></div>`).join('')}</div><p class="stat-note">${e(p.stats_note||'Estadísticas individuales pendientes de publicación.')}${p.secondary_warning?'<br>'+e(p.secondary_warning):''}<br>Partidos del equipo = disputados. Convocado incluye titular y suplente, aunque no llegue a jugar. «Parcial» indica la suma confirmada y cuántas actas respaldan ese dato; el resto sigue pendiente de lectura automática.<br>Participaciones verificadas: ${p.coverage?.acts_checked??0}/${p.stats?.team_played??'—'} · Minutos verificables: ${p.coverage?.minutes_checked??0}/${p.stats?.team_played??'—'}.<br>Actualización: ${e(timestamp(p.updated_at))}</p>${p.secondary_stats?secondarySummary(p.secondary_stats):''}${additionalTeamSummary(p)}<h3 class="mini-heading">${p.additional_teams?.length?'Próximos partidos de ambos equipos':'Próximos partidos del equipo'}</h3>${upcoming.length?upcoming.map(m=>`<div class="detail-match"><div>${e(m.home)} – ${e(m.away)}<small>${p.additional_teams?.length?e(matchTeam(p,m).team)+' · '+(['registration','additional'].includes(matchTeam(p,m).role)?'Equipo adicional':'Equipo seguido')+' · Convocatoria por confirmar · ':''}${dateText(m.date)} · ${e(m.time||'Hora por confirmar')} · ${e(m.venue||'Campo pendiente')}</small></div>${urlLink(m.source,'Ver ↗')}</div>`).join(''):'<p class="subtle">No hay próximos partidos publicados.</p>'}<h3 class="mini-heading">Histórico del equipo y participación</h3><p class="stat-note">El resultado pertenece al equipo. «—» en la participación significa que el acta individual no se ha validado. La fecha junto al enlace indica su última lectura.</p><div class="table-wrap"><table><thead><tr><th>Fecha / partido</th><th>Resultado</th><th>Convocado</th><th>Titular</th><th>Suplente</th><th>Min.</th><th>Goles</th><th>Acta</th></tr></thead><tbody>${history.map(m=>{const s=m.participation?.[id];return `<tr><td>${dateText(m.date,{month:'short'})}<small>${e(m.home)}<br>${e(m.away)}${p.additional_teams?.length?'<br>'+e(matchTeam(p,m).team)+' · '+(['registration','additional'].includes(matchTeam(p,m).role)?'Equipo adicional':'Equipo seguido'):''}</small></td><td class="score">${m.score_home}–${m.score_away}</td><td>${s?.called_up===1?'Sí':s?.called_up===0?'No':'—'}</td><td>${s?.starts===1?'Sí':s?.starts===0?'No':'—'}</td><td>${s?.bench===1?'Sí':s?.bench===0?'No':'—'}</td><td>${displayStat(s?.minutes)}</td><td>${displayStat(s?.goals)}</td><td>${urlLink(m.source,'Ver ↗')}${m.participation_source?.[id]?' · '+urlLink(m.participation_source[id],'Participación ↗'):''}${m.participation_checked_at?.[id]?`<small>${e(timestamp(m.participation_checked_at[id]))}</small>`:''}</td></tr>`}).join('')||'<tr><td colspan="8">Todavía no hay resultados publicados.</td></tr>'}</tbody></table></div></div>`;
  dialog.setAttribute('aria-labelledby','player-title');dialog.showModal();
}
document.addEventListener('click',event=>{
  const button=event.target.closest('button');if(!button||!data)return;
  if(button.dataset.region){region=button.dataset.region;collaborator='';query='';$('#search').value='';setupCollaborators();render()}
  if(button.dataset.view){view=button.dataset.view;render()}
  if(button.dataset.player)showPlayer(button.dataset.player);
  if(button.dataset.plan){const id=button.dataset.plan;planned.has(id)?planned.delete(id):planned.add(id);try{localStorage.setItem('rfhf-visits',JSON.stringify([...planned]))}catch{toast('El navegador no permite guardar visitas en este dispositivo.')}render()}
  if(button.hasAttribute('data-close'))dialog.close();
  if(button.dataset.sort){sort=button.dataset.sort;renderComparison()}
  if(button.dataset.jump){collaborator='';query='';planOnly=false;view='agenda';$('#search').value='';setupCollaborators();render();document.querySelector(`[data-match="${CSS.escape(button.dataset.jump)}"]`)?.scrollIntoView({block:'center'});}
});
$('#collaborator').addEventListener('change',ev=>{collaborator=ev.target.value;render()});
$('#search').addEventListener('input',ev=>{query=ev.target.value;render()});
$('#prev-week').addEventListener('click',()=>{offset--;render()});
$('#next-week').addEventListener('click',()=>{offset++;render()});
$('#this-week').addEventListener('click',()=>{offset=0;render()});
$('#plan-filter').addEventListener('click',()=>{planOnly=!planOnly;render()});
$('#export').addEventListener('click',()=>{
  const games=matches(weekend(madridToday(),offset));const eligible=games.filter(m=>m.time&&m.status==='scheduled');
  if(!eligible.length){toast('No hay partidos con horario confirmado para exportar.');return}
  const url=URL.createObjectURL(new Blob([calendarICS(eligible)],{type:'text/calendar;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='rfhf-fin-de-semana.ics';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  if(eligible.length<games.length)toast('Calendario exportado. Se han omitido partidos sin horario o ya finalizados.');
});
dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close()}});
document.addEventListener('error',event=>{if(event.target instanceof HTMLImageElement){event.target.replaceWith(Object.assign(document.createElement('span'),{className:'logo-fallback',textContent:'⚽'}))}},true);
try {
  const response=await fetch(new URL('data/feed.json',import.meta.url),{cache:'no-cache'});if(!response.ok)throw new Error('No se han podido cargar los partidos.');rawData=await response.json();
  try{const r=await fetch('data/settings.json',{cache:'no-cache'});settings=await r.json();const reg=await fetch(settings.registry_url,{cache:'no-store',signal:AbortSignal.timeout(4000)});if(reg.ok)registryData=await reg.json()}catch{}
  data=applyPublicRegistry(rawData,registryData);
  data.matches=data.matches.map(m=>({...m,search_names:data.players.filter(p=>m.player_ids.includes(p.id)).map(p=>p.name)}));
  const allowed=new Set(data.matches.map(m=>m.id));planned=new Set([...planned].filter(id=>allowed.has(id)));
  setupCollaborators();render();
  async function refresh(){try{const r=await fetch(new URL('data/feed.json',import.meta.url),{cache:'no-cache'});if(r.ok)rawData=await r.json();if(settings?.registry_url){const reg=await fetch(settings.registry_url,{cache:'no-store',signal:AbortSignal.timeout(4000)});if(reg.ok)registryData=await reg.json()}data=applyPublicRegistry(rawData,registryData);data.matches=data.matches.map(m=>({...m,search_names:data.players.filter(p=>m.player_ids.includes(p.id)).map(p=>p.name)}));setupCollaborators();render()}catch{}}
  setInterval(refresh,30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh()});
} catch(error) {$('#agenda').innerHTML=`<div class="fatal">${e(error.message)} Recarga la página dentro de unos minutos.</div>`;$('#source-status').textContent='No se ha podido cargar la agenda.';}
