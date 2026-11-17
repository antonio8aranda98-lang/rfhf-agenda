export const REPOSITORY = 'antonio8aranda98-lang/rfhf-agenda';
const labels = {add:'Alta de jugador',deactivate:'Desactivar jugador',reactivate:'Reactivar jugador',assign:'Cambiar colaborador'};
export function managementRequest(values) {
  if (!labels[values.action]) throw new Error('Selecciona una operación.');
  const request = {version:1,action:values.action};
  const requiredText = (key,label) => {
    const value=String(values[key]||'').trim();
    if(value.length<2||value.length>100||/[\x00-\x1f]/.test(value))throw new Error(`Revisa ${label}.`);
    request[key]=value;
  };
  if(values.action==='add') {
    requiredText('name','el nombre completo');requiredText('collaborator','el colaborador');
    if(!['madrid','catalunya','murcia','valencia'].includes(values.federation))throw new Error('Selecciona una federación.');
    const hosts={madrid:['rffm.es','www.rffm.es'],catalunya:['fcf.cat','www.fcf.cat'],murcia:['ffrm.es','www.ffrm.es'],valencia:['ffcv.es','www.ffcv.es']};
    let url;try{url=new URL(values.source)}catch{throw new Error('Introduce el enlace oficial del equipo.')}
    if(url.protocol!=='https:'||!hosts[values.federation].includes(url.hostname)||url.username||url.password||url.port)throw new Error('El enlace debe pertenecer a la federación seleccionada.');
    request.federation=values.federation;request.source=url.href;
    request.match_duration=Number(values.match_duration);
    if(![60,70,80,90].includes(request.match_duration))throw new Error('Selecciona la duración reglamentaria.');
    if(values.competition_source?.trim())request.competition_source=values.competition_source.trim();
  } else {
    requiredText('player_id','el jugador');
    if(values.action==='assign')requiredText('collaborator','el colaborador');
  }
  return request;
}
export function issueURL(request, playerName='') {
  const title=`[RFHF] ${labels[request.action]} · ${request.name||playerName||request.player_id}`;
  const body='RFHF-ROSTER-V1\n```json\n'+JSON.stringify(request,null,2)+'\n```';
  return `https://github.com/${REPOSITORY}/issues/new?`+new URLSearchParams({title,body});
}
