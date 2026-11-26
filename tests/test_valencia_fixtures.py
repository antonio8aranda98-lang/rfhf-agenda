import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from valencia_fixtures import refresh, select_rounds, merge_fixture, scopes_for
from valencia_data import round_matches

AT='2026-11-26T12:00:00+00:00'
P=dict(id='p',name='Jugador Uno',official_name='UNO, JUGADOR',collaborator='Persona Uno',federation='valencia',team_id='1',competition_id='2',group_id='3',season_id='22',team='CLUB',source='https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=1',competition_label='Liga',active=True)
R=dict(season='2026-2027',players=[P])
M=dict(id='valencia-9',federation='valencia',season='2026-2027',competition_id='2',group_id='3',round=10,home_team_id='1',away_team_id='8',home='CLUB',away='RIVAL',date='2026-11-29',time='17:00',venue='VIEJO',status='scheduled',player_ids=['p'],participation={},updated_at='2026-11-18T12:00:00+00:00')
F=dict(season='2026-2027',generated_at='yesterday',players=[{**P,'updated_at':'old stats date','stats':{'minutes':30},'coverage':{'acts_checked':1}}],matches=[M],federations=[dict(id='valencia',last_success='old stats date',status='partial'),dict(id='madrid',status='ok')])


class API:
    def __init__(self,fail=False,hour='12:30'):
        self.client=type('Client',(),dict(retry_after=None))();self.calls=[];self.fail=fail;self.hour=hour
    def get(self,route,**params):
        self.calls.append((route,params))
        if self.fail:raise ValueError('No disponible')
        if 'jornadas_fetch' in route:return dict(jornadas=[dict(codjornada='10',fecha_jornada='29-11-2026')])
        return dict(jornada='10',partidos=[dict(codacta='9',cod_equipo_local='1',cod_equipo_visitante='8',local='CLUB',visitante='RIVAL',fecha='28/11/2026',hora=self.hour,campo='NUEVO',resultado='0')])


class ValenciaFixturesTests(unittest.TestCase):
    def test_live_hours_and_real_match_date_replace_old_values_without_touching_stats(self):
        api=API();original=copy.deepcopy(F)
        result=refresh(F,R,R,api,today=date(2026,11,26),clock=lambda:AT)
        m=result['matches'][0]
        self.assertEqual((m['date'],m['time'],m['venue']),('2026-11-28','12:30','NUEVO'))
        self.assertEqual(m['schedule_checked_at'],AT)
        self.assertEqual(result['players'][0]['stats'],F['players'][0]['stats'])
        self.assertEqual(result['players'][0]['updated_at'],'old stats date')
        self.assertEqual(result['federations'][1],F['federations'][1])
        self.assertEqual(F,original)
        self.assertEqual(len(api.calls),2)
    def test_shared_group_is_read_once_for_multiple_players(self):
        roster={**R,'players':[P,{**P,'id':'other'}]};feed=copy.deepcopy(F);feed['players'].append({**feed['players'][0],'id':'other'})
        api=API();result=refresh(feed,roster,roster,api,today=date(2026,11,26),clock=lambda:AT)
        self.assertEqual(len(api.calls),2);self.assertEqual(result['matches'][0]['player_ids'],['other','p'])
    def test_other_federations_are_preserved_exactly(self):
        feed=copy.deepcopy(F);other={**M,'id':'madrid-20','federation':'madrid','player_ids':['madrid-player']}
        feed['matches'].append(other);feed['players'].append({'id':'madrid-player','name':'Otro','federation':'madrid','stats':{'minutes':99},'updated_at':'unchanged'})
        result=refresh(feed,R,R,API(),today=date(2026,11,26),clock=lambda:AT)
        self.assertEqual(next(m for m in result['matches'] if m['id']=='madrid-20'),other)
        self.assertEqual(result['players'][1],feed['players'][1])
    def test_source_failure_preserves_fixture_and_its_original_read_date(self):
        result=refresh(F,R,R,API(fail=True),today=date(2026,11,26),clock=lambda:AT)
        self.assertEqual(result['matches'],F['matches']);self.assertEqual(result['federations'][0]['fixtures_status'],'error')
        self.assertNotIn('fixtures_checked_at',result['players'][0])
    def test_source_removing_a_time_clears_old_confirmed_hour(self):
        result=refresh(F,R,R,API(hour=''),today=date(2026,11,26),clock=lambda:AT)
        self.assertIsNone(result['matches'][0]['time']);self.assertEqual(result['matches'][0]['status'],'time_pending')
    def test_moved_fixture_from_an_older_round_is_also_rechecked(self):
        rounds=[dict(codjornada='1',fecha_jornada='01-09-2026'),dict(codjornada='10',fecha_jornada='29-11-2026'),dict(codjornada='20',fecha_jornada='01-03-2027')]
        moved={**M,'round':1}
        chosen=select_rounds(rounds,[moved],('22','2','3'),date(2026,11,26))
        self.assertEqual([r['codjornada'] for r in chosen],['1','10'])
    def test_pending_transfer_and_inactive_players_are_not_used_as_verified_scopes(self):
        self.assertEqual(scopes_for(R,{'players':[{**P,'_identity_revision':2}]},F),{})
        self.assertEqual(scopes_for(R,{'players':[{**P,'active':False}]},F),{})
    def test_wrong_round_and_empty_responses_do_not_stamp_old_fixture_as_fresh(self):
        class Wrong(API):
            def get(self,route,**params):
                d=super().get(route,**params)
                if 'partidos' in d:d['jornada']='1'
                return d
        result=refresh(F,R,R,Wrong(),today=date(2026,11,26),clock=lambda:AT)
        self.assertEqual(result['matches'],F['matches'])
    def test_absent_fixture_keeps_last_known_values_but_requires_reconfirmation(self):
        class Missing(API):
            def get(self,route,**params):
                d=super().get(route,**params)
                if 'partidos' in d:d['partidos'][0]['cod_equipo_local']='7'
                return d
        m=refresh(F,R,R,Missing(),today=date(2026,11,26),clock=lambda:AT)['matches'][0]
        self.assertEqual(m['schedule_status'],'unconfirmed');self.assertEqual(m['updated_at'],M['updated_at'])
    def test_reading_fixture_does_not_invent_or_redate_participation(self):
        old={**M,'status':'finished','score_home':1,'score_away':0,'participation':{'p':{'minutes':30}},'participation_checked_at':{'p':'old act date'}}
        fresh={**M,'status':'finished','score_home':1,'score_away':0}
        m=merge_fixture(old,fresh,AT);self.assertEqual(m['participation']['p']['minutes'],30);self.assertEqual(m['participation_checked_at']['p'],'old act date')
        m=merge_fixture(old,{**fresh,'score_home':2},AT);self.assertEqual(m['participation'],{})
    def test_general_sync_preserves_independent_fixtures_check_metadata(self):
        import sync
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            feed=copy.deepcopy(F);feed['federations'][0]['fixtures_checked_at']=AT
            (root/'data/roster.json').write_text(json.dumps(R));(root/'docs/data/feed.json').write_text(json.dumps(feed))
            with patch.object(sync,'ROOT',root),patch.object(sync,'FEDERATIONS',{'valencia':sync.FEDERATIONS['valencia']}),patch.object(sync,'collect_player',return_value={'matches':[copy.deepcopy(M)],'stats':{}}):
                sync._sync()
            published=json.loads((root/'docs/data/feed.json').read_text())
            self.assertEqual(published['federations'][0]['fixtures_checked_at'],AT)
