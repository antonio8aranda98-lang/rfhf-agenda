import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import sync
from fixtures_refresh import refresh_region, madrid_calendar, read_calendar

AT='2026-11-27T12:00:00+00:00'
P=dict(id='p',name='Jugador',federation='murcia',team='CLUB',team_id='1',group_id='3',competition_id='2',season_id='22',source='https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?Codigo_Equipo=1')
M=dict(id='murcia-1-9',federation='murcia',season='2026-2027',group_id='3',competition_id='2',round=9,date='2026-11-29',time=None,home='CLUB',away='RIVAL',home_team_id='1',away_team_id=None,status='time_pending',player_ids=['p'],participation={},updated_at='2026-11-20T12:00:00+00:00')
F=dict(season='2026-2027',players=[{**P,'stats':{'minutes':30},'updated_at':'old stats'}],matches=[M],federations=[{'id':'murcia','last_success':'old stats'},{'id':'madrid'}])
R=dict(season='2026-2027',players=[P])


class FixturesRefreshTests(unittest.TestCase):
    def test_new_time_replaces_week_old_pending_time_without_rereading_player(self):
        calls=[]
        def reader(client,p):calls.append(p);return [{**M,'time':'17:00','status':'scheduled'}]
        result=refresh_region(F,R,R,'murcia',client=object(),reader=reader,clock=lambda:AT,today=date(2026,11,27))
        self.assertEqual(len(calls),1);self.assertEqual(result['matches'][0]['time'],'17:00')
        self.assertEqual(result['matches'][0]['schedule_checked_at'],AT)
        self.assertEqual(result['players'][0]['stats'],F['players'][0]['stats']);self.assertEqual(result['players'][0]['updated_at'],'old stats')
        self.assertEqual(result['federations'][1],F['federations'][1])
    def test_shared_team_and_additional_team_have_separate_calendars_and_one_read_per_team(self):
        extra={**P,'team_id':'4','group_id':'5','team':'CLUB B','team_source':P['source']}
        roster={**R,'players':[{**P,'additional_teams':[extra]},{**P,'id':'other'}]}
        feed=copy.deepcopy(F);feed['players'].append({**P,'id':'other'});calls=[]
        def reader(client,p):
            calls.append(p['team_id']);return [{**M,'id':'murcia-'+p['team_id']+'-9','home_team_id':p['team_id'],'home':p['team'],'group_id':p['group_id'],'time':'10:00','status':'scheduled'}]
        result=refresh_region(feed,roster,roster,'murcia',client=object(),reader=reader,clock=lambda:AT,today=date(2026,11,27))
        self.assertEqual(calls,['1','4']);self.assertEqual(len(result['matches']),2)
        self.assertEqual(next(m for m in result['matches'] if m['group_id']=='3')['player_ids'],['other','p'])
    def test_failed_source_does_not_stamp_old_hours_as_fresh(self):
        result=refresh_region(F,R,R,'murcia',client=object(),reader=lambda *a:(_ for _ in ()).throw(ValueError('source unavailable')),clock=lambda:AT,today=date(2026,11,27))
        self.assertEqual(result['matches'][0]['time'],M['time']);self.assertEqual(result['matches'][0]['updated_at'],M['updated_at'])
        self.assertEqual(result['matches'][0]['schedule_status'],'unconfirmed');self.assertEqual(result['federations'][0]['fixtures_status'],'error')
        self.assertNotIn('fixtures_checked_at',result['players'][0])
    def test_madrid_calendar_fetch_does_not_need_roster_or_player_statistics(self):
        class Client:
            def next_props(self,url):
                self.url=url
                return {'calendar':{'temporada':'2026-2027','rounds':[{'codjornada':'9','equipos':[dict(codacta='7',codigo_equipo_local='1',codigo_equipo_visitante='8',equipo_local='CLUB',equipo_visitante='RIVAL',fecha='29-11-2026',hora='12:00',goles_casa='',goles_visitante='')]}]}}
        c=Client();m=madrid_calendar(c,{**P,'federation':'madrid','season':'2026-2027'})[0]
        self.assertIn('/competicion/calendario?',c.url);self.assertEqual(m['time'],'12:00');self.assertEqual(m['status'],'scheduled')
    def test_wrong_season_is_not_used_for_madrid(self):
        c=type('Client',(),{'next_props':lambda self,url:{'calendar':{'temporada':'2025-2026'}}})()
        with self.assertRaises(ValueError):madrid_calendar(c,{**P,'season':'2026-2027'})
    def test_general_updates_controls_mode_cannot_silently_skip_the_whole_roster(self):
        for mode,ids,expected in [('controls',[],False),('priority',[],False),('priority',['p'],True)]:
            with self.subTest(mode=mode,ids=ids),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
                (root/'data/roster.json').write_text(json.dumps({**R,'registry_revision':27}))
                (root/'docs/data/registry-status.json').write_text(json.dumps({'intake_mode':mode,'intake_ids':ids}))
                with patch.object(sync,'ROOT',root),patch.object(sync,'_sync') as runner:
                    sync.sync(watch_intake=True)
                self.assertEqual(runner.call_args.args[2],expected)
    def test_explicit_intake_remains_targeted_when_there_are_no_new_players(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            (root/'data/roster.json').write_text(json.dumps({**R,'registry_revision':27}))
            (root/'docs/data/registry-status.json').write_text(json.dumps({'intake_mode':'controls','intake_ids':[]}))
            with patch.object(sync,'ROOT',root),patch.object(sync,'_sync') as runner:sync.sync(intake=True,watch_intake=True)
            self.assertTrue(runner.call_args.args[2])
