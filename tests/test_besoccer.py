import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from besoccer_data import BASE, url, parse_roster, parse_profile, parse_calendar, parse_lineup, enrich_official, PublicBeSoccer
from registry import resolve_player
from registry_remote import reconcile
from sync import apply_roster, PublicRedirect, retain_participation

TEAM = BASE + '/equipo/equipo-juvenil'
PLAYER = BASE + '/jugador/j-ejemplo-123'
MATCH = BASE + '/partido/equipo-juvenil/rival-juvenil/2027123'


def roster_html():
    team = json.dumps({'@type':'SportsTeam','name':'Equipo Juvenil','image':'https://cdn.resfu.com/img_data/equipos/11.png'})
    return f'''<script type="application/ld+json">{team}</script><select id="season"><option selected value="2027">2026-27</option></select>
    <select id="competition"><option selected value="156">División de Honor</option></select>
    <table><tr class="row-body"><td class="name"><a href="{PLAYER}">J. Ejemplo</a></td></tr></table>'''


def profile_html():
    return '''<div class="panel-subtitle">Jugador Ejemplo Uno</div><table class="table_parents">
    <tr class="parent_row"><td><img src="https://cdn.resfu.com/img_data/escudos/medium/11.jpg"></td><td>2026/27</td></tr>
    <tr class="parent_son"><td><a onclick="setCookie('clickedTrajectoryComp',156,1);setCookie('clickedTrajectoryYear',2027,1)">División de Honor</a></td>
    <td data-content-tab="tprc1">8</td><td data-content-tab="tprc1">2</td><td data-content-tab="tprc1">0</td><td data-content-tab="tprc1">1</td><td data-content-tab="tprc1">0</td>
    <td data-content-tab="tptc1">8</td><td data-content-tab="tptc1">7</td><td data-content-tab="tptc1">1</td><td data-content-tab="tptc1">654'</td></tr></table>'''


def card(source=MATCH, stamp='2026-11-21T16:00:00Z', hour=True, finished=False, comp='División de Honor'):
    marker='<span class="r1">0</span>-<span class="r2">1</span>' if finished else '<p class="match_hour time">16:00</p>' if hour else ''
    return f'''<a class="match-link" href="{source}" starttime="{stamp}"><div class="middle-info">{comp}. Jornada 9</div>
    <div class="match-status-label">{'FIN' if finished else ''}</div><div class="team-name"><div class="name">Equipo Juvenil</div></div>
    <div class="team-name"><div class="name">Rival Juvenil</div></div>{marker}</a>'''


def player():
    return {'id':'one','name':'Jugador Ejemplo Uno','official_name':'Jugador Ejemplo Uno','federation':'madrid','season':'2026-2027',
        'match_duration':90,'besoccer_team_source':TEAM,'besoccer_team_slug':'equipo-juvenil','besoccer_player_source':PLAYER,
        'besoccer_competition_label':'División de Honor','team':'Equipo Juvenil','team_id':'official-11'}


def lineup(target=True, bench=False, events='', starters=11):
    nodes=''.join(f'<a class="local" data-cy="starterPlayer" href="{PLAYER if target and not bench and i==0 else BASE+"/jugador/otro-"+str(i)}"><div class="info-wrapper">{events if target and not bench and i==0 else ""}</div></a>' for i in range(starters))
    if target and bench:
        nodes+=f'<a class="local" data-cy="benchPlayer" href="{PLAYER}"><div class="info-wrapper">{events}</div></a>'
    return f'<link rel="canonical" href="{MATCH}/alineaciones">'+nodes


class BeSoccerTests(unittest.TestCase):
    def test_allowlisted_resource_urls_and_redirects(self):
        self.assertEqual(url(BASE+'/equipo/plantilla/equipo-juvenil'),TEAM)
        for value in ['http://es.besoccer.com/equipo/a','https://es.besoccer.com.evil.test/equipo/a','https://user@es.besoccer.com/equipo/a',TEAM+'?season=2020',TEAM+'#x','https://es.besoccer.com:999/equipo/a','https://es.besoccer.com/noticias/a']:
            with self.assertRaises(ValueError):url(value)
        from urllib.request import Request
        with self.assertRaises(ValueError):PublicRedirect().redirect_request(Request(TEAM),None,302,'',{},'https://elsewhere.test/private')

    def test_scoped_profile_does_not_treat_played_substitute_as_bench(self):
        team=parse_roster(roster_html(),TEAM,'2026-2027')
        result=parse_profile(profile_html(),'Jugador Ejemplo Uno',team,'2026-2027')
        self.assertEqual(result['stats'],{'played':8,'starts':7,'minutes':654,'goals':2})
        self.assertNotIn('called_up',result['stats']);self.assertNotIn('bench',result['stats'])
        with self.assertRaises(ValueError):parse_profile(profile_html(),'Otro Jugador',team,'2026-2027')
        with self.assertRaises(ValueError):parse_roster(roster_html().replace('2027','2026'),TEAM,'2026-2027')
        with self.assertRaises(ValueError):parse_profile(profile_html().replace('2026/27','2025/26'),'Jugador Ejemplo Uno',team,'2026-2027')

    def test_calendar_fixes_timezone_and_rejects_other_seasons_competitions_and_teams(self):
        html=card()+card(source=MATCH.replace('2027123','2026123'))+card(comp='Otra Liga')+card(source=MATCH.replace('equipo-juvenil','otro-equipo'))
        games=parse_calendar(html,player());self.assertEqual(len(games),1)
        self.assertEqual(games[0]['time'],'17:00')
        self.assertEqual(games[0]['date'],'2026-11-21')
        self.assertIsNone(parse_calendar(card(hour=False),player())[0]['time'])
        game=parse_calendar(card(finished=True),player())[0]
        self.assertEqual((game['score_home'],game['score_away'],game['status']),(0,1,'finished'))

    def test_unused_substitute_is_called_up_without_playing_and_absence_stays_unknown(self):
        m=parse_calendar(card(finished=True),player())[0]
        s=parse_lineup(lineup(bench=True),player(),m)
        self.assertEqual((s['called_up'],s['starts'],s['bench'],s['minutes']),(1,0,1,0))
        self.assertIsNone(parse_lineup(lineup(target=False),player(),m))
        self.assertIsNone(parse_lineup(lineup(starters=9),player(),m))

    def test_substitutions_red_cards_and_own_goals(self):
        m=parse_calendar(card(finished=True),player())[0]
        events='<div><img alt="Entra"><p class="min">65\'</p></div><div><img alt="Gol en propia puerta"><p class="min">+1</p></div>'
        s=parse_lineup(lineup(bench=True,events=events),player(),m)
        self.assertEqual((s['minutes'],s['goals']),(25,0))
        events='<div><img alt="Tarjeta roja"><p class="min">74\'</p></div><div><img alt="Gol"><p class="min">+2</p></div>'
        s=parse_lineup(lineup(events=events),player(),m)
        self.assertEqual((s['minutes'],s['goals']),(74,2))
        with self.assertRaises(ValueError):parse_lineup(lineup().replace('2027123','2027999'),player(),m)

    def test_enrichment_keeps_official_values_and_requires_same_opponent_date_round_score(self):
        m=parse_calendar(card(finished=True),player())[0]
        official=copy.deepcopy(m);official['source']='https://www.rffm.es/acta-partido/42'
        official['participation']={'one':{'starts':1,'minutes':None,'goals':2}}
        extra=copy.deepcopy(m);extra['participation']={'one':{'starts':1,'minutes':74,'goals':1}}
        result=enrich_official({'matches':[official]},{'matches':[extra]},player())
        self.assertEqual(result['matches'][0]['participation']['one']['minutes'],74)
        self.assertEqual(result['matches'][0]['participation']['one']['goals'],2)
        extra['score_away']=2
        result=enrich_official({'matches':[official]},{'matches':[extra]},player())
        self.assertIsNone(result['matches'][0]['participation']['one']['minutes'])

    def test_primary_besoccer_resolver_generates_namespaced_ids_and_ignores_browser_ids(self):
        linked={**{k:v for k,v in player().items() if k.startswith('besoccer_')},'besoccer_team_id':'11','besoccer_team':'Equipo Juvenil','official_name':'Jugador Ejemplo Uno'}
        request={'name':'Jugador Ejemplo Uno','federation':'madrid','collaborator':'Persona Uno','match_duration':90,'source':TEAM,'player_id':'untrusted'}
        with patch('registry.resolve_besoccer',return_value=linked):
            result=resolve_player(request,{'season':'2026-2027','players':[]})
        self.assertEqual(result['provider'],'besoccer');self.assertEqual(result['player_id'],'besoccer-123')

    def test_registry_passes_supplementary_links_for_new_players(self):
        request={'id':'new','name':'Jugador Ejemplo Uno','federation':'madrid','collaborator':'Persona Uno','match_duration':90,'source':TEAM,'besoccer_player_source':PLAYER}
        def resolver(r,current):
            self.assertEqual(r['besoccer_player_source'],PLAYER)
            return {**r,'official_name':r['name']}
        updated,status=reconcile({'season':'2026-2027','players':[]},{'season':'2026-2027','revision':1,'players':[request]},resolver)
        self.assertEqual(status['players'][0]['state'],'verified')

    def test_cross_collaborator_matchup_uses_verified_besoccer_ids_and_removes_inactive(self):
        m=parse_calendar(card(finished=True),player())[0]
        m.update(home_besoccer_team_id='11',away_besoccer_team_id='12')
        roster={'players':[{**player(),'besoccer_team_id':'11'}, {'id':'two','federation':'madrid','team':'Rival','besoccer_team_id':'12','collaborator':'Persona Dos'}]}
        result=apply_roster({'players':[{'id':'one'},{'id':'two'}],'matches':[m]},roster)
        self.assertTrue(result['matches'][0]['is_internal_matchup'])
        roster['players'][1]['active']=False
        result=apply_roster(result,roster)
        self.assertFalse(result['matches'][0]['is_internal_matchup'])

    def test_temporary_secondary_failure_preserves_known_minutes_with_original_date(self):
        m=parse_calendar(card(finished=True),player())[0]
        previous=copy.deepcopy(m)
        previous['participation']={'one':{'called_up':1,'starts':1,'bench':0,'minutes':74}}
        previous['participation_checked_at']={'one':'2026-11-17'}
        previous['participation_source']={'one':MATCH+'/alineaciones'}
        m['participation']={'one':{'called_up':1,'starts':1,'bench':0,'minutes':None}}
        retain_participation(m,previous,'one')
        self.assertEqual(m['participation']['one']['minutes'],74)
        self.assertEqual(m['participation_checked_at']['one'],'2026-11-17')
        m['participation']['one']['minutes']=None
        retain_participation(m,previous,'one',allow_secondary=False)
        self.assertIsNone(m['participation']['one']['minutes'])
        m['participation']['one']['starts']=0
        retain_participation(m,previous,'one')
        self.assertIsNone(m['participation']['one']['minutes'])


if __name__=='__main__':unittest.main()
