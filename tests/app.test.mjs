import test from 'node:test';
import assert from 'node:assert/strict';
import { weekend, madridToday, filterMatches, calendarICS, overlaps, matchups, applyPublicRegistry, displayStat, escapeHTML, safeURL } from '../docs/model.mjs';

test('the weekend contains Saturday and Sunday only, including while browsing on Sunday',()=>{
  for(const day of ['2026-11-17','2026-11-20','2026-11-21','2026-11-22'])assert.deepEqual(weekend(day),['2026-11-21','2026-11-22']);
  assert.deepEqual(weekend('2026-11-23'),['2026-11-28','2026-11-29']);
  assert.deepEqual(weekend('2026-12-31'),['2027-01-02','2027-01-03']);
});
test('Madrid date is independent of browser or runner timezone',()=>{
  assert.equal(madridToday(new Date('2026-11-21T23:30:00Z')),'2026-11-22');
  assert.equal(madridToday(new Date('2026-07-01T22:30:00Z')),'2026-07-02');
});
test('collaborator agenda includes only assigned players and deduplicates upstream',()=>{
  const games=[{id:'a',player_ids:['jorge'],date:'2026-11-21',home:'Daganzo',away:'Getafe'},{id:'b',player_ids:['daniel'],date:'2026-11-21',home:'Buñol',away:'EAF'}];
  assert.deepEqual(filterMatches(games,['jorge'],['2026-11-21']).map(m=>m.id),['a']);
  assert.equal(filterMatches(games,['daniel'],null,'bunol').length,1);
  assert.equal(filterMatches(games,['jorge'],null,'',new Set(['b'])).length,0);
});
test('missing stats stay distinct from a confirmed zero',()=>{assert.equal(displayStat(null),'—');assert.equal(displayStat(undefined),'—');assert.equal(displayStat(0),'0')});
test('pending and cancelled games are never exported as appointments',()=>{
  const m={id:'1',home:'Getafe, B',away:'Daganzo',date:'2026-11-21',time:'16:00',status:'scheduled',source:'https://www.rffm.es/'};
  const ics=calendarICS([m,{...m,id:'2',time:null,status:'time_pending'},{...m,id:'3',status:'cancelled'}],new Date('2026-11-17T12:00:00Z'));
  assert.equal((ics.match(/BEGIN:VEVENT/g)||[]).length,1);
  assert.ok(ics.includes('DTSTART;TZID=Europe/Madrid:20261121T160000'));
  assert.ok(ics.includes('SUMMARY:Getafe\\, B'));
  assert.ok(ics.includes('BEGIN:VTIMEZONE'));
  for(const line of ics.split('\r\n'))assert.ok(Buffer.byteLength(line)<=75);
});
test('overlap warning ignores the same fixture, unknown times and completed matches',()=>{
  const a={id:'a',date:'2026-11-21',time:'16:00',status:'scheduled'};
  assert.equal(overlaps(a,{...a,id:'b',time:'17:30'}),true);
  assert.equal(overlaps(a,{...a,id:'b',time:'18:00'}),false);
  assert.equal(overlaps(a,a),false);
  assert.equal(overlaps(a,{...a,id:'b',time:null}),false);
});
test('federation text and links cannot inject markup or script schemes',()=>{
  assert.equal(escapeHTML('<script>"'), '&lt;script&gt;&quot;');
  assert.equal(safeURL('javascript:alert(1)'), '');
  assert.equal(safeURL('https://www.fcf.cat/'),'https://www.fcf.cat/');
});
test('opponent alert ignores collaborator filter, while excluding inactive and postponed players',()=>{
  const players=[{id:'a',collaborator:'Uno'},{id:'b',collaborator:'Dos'}];
  const m={id:'fixture',federation:'madrid',date:'2026-11-21',home:'Club A',away:'Club B',home_player_ids:['a'],away_player_ids:['b'],status:'scheduled'};
  const found=matchups([m,{...m,id:'duplicate'}],players,['2026-11-21']);
  assert.equal(found.length,1);assert.equal(found[0].away_players[0].collaborator,'Dos');
  assert.equal(matchups([m],players.map(p=>({...p,active:p.id!=='b'})),['2026-11-21']).length,0);
  assert.equal(matchups([{...m,status:'postponed'}],players,['2026-11-21']).length,0);
  assert.equal(matchups([{...m,away_player_ids:[]}],players,['2026-11-21']).length,0);
});
test('public registry removes players and crossings immediately without publishing unverified additions',()=>{
  const feed={season:'2026-2027',registry_revision:1,players:[{id:'a',collaborator:'Uno'},{id:'b',collaborator:'Dos'}],matches:[{id:'m',player_ids:['a','b'],home_player_ids:['a'],away_player_ids:['b'],participation:{a:{minutes:90},b:{minutes:20}}}]};
  const registry={initialized:true,season:feed.season,revision:2,players:[{id:'a',collaborator:'Nuevo'},{id:'b',collaborator:'Dos',active:false},{id:'new',name:'Unverified'}]};
  const next=applyPublicRegistry(feed,registry);assert.deepEqual(next.players,[{id:'a',collaborator:'Nuevo'}]);assert.deepEqual(next.matches[0].away_player_ids,[]);assert.equal(next.matches[0].participation.b,undefined);assert.equal(feed.players.length,2);
  registry.players[1]={id:'b',active:true,_activation_revision:3};assert.equal(applyPublicRegistry(feed,registry).players.length,1);
});

test('two teams belonging to the same followed player never create a self matchup',()=>{
 const player={id:'one',name:'Jugador Uno',active:true};
 const games=[{id:'same',date:'2026-11-21',home:'A',away:'B',federation:'madrid',home_player_ids:['one'],away_player_ids:['one'],status:'scheduled'}];
 assert.equal(matchups(games,[player],['2026-11-21']).length,0);
});

test('partial evidence shows a confirmed zero and coverage without becoming a full season total',async()=>{
  const {statEvidence}=await import('../docs/model.mjs');
  const player={stats:{minutes:null},coverage:{team_played:8,confirmed:{minutes:0},field_checked:{minutes:6}}};
  assert.deepEqual(statEvidence(player,'minutes'),{value:0,partial:true,checked:6,total:8});
  player.coverage.field_checked.minutes=0;
  assert.equal(statEvidence(player,'minutes').value,null);
  player.stats.minutes=500;
  assert.deepEqual(statEvidence(player,'minutes'),{value:500,partial:false});
});
