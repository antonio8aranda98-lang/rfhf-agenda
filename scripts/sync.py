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
from player_stats import participation, absent, summarize, STAT_FIELDS
from federation_acts import murcia_round, parse_murcia_act, parse_catalunya_act, parse_murcia_calendar

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
    return {k: None for k in (*STAT_FIELDS, 'played', 'assists', 'yellow', 'red')}


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(req.full_url).hostname == 'es.besoccer.com':
            u = urllib.parse.urlparse(newurl)
            if u.scheme != 'https' or u.hostname != 'es.besoccer.com' or u.username or u.password or u.port not in (None,443):
                raise ValueError('BeSoccer ha redirigido fuera de la fuente pública autorizada')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(PublicRedirect(), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.opener.addheaders = [('User-Agent', 'RFHF-Agenda/1.0 (public football fixtures; github.com/antonio8aranda98-lang/rfhf-agenda)'), ('Accept', 'text/html,application/json')]
        self.last_request = 0
        self.cache = {}
        self.empty_cooldown_used = False

    def get(self, url, headers=None):
        if url in self.cache:
            return self.cache[url]
        # The legacy Murcia portal sometimes returns empty HTTP 200 responses.
        # Keep a conservative request rate and pause once before giving up.
        interval = 8 if 'ffrm.es' in self.base else 2 if 'besoccer.com' in self.base else .65
        time.sleep(max(0, interval - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(url, headers={'Referer': self.base, **(headers or {})})
        with self.opener.open(request, timeout=35) as response:
            if '/NLogin' in response.url or ('ffcv.es/wp/' in response.url and '/competiciones/' in url):
                raise ValueError('La fuente redirige fuera de la consulta deportiva pública')
            raw = response.read(8_000_000)
            if not raw:
                if 'ffrm.es' in self.base and not self.empty_cooldown_used:
                    self.empty_cooldown_used = True
                    time.sleep(55)
                    return self.get(url, headers)
                raise ValueError('La fuente ha devuelto una respuesta vacía; no se guarda como calendario válido')
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
            'round': None, 'competition_id': player.get('competition_id'), 'group_id': player.get('group_id'),
            'season': player.get('season'), 'participation': {}, **extra}


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
        mapping = {'Convocados': 'called_up', 'Jugados': 'played', 'Titular': 'starts', 'Suplente': 'bench', 'Total Goles': 'goals'}
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
                            score_home=sh, score_away=sa, home_team_id=str(m['codigo_equipo_local']), away_team_id=str(m['codigo_equipo_visitante']))
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
            if game.get('acta_cerrada') != '1' or len(rows) < 7:
                continue
            if not row:
                m['participation'][player['id']] = absent()
                continue
            if row.get('ver_estadisiticas_jugador') != '1':
                continue
            starter = row.get('titular') == '1'
            subs = game.get('sustituciones_equipo_' + side, [])
            entries = [s.get('minuto') for s in subs if str(s.get('codjugador_entra')) == player['player_id']]
            exits = [s.get('minuto') for s in subs if str(s.get('codjugador_sale')) == player['player_id']]
            goals = None
            # Require both competition visibility switches before publishing derived data.
            if competition.get('vis_goles') == '1':
                target_goals = [g for g in game.get('goles_equipo_' + side, []) if str(g.get('codjugador')) == player['player_id']]
                # Type 100 was verified as a regular goal. Do not guess other enum values.
                goals = len(target_goals) if all(str(g.get('tipo_gol')) == '100' for g in target_goals) else None
            cards = [c for c in game.get('tarjetas_equipo_' + side, []) if str(c.get('codjugador')) == player['player_id']]
            reds = [c.get('minuto') for c in cards if str(c.get('codigo_tipo_amonestacion')) == '101' or str(c.get('segunda_amarilla')) == '1']
            stats = participation(starter, player['match_duration'], entries, exits, reds, goals)
            if competition.get('vis_minutos') != '1':
                stats['minutes'] = None
            m['participation'][player['id']] = stats
        except Exception:
            continue
    return {'matches': matches, 'stats': summary, 'logo': logo, 'stats_note': 'Convocado = titular o suplente en el acta. Los minutos calculados usan tiempo reglamentario, sin añadido.'}


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
            round=integer(m.get('JORNADA')), home_team_id=str(m['CODEQUIPO_CASA']), away_team_id=str(m['CODEQUIPO_FUERA'])))
        if closed:
            slug = lambda text: re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()).strip('-')
            path = f"ca/partit/{player.get('season', '2026-2027')}/{slug(m['NOMBRE_COMPETICION'])}/{slug(m['GRUPO'])}/jornada-{m['JORNADA']}/{m['SLUG_CASA']}-vs-{m['SLUG_FUERA']}"
            try:
                html = client.get('https://www.fcf.cat/' + path)
                matches[-1]['participation'][player['id']] = parse_catalunya_act(html, player)
                matches[-1]['source'] = 'https://www.fcf.cat/' + path
            except Exception:
                pass
    return {'matches': matches, 'stats': new_stats(), 'logo': escudos + data['info']['FICHERO'],
            'stats_note': 'Convocatorias, titulares, suplentes y goles según actas. Los minutos quedan sin dato cuando la FCF no publica intervalos de sustitución verificables.'}


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
    team_url = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?' + urllib.parse.urlencode({'Codigo_Equipo':player['team_id'], 'cod_primaria':'3001860'})
    team = BeautifulSoup(client.get(team_url), 'html.parser')
    if normalized(player['official_name']) not in normalized(team.get_text(' ', strip=True)):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    url = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisCalendario_Vis?' + urllib.parse.urlencode({'cod_primaria':'1000120','codcompeticion':player['competition_id'],'codgrupo':player['group_id'],'codtemporada':player['season_id'],'CDetalle':'1'})
    matches = parse_murcia_calendar(client.get(url), player, url)
    image = team.select_one('img[src*="/Clubes/"]')
    logo = urllib.parse.urljoin(player['source'], image['src']) if image else None
    if logo:
        for match in matches:
            if normalized(match['home']) == normalized(player['team']):
                match['home_logo'] = logo
            if normalized(match['away']) == normalized(player['team']):
                match['away_logo'] = logo
    today = datetime.now(MADRID).date().isoformat()
    for match in matches:
        if match['status'] != 'finished' and (not match.get('date') or abs((datetime.fromisoformat(match['date']).date() - datetime.now(MADRID).date()).days) > 7):
            continue
        try:
            report = murcia_round(client, player, match['round'])
            match.update({k: v for k, v in report.items() if k not in ('url','alternate_url') and v})
            match['source'] = report['url']
            try:
                html = client.get(report['url'])
            except ValueError as error:
                if 'respuesta vacía' not in str(error) or report['alternate_url']==report['url']:
                    raise
                html = client.get(report['alternate_url'])
                match['source'] = report['alternate_url']
            if match['status'] == 'finished':
                match['participation'][player['id']] = parse_murcia_act(html, player)
            soup = BeautifulSoup(html, 'html.parser')
            field = soup.find(string=re.compile(r'^\s*Estadio:'))
            if field:
                container = field.parent.parent if field.parent.name == 'strong' else field.parent
                venue = container.get_text(' ', strip=True).removeprefix('Estadio:').strip()
                if venue and len(venue) <= 250:
                    match['venue'] = venue
            city = soup.find(string=re.compile(r'^\s*Ciudad:'))
            if city:
                container = city.parent.parent if city.parent.name == 'strong' else city.parent
                locality = container.get_text(' ', strip=True).removeprefix('Ciudad:').strip()
                if locality and len(locality) <= 100:
                    match['locality'] = locality
        except Exception as error:
            print('::warning::Murcia acta J' + str(match['round']) + ': ' + type(error).__name__ + ': ' + str(error)[:160])
    return {'matches': matches, 'stats': new_stats(), 'logo': logo,
            'stats_note': 'Convocatorias y participación según actas. Minutos calculados con la duración reglamentaria de la categoría, sin añadido.'}


def valencia(client, player):
    from valencia_data import load_valencia
    return load_valencia(client, player)


ADAPTERS = {'madrid': madrid, 'catalunya': catalunya, 'murcia': murcia, 'valencia': valencia}


def collect_player(client, secondary_client, player, previous=()):
    from besoccer_data import PublicBeSoccer, adapter, enrich_official
    api = PublicBeSoccer(secondary_client)
    if player.get('provider') == 'besoccer':
        return adapter(api, player, previous)
    result = ADAPTERS[player['federation']](client, player)
    if player.get('besoccer_team_source'):
        try:
            secondary = adapter(api, player)
            result = enrich_official(result, secondary, player)
            result['secondary_stats'] = {'provider':'besoccer', 'source':player['besoccer_player_source'],
                'team':player['besoccer_team'], 'competition':player['besoccer_competition_label'],
                'season':player['season'], 'stats':secondary['stats'], 'checked_at':now()}
        except Exception:
            result['secondary_warning'] = 'BeSoccer no está disponible o no confirma la plantilla; se conservan los datos de la federación.'
    return result


def sync(browser=False):
    roster = json.loads((ROOT / 'data/roster.json').read_text())
    path = ROOT / 'docs/data/feed.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    if browser:
        run = subprocess.run(['node', 'scripts/valencia.mjs'], cwd=ROOT, timeout=360, check=False)
        if run.returncode:
            print('::warning::Valencia: consulta de navegador incompleta; se conservarán datos anteriores')
    feed = {'schema_version': 1, 'generated_at': now(), 'season': roster['season'], 'registry_revision': roster.get('registry_revision', 0), 'federations': [], 'players': [], 'matches': []}
    old_matches = previous.get('matches', [])
    total_success = 0
    secondary_client = Client('https://es.besoccer.com')
    for fid, (label, acronym, base) in FEDERATIONS.items():
        client = Client(base)
        # Normal public landing establishes the same public session as website navigation.
        try:
            if fid not in ('valencia', 'murcia'):
                client.get(base)
        except Exception:
            pass
        old_fed = next((f for f in previous.get('federations', []) if f['id'] == fid), {})
        errors = []
        successes = 0
        configs = [p for p in roster['players'] if p['federation'] == fid and p.get('active', True)]
        for config in configs:
            config = {**config, 'season': roster['season']}
            old_player = next((p for p in previous.get('players', []) if p['id'] == config['id']), {})
            public = {k: config[k] for k in ('id', 'name', 'federation', 'collaborator', 'team', 'competition_label', 'source')}
            public['provider'] = config.get('provider', 'federation')
            public.update({k:config[k] for k in ('besoccer_team_source','besoccer_player_source') if config.get(k)})
            try:
                result = collect_player(client, secondary_client, config, old_matches)
                if not result['matches']:
                    raise ValueError('Calendario vacío inesperado; se conservan los datos anteriores')
                public.update({k: result.get(k) for k in ('stats', 'logo', 'stats_note')})
                public.update({k:result[k] for k in ('secondary_stats','secondary_warning') if k in result})
                public['updated_at'] = now()
                for m in result['matches']:
                    checked = m.setdefault('participation_checked_at', {})
                    for player_id in m.get('participation', {}):
                        checked.setdefault(player_id, public['updated_at'])
                    previous_match = next((old for old in old_matches if old['id'] == m['id']), None)
                    # A temporary act failure must not erase a previously verified
                    # record. Retain its original date, only for an unchanged result.
                    if previous_match and m['status'] == previous_match['status'] == 'finished' and (m['score_home'], m['score_away']) == (previous_match['score_home'], previous_match['score_away']):
                        old_record = previous_match.get('participation', {}).get(config['id'])
                        if config['id'] not in m['participation'] and old_record is not None:
                            m['participation'][config['id']] = copy.deepcopy(old_record)
                            checked[config['id']] = previous_match.get('participation_checked_at', {}).get(config['id'], previous_match.get('updated_at'))
                            previous_source = previous_match.get('participation_source', {}).get(config['id'])
                            if previous_source: m.setdefault('participation_source', {})[config['id']] = previous_source
                    m['updated_at'] = public['updated_at']
                    feed['matches'].append(m)
                successes += 1
                total_success += 1
                print(fid + ': ' + str(len(result['matches'])) + ' partidos verificados')
            except Exception as error:
                message = f'{type(error).__name__}: {str(error)[:180]}'
                print('::warning::' + fid + ': ' + message)
                errors.append(config['id'])
                public.update({k: old_player.get(k) for k in ('stats', 'logo', 'stats_note', 'updated_at', 'coverage', 'secondary_stats')})
                public['stats'] = public.get('stats') or new_stats()
                feed['matches'].extend(copy.deepcopy(m) for m in old_matches if config['id'] in m['player_ids'])
            feed['players'].append(public)
        feed['federations'].append({'id': fid, 'label': label, 'acronym': acronym, 'source': base,
            'status': 'empty' if not configs else 'ok' if successes and not errors else 'partial' if successes else 'error',
            'checked_at': now(), 'last_success': now() if successes and not errors else old_fed.get('last_success'),
            'message': 'Sin jugadores activos' if not configs else 'Consulta automática completada' if successes and not errors else 'No se pudo completar la consulta. Se conserva el último dato válido.', 'failed_players': errors})
    feed = apply_roster(feed, roster)
    for player in feed['players']:
        own = [m for m in feed['matches'] if player['id'] in m['player_ids']]
        if own:
            player['stats'], player['coverage'] = summarize(own, player['id'], player.get('stats'))
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)
    print(f'Actualizadas {total_success}/{sum(p.get("active", True) for p in roster["players"])} fichas; {len(feed["matches"])} partidos publicados.')
    if not total_success and feed['players']:
        raise SystemExit(1)


def apply_roster(feed, roster):
    """Remove inactive players even from stale/shared fixtures and detect both sides."""
    configs = [p for p in roster['players'] if p.get('active', True)]
    active = {p['id'] for p in configs}
    feed['players'] = [p for p in feed['players'] if p['id'] in active]
    merged = {}
    for m in feed['matches']:
        m['player_ids'] = [id for id in m['player_ids'] if id in active]
        m['participation'] = {id: stats for id, stats in m.get('participation', {}).items() if id in active}
        m['participation_checked_at'] = {id: stamp for id, stamp in m.get('participation_checked_at', {}).items() if id in active}
        m['participation_source'] = {id: source for id, source in m.get('participation_source', {}).items() if id in active}
        if not m['player_ids']:
            continue
        if m.get('besoccer_match_id'):
            key = (m['federation'], 'besoccer', m['besoccer_match_id'])
        elif m['federation'] == 'murcia':
            config = next((p for p in configs if p['id'] in m['player_ids']), {})
            key = ('murcia', m.get('group_id') or config.get('group_id'), m.get('round'), normalized(m['home']), normalized(m['away']))
        else:
            key = (m['federation'], m['id'])
        if key in merged:
            old = merged[key]
            # Prefer the latest fixture details when one player's refresh failed.
            older, newer = (old, m) if (m.get('updated_at') or '') >= (old.get('updated_at') or '') else (m, old)
            preferred = next((x for x in (newer,older) if x.get('provider') != 'besoccer'), newer)
            combined = copy.deepcopy(preferred)
            combined['player_ids'] = sorted(set(old['player_ids'] + m['player_ids']))
            if (older.get('status'), older.get('score_home'), older.get('score_away')) == (newer.get('status'), newer.get('score_home'), newer.get('score_away')):
                combined['participation'] = {**older['participation'], **newer['participation']}
                combined['participation_checked_at'] = {**older['participation_checked_at'], **newer['participation_checked_at']}
                combined['participation_source'] = {**older['participation_source'], **newer['participation_source']}
            merged[key] = combined
        else:
            merged[key] = m
    for match in merged.values():
        for side in ('home', 'away'):
            def same_team(p):
                if p.get('besoccer_team_id') and match.get(side + '_besoccer_team_id'):
                    return str(p['besoccer_team_id']) == str(match[side + '_besoccer_team_id'])
                if p.get('team_id') and match.get(side + '_team_id'):
                    return str(p['team_id']) == str(match[side + '_team_id'])
                return normalized(p['team']) == normalized(match[side])
            players = [p['id'] for p in configs if p['federation'] == match['federation'] and same_team(p)]
            match[side + '_player_ids'] = players
        match['player_ids'] = sorted(set(match['player_ids'] + match['home_player_ids'] + match['away_player_ids']))
        match['is_internal_matchup'] = bool(match['home_player_ids'] and match['away_player_ids'])
    feed['matches'] = sorted(merged.values(), key=lambda m: (m['date'] or '9999', m['time'] or '99:99', m['id']))
    return feed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true', help='Recoger Valencia con Chromium estándar')
    args = parser.parse_args()
    sync(args.browser)
