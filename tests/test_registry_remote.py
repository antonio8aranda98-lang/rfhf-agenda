import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from registry_remote import reconcile, needed, calendars_due, RESOLVER_VERSION
from datetime import datetime, timezone
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
        self.assertFalse(needed(self.desired,{'resolver_version':RESOLVER_VERSION,'revision':2,'players':[{'state':'verified'}]}));self.assertTrue(needed(self.desired,{'revision':1}))

    def test_new_resolver_rechecks_unchanged_registry(self):
        self.assertTrue(needed(self.desired,{'revision':2,'players':[{'state':'verified'}]}))

    def test_missing_verified_calendar_resumes_after_the_source_pause(self):
        desired={'players':[{'id':'new','federation':'valencia','active':True}]}
        status={'checked_at':'2026-11-18T17:00:00+00:00','players':[{'id':'new','state':'verified'}]}
        feed={'players':[],'federations':[{'id':'valencia','retry_after':'2026-11-18T18:00:00+00:00'}]}
        before=datetime(2026,11,18,17,30,tzinfo=timezone.utc)
        after=datetime(2026,11,18,18,1,tzinfo=timezone.utc)
        self.assertFalse(calendars_due(desired,status,feed,at=before))
        self.assertTrue(calendars_due(desired,status,feed,at=after))
        self.assertFalse(calendars_due(desired,status,feed,{'source_pauses':{'valencia':'2026-11-18T19:00:00+00:00'}},after))

    def test_missing_calendar_does_not_revalidate_pending_or_already_published_identity(self):
        desired={'players':[{'id':'new','federation':'valencia'}]}
        self.assertFalse(calendars_due(desired,{'players':[{'id':'new','state':'pending'}]},{'players':[]}))
        self.assertFalse(calendars_due(desired,{'players':[{'id':'new','state':'verified'}]},{'players':[{'id':'new','updated_at':'2026-11-18T17:00:00+00:00'}]}))

    def test_official_migration_does_not_reenable_blocked_secondary_source(self):
        self.current['players'][0].update(source_request='https://es.besoccer.com/equipo/cd-alfaro',provider='frf',official_adapter_version=2)
        self.desired['players'][0].update(source='https://es.besoccer.com/equipo/cd-alfaro',besoccer_team_source='https://es.besoccer.com/equipo/cd-alfaro')
        updated,status=reconcile(self.current,self.desired)
        self.assertEqual(status['players'][0]['state'],'verified')
        self.assertNotIn('besoccer_team_source',updated['players'][0])

    def test_identity_correction_revalidates_without_self_and_preserves_id(self):
        self.desired['players'][0].update(name='Jugador Corregido',_identity_revision=3)
        def resolve(request,current):
            self.assertFalse(any(p['id']=='a' for p in current['players']))
            return {**request,'id':'generated','official_name':'CORREGIDO, JUGADOR','active':True}
        updated,status=reconcile(self.current,self.desired,resolver=resolve)
        self.assertEqual(len(updated['players']),1)
        self.assertEqual(updated['players'][0]['id'],'a')
        self.assertEqual(updated['players'][0]['identity_revision'],3)
        self.assertEqual(updated['players'][0]['official_name'],'CORREGIDO, JUGADOR')
        self.assertEqual(status['players'][0]['state'],'verified')

    def test_failed_correction_hides_previous_identity_until_validated(self):
        self.desired['players'][0]['_identity_revision']=3
        def reject(*args):raise ValueError('Identidad pendiente')
        updated,status=reconcile(self.current,self.desired,resolver=reject)
        self.assertFalse(updated['players'][0]['active'])
        self.assertEqual(updated['players'][0]['official_name'],'UNO, JUGADOR')
        self.assertEqual(status['players'][0]['state'],'pending')


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
