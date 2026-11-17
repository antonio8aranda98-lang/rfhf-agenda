import test from 'node:test';
import assert from 'node:assert/strict';
import {managementRequest,issueURL} from '../docs/gestion-model.mjs';
const input={action:'add',name:'Jugador Ejemplo Completo',federation:'madrid',collaborator:'Persona Ejemplo',source:'https://www.rffm.es/fichaequipo/123',match_duration:'90'};
test('management requests contain only sporting and assignment fields',()=>{
  const request=managementRequest({...input,token:'do-not-include',contract:'private'});
  assert.equal(request.match_duration,90);assert.equal(request.version,1);
  assert.equal(request.token,undefined);assert.equal(request.contract,undefined);
  const url=new URL(issueURL(request));
  assert.equal(url.origin,'https://github.com');assert.equal(url.pathname,'/antonio8aranda98-lang/rfhf-agenda/issues/new');
  assert.ok(url.searchParams.get('body').startsWith('RFHF-ROSTER-V1\n```json\n'));
  assert.deepEqual(JSON.parse(url.searchParams.get('body').split('```json\n')[1].split('\n```')[0]),request);
});
test('unsafe or mismatched source URLs are rejected before leaving the form',()=>{
  for(const source of ['javascript:alert(1)','http://www.rffm.es/fichaequipo/1','https://www.rffm.es.evil.test/','https://www.fcf.cat/','https://user@www.rffm.es/'])assert.throws(()=>managementRequest({...input,source}));
});
test('deactivation requires an existing player ID; reassignment requires a collaborator',()=>{
  assert.throws(()=>managementRequest({action:'deactivate'}));
  assert.deepEqual(managementRequest({action:'deactivate',player_id:'existing-id'}),{version:1,action:'deactivate',player_id:'existing-id'});
  assert.throws(()=>managementRequest({action:'assign',player_id:'existing-id'}));
});
