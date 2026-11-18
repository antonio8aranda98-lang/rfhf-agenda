import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from murcia_registration import discover_scope
from registry import resolve_player
from sync import murcia, apply_roster
from federation_acts import parse_murcia_calendar

SOURCE='https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?Codigo_Equipo=7&cod_primaria=3001860'
TEAM='<span class="la_roja_regular_titulo1">UCAM</span><table><tr><th>Jugadores (1)</th></tr><tr><td>MARIN MOYA, SALVADOR</td></tr></table><a href="NFG_VisCompeticiones_Equipo?codequipo=7&codtemporada=22">Ficha de Competición</a>'
def row(comp='10',group='11',team='7'):
    return f'<tr><td><a href="NFG_VisCompeticiones_Vis?codcompeticion={comp}">LIGA NACIONAL JUVENIL</a></td><td><a href="NFG_VisGrupos_Vis?codgrupo={group}">GRUPO X</a></td><td><a href="NFG_VisCompeticiones_Grupo?codequipo={team}&codgrupo={group}">Ficha</a></td></tr>'
HISTORY='<h4>2026-2027</h4><table>'+row()+'</table><h4>2025-2026</h4><table>'+row('20','21')+'</table>'
class FakeClient:
    def __init__(self,history=HISTORY):self.history=history;self.calls=[]
    def get(self,url):
        self.calls.append(url)
        if 'NFG_VisCompeticiones_Equipo?' in url:return self.history
        if 'NFG_VisCompeticiones_Grupo?' in url:return '<h4>UCAM</h4><h4>Temporada 2026-2027</h4>'
        if 'NFG_VisEquipos?' in url:return TEAM
        raise AssertionError('unexpected '+url)
class MurciaRegistrationTests(unittest.TestCase):
    def test_club_names_do_not_mix_different_age_groups(self):
        players=[dict(id='a',federation='murcia',team='MOLINENSE',team_id='7',group_id='10'),dict(id='b',federation='murcia',team='MOLINENSE',team_id='8',group_id='11')]
        matches=[dict(id='m1',federation='murcia',player_ids=['a'],home='MOLINENSE',away='OTRO',group_id='10',round=1,date='2026-11-21',time='10:00',participation={}),dict(id='m2',federation='murcia',player_ids=['b'],home='MOLINENSE',away='OTRO',group_id='11',round=1,date='2026-11-21',time='12:00',participation={})]
        result=apply_roster(dict(players=players,matches=matches),dict(players=players))
        self.assertEqual([m['player_ids'] for m in result['matches']],[['a'],['b']])
    def test_bye_does_not_invalidate_the_remaining_calendar(self):
        bye='<div class="row"><table><tr><td>Descansa</td><td></td><td>UCAM</td></tr></table><div class="right"></div></div>'
        game='<div class="row"><table><tr><td>UCAM</td><td></td><td>OTRO</td></tr></table><div class="right">CAMPO 22-11-2026 - 16:00</div></div>'
        html='<div class="card-body"><h5 class="card-title">Jornada 1</h5>'+bye+'</div><div class="card-body"><h5 class="card-title">Jornada 2</h5>'+game+'</div>'
        result=parse_murcia_calendar(html,dict(id='p',team_id='7',team='UCAM'),SOURCE)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['round'],2)
        self.assertEqual(result[0]['time'],'16:00')
    def test_current_season_scope_is_discovered_without_taking_historical_group(self):
        result=discover_scope(FakeClient(),BeautifulSoup(TEAM,'html.parser'),SOURCE,'7','2026-2027')
        self.assertEqual((result['team_id'],result['competition_id'],result['group_id'],result['season_id']),('7','10','11','22'))
        self.assertEqual(result['team'],'UCAM')
    def test_ambiguous_or_other_team_scope_does_not_activate(self):
        for history in ('<h4>2026-2027</h4><table>'+row()+row('12','13')+'</table>', '<h4>2026-2027</h4><table>'+row(team='8')+'</table>',HISTORY.replace('2026-2027','2024-2025')):
            with self.assertRaises(ValueError):discover_scope(FakeClient(history),BeautifulSoup(TEAM,'html.parser'),SOURCE,'7','2026-2027')
    def test_external_competition_link_is_rejected_before_fetch(self):
        team=TEAM.replace('href="NFG_VisCompeticiones_Equipo','href="https://evil.test/pnfg/NPcd/NFG_VisCompeticiones_Equipo')
        client=FakeClient()
        with self.assertRaises(ValueError):discover_scope(client,BeautifulSoup(team,'html.parser'),SOURCE,'7','2026-2027')
        self.assertEqual(client.calls,[])
    def test_new_player_checks_calendar_without_downloading_acts(self):
        request=dict(name='Salvador Marin Moya',federation='murcia',collaborator='Iván Macià',source=SOURCE,age_category='juvenil',match_duration=90)
        def calendar(client,player):
            self.assertTrue(player['_calendar_only'])
            return {'matches':[{'id':'game'}]}
        with patch.dict('registry.ADAPTERS',{'murcia':calendar}):
            result=resolve_player(request,{'season':'2026-2027','players':[]},client=FakeClient())
        self.assertEqual(result['official_name'],'MARIN MOYA, SALVADOR')
        self.assertEqual(result['match_duration'],90)
    def test_calendar_only_adapter_does_not_request_match_reports(self):
        client=FakeClient()
        original=client.get
        def get(url):
            if 'NFG_VisCalendario_Vis?' in url:
                from urllib.parse import parse_qs,urlparse
                self.assertEqual(parse_qs(urlparse(url).query)['CodJornada'],['1'])
                return '<calendar/>'
            return original(url)
        client.get=get
        player=dict(id='p',official_name='MARIN MOYA, SALVADOR',source=SOURCE,team_id='7',team='UCAM',competition_id='10',group_id='11',season_id='22',_calendar_only=True)
        games=[{'status':'finished','round':1,'date':'2026-11-01','home':'UCAM','away':'B'}]
        with patch('sync.parse_murcia_calendar',return_value=games),patch('sync.murcia_round',side_effect=AssertionError('No acts during registration')):
            self.assertEqual(murcia(client,player)['matches'],games)
