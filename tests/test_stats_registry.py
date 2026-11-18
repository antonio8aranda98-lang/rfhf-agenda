import copy
import json
import sys
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from player_stats import minute, participation, absent, summarize
from federation_acts import parse_murcia_act, parse_catalunya_act, flight_players, public_digits, parse_murcia_calendar, murcia_round
from sync import apply_roster
from registry import change, request_from_event, official_url, unique_name
import registry


class ParticipationTests(unittest.TestCase):
    def test_minutes_substitutions_and_dismissals(self):
        self.assertEqual(participation(True, 90, exits=['62'], goals=0)['minutes'], 62)
        self.assertEqual(participation(True, 90, dismissals=['73'])['minutes'], 73)
        self.assertEqual(participation(False, 80, entries=['40'])['minutes'], 40)
        self.assertEqual(participation(True, 90)['minutes'], 90)
        self.assertEqual(minute(0, 90), 0)
        self.assertEqual(minute('90+4', 90), 90)
        self.assertIsNone(participation(False, 80, entries=['?'])['minutes'])

    def test_bench_is_not_played_and_absence_is_not_missing(self):
        bench = participation(False, 80, goals=0)
        self.assertEqual((bench['called_up'], bench['starts'], bench['bench'], bench['played'], bench['minutes']), (1, 0, 1, 0, 0))
        self.assertEqual(absent(), dict(called_up=0, starts=0, bench=0, played=0, minutes=0, goals=0))

    def test_partial_act_coverage_never_becomes_a_season_total(self):
        games = [{'status':'finished','participation':{'p':participation(True,90,goals=0)}}, {'status':'finished','participation':{}}]
        stats, coverage = summarize(games, 'p')
        self.assertIsNone(stats['minutes']);self.assertEqual(stats['team_played'],2);self.assertEqual(coverage['acts_checked'],1)
        games[1]['participation']['p'] = absent()
        stats, coverage = summarize(games, 'p')
        self.assertEqual((stats['called_up'],stats['starts'],stats['minutes']),(1,1,90))
        games[0]['participation']['p']['goals'] = None
        stats, _ = summarize(games, 'p', {'goals': 1})
        self.assertEqual(stats['goals'], 1) # Verified published summary remains usable.

    def test_murcia_yellow_card_does_not_erase_minutes(self):
        starters=''.join(f'<tr><td>{i}</td><td>{"EJEMPLO APELLIDO, NOMBRE" if i==1 else "OTRO "+str(i)}</td></tr>' for i in range(1,12))
        html=f'''<div class="details"><div class="number">EQUIPO A</div><div class="desc"><h5>Titulares</h5><table>{starters}</table><h5>Suplentes</h5><table><tr><td>12</td><td>SUPLENTE</td></tr></table><h4>Sustituciones</h4><table><tr><td><i class="fa-arrow-left"></i></td><td>SUPLENTE</td></tr><tr><td><i class="fa-arrow-right"></i></td><td><span>(40')</span> EJEMPLO APELLIDO, NOMBRE</td></tr></table><h4>Tarjetas</h4><table><tr><td><img src="tarj_amar.gif"></td><td>(20') EJEMPLO APELLIDO, NOMBRE</td></tr></table></div></div><div class="details"><div class="number">Goles</div><table></table></div>'''
        stats=parse_murcia_act(html, {'team':'EQUIPO A','official_name':'EJEMPLO APELLIDO, NOMBRE','match_duration':80})
        self.assertEqual(stats['minutes'],40);self.assertEqual(stats['starts'],1);self.assertEqual(stats['goals'],0)

    def test_catalan_goal_component_cannot_overwrite_starter_identity(self):
        players=[{'player':{'id':i,'nombre':f'JUGADOR {i}','titular':'1'}} for i in range(15)]
        players.append({'player':{'id':1,'nombre':'JUGADOR 1'}})
        payload='5:'+json.dumps(players)
        html='<main>FINALITZAT<div><div><h3>GOLS</h3></div><div><span>JUGADOR 1</span></div></div></main><script>self.__next_f.push('+json.dumps([1,payload])+')</script>'
        stats=parse_catalunya_act(html, {'official_name':'JUGADOR 1'})
        self.assertEqual(stats['starts'],1);self.assertEqual(stats['bench'],0);self.assertEqual(stats['goals'],1);self.assertIsNone(stats['minutes'])

    def test_murcia_displayed_scores_ignore_hidden_decoys(self):
        from bs4 import BeautifulSoup
        mapping=[2,5,9,4,1,0,8,6,3,7]*4
        html='<script>const ntype='+json.dumps(mapping)+'</script><div class="card-body"><h5 class="card-title">Jornada 1</h5><div class="row"><table><tr><td>CLUB A</td><td><strong><i id="home"><script>ntype("home",4,0,"fa-9");</script><span style="display:none">9</span></i></strong> - <strong><style>#away:before{content:"\\0032"}</style><span id="away"><span style="display:none">8</span></span></strong></td><td>CLUB B</td></tr></table><div class="right">CAMPO OFICIAL 21-11-2026 - 12:00</div></div></div>'
        matches=parse_murcia_calendar(html,{'id':'p','team_id':'1','team':'CLUB A'},'https://www.ffrm.es/')
        self.assertEqual((matches[0]['score_home'],matches[0]['score_away']),(1,2));self.assertEqual(matches[0]['venue'],'CAMPO OFICIAL');self.assertEqual(matches[0]['time'],'12:00')

    def test_murcia_recovers_using_its_public_filter_link_when_calendar_link_is_empty(self):
        class Client:
            calls=[]
            def get(self,url):
                self.calls.append(url)
                if len(self.calls)==1:raise ValueError('La fuente ha devuelto una respuesta vacía')
                return '<h3>Jornada 7</h3><table><tr><td><a href="NFG_VisEquipos?Codigo_Equipo=1">CLUB A</a><a href="NFG_VisEquipos?Codigo_Equipo=2">CLUB B</a><a href="NFG_CmpPartido?cod_primaria=1000120&CodActa=42&cod_acta=42">Acta</a></td></tr></table>'
        c=Client();report=murcia_round(c,{'team_id':'1','competition_id':'10','group_id':'11','season_id':'22'},7)
        self.assertEqual(len(c.calls),2);self.assertIn('Sch_Tipo_Juego=',c.calls[1]);self.assertIn('CodActa=42',report['url']);self.assertEqual(report['home_team_id'],'1')


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.roster={'season':'2026-2027','players':[
            {'id':'a','name':'Jugador A','official_name':'A, JUGADOR','federation':'madrid','team':'CLUB A','team_id':'1','collaborator':'Persona A'},
            {'id':'b','name':'Jugador B','official_name':'B, JUGADOR','federation':'madrid','team':'CLUB B','team_id':'2','collaborator':'Persona B'}]}
        self.match={'id':'madrid-42','federation':'madrid','date':'2026-11-21','round':3,'time':'12:00','home':'CLUB A','away':'CLUB B','home_team_id':'1','away_team_id':'2','player_ids':['a','b'],'participation':{'a':absent(),'b':absent()}}

    def test_owner_guard_checks_both_sender_and_issue_author(self):
        event={'sender':{'login':'owner'},'issue':{'title':'[RFHF] Alta','user':{'login':'owner'},'body':'RFHF-ROSTER-V1\n```json\n{"version":1,"action":"deactivate","player_id":"a"}\n```'}}
        self.assertEqual(request_from_event(event,'owner/repo')['player_id'],'a')
        for field in ('sender','user'):
            modified=copy.deepcopy(event)
            if field=='sender':modified['sender']['login']='outsider'
            else:modified['issue']['user']['login']='outsider'
            with self.assertRaises(ValueError):request_from_event(modified,'owner/repo')

    def test_failed_new_identity_does_not_change_roster(self):
        before=copy.deepcopy(self.roster)
        def reject(*args):raise ValueError('Jugador no encontrado')
        with self.assertRaises(ValueError):change(self.roster,{'version':1,'action':'add'},resolver=reject)
        self.assertEqual(self.roster,before)
        with self.assertRaises(ValueError):unique_name(['APELLIDO, NOMBRE','APELLIDO, NOMBRE'],'Nombre Apellido')

    def test_deactivation_prunes_stale_shared_fixtures_and_crossing(self):
        roster=change(self.roster,{'version':1,'action':'deactivate','player_id':'b'})
        feed=apply_roster({'players':copy.deepcopy(self.roster['players']),'matches':[copy.deepcopy(self.match)]},roster)
        self.assertEqual([p['id'] for p in feed['players']],['a'])
        self.assertEqual(feed['matches'][0]['player_ids'],['a']);self.assertNotIn('b',feed['matches'][0]['participation'])
        self.assertFalse(feed['matches'][0]['is_internal_matchup'])

    def test_crossing_unifies_both_collaborators_and_uses_ids_over_name(self):
        other=copy.deepcopy(self.match);other['player_ids']=['b'];other['participation']={'b':absent()}
        first=copy.deepcopy(self.match);first['player_ids']=['a'];first['participation']={'a':absent()}
        feed=apply_roster({'players':copy.deepcopy(self.roster['players']),'matches':[first,other]},self.roster)
        self.assertEqual(len(feed['matches']),1);self.assertTrue(feed['matches'][0]['is_internal_matchup'])
        self.roster['players'][1].update(team='CLUB A',team_id='999')
        feed=apply_roster(feed,self.roster)
        self.assertEqual(feed['matches'][0]['away_player_ids'],[])

    def test_sources_cannot_point_to_arbitrary_hosts_or_paths(self):
        official_url('https://www.rffm.es/fichaequipo/123','madrid')
        for url in ('http://www.rffm.es/fichaequipo/123','https://www.rffm.es.evil.test/fichaequipo/123','https://www.rffm.es/other','https://user@www.rffm.es/fichaequipo/1'):
            with self.assertRaises(ValueError):official_url(url,'madrid')

    def test_rescheduled_shared_fixture_prefers_fresh_data(self):
        old={**copy.deepcopy(self.match),'date':'2026-11-21','updated_at':'2026-11-16T12:00:00Z'}
        new={**copy.deepcopy(self.match),'date':'2026-11-22','time':'17:00','updated_at':'2026-11-17T12:00:00Z'}
        feed=apply_roster({'players':self.roster['players'],'matches':[new,old]},self.roster)
        self.assertEqual(len(feed['matches']),1);self.assertEqual(feed['matches'][0]['date'],'2026-11-22');self.assertEqual(feed['matches'][0]['time'],'17:00')

    def test_assignment_keeps_identity_and_history(self):
        result=change(self.roster,{'version':1,'action':'assign','player_id':'a','collaborator':'Otra Persona'})
        self.assertEqual(result['players'][0]['collaborator'],'Otra Persona');self.assertEqual(result['players'][0]['team_id'],'1')
        self.assertEqual(self.roster['players'][0]['collaborator'],'Persona A')

    def test_event_handler_removes_player_before_optional_network_refresh(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            (root/'data/roster.json').write_text(json.dumps(self.roster))
            (root/'docs/data/feed.json').write_text(json.dumps({'players':self.roster['players'],'matches':[self.match]}))
            body='RFHF-ROSTER-V1\n```json\n'+json.dumps({'version':1,'action':'deactivate','player_id':'b'})+'\n```'
            event={'sender':{'login':'owner'},'issue':{'title':'[RFHF] Baja','user':{'login':'owner'},'body':body}}
            (root/'event.json').write_text(json.dumps(event))
            with patch.object(registry,'ROOT',root),patch.dict(os.environ,{'GITHUB_EVENT_PATH':str(root/'event.json'),'GITHUB_REPOSITORY':'owner/repo','GITHUB_OUTPUT':str(root/'output')}):registry.main()
            published=json.loads((root/'docs/data/feed.json').read_text())
            self.assertEqual([p['id'] for p in published['players']],['a']);self.assertFalse(published['matches'][0]['is_internal_matchup'])
            self.assertIn('applied=true',(root/'output').read_text())


if __name__=='__main__':unittest.main()


class MadridCalendarScopeTests(unittest.TestCase):
    def test_missing_player_competition_can_use_verified_team_calendar(self):
        from registry import resolve_player
        source='https://www.rffm.es/competicion/calendario?competicion=100&grupo=200&temporada=22&tipojuego=1'
        class Client:
            def get(self,url):return ''
            def next_props(self,url):
                if '/fichaequipo/' in url:return {'team':{'nombre_equipo':'Equipo C','categoria':'PRIMERA AFICIONADO','jugadores_equipo':[{'nombre':'APELLIDO, JUGADOR','cod_jugador':'3'}]}}
                if '/fichajugador/' in url:return {'player':{'nombre_temporada':'2026-2027','codigo_temporada':'22','competiciones_participa':[]}}
                return {'calendar':{'temporada':'2026-2027','competicion':'PRIMERA AFICIONADO','grupo':'Grupo 5','rounds':[{'equipos':[{'codigo_equipo_local':'11','codigo_equipo_visitante':'12'}]}]}}
        request={'name':'Jugador Apellido','federation':'madrid','source':'https://www.rffm.es/fichaequipo/11','collaborator':'Persona Uno','match_duration':90,'age_category':'senior','competition_source':source}
        with patch.dict(registry.ADAPTERS,{'madrid':lambda *args:{'matches':[{}]}}):
            p=resolve_player(request,{'season':'2026-2027','players':[]},Client())
            self.assertEqual((p['competition_id'],p['group_id'],p['season_id']),('100','200','22'))
            with self.assertRaises(ValueError):resolve_player({**request,'source':'https://www.rffm.es/fichaequipo/99'},{'season':'2026-2027','players':[]},Client())
            with self.assertRaises(ValueError):resolve_player({**request,'competition_source':source.replace('temporada=22','temporada=21')},{'season':'2026-2027','players':[]},Client())
