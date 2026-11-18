import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sync import parse_murcia, iso_date, http_time, initial_data

class FederationTests(unittest.TestCase):
    def test_murcia_without_hour_is_not_a_confirmed_appointment(self):
        html='<table><tr><td>10</td><td><h5>UNION MOLINENSE</h5><h5>E.F. MOLINA</h5><h5>22-11-2026</h5></td><td> - </td></tr><tr><td>9</td><td><h5>UNION MOLINENSE</h5><h5>CIEZA</h5><h5>13-11-2026 19:45</h5></td><td>6 - 0</td></tr></table>'
        games=parse_murcia(html,{'id':'iker','team_id':'123'},'https://www.ffrm.es/')
        self.assertEqual(games[0]['status'],'time_pending')
        self.assertIsNone(games[0]['time'])
        self.assertIsNone(games[0]['venue'])
        self.assertEqual(games[1]['score_away'],0)
        self.assertEqual(games[1]['status'],'finished')
    def test_format_failure_does_not_erase_fixtures(self):
        with self.assertRaises(ValueError):parse_murcia('<html>Inicia sesión</html>',{'id':'iker','team_id':'1'},'https://www.ffrm.es/')
    def test_date_and_time_validation(self):
        self.assertEqual(iso_date('22-11-2026'),'2026-11-22')
        self.assertIsNone(iso_date('31-02-2026'))
        self.assertIsNone(http_time('25:00'))
        self.assertEqual(http_time('9:05'),'09:05')
    def test_flight_json_without_evaluation(self):
        import json
        payload='5:'+json.dumps(['$','component',None,{'initialData':{'matches':[{'CODACTA':'42'}]}}])
        html='<script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
        self.assertEqual(initial_data(html)['matches'][0]['CODACTA'],'42')
        with self.assertRaises(ValueError):initial_data('<script>alert(1)</script>')
    def test_valencia_numeric_date_and_zero_score(self):
        from parse_valencia import parse_team
        html='''<a href="../partidos/partido.php?cod_partido=42"><div class="match-card"><div class="m-meta">Viernes 21 noviembre de 2026 · Jornada 9</div><div class="team-row"><span class="team-name">EAF</span><span class="team-goals">0</span></div><div class="team-row"><span class="team-name">Buñol</span><span class="team-goals">1</span></div><div class="match-right">Finalizado</div></div></a>'''
        games=parse_team(html,{'id':'daniel'})
        self.assertEqual(games[0]['date'],'2026-11-21')
        self.assertEqual(games[0]['score_home'],0)
        self.assertEqual(games[0]['status'],'finished')
        with self.assertRaises(ValueError):parse_team('<h1>Portada</h1>',{'id':'daniel'})

if __name__=='__main__':unittest.main()

class MadridScopeTests(unittest.TestCase):
    def client(self):
        from sync import Client
        class Fake:
            def __init__(self):self.calls=[]
            def next_props(self,url):
                self.calls.append(url)
                if '/fichaequipo/' in url:return {'team':{'nombre_equipo':'Equipo','jugadores_equipo':[{'cod_jugador':'3'}],'escudo_club':'','host':'https://www.rffm.es/'}}
                if '/fichajugador/' in url:return {'player':{'competiciones_participa':[{'codigo_competicion':'1','ver_estadisticas':'1','vis_goles':'1','vis_minutos':'1'},{'codigo_competicion':'2'}],'partidos':[{'nombre':'Convocados','valor':'99'}],'minutos_totales_jugados':'999'}}
                if '/calendario?' in url:return {'calendar':{'rounds':[{'codjornada':'1','equipos':[{'codacta':'9','codigo_equipo_local':'11','codigo_equipo_visitante':'12','equipo_local':'Equipo','equipo_visitante':'Rival','fecha':'01-11-2026','hora':'12:00','goles_casa':'0','goles_visitante':'1'}]}]}}
                if '/acta-partido/' in url:return {'game':{'codigo_equipo_local':'11','acta_cerrada':'1','jugadores_equipo_local':[{'codjugador':str(i),'titular':'1','ver_estadisiticas_jugador':'1'} for i in range(1,12)]}}
                raise AssertionError(url)
        return Fake()
    def player(self):return {'id':'one','name':'Jugador Uno','team_id':'11','player_id':'3','competition_id':'1','group_id':'2','season_id':'22','source':'https://www.rffm.es/fichajugador/3','match_duration':90}
    def test_multi_team_summary_is_not_mixed_with_the_followed_team(self):
        from sync import madrid
        from player_stats import summarize
        client=self.client();p=self.player();r=madrid(client,p)
        self.assertIsNone(r['stats']['called_up']);self.assertIsNone(r['stats']['minutes'])
        stats,_=summarize(r['matches'],'one',r['stats'])
        self.assertEqual((stats['called_up'],stats['minutes']),(1,90))
    def test_identity_validation_checks_calendar_without_reading_every_historical_act(self):
        from sync import madrid
        client=self.client();r=madrid(client,{**self.player(),'_calendar_only':True})
        self.assertEqual(len(r['matches']),1);self.assertFalse(any('/acta-partido/' in u for u in client.calls))

class RegistryRefreshTests(unittest.TestCase):
    def fixture(self):
        stamp='2026-11-18T10:00:00+00:00'
        player={'id':'one','name':'Jugador Uno','federation':'madrid','collaborator':'Persona Uno','team':'Equipo','team_id':'11','competition_label':'Liga','source':'https://www.rffm.es/fichajugador/3','active':True}
        game={'id':'match-one','federation':'madrid','player_ids':['one'],'home':'Equipo','away':'Rival','date':'2026-11-21','time':'12:00','status':'scheduled','participation':{}}
        roster={'season':'2026-2027','players':[player]}
        feed={'season':'2026-2027','players':[{**player,'updated_at':stamp,'stats':{}}],'matches':[game],'federations':[{'id':'madrid','status':'ok','last_success':stamp,'checked_at':stamp}]}
        return roster,feed

    def run_refresh(self,roster,baseline,collector):
        import json,tempfile
        from unittest.mock import patch
        import sync as module
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            (root/'data/roster.json').write_text(json.dumps(roster));(root/'docs/data/feed.json').write_text(json.dumps(baseline))
            with patch.object(module,'ROOT',root),patch.object(module,'FEDERATIONS',{'madrid':module.FEDERATIONS['madrid']}),patch.object(module.Client,'get',side_effect=AssertionError('No network')),patch.object(module,'collect_player',side_effect=collector):
                module.sync(registry_changes=True)
            return json.loads((root/'docs/data/feed.json').read_text())

    def test_unchanged_sporting_sources_keep_their_dates_and_skip_network(self):
        roster,baseline=self.fixture();roster['players'][0]['collaborator']='Persona de prueba'
        def no_refresh(*args):raise AssertionError('No sporting refresh required')
        result=self.run_refresh(roster,baseline,no_refresh)
        self.assertEqual(result['players'][0]['updated_at'],baseline['players'][0]['updated_at'])
        self.assertEqual(result['federations'],baseline['federations'])
        self.assertEqual(result['players'][0]['collaborator'],'Persona de prueba')

    def test_profile_without_calendar_retries_even_if_source_is_unchanged(self):
        import copy
        roster,baseline=self.fixture();game=baseline['matches'][0];baseline['matches']=[];calls=[]
        def refresh(*args):
            calls.append(True);return {'matches':[copy.deepcopy(game)],'stats':{}}
        result=self.run_refresh(roster,baseline,refresh)
        self.assertEqual(len(calls),1);self.assertEqual(len(result['matches']),1)

    def test_opponent_fixture_does_not_replace_first_successful_player_read(self):
        import copy
        roster,baseline=self.fixture();baseline['players'][0]['updated_at']=None;calls=[]
        game=baseline['matches'][0]
        def refresh(*args):
            calls.append(True)
            return {'matches':[copy.deepcopy(game)],'stats':{},'checked_at':'2026-11-18T12:15:52+00:00'}
        result=self.run_refresh(roster,baseline,refresh)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['players'][0]['updated_at'],'2026-11-18T12:15:52+00:00')
