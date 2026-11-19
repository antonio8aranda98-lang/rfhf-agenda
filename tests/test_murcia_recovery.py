import copy,json,sys,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from sync import murcia
from murcia_recovery import previous_calendar,report_url,validate_report
from intake_priority import IntakeWatch,IntakeYield

REPORT='https://www.ffrm.es/pnfg/NPcd/NFG_CmpPartido?cod_primaria=1000120&CodActa=42&cod_acta=42'
PLAYER=dict(id='p',federation='murcia',name='Jugador Uno',collaborator='Iván Macià',competition_label='Liga',official_name='UNO, JUGADOR',team='UCAM',team_id='7',competition_id='10',group_id='11',season_id='22',season='2026-2027',match_duration=90,source='https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?Codigo_Equipo=7')
MATCH=dict(id='murcia-7-1',federation='murcia',player_ids=['p'],season='2026-2027',competition_id='10',group_id='11',round=1,date='2026-09-12',time='12:00',status='finished',home='UCAM',away='RIVAL',home_team_id='7',away_team_id='8',score_home=3,score_away=1,source=REPORT,updated_at='2026-11-18T10:00:00+00:00',participation={})
TEAM='<h4>UCAM</h4><table><td>UNO, JUGADOR</td></table>'
def act(season='2026-2027',rnd=1,date='12-09-2026',home='UCAM',away='RIVAL',score='3 - 1'):
    rows='<tr><td>1</td><td>UNO, JUGADOR</td></tr>'+'<tr><td>Otro</td></tr>'*10
    return f'<h5>Temporada {season} Jornada {rnd} {date} 12:00 h</h5><h2 class="ntype"><strong>{score}</strong></h2><div class="details"><div class="number">{home}</div><h5>Titulares</h5><table>{rows}</table><h5>Suplentes</h5><table></table></div><div class="details"><div class="number">{away}</div><h5>Titulares</h5><table>{rows}</table><h5>Suplentes</h5><table></table></div><div class="details"><div class="number">Goles</div><table></table></div>'

class FakeClient:
    def __init__(self,failed='calendar',report=None):self.failed=failed;self.calls=[];self.report=report or act()
    def get(self,url):
        self.calls.append(url)
        if 'NFG_VisEquipos' in url:
            if self.failed=='team':raise ValueError('La fuente ha devuelto una respuesta vacía')
            if self.failed=='identity':return '<td>OTRA PERSONA</td>'
            if self.failed=='forbidden':raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
            return TEAM
        if 'NFG_VisCalendario_Vis' in url:raise ValueError('La fuente ha devuelto una respuesta vacía')
        if 'NFG_CmpPartido' in url:return self.report
        raise AssertionError('Unexpected URL '+url)

class MurciaRecoveryTests(unittest.TestCase):
    def test_calendar_failure_does_not_block_a_known_report_or_replace_calendar_date(self):
        before=copy.deepcopy(MATCH);c=FakeClient()
        with patch('sync.murcia_round',side_effect=AssertionError('No need to reread round index')):
            result=murcia(c,{**PLAYER,'_previous':[before]})
        record=result['matches'][0]['participation']['p']
        self.assertEqual((record['called_up'],record['starts'],record['minutes'],record['goals']),(1,1,90,0))
        self.assertEqual(result['checked_at'],before['updated_at'])
        self.assertIn('source_warning',result)
        self.assertIn('p',result['matches'][0]['participation_checked_at'])
        self.assertEqual(before['participation'],{})
    def test_transient_team_failure_can_still_recover_historical_participation(self):
        c=FakeClient('team');result=murcia(c,{**PLAYER,'_previous':[MATCH]})
        self.assertEqual(result['matches'][0]['participation']['p']['minutes'],90)
        self.assertFalse(any('Calendario' in u for u in c.calls))
    def test_recovery_remains_bounded_to_three_missing_reports(self):
        games=[{**copy.deepcopy(MATCH),'id':'murcia-7-'+str(i),'round':i,'source':REPORT.replace('42',str(i))} for i in range(1,9)]
        c=FakeClient()
        with patch('sync.murcia_round',side_effect=AssertionError('Known reports only')):
            murcia(c,{**PLAYER,'_previous':games})
        self.assertEqual(sum('NFG_CmpPartido' in u for u in c.calls),3)
    def test_initial_registration_cannot_use_a_stale_calendar_as_validation(self):
        with self.assertRaisesRegex(ValueError,'vacía'):
            murcia(FakeClient(),{**PLAYER,'_previous':[MATCH],'_calendar_only':True})
    def test_missing_roster_identity_and_access_denial_do_not_trigger_recovery(self):
        for mode in ['identity','forbidden']:
            with self.subTest(mode=mode),self.assertRaises((ValueError,urllib.error.HTTPError)):
                murcia(FakeClient(mode),{**PLAYER,'_previous':[MATCH]})
    def test_a_source_failure_without_this_player_history_keeps_the_first_load_pending(self):
        with self.assertRaisesRegex(ValueError,'vacía'):murcia(FakeClient(),PLAYER)
    def test_other_teams_seasons_competitions_and_players_cannot_supply_recovery_history(self):
        for changed in [dict(season='2025-2026'),dict(group_id='other'),dict(competition_id='other'),dict(home_team_id='other'),dict(player_ids=['other']),dict(federation='madrid')]:
            with self.subTest(changed=changed):self.assertEqual(previous_calendar({**PLAYER,'_previous':[{**MATCH,**changed}]}),[])
    def test_wrong_report_does_not_turn_into_a_confirmed_absence(self):
        for changed in [dict(season='2025-2026'),dict(rnd=2),dict(date='13-09-2026'),dict(home='OTRO'),dict(score='2 - 1')]:
            with self.subTest(changed=changed),self.assertRaises(ValueError):validate_report(act(**changed),PLAYER,MATCH)
        result=murcia(FakeClient(report=act(home='OTRO')),{**PLAYER,'_previous':[MATCH]})
        self.assertNotIn('p',result['matches'][0]['participation'])
        self.assertIn('source_warning',result)
    def test_a_rejected_report_cannot_replace_the_verified_fixture_link_or_team_ids(self):
        game={**copy.deepcopy(MATCH),'source':'https://www.ffrm.es/pnfg/NPcd/NFG_VisCalendario_Vis'}
        candidate={'url':REPORT,'alternate_url':REPORT,'away_team_id':'wrong'}
        with patch('sync.murcia_round',return_value=candidate):
            result=murcia(FakeClient(report=act(home='OTRO')),{**PLAYER,'_previous':[game]})
        self.assertEqual(result['matches'][0]['source'],game['source'])
        self.assertEqual(result['matches'][0]['away_team_id'],'8')
    def test_only_known_public_official_report_urls_can_skip_the_round_index(self):
        self.assertEqual(report_url(REPORT),REPORT)
        for bad in [REPORT.replace('https:','http:'),REPORT.replace('www.ffrm.es','evil.test'),REPORT+'&url=http://localhost',REPORT+'&CodActa=9',REPORT.replace('cod_acta=42','cod_acta=9'),REPORT.replace('1000120','1000999')]:
            self.assertIsNone(report_url(bad))
    def test_public_score_glyphs_are_verified_without_running_javascript(self):
        mapping=[3,1]+[0]*38
        score='<script>var ntypeMapping='+json.dumps(mapping)+'</script>'
        for i in range(2):
            if i:score+=' - '
            score+=f'<i><i id="score{i}"><script>ntype("score{i}",{i},0,"x");</script><span style="display:none">9</span></i></i>'
        validate_report(act(score=score),PLAYER,MATCH)
    def test_goal_and_referee_panels_are_not_mistaken_for_the_two_teams(self):
        extra='<div class="details"><div class="number">Goles</div><h4>Incidencias</h4></div>'
        validate_report(extra+act(),PLAYER,MATCH)
    def test_recovery_yields_to_owner_changes_without_swallowing_the_signal(self):
        c=FakeClient();original=c.get
        def get(url):
            if 'CmpPartido' in url:raise IntakeYield('new owner revision')
            return original(url)
        c.get=get
        with self.assertRaises(IntakeYield):murcia(c,{**PLAYER,'_previous':[MATCH]})
    def test_shared_execution_deadline_yields_even_when_registry_revision_does_not_change(self):
        clock=[0];watch=IntakeWatch(lambda:{'revision':1},1,clock=lambda:clock[0]);watch()
        clock[0]=1501
        with self.assertRaises(IntakeYield):watch()
    def test_a_directed_murcia_refresh_keeps_other_federations_untouched(self):
        import sync as s
        other={**PLAYER,'id':'other','federation':'madrid','name':'Otro jugador','updated_at':'2026-11-18T10:00:00+00:00','stats':{}}
        old={**PLAYER,'updated_at':'2026-11-18T10:00:00+00:00','stats':{}}
        other_match={**copy.deepcopy(MATCH),'id':'other-match','federation':'madrid','player_ids':['other']}
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data').mkdir();(root/'docs/data').mkdir(parents=True)
            (root/'data/roster.json').write_text(json.dumps({'season':'2026-2027','players':[PLAYER,other]}))
            feed={'players':[old,other],'matches':[copy.deepcopy(MATCH),other_match],'federations':[{'id':'madrid','status':'ok'},{'id':'murcia','status':'partial'}]}
            (root/'docs/data/feed.json').write_text(json.dumps(feed));calls=[]
            def collect(c,secondary,p,previous):
                calls.append(p['id']);return {'matches':[copy.deepcopy(MATCH)],'stats':{}}
            with patch.object(s,'ROOT',root),patch.object(s,'collect_player',side_effect=collect),patch.object(s.Client,'get',return_value=''):
                s.sync(federation='murcia')
            after=json.loads((root/'docs/data/feed.json').read_text())
            self.assertEqual(calls,['p']);self.assertEqual(next(p for p in after['players'] if p['id']=='other')['updated_at'],other['updated_at'])
            self.assertEqual({k:next(m for m in after['matches'] if m['id']=='other-match').get(k) for k in other_match},other_match)
