import copy
import sys
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from report_refresh import report_plan
from player_stats import summarize, participation, absent

AT=datetime(2026,11,18,20,tzinfo=timezone.utc)
def game(id,date,record=None,attempt=None):
    result=dict(id=id,date=date,status='finished',score_home=1,score_away=0,participation={})
    if record is not None:result['participation']['p']=record
    if attempt:result['participation_attempted_at']={'p':attempt.isoformat()}
    return result

class PartialEvidenceTests(unittest.TestCase):
    def test_partial_sum_reports_its_own_field_coverage(self):
        games=[game('a','2026-10-01',participation(True,90,exits=['60'],goals=0)),game('b','2026-10-08',{'called_up':1,'starts':0,'bench':1,'minutes':None,'goals':1}),game('c','2026-10-15')]
        stats,coverage=summarize(games,'p')
        self.assertIsNone(stats['minutes']);self.assertIsNone(stats['goals'])
        self.assertEqual(coverage['confirmed']['minutes'],60)
        self.assertEqual(coverage['field_checked']['minutes'],1)
        self.assertEqual(coverage['confirmed']['goals'],1)
        self.assertEqual(coverage['field_checked']['goals'],2)
        self.assertEqual(coverage['team_played'],3)
    def test_confirmed_zero_is_distinct_from_no_evidence(self):
        stats,c=summarize([game('a','2026-10-01',absent()),game('b','2026-10-08')],'p')
        self.assertEqual(c['confirmed']['minutes'],0);self.assertEqual(c['field_checked']['minutes'],1)
        stats,c=summarize([game('b','2026-10-08')],'p')
        self.assertIsNone(c['confirmed']['minutes']);self.assertEqual(c['field_checked']['minutes'],0)
    def test_last_missing_report_turns_partial_into_full_total(self):
        games=[game('a','2026-10-01',participation(True,80,goals=1)),game('b','2026-10-08',absent())]
        stats,c=summarize(games,'p');self.assertEqual(stats['minutes'],80);self.assertEqual(c['field_checked']['minutes'],2)

class ReportRetryTests(unittest.TestCase):
    def test_old_partial_record_is_not_skipped_as_if_complete(self):
        old=[game('old','2026-09-01',{'called_up':1,'starts':1,'bench':0,'minutes':None,'goals':0},AT-timedelta(days=1))]
        new=[game('old','2026-09-01')]
        selected=report_plan(new,{'id':'p'},old,at=AT)
        self.assertEqual(selected,{'old'});self.assertEqual(new[0]['participation']['p']['starts'],1)
    def test_failed_reports_rotate_and_cooldown_does_not_starve_remaining_gaps(self):
        previous=[game(str(i),f'2026-10-{i+1:02}') for i in range(6)]
        fresh=copy.deepcopy(previous);selected=report_plan(fresh,{'id':'p'},previous,at=AT,retry_limit=2)
        self.assertEqual(selected,{'0','1'})
        next_games=[game(str(i),f'2026-10-{i+1:02}') for i in range(6)]
        selected=report_plan(next_games,{'id':'p'},fresh,at=AT+timedelta(minutes=30),retry_limit=2)
        self.assertEqual(selected,{'2','3'})
        only_first=[game('0','2026-10-01')]
        self.assertEqual(report_plan(only_first,{'id':'p'},fresh,at=AT+timedelta(hours=5)),set())
        self.assertEqual(report_plan(only_first,{'id':'p'},fresh,at=AT+timedelta(hours=6)),{'0'})
    def test_changed_result_invalidates_previous_participation_and_cooldown(self):
        before=game('a','2026-10-01',absent(),AT)
        new=game('a','2026-10-01');new['score_home']=2
        self.assertEqual(report_plan([new],{'id':'p'},[before],at=AT),{'a'})
        self.assertNotIn('p',new['participation'])
    def test_old_complete_report_keeps_provenance_without_refetch(self):
        old=[game(str(i),f'2026-10-{i+1:02}',absent(),AT-timedelta(days=1)) for i in range(4)]
        old[0]['participation_checked_at']={'p':'2026-11-17T10:00:00+00:00'}
        new=[game(str(i),f'2026-10-{i+1:02}') for i in range(4)]
        selected=report_plan(new,{'id':'p'},old,at=AT)
        self.assertNotIn('0',selected);self.assertEqual(new[0]['participation_checked_at']['p'],'2026-11-17T10:00:00+00:00')

class ValenciaCalendarPriorityTests(unittest.TestCase):
    def test_calendar_finishes_before_bounded_historical_reads(self):
        from unittest.mock import patch
        from valencia_data import load_valencia
        class API:
            def __init__(self):self.calls=[]
            def get(self,route,**params):
                self.calls.append((route,params))
                if route=='equipos/plantilla_home.php':return {'jugadores_equipo':[{'cod_jugador':'3'}]}
                if route=='jugadores/jugador_api.php':return {'nombre_jugador':'JUGADOR','competiciones_participa':[{'codigo_competicion':'10','codgrupo':'11','codequipo':'1'}]}
                if route=='filtros/jornadas_fetch.php':return {'jornadas':[{'codjornada':str(i)} for i in range(1,10)]}
                if route=='partidos/resultados_por_grupo_jornada_data.php':
                    return {'partidos':[dict(codacta=str(100+int(params['cod_jornada'])),cod_equipo_local='1',cod_equipo_visitante='2',local='A',visitante='B',fecha='01-11-2026',hora='12:00',resultado='1 - 0',resultado_provisional='0')]}
                if route=='partidos/ficha_partido_ajax.php':return {'acta_cerrada':'0'}
                raise AssertionError(route)
        api=API();player=dict(id='p',name='Jugador',official_name='JUGADOR',team_id='1',player_id='3',competition_id='10',group_id='11',season_id='22',match_duration=90)
        with patch('valencia_data.PublicFFCV',return_value=api):result=load_valencia(None,player)
        routes=[r for r,_ in api.calls];act_index=routes.index('partidos/ficha_partido_ajax.php')
        self.assertEqual(routes[:act_index].count('partidos/resultados_por_grupo_jornada_data.php'),9)
        self.assertEqual(routes.count('partidos/ficha_partido_ajax.php'),3)
        self.assertEqual(len(result['matches']),9)
        self.assertTrue(all('p' not in m['participation'] for m in result['matches']))

class DirectedRefreshTests(unittest.TestCase):
    def test_directed_refresh_keeps_feed_and_updates_shared_fixture(self):
        from unittest.mock import patch
        from improve_data import refresh_one,recompute
        profile=dict(id='p',name='Jugador',federation='madrid',team='A',team_id='1',collaborator='Uno',stats={})
        match={**game('m','2026-11-01'), 'federation':'madrid','player_ids':['p'],'home':'A','away':'B','home_team_id':'1','away_team_id':'2','time':'12:00'}
        known={**profile,'id':'q','name':'Totales oficiales disponibles','team':'C','team_id':'22','stats':{'called_up':1,'starts':1,'bench':0,'minutes':90,'goals':0}}
        other={**copy.deepcopy(match),'id':'other','player_ids':['q'],'home':'C','home_team_id':'22'}
        feed=dict(season='2026-2027',players=[known,profile],matches=[other,match],federations=[])
        roster=dict(season='2026-2027',players=[known,profile])
        fresh=copy.deepcopy(match);fresh['participation']={'p':participation(True,90,goals=0)}
        with patch('improve_data.madrid',return_value={'matches':[fresh],'stats':{}}) as reader:
            self.assertTrue(refresh_one(feed,roster,{'players':[known,profile]}))
            self.assertEqual(reader.call_args.args[1]['id'],'p')
        recompute(feed)
        self.assertEqual(feed['season'],'2026-2027');self.assertEqual(len(feed['matches']),2)
        self.assertEqual(next(p for p in feed['players'] if p['id']=='p')['stats']['minutes'],90)
