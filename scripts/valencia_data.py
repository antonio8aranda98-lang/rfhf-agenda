"""FFCV public website JSON, using its ordinary public page token and cookies."""
import json
import re
from urllib.parse import urlencode, urljoin
from bs4 import BeautifulSoup
from player_stats import participation, absent

BASE = 'https://ffcv.es/competiciones/'
FILES = 'https://appwebffcv.novanet.es/'


class PublicFFCV:
    def __init__(self, client):
        self.client = client
        html = client.get(BASE)
        node = BeautifulSoup(html, 'html.parser').select_one('meta[name="ffcv-pt"]')
        if not node or not node.get('content'):
            raise ValueError('La web FFCV no devuelve su token público de página')
        self.token = node['content']

    def get(self, route, **params):
        # Same header injected by the public site's fetch wrapper. No login,
        # private credentials, CAPTCHA handling or browser fingerprint changes.
        url = BASE + 'api/' + route + '?' + urlencode(params)
        data = json.loads(self.client.get(url, headers={'X-FFCV-Page-Token': self.token}))
        if not isinstance(data, dict) or str(data.get('estado', '1')) == '0':
            raise ValueError('FFCV no ha devuelto una respuesta deportiva válida')
        return data


def act_participation(game, player, visibility):
    if str(game.get('acta_cerrada')) != '1':
        return None
    side = 'local' if str(game.get('codigo_equipo_local')) == player['team_id'] else 'visitante'
    if str(game.get('codigo_equipo_' + side)) != player['team_id']:
        raise ValueError('Acta de otro equipo')
    rows = game.get('jugadores_equipo_' + side, [])
    if len(rows) < 7:
        return None
    row = next((r for r in rows if str(r.get('codjugador')) == player['player_id']), None)
    if not row:
        return absent()
    if str(row.get('ver_estadisiticas_jugador')) != '1' or str(visibility.get('ver_estadisticas')) != '1':
        return None
    subs = game.get('sustituciones_equipo_' + side, [])
    entries = [s.get('minuto') for s in subs if str(s.get('codjugador_entra')) == player['player_id']]
    exits = [s.get('minuto') for s in subs if str(s.get('codjugador_sale')) == player['player_id']]
    reds = [c.get('minuto') for c in game.get('tarjetas_equipo_' + side, []) if str(c.get('codjugador')) == player['player_id'] and (str(c.get('codigo_tipo_amonestacion')) == '101' or str(c.get('segunda_amarilla')) == '1')]
    goals = None
    if str(visibility.get('vis_goles')) == '1':
        own = [g for g in game.get('goles_equipo_' + side, []) if str(g.get('codjugador')) == player['player_id']]
        goals = len(own) if all(str(g.get('tipo_gol')) == '100' for g in own) else None
    result = participation(str(row.get('titular')) == '1', player['match_duration'], entries, exits, reds, goals)
    if str(visibility.get('vis_minutos')) != '1':
        result['minutes'] = None
    return result


def resolve_ffcv(api, request, season, name_key):
    from registry import official_url, unique_name
    from urllib.parse import parse_qs
    team_id = parse_qs(official_url(request['source'], 'valencia').query).get('cod_equipo', [''])[0]
    if not team_id.isdigit():
        raise ValueError('Falta el código del equipo en el enlace FFCV')
    roster = api.get('equipos/plantilla_home.php', cod_equipo=team_id)
    members = roster.get('jugadores_equipo', [])
    def member_name(p):
        return p.get('nombre_jugador') or p.get('nombre') or ''
    official_name = unique_name([member_name(p) for p in members], request['name'])
    member = next(p for p in members if member_name(p) == official_name)
    player_id = str(member.get('cod_jugador') or member.get('codjugador') or member.get('codigo_jugador') or '')
    if not player_id.isdigit():
        raise ValueError('No se identifica el código federativo del jugador')
    data = api.get('jugadores/jugador_api.php', codigo=player_id)
    scopes = [c for c in data.get('competiciones_participa', []) if str(c.get('codequipo')) == team_id]
    if data.get('nombre_temporada') != season or len(scopes) != 1:
        raise ValueError('No se verifica una única competición del equipo en esta temporada')
    c = scopes[0]
    return {'team_id': team_id, 'team': c['nombre_equipo'], 'player_id': player_id, 'official_name': official_name,
            'competition_id': str(c['codigo_competicion']), 'group_id': str(c['codgrupo']), 'season_id': str(data['codigo_temporada']),
            'competition_label': c['nombre_competicion'] + ' · ' + c['nombre_grupo'], 'source': request['source']}


def load_valencia(client, player):
    from sync import fixture, integer, iso_date, http_time, normalized, new_stats
    api = PublicFFCV(client)
    roster = api.get('equipos/plantilla_home.php', cod_equipo=player['team_id'])
    if not any(str(p.get('cod_jugador') or p.get('codjugador') or p.get('codigo_jugador')) == player['player_id'] for p in roster.get('jugadores_equipo', [])):
        raise ValueError('El jugador ya no figura en la plantilla configurada')
    pdata = api.get('jugadores/jugador_api.php', codigo=player['player_id'], cod_temporada=player['season_id'])
    if normalized(pdata.get('nombre_jugador')) != normalized(player['official_name']):
        raise ValueError('La ficha individual no coincide con el jugador configurado')
    scope = next((c for c in pdata.get('competiciones_participa', []) if str(c.get('codigo_competicion')) == player['competition_id'] and str(c.get('codgrupo')) == player['group_id'] and str(c.get('codequipo')) == player['team_id']), None)
    if not scope:
        raise ValueError('No se verifica el equipo dentro de la competición y grupo configurados')
    rounds = api.get('filtros/jornadas_fetch.php', cod_grupo=player['group_id']).get('jornadas', [])
    if not rounds:
        raise ValueError('Calendario FFCV sin jornadas verificables')
    matches = []
    for rnd in rounds:
        data = api.get('partidos/resultados_por_grupo_jornada_data.php', cod_temporada=player['season_id'], cod_competicion=player['competition_id'], cod_grupo=player['group_id'], cod_jornada=rnd['codjornada'])
        for m in data.get('partidos', []):
            if player['team_id'] not in (str(m.get('cod_equipo_local')), str(m.get('cod_equipo_visitante'))):
                continue
            score = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', str(m.get('resultado', '')))
            finished = bool(score and str(m.get('resultado_provisional', '0')) == '0')
            hour = http_time(m.get('hora'))
            reason = str(m.get('motivo_estado') or '').lower()
            status = 'finished' if finished else 'postponed' if 'aplaz' in reason or str(m.get('estado')) == '3' else 'cancelled' if 'suspend' in reason else 'scheduled' if hour else 'time_pending'
            match = fixture('valencia', player, m['codacta'], m['local'], m['visitante'], iso_date(m.get('fecha')), hour,
                BASE + 'partidos/partido.php?cod_partido=' + str(m['codacta']), round=integer(rnd['codjornada']), status=status,
                home_team_id=str(m['cod_equipo_local']), away_team_id=str(m['cod_equipo_visitante']), venue=m.get('campo') or None,
                home_logo=urljoin(FILES, m.get('escudo_local') or ''), away_logo=urljoin(FILES, m.get('escudo_visitante') or ''),
                score_home=int(score[1]) if finished else None, score_away=int(score[2]) if finished else None)
            if finished:
                try:
                    game = api.get('partidos/ficha_partido_ajax.php', cod_partido=m['codacta'])
                    stats = act_participation(game, player, scope)
                    if stats is not None:
                        match['participation'][player['id']] = stats
                except Exception:
                    pass
            matches.append(match)
    if len(matches) < len(rounds) - 3:
        raise ValueError('El calendario FFCV está incompleto; se conserva el último válido')
    return {'matches': matches, 'stats': new_stats(), 'logo': urljoin(FILES, scope.get('escudo_equipo') or ''),
            'stats_note': 'Estadísticas calculadas con las actas de este equipo y competición. No se mezclan otras participaciones del jugador en equipos A/B. Minutos reglamentarios sin añadido.'}
