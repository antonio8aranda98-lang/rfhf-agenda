import json
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from valencia_data import PublicFFCV, BASE, resolve_ffcv, load_valencia
from registry import name_key
from categories import team_category


class StatefulPublicPortal:
    def __init__(self, wrong_team=False):
        self.selected = None
        self.wrong_team = wrong_team

    def get(self, url, headers=None):
        if url == BASE:
            return '<meta name="ffcv-pt" content="public-page-token">'
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.path.endswith('/ver_equipo.php'):
            self.selected = query['codequipo'][0]
            return json.dumps({'estado': '1', 'codigo_equipo': 'other' if self.wrong_team else self.selected})
        requested = query['cod_equipo'][0]
        if self.selected != requested:
            raise ValueError('El portal requiere seleccionar el equipo')
        return json.dumps({'estado': '1', 'jugadores_equipo': [{'codjugador': requested + '1'}]})


class FFCVSessionTests(unittest.TestCase):
    def test_rosters_follow_the_selected_team_when_switching_clubs(self):
        api = PublicFFCV(StatefulPublicPortal())
        for team in ('14347', '28403', '14347'):
            roster = api.get('equipos/plantilla_home.php', cod_equipo=team)
            self.assertEqual(roster['jugadores_equipo'][0]['codjugador'], team + '1')

    def test_wrong_team_selection_cannot_supply_a_players_identity(self):
        api = PublicFFCV(StatefulPublicPortal(wrong_team=True))
        with self.assertRaisesRegex(ValueError, 'otro equipo'):
            api.get('equipos/plantilla_home.php', cod_equipo='14347')


class SportingAPI:
    def __init__(self, team='17737', player='9809151', name='PEREZ SANCHEZ, CHRISTIAN'):
        self.team, self.player, self.name = team, player, name
        self.requests = []
        self.scopes = [self.scope('league', 'Primera FFCV'), self.scope('cup', 'VI La Nostra Copa')]

    def scope(self, code, name):
        return {'codequipo': self.team, 'nombre_equipo': 'Equipo A', 'codigo_competicion': code,
                'codgrupo': 'group', 'nombre_competicion': name, 'nombre_grupo': 'Grup 1',
                'ver_estadisticas': '1', 'vis_minutos': '1', 'vis_goles': '1'}

    def get(self, route, **params):
        self.requests.append((route, params))
        if route.endswith('plantilla_home.php'):
            return {'jugadores_equipo': [{'nombre': self.name, 'codjugador': self.player}]}
        if route.endswith('ver_equipo.php'):
            return {'codigo_equipo': self.team, 'categoria': 'Primera FFCV'}
        if route.endswith('jugador_api.php'):
            return {'nombre_jugador': self.name, 'nombre_temporada': '2026-2027',
                    'codigo_temporada': '22', 'competiciones_participa': self.scopes}
        if route.endswith('jornadas_fetch.php'):
            return {'jornadas': [{'codjornada': str(i)} for i in range(1, 9)]}
        if route.endswith('resultados_por_grupo_jornada_data.php'):
            return {'partidos': [{'cod_equipo_local': self.team, 'cod_equipo_visitante': 'other',
                                 'codacta': params['cod_jornada'], 'local': 'Equipo A', 'visitante': 'Rival',
                                 'fecha': '01/10/2026', 'hora': '12:00', 'resultado': '1-0'}]}
        raise AssertionError('La comprobación de calendario no debe leer actas: ' + route)


class FFCVIdentityTests(unittest.TestCase):
    def request(self, name, team):
        return {'name': name, 'source': BASE + 'equipos/equipo.php?cod_equipo=' + team}

    def test_league_and_cup_do_not_make_the_clubs_league_ambiguous(self):
        result = resolve_ffcv(SportingAPI(), self.request('Christian Perez Sanchez', '17737'), '2026-2027', name_key)
        self.assertEqual(result['competition_id'], 'league')

    def test_two_matching_leagues_still_require_review(self):
        api = SportingAPI()
        api.scopes.append(api.scope('second-league', 'Primera FFCV'))
        with self.assertRaisesRegex(ValueError, 'única competición'):
            resolve_ffcv(api, self.request('Christian Perez Sanchez', '17737'), '2026-2027', name_key)

    def test_confirmed_alias_requires_the_exact_licence_and_team(self):
        api = SportingAPI('22701', '901434497', 'PEIGENG , LIU')
        result = resolve_ffcv(api, self.request('Blake Liu', '22701'), '2026-2027', name_key)
        self.assertEqual(result['player_id'], '901434497')
        self.assertEqual(result['official_display_name'], 'Liu Peigeng')
        api.player = 'different'
        with self.assertRaisesRegex(ValueError, 'identidad FFCV'):
            resolve_ffcv(api, self.request('Blake Liu', '22701'), '2026-2027', name_key)

    def test_registration_proves_calendar_without_downloading_season_acts(self):
        api = SportingAPI()
        player = {'id': 'p', 'team_id': api.team, 'player_id': api.player, 'official_name': api.name,
                  'competition_id': 'league', 'group_id': 'group', 'season_id': '22',
                  'season': '2026-2027', 'match_duration': 90, '_calendar_only': True}
        with patch('valencia_data.PublicFFCV', return_value=api):
            result = load_valencia(object(), player)
        self.assertEqual({m['round'] for m in result['matches']}, {1, 2, 7, 8})
        self.assertTrue(all(not m['participation'] for m in result['matches']))

    def test_valencian_cadet_label_has_cadete_duration_category(self):
        self.assertEqual(team_category('Lliga Autonòmica Cadet'), 'cadete')


if __name__ == '__main__':
    unittest.main()
