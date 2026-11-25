import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from additional_teams import resolve, collect
from registry_remote import reconcile
from intake_priority import fingerprint

SOURCE='https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=2'
PLAYER=dict(id='p',name='Jugador Uno',official_name='UNO, JUGADOR',federation='valencia',team_id='1',player_id='3',season_id='22',source='https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=1',age_category='juvenil',collaborator='Persona Uno')


class API:
    def get(self,route,**params):
        if 'jugador_api' in route:return dict(nombre_temporada='2026-2027',nombre_jugador='UNO, JUGADOR',competiciones_participa=[dict(codequipo='2',nombre_equipo='CLUB A',codigo_competicion='10',codgrupo='11',nombre_competicion='Lliga Comunitat Juvenil',nombre_grupo='Nord')])
        return dict(codigo_equipo=params['codequipo'],codigo_club='4')


class AdditionalTeamsTests(unittest.TestCase):
    def test_evidence_recompute_preserves_incomplete_secondary_calendar(self):
        from improve_data import recompute
        player={**PLAYER,'additional_teams':[dict(team_id='2',group_id='11',calendar_complete=False)]}
        game=dict(id='m',player_ids=['p'],home_team_id='2',away_team_id='9',group_id='11',status='finished',participation={})
        result=recompute(dict(players=[player],matches=[game]))
        secondary=result['players'][0]['additional_teams'][0]
        self.assertFalse(secondary['coverage']['calendar_complete'])
        self.assertIsNone(secondary['stats']['team_played'])
    def test_ffcv_second_team_uses_individual_competition_without_second_registration(self):
        with patch('valencia_data.PublicFFCV',return_value=API()):
            extra=resolve(None,PLAYER,[SOURCE],'2026-2027')
        self.assertEqual(extra[0]['team_id'],'2');self.assertEqual(extra[0]['group_id'],'11')
        self.assertEqual(PLAYER['team_id'],'1');self.assertEqual(extra[0]['match_duration'],90)

    def test_wrong_club_or_absent_participation_cannot_attach_a_team(self):
        class Wrong(API):
            def get(self,route,**params):
                d=super().get(route,**params)
                if params.get('codequipo')=='2':d['codigo_club']='9'
                return d
        with patch('valencia_data.PublicFFCV',return_value=Wrong()):
            with self.assertRaises(ValueError):resolve(None,PLAYER,[SOURCE],'2026-2027')
        with patch('valencia_data.PublicFFCV',return_value=API()):
            with self.assertRaises(ValueError):resolve(None,PLAYER,[SOURCE.replace('=2','=9')],'2026-2027')

    def test_failed_second_calendar_retains_only_its_own_previous_fixtures(self):
        scope=dict(team_id='2',group_id='11',team_source=SOURCE)
        previous=[dict(id='old-extra',home_team_id='2',away_team_id='9',group_id='11'),dict(id='old-main',home_team_id='1',away_team_id='8',group_id='12')]
        player={**PLAYER,'additional_teams':[scope],'_previous':previous}
        def fail(client,p):
            self.assertTrue(p['_additional_scope']);self.assertEqual(p['source'],SOURCE)
            raise ValueError('Unavailable')
        result=collect(None,player,dict(matches=[dict(id='new-main')]),fail)
        self.assertEqual([m['id'] for m in result['matches']],['new-main','old-extra'])
        self.assertEqual(result['additional_teams'][0]['calendar_status'],'pending')

    def test_secondary_scope_save_is_prioritized_without_replacing_identity(self):
        current=dict(season='2026-2027',players=[copy.deepcopy(PLAYER)])
        desired=dict(season='2026-2027',revision=3,players=[{**PLAYER,'additional_team_sources':[SOURCE]}])
        self.assertNotEqual(fingerprint(PLAYER),fingerprint(desired['players'][0]))
        with patch('additional_teams.resolve',return_value=[dict(team_id='2')]) as extra:
            updated,status=reconcile(current,desired,resolver=lambda *a: self.fail('Primary re-resolution'))
        self.assertEqual(extra.call_count,1);self.assertEqual(updated['players'][0]['team_id'],'1')
        self.assertEqual(updated['players'][0]['additional_teams'][0]['team_id'],'2')
        self.assertEqual(status['players'][0]['state'],'verified')

    def test_removing_secondary_scope_does_not_query_source(self):
        current=dict(season='2026-2027',players=[{**PLAYER,'additional_team_sources':[SOURCE],'additional_teams':[dict(team_id='2')]}])
        desired=dict(season='2026-2027',revision=4,players=[copy.deepcopy(PLAYER)])
        updated,status=reconcile(current,desired)
        self.assertEqual(updated['players'][0]['additional_teams'],[])

