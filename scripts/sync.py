#!/usr/bin/env python3
"""Public federation adapters. Only allowlisted sporting fields leave the process."""
import argparse
import copy
import http.cookiejar
import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
MADRID = ZoneInfo('Europe/Madrid')
FEDERATIONS = {
    'madrid': ('Madrid', 'RFFM', 'https://www.rffm.es/'),
    'catalunya': ('Cataluña', 'FCF', 'https://www.fcf.cat/'),
    'murcia': ('Murcia', 'FFRM', 'https://www.ffrm.es/pnfg/'),
    'valencia': ('Comunitat Valenciana', 'FFCV', 'https://ffcv.es/competiciones/'),
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def normalized(value):
    return re.sub(r'[^A-Z0-9]+', ' ', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().upper()).strip()


def integer(value):
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return None


def iso_date(value):
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%d/%m/%y', '%d.%m.%Y'):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def http_time(value):
    m = re.fullmatch(r'(\d{1,2}):(\d{2})(?::\d{2})?', str(value or '').strip())
    if not m or int(m[1]) > 23 or int(m[2]) > 59:
        return None
    return f'{int(m[1]):02}:{m[2]}'


def new_stats():
    return {k: None for k in ('played', 'starts', 'minutes', 'goals', 'assists', 'yellow', 'red')}


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.addheaders = [('User-Agent', 'RFHF-Agenda/1.0 (public football fixtures; github.com/antonio8aranda98-lang/rfhf-agenda)'), ('Accept', 'text/html,application/json')]
        self.last_request = 0
        self.cache = {}

    def get(self, url):
        if url in self.cache:
            return self.cache[url]
        time.sleep(max(0, .45 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(url, headers={'Referer': self.base})
        with self.opener.open(request, timeout=35) as response:
            if '/NLogin' in response.url or ('ffcv.es/wp/' in response.url and '/competiciones/' in url):
                raise ValueError('La fuente redirige fuera de la consulta deportiva pública')
            raw = response.read(8_000_000)
            charset = response.headers.get_content_charset()
            if not charset:
                match = re.search(br'charset\s*=\s*["\x27]?([a-zA-Z0-9-]+)', raw[:4000])
                charset = match[1].decode() if match else 'utf-8'
            try:
                content = raw.decode(charset)
            except (UnicodeDecodeError, LookupError):
                content = raw.decode('iso-8859-1')
            self.cache[url] = content
            return content

    def next_props(self, url):
        soup = BeautifulSoup(self.get(url), 'html.parser')
        node = soup.find('script', id='__NEXT_DATA__')
        if not node:
            raise ValueError('El formato de la fuente ha cambiado: faltan datos deportivos')
        return json.loads(node.string)['props']['pageProps']


def initial_data(html):
    """Read JSON from Next Flight scripts without executing remote JavaScript."""
    soup = BeautifulSoup(html, 'html.parser')
    for script in soup.find_all('script'):
        text = script.get_text()
        if 'self.__next_f.push(' not in text:
            continue
        try:
            record = json.loads(text[text.index('(') + 1:text.rindex(')')])
        except (ValueError, IndexError):
            continue
        if len(record) < 2 or not isinstance(record[1], str):
            continue
        for line in record[1].splitlines():
            if 'initialData' not in line or ':' not in line:
                continue
            try:
                obj = json.loads(line.split(':', 1)[1])
                if isinstance(obj, list) and len(obj) > 3 and isinstance(obj[3], dict):
                    data = obj[3].get('initialData')
                    if data:
                        return data
            except (ValueError, KeyError, TypeError):
                pass
    raise ValueError('La fuente no ha publicado los datos esperados del equipo')


def fixture(fid, player, key, home, away, date, hour, source, **extra):
    return {'id': f'{fid}-{key}', 'federation': fid, 'player_ids': [player['id']],
            'home': home.strip(), 'away': away.strip(), 'date': date, 'time': hour,
            'status': 'scheduled' if hour else 'time_pending', 'source': source,
            'venue': None, 'locality': None, 'address': None, 'latitude': None, 'longitude': None,
            'home_logo': None, 'away_logo': None, 'score_home': None, 'score_away': None,
            'round': None, 'participation': {}, **extra}


def madrid(client, player):
    base = FEDERATIONS['madrid'][2]
    team = client.next_props(base + 'fichaequipo/' + player['team_id'])['team']
    if not any(str(p['cod_jugador']) == player['player_id'] for p in team.get('jugadores_equipo', [])):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    url = base + 'competicion/calendario?' + urllib.parse.urlencode({'competicion': player['competition_id'], 'grupo': player['group_id'], 'temporada': player['season_id'], 'tipojuego': 1})
    cal = client.next_props(url)['calendar']
    matches = []
    host = str(team.get('host', 'https://www.rffm.es/'))
    if not host.startswith('https://'):
        host = base
    logo = urllib.parse.urljoin(host, team.get('escudo_club', ''))
    summary = new_stats()
    pdata = client.next_props(player['source'])['player']
    competition = next((c for c in pdata.get('competiciones_participa', []) if str(c.get('codigo_competicion')) == player['competition_id']), {})
    visible = competition.get('ver_estadisticas') == '1'
    if visible:
        mapping = {'Jugados': 'played', 'Titular': 'starts', 'Total Goles': 'goals'}
        for item in pdata.get('partidos', []):
            if item.get('nombre') in mapping:
                if item.get('nombre') == 'Total Goles' and competition.get('vis_goles') != '1':
                    continue
                summary[mapping[item['nombre']]] = integer(item.get('valor'))
        if competition.get('vis_minutos') == '1':
            summary['minutes'] = integer(pdata.get('minutos_totales_jugados'))
        for card in pdata.get('tarjetas', []):
            key = {'Amarillas': 'yellow', 'Rojas': 'red'}.get(card.get('nombre'))
            if key:
                summary[key] = integer(card.get('valor'))
    today = datetime.now(MADRID).date().isoformat()
    for rnd in cal.get('rounds', []):
        for m in rnd.get('equipos', []):
            if player['team_id'] not in (str(m.get('codigo_equipo_local')), str(m.get('codigo_equipo_visitante'))):
                continue
            sh, sa = integer(m.get('goles_casa')), integer(m.get('goles_visitante'))
            date = iso_date(m.get('fecha'))
            match = fixture('madrid', player, m['codacta'], m['equipo_local'], m['equipo_visitante'], date,
                            http_time(m.get('hora')), base + 'acta-partido/' + m['codacta'],
                            round=integer(rnd.get('codjornada')), venue=m.get('campo') or None,
                            home_logo=urllib.parse.urljoin(host, m.get('escudo_equipo_local', '')),
                            away_logo=urllib.parse.urljoin(host, m.get('escudo_equipo_visitante', '')),
                            score_home=sh, score_away=sa)
            if sh is not None and sa is not None:
                match['status'] = 'finished'
            if date and today <= date and m.get('codigo_campo'):
                try:
                    field = client.next_props(base + 'campo/' + m['codigo_campo'])['field']
                    for dest, src in [('address', 'direccion'), ('locality', 'localidad'), ('latitude', 'latitud'), ('longitude', 'longitud')]:
                        match[dest] = field.get(src) or None
                except Exception:
                    pass  # Keep fixture even if optional location enrichment is unavailable.
            matches.append(match)
    # Only closed acts yield individual participation; bench is never assumed played.
    completed = sorted([m for m in matches if m['status'] == 'finished'], key=lambda m: m['date'] or '', reverse=True)
    for m in completed:
        try:
            game = client.next_props(m['source'])['game']
            side = 'local' if str(game['codigo_equipo_local']) == player['team_id'] else 'visitante'
            rows = game.get('jugadores_equipo_' + side, [])
            row = next((r for r in rows if str(r.get('codjugador')) == player['player_id']), None)
            if not row or game.get('acta_cerrada') != '1' or row.get('ver_estadisiticas_jugador') != '1':
                continue
            starter = row.get('titular') == '1'
            subs = game.get('sustituciones_equipo_' + side, [])
            entry = next((integer(s.get('minuto')) for s in subs if str(s.get('codjugador_entra')) == player['player_id']), None)
            departure = next((integer(s.get('minuto')) for s in subs if str(s.get('codjugador_sale')) == player['player_id']), None)
            played = starter or entry is not None
            stats = new_stats()
            stats.update({'played': int(played), 'starts': int(starter)})
            # Require both competition visibility switches before publishing derived data.
            if competition.get('vis_goles') == '1':
                target_goals = [g for g in game.get('goles_equipo_' + side, []) if str(g.get('codjugador')) == player['player_id']]
                # Type 100 was verified as a regular goal. Do not guess other enum values.
                stats['goals'] = len(target_goals) if all(str(g.get('tipo_gol')) == '100' for g in target_goals) else None
            # Red cards and stoppage-time notation make naive minute inference unsafe.
            cards = [c for c in game.get('tarjetas_equipo_' + side, []) if str(c.get('codjugador')) == player['player_id']]
            if competition.get('vis_minutos') == '1' and not cards and played:
                stats['minutes'] = max(0, min(player['match_duration'], departure if departure is not None else player['match_duration']) - (0 if starter else entry))
            elif not played and competition.get('vis_minutos') == '1':
                stats['minutes'] = 0
            m['participation'][player['id']] = stats
        except Exception:
            continue
    return {'matches': matches, 'stats': summary, 'logo': logo, 'stats_note': 'Resumen publicado por la federación. Minutos por partido calculados solo cuando el acta permite hacerlo con seguridad.'}


def catalunya(client, player):
    data = initial_data(client.get(player['source']))
    wanted = normalized(player['name'])
    if not any(normalized(p.get('NOMBRE')) == wanted for p in data.get('players', [])):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    escudos = 'https://files.fcf.cat/escudos/clubes/escudos/'
    matches = []
    for m in data.get('matches', []):
        start = str(m.get('COMIENZO1') or '').split(' ')
        date = iso_date(start[0])
        hour = http_time(start[1]) if len(start) > 1 else None
        closed = str(m.get('CERRADA')) == '1'
        matches.append(fixture('catalunya', player, m['CODACTA'], m['NOMBRE_CASA'], m['NOMBRE_FUERA'], date, hour,
            'https://www.fcf.cat/ca/competicio/acta/' + str(m['CODACTA']),
            status='finished' if closed else ('scheduled' if hour else 'time_pending'),
            venue=m.get('CAMPO') or None, latitude=m.get('LATITUD') or None, longitude=m.get('LONGITUD') or None,
            home_logo=escudos + m['ESCUDO_CASA'] if m.get('ESCUDO_CASA') else None,
            away_logo=escudos + m['ESCUDO_FUERA'] if m.get('ESCUDO_FUERA') else None,
            score_home=integer(m.get('GOLES_CASA')) if closed else None, score_away=integer(m.get('GOLES_FUERA')) if closed else None,
            round=integer(m.get('JORNADA'))))
    return {'matches': matches, 'stats': new_stats(), 'logo': escudos + data['info']['FICHERO'],
            'stats_note': 'Calendario y resultados del equipo disponibles. Estadísticas individuales pendientes de validar en las actas; aparecer en el banquillo no implica haber jugado.'}


def parse_murcia(html, player, source):
    soup = BeautifulSoup(html, 'html.parser')
    matches = []
    for row in soup.find_all('tr'):
        cells = row.find_all('td', recursive=False)
        if len(cells) != 3:
            continue
        rnd = integer(cells[0].get_text(strip=True))
        lines = [h.get_text(' ', strip=True) for h in cells[1].find_all('h5')]
        if rnd is None or len(lines) != 3:
            continue
        dt = re.search(r'(\d{2}-\d{2}-\d{4})(?:\s+(\d{1,2}:\d{2}))?', lines[2])
        if not dt:
            continue
        score = re.search(r'(\d+)\s*-\s*(\d+)', cells[2].get_text(' ', strip=True))
        hour = http_time(dt[2])
        matches.append(fixture('murcia', player, player['team_id'] + '-' + str(rnd), lines[0], lines[1], iso_date(dt[1]), hour, source,
            round=rnd, status='finished' if score else ('scheduled' if hour else 'time_pending'),
            score_home=int(score[1]) if score else None, score_away=int(score[2]) if score else None))
    if not matches:
        raise ValueError('La fuente no devuelve filas válidas del calendario')
    return matches


def murcia(client, player):
    team = BeautifulSoup(client.get(player['source']), 'html.parser')
    if normalized(player['official_name']) not in normalized(team.get_text(' ', strip=True)):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    url = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisCompeticiones_Grupo?' + urllib.parse.urlencode({'cod_primaria': '1000123', 'codequipo': player['team_id'], 'codgrupo': player['group_id']})
    matches = parse_murcia(client.get(url), player, url)
    image = team.select_one('img[src*="/Clubes/"]')
    logo = urllib.parse.urljoin(player['source'], image['src']) if image else None
    if logo:
        for match in matches:
            if normalized(match['home']) == normalized(player['team']):
                match['home_logo'] = logo
            if normalized(match['away']) == normalized(player['team']):
                match['away_logo'] = logo
    return {'matches': matches, 'stats': new_stats(), 'logo': logo,
            'stats_note': 'Resultados del equipo disponibles. La fecha sin hora es la referencia de jornada. Estadísticas individuales y campo pendientes de validar en las actas.'}


def valencia(client, player):
    path = ROOT / '.cache' / 'valencia.json'
    if not path.exists():
        raise ValueError('Pendiente de consulta con navegador público')
    data = json.loads(path.read_text())
    # A failed/new run may not re-stamp an old browser snapshot as fresh.
    checked = datetime.fromisoformat(data['checked_at'])
    if (datetime.now(timezone.utc) - checked).total_seconds() > 1800:
        raise ValueError('La captura del navegador tiene más de 30 minutos')
    result = data.get('players', {}).get(player['id'])
    if not result or result.get('error'):
        raise ValueError((result or {}).get('error', 'El navegador no devolvió el jugador'))
    return result


ADAPTERS = {'madrid': madrid, 'catalunya': catalunya, 'murcia': murcia, 'valencia': valencia}


def sync(browser=False):
    roster = json.loads((ROOT / 'data/roster.json').read_text())
    path = ROOT / 'docs/data/feed.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    if browser:
        run = subprocess.run(['node', 'scripts/valencia.mjs'], cwd=ROOT, timeout=360, check=False)
        if run.returncode:
            print('::warning::Valencia: consulta de navegador incompleta; se conservarán datos anteriores')
    feed = {'schema_version': 1, 'generated_at': now(), 'season': roster['season'], 'federations': [], 'players': [], 'matches': []}
    old_matches = previous.get('matches', [])
    total_success = 0
    for fid, (label, acronym, base) in FEDERATIONS.items():
        client = Client(base)
        # Normal public landing establishes the same public session as website navigation.
        try:
            if fid != 'valencia':
                client.get(base)
        except Exception:
            pass
        old_fed = next((f for f in previous.get('federations', []) if f['id'] == fid), {})
        errors = []
        successes = 0
        for config in [p for p in roster['players'] if p['federation'] == fid]:
            old_player = next((p for p in previous.get('players', []) if p['id'] == config['id']), {})
            public = {k: config[k] for k in ('id', 'name', 'federation', 'collaborator', 'team', 'competition_label', 'source')}
            try:
                result = ADAPTERS[fid](client, config)
                if not result['matches']:
                    raise ValueError('Calendario vacío inesperado; se conservan los datos anteriores')
                public.update({k: result.get(k) for k in ('stats', 'logo', 'stats_note')})
                public['updated_at'] = now()
                for m in result['matches']:
                    m['updated_at'] = public['updated_at']
                    feed['matches'].append(m)
                successes += 1
                total_success += 1
                print(fid + ': ' + str(len(result['matches'])) + ' partidos verificados')
            except Exception as error:
                message = f'{type(error).__name__}: {str(error)[:180]}'
                print('::warning::' + fid + ': ' + message)
                errors.append(config['id'])
                public.update({k: old_player.get(k) for k in ('stats', 'logo', 'stats_note', 'updated_at')})
                public['stats'] = public.get('stats') or new_stats()
                feed['matches'].extend(copy.deepcopy(m) for m in old_matches if config['id'] in m['player_ids'])
            feed['players'].append(public)
        feed['federations'].append({'id': fid, 'label': label, 'acronym': acronym, 'source': base,
            'status': 'ok' if successes and not errors else 'partial' if successes else 'error',
            'checked_at': now(), 'last_success': now() if successes and not errors else old_fed.get('last_success'),
            'message': 'Consulta automática completada' if successes and not errors else 'No se pudo completar la consulta. Se conserva el último dato válido.', 'failed_players': errors})
    # Merge shared fixtures so two assigned players in the same match are one visit.
    merged = {}
    for m in feed['matches']:
        if m['id'] in merged:
            old = merged[m['id']]
            old['player_ids'] = sorted(set(old['player_ids'] + m['player_ids']))
            old['participation'].update(m['participation'])
        else:
            merged[m['id']] = m
    feed['matches'] = sorted(merged.values(), key=lambda m: (m['date'] or '9999', m['time'] or '99:99', m['id']))
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)
    print(f'Actualizadas {total_success}/{len(roster["players"])} fichas; {len(feed["matches"])} partidos publicados.')
    if not total_success:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true', help='Recoger Valencia con Chromium estándar')
    args = parser.parse_args()
    sync(args.browser)
