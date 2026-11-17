import test from 'node:test';
import assert from 'node:assert/strict';
import { weekend, madridToday, filterMatches, calendarICS, overlaps, displayStat, escapeHTML, safeURL } from '../docs/model.mjs';

test('Friday, Saturday and Sunday stay in the same weekend, including Sunday',()=>{
  for(const day of ['2026-11-17','2026-11-20','2026-11-21','2026-11-22'])assert.deepEqual(weekend(day),['2026-11-20','2026-11-21','2026-11-22']);
  assert.deepEqual(weekend('2026-11-23'),['2026-11-27','2026-11-28','2026-11-29']);
  assert.deepEqual(weekend('2026-12-31'),['2027-01-01','2027-01-02','2027-01-03']);
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
