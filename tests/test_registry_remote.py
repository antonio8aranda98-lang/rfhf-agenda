import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from registry_remote import reconcile, needed
from valencia_data import act_participation


class RemoteRegistryTests(unittest.TestCase):
    def setUp(self):
        self.current={'season':'2026-2027','players':[{'id':'a','name':'Jugador Uno','official_name':'UNO, JUGADOR','collaborator':'Persona Uno','federation':'madrid','active':True}]}
        self.desired={'season':'2026-2027','revision':2,'players':[{'id':'a','name':'Jugador Uno','collaborator':'Persona Dos','federation':'madrid','active':True}]}

    def test_deactivation_and_assignment_use_existing_verified_identity(self):
        updated,status=reconcile(self.current,self.desired)
        self.assertEqual(updated['players'][0]['collaborator'],'Persona Dos');self.assertEqual(updated['players'][0]['official_name'],'UNO, JUGADOR')
        self.desired['players'][0]['active']=False
        updated,status=reconcile(self.current,self.desired)
        self.assertFalse(updated['players'][0]['active']);self.assertEqual(status['players'][0]['state'],'inactive')

    def test_new_player_ignores_browser_identifiers_and_waits_for_federation(self):
        self.desired['players'].append({'id':'new','name':'Jugador Nuevo','federation':'valencia','collaborator':'Persona Dos','source':'https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=1','match_duration':90,'player_id':'untrusted'})
        def resolver(request,current):
            self.assertNotIn('player_id',request)
            raise ValueError('La plantilla no confirma el jugador')
        updated,status=reconcile(self.current,self.desired,resolver=resolver)
        self.assertEqual(len(updated['players']),1);self.assertEqual(status['players'][1]['state'],'pending')
        def success(request,current):return {'id':'resolved','player_id':'verified-id',**request}
        updated,status=reconcile(self.current,self.desired,resolver=success)
        self.assertEqual(updated['players'][1]['id'],'new');self.assertEqual(updated['players'][1]['player_id'],'verified-id')

    def test_reactivation_failure_keeps_player_inactive(self):
        self.current['players'][0]['active']=False
        def reject(*args):raise ValueError('Plantilla no disponible')
        updated,status=reconcile(self.current,self.desired,revalidate=reject)
        self.assertFalse(updated['players'][0]['active']);self.assertEqual(status['players'][0]['state'],'pending')

    def test_empty_remote_portfolio_deactivates_without_erasing_history(self):
        self.desired['players']=[]
        updated,status=reconcile(self.current,self.desired)
        self.assertEqual(len(updated['players']),1);self.assertFalse(updated['players'][0]['active'])

    def test_checks_skip_unchanged_revision_without_pending_players(self):
        self.assertFalse(needed(self.desired,{'revision':2,'players':[{'state':'verified'}]}));self.assertTrue(needed(self.desired,{'revision':1}))


class FFCVParticipationTests(unittest.TestCase):
    def game(self):
        return {'acta_cerrada':'1','codigo_equipo_local':'1','codigo_equipo_visitante':'2','jugadores_equipo_local':[{'codjugador':str(i),'titular':'1','ver_estadisiticas_jugador':'1'} for i in range(1,12)],'sustituciones_equipo_local':[{'codjugador_entra':'12','codjugador_sale':'3','minuto':'67'}],'tarjetas_equipo_local':[{'codjugador':'3','codigo_tipo_amonestacion':'100','minuto':'15'}],'goles_equipo_local':[{'codjugador':'3','tipo_gol':'100'}]}

    def test_full_closed_act_yields_starts_minutes_and_goals(self):
        stats=act_participation(self.game(),{'team_id':'1','player_id':'3','match_duration':90},{'ver_estadisticas':'1','vis_minutos':'1','vis_goles':'1'})
        self.assertEqual((stats['called_up'],stats['starts'],stats['bench'],stats['minutes'],stats['goals']),(1,1,0,67,1))

    def test_hidden_or_open_act_never_turns_into_zero_participation(self):
        player={'team_id':'1','player_id':'3','match_duration':90};game=self.game()
        self.assertIsNone(act_participation(game,player,{'ver_estadisticas':'0'}));game['acta_cerrada']='0';self.assertIsNone(act_participation(game,player,{'ver_estadisticas':'1'}))

    def test_complete_lineup_can_confirm_non_call_up(self):
        stats=act_participation(self.game(),{'team_id':'1','player_id':'99','match_duration':90},{'ver_estadisticas':'1','vis_minutos':'1','vis_goles':'1'})
        self.assertEqual(stats['called_up'],0);self.assertEqual(stats['minutes'],0)


if __name__=='__main__':unittest.main()
