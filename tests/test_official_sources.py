import sys
import unittest
import tempfile
import json
from unittest.mock import patch
from pathlib import Path
from bs4 import BeautifulSoup

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from official_sources import alternative, parse_act, parse_round, parse_calendar, parse_team_calendar, round_url, calendar_url, page, save_initial_snapshot, initial_snapshot, snapshot_path,reviewed_bootstrap,adapter

FIXTURES=Path(__file__).parent/'fixtures'
def html(name):return (FIXTURES/name).read_text()
def config(name='Tiago Arzeno Rosso',slug='ad-sporting-hortaleza-a-juvenil'):
    p=alternative({'name':name,'source':'https://es.besoccer.com/equipo/'+slug},'2026-2027')
    return {**p,'id':'tracked','name':name,'federation':'madrid','season':'2026-2027','match_duration':90}


class OfficialSourcesTests(unittest.TestCase):
    def test_fresh_validation_is_reused_when_player_already_appears_as_opponent(self):
        cached={'matches':[{'player_ids':['tracked']}],'checked_at':'2026-11-18T12:00:00+00:00'}
        with patch('official_sources.initial_snapshot',return_value=cached),patch('official_sources.calendar',side_effect=AssertionError('Do not repeat a verified read')):
            self.assertEqual(adapter(None,config(),previous=[{'player_ids':['tracked']}]),cached)

    def test_reviewed_reading_can_publish_a_verified_profile_when_refresh_fails(self):
        reading={'matches':[{'player_ids':['tracked']}],'source_warning':True}
        with patch('official_sources.initial_snapshot',return_value=None),patch('official_sources.calendar',side_effect=ValueError('Fuente no disponible')),patch('official_sources.reviewed_bootstrap',return_value=reading):
            self.assertEqual(adapter(None,config()),reading)

    def test_verified_snapshot_is_scoped_rekeyed_and_expires(self):
        p=config();game={'player_ids':['tracked'],'participation':{'tracked':{'minutes':22}}}
        with tempfile.TemporaryDirectory() as directory,patch('sync.ROOT',Path(directory)):
            save_initial_snapshot(p,{'matches':[game]})
            result=initial_snapshot({**p,'id':'real-registry-id'})
            self.assertEqual(result['matches'][0]['participation'],{'real-registry-id':{'minutes':22}})
            self.assertEqual(result['matches'][0]['player_ids'],['real-registry-id'])
            self.assertIsNone(initial_snapshot({**p,'team_id':'another-club'}))
            path=snapshot_path(p);data=json.loads(path.read_text());data['saved_at']='2020-01-01T00:00:00+00:00';path.write_text(json.dumps(data))
            self.assertIsNone(initial_snapshot(p))

    def test_reviewed_reading_keeps_source_date_and_rejects_another_team(self):
        from datetime import datetime,timezone
        p=config('Alvaro Contera Gil','cd-azuqueca');stamp=datetime.now(timezone.utc).isoformat()
        result={'matches':[{}]*34,'checked_at':stamp,'source_warning':True}
        entry={'team_id':p['team_id'],'source_request':p['source_request'],'season':p['season'],'verified_at':stamp,'result':result}
        with tempfile.TemporaryDirectory() as directory,patch('sync.ROOT',Path(directory)):
            path=Path(directory)/'data/official-bootstrap.json';path.parent.mkdir();path.write_text(json.dumps({'entries':{p['official_name']:entry}}))
            self.assertEqual(reviewed_bootstrap(p)['checked_at'],stamp)
            self.assertIsNone(reviewed_bootstrap({**p,'team_id':'another-club'}))
            entry['verified_at']='2020-01-01T00:00:00+00:00';path.write_text(json.dumps({'entries':{p['official_name']:entry}}))
            self.assertIsNone(reviewed_bootstrap(p))

    def test_empty_http_can_use_ordinary_browser_and_cache_the_response(self):
        class Client:
            cache={}
            def get(self,url):raise ValueError('La fuente ha devuelto una respuesta vacía')
        client=Client();url=calendar_url('frf')
        with patch('official_sources.browser_page',return_value='<h4>Calendario público</h4>') as browser:
            self.assertIn('Calendario',page(client,url));browser.assert_called_once_with(url)
        self.assertIn(url,client.cache)

    def test_denial_or_challenge_never_triggers_browser_fallback(self):
        class Client:
            def get(self,url):raise ValueError('La fuente solicita una verificación')
        with patch('official_sources.browser_page') as browser:
            with self.assertRaises(ValueError):page(Client(),calendar_url('frf'))
            browser.assert_not_called()

    def test_only_reviewed_full_identity_and_season_get_an_alternative(self):
        self.assertIsNotNone(alternative({'name':'Timoteo Mba Edu Masa','source':'https://es.besoccer.com/equipo/cd-alfaro'},'2026-2027'))
        for request in [{'name':'Otro Jugador','source':'https://es.besoccer.com/equipo/cd-alfaro'}, {'name':'Timoteo Mba Edu Masa','source':'https://es.besoccer.com.evil.test/equipo/cd-alfaro'}, {'name':'Timoteo Mba Edu Masa','source':'https://es.besoccer.com/equipo/cd-alfaro?url=http://localhost'}]:
            self.assertIsNone(alternative(request,'2026-2027'))
        self.assertIsNone(alternative({'name':'Timoteo Mba Edu Masa','source':'https://es.besoccer.com/equipo/cd-alfaro'},'2027-2028'))

    def test_rfef_starter_substitute_and_minutes(self):
        a=html('rfef-acta.html')
        for p,starts,minutes in [(config(),0,22),(config('Brodie David Briceno'),1,80),(config('Sidi Neculae Sinayoko Budaca','trival-valderas-juvenil'),1,68)]:
            s=parse_act(a,p);self.assertEqual((s['called_up'],s['starts'],s['minutes']),(1,starts,minutes))

    def test_territorial_acts_and_goal(self):
        tests=[('frf-alfaro-acta.html',config('Jordi Julia Urchaga','cd-alfaro'),90,0),('frf-calzada-acta.html',config('Javier Rullan Serrano','cdfc-calzada'),8,0),('ffcm-azuqueca-acta.html',config('Alvaro Contera Gil','cd-azuqueca'),90,1)]
        for file,p,minutes,goals in tests:
            s=parse_act(html(file),p);self.assertEqual((s['minutes'],s['goals']),(minutes,goals))

    def test_missing_substitution_section_does_not_invent_full_minutes(self):
        a=html('rfef-acta.html').replace('Sustituciones','Sin información')
        s=parse_act(a,config('Brodie David Briceno'));self.assertEqual(s['starts'],1);self.assertIsNone(s['minutes'])

    def test_incomplete_lineup_is_unknown_instead_of_not_called_up(self):
        s=BeautifulSoup(html('rfef-acta.html'),'html.parser')
        h=next(h for h in s.select('h5') if h.get_text(strip=True)=='Titulares');h.find_next('table').select('tr')[0].decompose()
        with self.assertRaises(ValueError):parse_act(str(s),config('Sidi Neculae Sinayoko Budaca','trival-valderas-juvenil'))

    def test_unknown_card_type_keeps_minutes_unknown(self):
        a=html('rfef-acta.html').replace('tarj_amar.gif','unknown.gif')
        s=parse_act(a,config('Sidi Neculae Sinayoko Budaca','trival-valderas-juvenil'));self.assertIsNone(s['minutes'])

    def test_rfef_round_location_date_ids_and_scoped_teams(self):
        games=parse_round(html('rfef-dh.html'),config(),7,round_url('rfef',7));self.assertEqual(len(games),1)
        m=games[0];self.assertEqual((m['date'],m['time'],m['venue'],m['score_home'],m['score_away']),('2026-10-24','16:00','Polideportivo La Canaleja',1,2))
        self.assertEqual(m['away_team_id'],'rfef-23289693')

    def test_nova_scores_use_displayed_glyphs_not_hidden_decoys(self):
        games=parse_round(html('ffcm-11.html'),config('Alvaro Contera Gil','cd-azuqueca'),11,round_url('ffcm',11))
        self.assertEqual(len(games),1);self.assertEqual((games[0]['score_home'],games[0]['score_away']),(1,0))

    def test_round_date_is_explicit_when_only_basic_calendar_is_available(self):
        games,label=parse_calendar(html('frf-calendar.html'),config('Timoteo Mba Edu Masa','cd-alfaro'),calendar_url('frf',False),False)
        self.assertEqual(len(games),34);self.assertTrue(all(m['date_precision']=='round' and m['time'] is None for m in games))
        self.assertIn('TERCERA',label)

    def test_castilla_mancha_group_calendar_has_real_match_dates(self):
        p=config('Alvaro Contera Gil','cd-azuqueca')
        games,label=parse_team_calendar(html('ffcm-team-calendar.html'),p,'https://www.ffcm.es/')
        self.assertEqual(len(games),34);self.assertEqual((games[0]['date'],games[0]['time']),('2026-09-05','18:00'))
        self.assertIn('LIGA NACIONAL',label)

    def test_extended_rfef_calendar_has_actual_times_and_venues(self):
        games,label=parse_calendar(html('rfef-calendar.html'),config(),calendar_url('rfef'),True)
        self.assertEqual(len(games),30);self.assertEqual(games[0]['date_precision'],'match');self.assertEqual(games[0]['date'],'2026-09-05')
        upcoming=next(m for m in games if m['round']==10);self.assertIsNotNone(upcoming['venue'])

    def test_calendar_rejects_other_season(self):
        with self.assertRaises(ValueError):parse_calendar(html('frf-calendar.html'),{**config('Timoteo Mba Edu Masa','cd-alfaro'),'season':'2027-2028'},calendar_url('frf',False),False)

    def test_castilla_leon_calendar_scopes_isoba(self):
        games,label=parse_calendar(html('rfcylf-calendar.html'),config('Tihago Edu Uribe Faiffer','cd-isoba-juvenil'),calendar_url('rfcylf',False),False)
        self.assertEqual(len(games),30);self.assertIn('Liga Nacional',label)

    def test_two_players_in_same_club_have_same_fixture_ids(self):
        a,_=parse_calendar(html('frf-calendar.html'),config('Timoteo Mba Edu Masa','cd-alfaro'),calendar_url('frf',False),False)
        b,_=parse_calendar(html('frf-calendar.html'),config('Jordi Julia Urchaga','cd-alfaro'),calendar_url('frf',False),False)
        self.assertEqual([m['id'] for m in a],[m['id'] for m in b])


if __name__=='__main__':unittest.main()

class DirectOfficialSourcesTests(unittest.TestCase):
    def test_official_team_url_rejects_extra_queries_credentials_and_duplicates(self):
        from official_sources import source_team
        good='https://www.ffcm.es/pnfg/NPcd/NFG_VisEquipos?cod_primaria=1000119&Codigo_Equipo=33266'
        self.assertEqual(source_team(good),('ffcm','33266'))
        for bad in [good+'&url=http://localhost',good+'&Codigo_Equipo=123',good.replace('https:','http:'),good.replace('www.ffcm.es','user@www.ffcm.es'),good.replace('1000119','1000120')]:
            with self.assertRaises(ValueError):source_team(bad)
        self.assertIsNone(source_team(good.replace('www.ffcm.es','evil.test')))

    def test_direct_discovery_uses_current_team_and_own_competition_in_madrid(self):
        from official_sources import discover_direct,calendar_url,stable_id
        source='https://www.ffcm.es/pnfg/NPcd/NFG_VisEquipos?cod_primaria=1000119&Codigo_Equipo=33266'
        roster='<table><tr><th>Jugadores (1)</th></tr><tr><td>RIOJA PIZARRO, GIANCARLO</td></tr></table><a href="NFG_VisCompeticiones_Equipo?codequipo=33266&amp;codtemporada=22">Competición</a>'
        history='<h4>2026-2027</h4><table><tr><td><a href="NFG_VisCompeticiones_Vis?codcompeticion=22916201">Juvenil Preferente</a></td><td><a href="NFG_VisCompeticiones_Grupo?codequipo=33266&amp;codgrupo=22916203">Ficha</a></td></tr></table><h4>2025-2026</h4><table><tr><td><a href="NFG_VisCompeticiones_Vis?codcompeticion=old">Anterior</a><a href="NFG_VisCompeticiones_Grupo?codequipo=33266&amp;codgrupo=old">Anterior</a></td></tr></table>'
        class Client:
            def get(self,url):
                if 'NFG_VisEquipos?' in url:return roster
                if 'NFG_VisCompeticiones_Equipo?' in url:return history
                if 'NFG_VisCompeticiones_Grupo?' in url:return '<h4>C.D. GUADALAJARA "B"</h4>'
                raise AssertionError(url)
        with patch('official_sources.client_for',return_value=Client()):
            p=discover_direct(None,{'name':'Giancarlo Rioja','source':source},'2026-2027')
            self.assertEqual(p['official_name'],'RIOJA PIZARRO, GIANCARLO')
            self.assertEqual(p['official_group_id'],'22916203')
            p.update(federation='madrid')
            self.assertIn('codgrupo=22916203',calendar_url('ffcm',True,p))
            self.assertIn('madrid-ffcm-22916203',stable_id(p,1,'A','B'))
            with self.assertRaises(ValueError):discover_direct(None,{'name':'Giancarlo Rioja','source':source},'2027-2028')
