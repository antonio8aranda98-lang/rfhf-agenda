import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from bs4 import BeautifulSoup
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from murcia_registration import discover_scope
from registry import resolve_player
from sync import murcia

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
        client.get=lambda url: '<calendar/>' if 'NFG_VisCalendario_Vis?' in url else original(url)
        player=dict(id='p',official_name='MARIN MOYA, SALVADOR',source=SOURCE,team_id='7',team='UCAM',competition_id='10',group_id='11',season_id='22',_calendar_only=True)
        games=[{'status':'finished','round':1,'date':'2026-11-01','home':'UCAM','away':'B'}]
        with patch('sync.parse_murcia_calendar',return_value=games),patch('sync.murcia_round',side_effect=AssertionError('No acts during registration')):
            self.assertEqual(murcia(client,player)['matches'],games)
