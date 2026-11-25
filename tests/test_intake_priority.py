import copy,json,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from intake_priority import plan,fingerprint,IntakeWatch,IntakeYield
from registry_remote import reconcile
from player_stats import summarize

AT=datetime(2026,11,18,20,tzinfo=timezone.utc)
def entry(id,fed='madrid'):
    return dict(id=id,name='Jugador '+id,federation=fed,collaborator='Antonio',source='https://www.rffm.es/fichaequipo/1',active=True)

class IntakePlanTests(unittest.TestCase):
    def test_secondary_team_change_of_a_legacy_verified_row_is_prioritized(self):
        p={**entry('one','valencia'),'additional_team_sources':['https://ffcv.es/competiciones/equipos/equipo.php?cod_equipo=2'],'_verification_revision':25}
        other=entry('untouched')
        for revision in (23,27):
            result=plan({'revision':27,'players':[p,other]},{'revision':revision,'players':[{'id':'one','state':'verified'},{'id':'untouched','state':'verified'}]}, {'players':[{'id':'one','updated_at':'today'},{'id':'untouched','updated_at':'today'}]},at=AT)
            self.assertEqual(result['resolve_ids'],['one'])
        row={'id':'one','state':'verified','control_fingerprint':fingerprint(p)}
        self.assertEqual(plan({'revision':27,'players':[p]},{'revision':27,'players':[row]},{'players':[{'id':'one','updated_at':'today'}]},at=AT)['resolve_ids'],[])
    def test_new_registration_precedes_a_large_old_pending_backlog(self):
        old=[entry(str(i)) for i in range(50)]
        status={'revision':1,'checked_at':(AT-timedelta(hours=1)).isoformat(),'players':[{'id':p['id'],'state':'pending'} for p in old]}
        desired={'revision':2,'players':old+[entry('new')]}
        result=plan(desired,status,{'players':[]},at=AT)
        self.assertEqual(result,dict(mode='priority',resolve_ids=['new'],calendar_ids=['new']))
    def test_assignment_revision_does_not_trigger_old_network_retries(self):
        desired={'revision':2,'players':[entry('old')]}
        result=plan(desired,{'revision':1,'players':[{'id':'old','state':'pending'}]},{'players':[]},at=AT)
        self.assertEqual(result['mode'],'controls');self.assertEqual(result['resolve_ids'],[])
    def test_corrected_source_is_prioritized_even_when_revision_already_recorded(self):
        p=entry('one');before=fingerprint(p);p['source']='https://www.rffm.es/fichaequipo/2'
        result=plan({'revision':3,'players':[p]},{'revision':3,'players':[{'id':'one','state':'pending','control_fingerprint':before}]},{'players':[]},at=AT)
        self.assertEqual(result['resolve_ids'],['one'])
    def test_backfill_is_bounded_and_calendar_failures_rotate(self):
        entries=[entry(str(i)) for i in range(8)]
        rows=[{'id':str(i),'state':'pending' if i<4 else 'verified','checked_at':(AT-timedelta(hours=1)).isoformat(),'calendar_attempted_at':(AT-timedelta(minutes=i)).isoformat()} for i in range(8)]
        result=plan({'revision':1,'players':entries},{'revision':1,'players':rows},{'players':[]},at=AT)
        self.assertEqual(len(result['resolve_ids']),2);self.assertEqual(len(result['calendar_ids']),3)
        self.assertEqual(result['calendar_ids'][-1],'7')
    def test_pause_of_one_federation_does_not_delay_another_new_registration(self):
        desired={'revision':2,'players':[entry('v','valencia'),entry('m')]}
        feed={'players':[],'federations':[{'id':'valencia','retry_after':(AT+timedelta(hours=1)).isoformat()}]}
        result=plan(desired,{'revision':1,'players':[]},feed,at=AT)
        self.assertEqual(result['resolve_ids'],['m'])
    def test_new_verified_profile_keeps_priority_until_its_first_calendar(self):
        desired={'revision':2,'players':[entry('one')]}
        status={'revision':2,'players':[{'id':'one','state':'verified','priority_calendar':True}]}
        self.assertEqual(plan(desired,status,{'players':[]},at=AT)['mode'],'priority')
        self.assertEqual(plan(desired,status,{'players':[{'id':'one','updated_at':'today'}]},at=AT)['calendar_ids'],[])

class PriorityReconcileTests(unittest.TestCase):
    def test_deferred_sporting_change_keeps_old_calendar_but_waits_for_verification(self):
        p={**entry('one'),'official_name':'ONE'};d={**entry('one'),'_verification_revision':2}
        updated,status=reconcile({'season':'2026-2027','players':[p]},{'season':'2026-2027','revision':2,'players':[d]},selected_ids=set(),previous_status={'revision':1,'players':[{'id':'one','state':'verified'}]})
        self.assertTrue(updated['players'][0]['active']);self.assertEqual(status['players'][0]['state'],'pending');self.assertTrue(status['players'][0]['waiting_priority'])
    def test_deferred_failed_enrichment_keeps_its_retry_status(self):
        p={**entry('old'),'official_name':'Jugador old'}
        previous={'revision':1,'players':[{'id':'old','state':'pending','message':'Fuente no disponible'}]}
        updated,status=reconcile({'season':'2026-2027','players':[p]}, {'season':'2026-2027','revision':2,'players':[entry('old')]},selected_ids=set(),previous_status=previous)
        self.assertTrue(updated['players'][0]['active'])
        self.assertEqual(status['players'][0]['state'],'pending')
        self.assertEqual(status['players'][0]['message'],'Fuente no disponible')
    def test_reactivation_checks_calendar_without_waiting_for_historical_reports(self):
        p={**entry('one'),'official_name':'Jugador one','active':False}
        with patch('sync.collect_player',return_value={'matches':[{'id':'game'}]}) as collect:
            updated,status=reconcile({'season':'2026-2027','players':[p]}, {'season':'2026-2027','revision':2,'players':[entry('one')]},selected_ids={'one'})
        self.assertTrue(updated['players'][0]['active'])
        self.assertTrue(collect.call_args.args[2]['_calendar_only'])
        self.assertTrue(collect.call_args.args[2]['_intake'])
    def test_old_pending_identity_is_not_requested_during_a_new_registration(self):
        current={'season':'2026-2027','players':[]};desired={'season':'2026-2027','revision':2,'players':[entry('old'),entry('new')]};calls=[]
        previous={'revision':1,'checked_at':AT.isoformat(),'players':[{'id':'old','state':'pending','message':'Nombre por revisar'}]}
        def resolver(request,roster):calls.append(request['name']);return {**request,'official_name':request['name']}
        updated,status=reconcile(current,desired,resolver=resolver,selected_ids={'new'},previous_status=previous)
        self.assertEqual(calls,['Jugador new']);self.assertEqual([p['id'] for p in updated['players']],['new'])
        self.assertEqual(next(p for p in status['players'] if p['id']=='old')['message'],'Nombre por revisar')
    def test_deferred_correction_cannot_republish_old_identity(self):
        p={**entry('one'),'official_name':'OLD'};d={**entry('one'),'_identity_revision':2,'name':'Corregido'}
        updated,status=reconcile({'season':'2026-2027','players':[p]},{'season':'2026-2027','revision':2,'players':[d]},selected_ids=set(),previous_status={'revision':1,'players':[{'id':'one','state':'verified'}]})
        self.assertFalse(updated['players'][0]['active']);self.assertTrue(status['players'][0]['waiting_priority'])
    def test_newer_change_checkpoints_the_registry_without_losing_prior_validation(self):
        calls=[]
        def resolver(request,roster):
            calls.append(request['name'])
            if len(calls)==2:raise IntakeYield('new owner revision')
            return {**request,'official_name':request['name']}
        entries=[entry('a'),entry('b'),entry('c')]
        updated,status=reconcile({'season':'2026-2027','players':[]},{'season':'2026-2027','revision':2,'players':entries},resolver=resolver,selected_ids={'a','b','c'})
        self.assertEqual(calls,['Jugador a','Jugador b']);self.assertEqual([p['id'] for p in updated['players']],['a'])
        self.assertEqual(next(p for p in status['players'] if p['id']=='b')['state'],'pending')

class WatchTests(unittest.TestCase):
    def test_new_owner_revision_yields_between_requests_and_is_not_swallowed_as_source_error(self):
        clock=[0];values=iter([{'revision':1},{'revision':2}]);calls=[]
        def fetch():calls.append(True);return next(values)
        watch=IntakeWatch(fetch,1,clock=lambda:clock[0]);watch();clock[0]=10;watch();self.assertEqual(len(calls),1)
        clock[0]=31
        with self.assertRaises(IntakeYield):
            try:watch()
            except Exception:self.fail('A source error handler swallowed the priority signal')
    def test_registry_outage_does_not_throw_away_sporting_progress(self):
        watch=IntakeWatch(lambda:(_ for _ in ()).throw(OSError('offline')),1)
        watch();self.assertFalse(watch.yielded)

class SyncIntakeTests(unittest.TestCase):
    def run_sync(self,collector,intake=False):
        import sync as s
        players=[{**entry(id), 'team':'Team '+id,'team_id':id,'competition_label':'Liga'} for id in ['a','b','c']]
        matches=[dict(id='m'+p['id'],federation='madrid',player_ids=[p['id']],home=p['team'],away='Rival',home_team_id=p['id'],away_team_id='rival',date='2026-11-22',time='12:00',status='scheduled',participation={}) for p in players]
        feed={'season':'2026-2027','players':[{**p,'updated_at':'2026-11-17T10:00:00+00:00','stats':{}} for p in players],'matches':matches,'federations':[{'id':'madrid','status':'ok'}]}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            (root/'data/roster.json').write_text(json.dumps({'season':'2026-2027','players':players}));(root/'docs/data/feed.json').write_text(json.dumps(feed))
            (root/'docs/data/registry-status.json').write_text(json.dumps({'intake_ids':['b'],'players':[{'id':p['id'],'state':'verified'} for p in players]}))
            with patch.object(s,'ROOT',root),patch.object(s,'FEDERATIONS',{'madrid':s.FEDERATIONS['madrid']}),patch.object(s.Client,'get',return_value=''),patch.object(s,'collect_player',side_effect=lambda c,second,p,prev:collector(p,copy.deepcopy(matches))):s.sync(intake=intake)
            return json.loads((root/'docs/data/feed.json').read_text())
    def test_intake_requests_only_the_selected_calendar_without_reports(self):
        calls=[]
        def collector(p,matches):
            calls.append(p['id']);self.assertTrue(p['_calendar_only']);self.assertTrue(p['_intake'])
            return {'matches':[matches[1]],'stats':{}}
        result=self.run_sync(collector,intake=True)
        self.assertEqual(calls,['b']);self.assertEqual(len(result['players']),3)
    def test_background_yield_keeps_completed_work_and_untouched_players(self):
        calls=[]
        def collector(p,matches):
            calls.append(p['id'])
            if p['id']=='b':raise IntakeYield('new arrival')
            return {'matches':[matches[0]],'stats':{},'checked_at':'2026-11-18T20:00:00+00:00'}
        result=self.run_sync(collector)
        self.assertEqual(calls,['a','b']);self.assertEqual(len(result['matches']),3);self.assertEqual(len(result['players']),3)
        self.assertEqual(next(p for p in result['players'] if p['id']=='a')['updated_at'],'2026-11-18T20:00:00+00:00')
        self.assertEqual(next(p for p in result['players'] if p['id']=='c')['updated_at'],'2026-11-17T10:00:00+00:00')
    def test_partial_calendar_does_not_invent_season_totals(self):
        stats,coverage=summarize([{'status':'finished','participation':{'p':{'called_up':1,'starts':1,'bench':0,'minutes':90,'goals':1}}}],'p',calendar_complete=False)
        self.assertIsNone(stats['team_played']);self.assertIsNone(stats['minutes']);self.assertEqual(coverage['confirmed']['minutes'],90)

class ValenciaFastCalendarTests(unittest.TestCase):
    def test_first_load_requests_three_nearest_rounds_without_any_match_reports(self):
        from datetime import datetime,timedelta
        from valencia_data import load_valencia
        from sync import MADRID
        today=datetime.now(MADRID).date()
        class API:
            calls=[]
            def get(self,route,**params):
                self.calls.append((route,params))
                if route=='equipos/plantilla_home.php':return {'jugadores_equipo':[{'codjugador':'3'}]}
                if route=='jugadores/jugador_api.php':return {'nombre_jugador':'JUGADOR','competiciones_participa':[{'codequipo':'1','codigo_competicion':'10','codgrupo':'11'}]}
                if route=='filtros/jornadas_fetch.php':return {'jornadas':[{'codjornada':str(i),'fecha_jornada':(today+timedelta(days=(i-5)*7)).strftime('%d-%m-%Y')} for i in range(1,10)]}
                if route=='partidos/resultados_por_grupo_jornada_data.php':return {'partidos':[{'cod_equipo_local':'1','cod_equipo_visitante':'2','codacta':params['cod_jornada'],'local':'A','visitante':'B','fecha':today.isoformat(),'hora':'12:00','resultado':''}]}
                raise AssertionError('No reports during first publication: '+route)
        api=API();p=dict(id='p',team_id='1',player_id='3',official_name='JUGADOR',competition_id='10',group_id='11',season_id='22',_calendar_only=True,_intake=True)
        with patch('valencia_data.PublicFFCV',return_value=api):result=load_valencia(None,p)
        requests=[params['cod_jornada'] for route,params in api.calls if route=='partidos/resultados_por_grupo_jornada_data.php']
        self.assertEqual(requests,['5','6','4']);self.assertFalse(result['calendar_complete']);self.assertEqual(len(result['matches']),3)
