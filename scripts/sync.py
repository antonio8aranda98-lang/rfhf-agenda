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
import urllib.error
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from player_stats import participation, absent, summarize, STAT_FIELDS
from report_refresh import report_plan, checked as report_checked
from intake_priority import IntakeYield, IntakeWatch, execution_deadline
from federation_acts import murcia_round, parse_murcia_act, parse_catalunya_act, parse_murcia_calendar

ROOT = Path(__file__).resolve().parents[1]
REQUEST_GUARD = None
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
        self.retry_after = None
        if urllib.parse.urlparse(base).hostname == 'ffcv.es':
            try:
                previous = json.loads((ROOT / 'docs/data/feed.json').read_text())
                self.retry_after = next((f.get('retry_after') for f in previous.get('federations', []) if f['id'] == 'valencia'), None)
            except (OSError, ValueError, KeyError):
                pass
            try:
                settings = json.loads((ROOT / 'docs/data/settings.json').read_text())
                deadline = settings.get('source_pauses', {}).get('valencia')
                if deadline and (not self.retry_after or datetime.fromisoformat(deadline) > datetime.fromisoformat(self.retry_after)):
                    self.retry_after = deadline
            except (OSError, ValueError, TypeError):
                pass

    def get(self, url, headers=None):
        if url in self.cache:
            return self.cache[url]
        if REQUEST_GUARD:REQUEST_GUARD()
        if self.retry_after and datetime.fromisoformat(self.retry_after) > datetime.now(timezone.utc):
            label = datetime.fromisoformat(self.retry_after).astimezone(MADRID).strftime('%d/%m %H:%M')
            raise ValueError('Las consultas a la FFCV están pausadas hasta ' + label + ' (hora de Madrid); se reintentará automáticamente.')
        # The legacy Murcia portal sometimes returns empty HTTP 200 responses.
        # Keep a conservative request rate and pause once before giving up.
        interval = 8 if 'ffrm.es' in self.base else 2 if any(host in self.base for host in ('besoccer.com', 'ffcv.es')) else .65
        time.sleep(max(0, interval - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(url, headers={'Referer': self.base, **(headers or {})})
        try:
            response = self.opener.open(request, timeout=35)
        except urllib.error.HTTPError as error:
            if urllib.parse.urlparse(self.base).hostname != 'ffcv.es' or error.code != 429:
                raise
            value = error.headers.get('Retry-After', '')
            try:
                until = datetime.fromtimestamp(time.time() + max(0, int(value)), timezone.utc) if value.isdigit() else parsedate_to_datetime(value)
                if until.tzinfo is None: until = until.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError, OverflowError):
                until = datetime.fromtimestamp(time.time() + 3600, timezone.utc)
            self.retry_after = until.astimezone(timezone.utc).isoformat(timespec='seconds')
            error.close()
            label = until.astimezone(MADRID).strftime('%d/%m %H:%M')
            raise ValueError('La FFCV ha solicitado una pausa hasta ' + label + ' (hora de Madrid); se reintentará automáticamente.') from error
        with response:
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


def _madrid_team(client, player):
    base = FEDERATIONS['madrid'][2]
    team = client.next_props(base + 'fichaequipo/' + player['team_id'])['team']
    listed=any(str(p['cod_jugador'])==player['player_id'] for p in team.get('jugadores_equipo',[]))
    if not listed:
        if not player.get('player_source'):raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
        linked=client.next_props(player['source'])['player']
        scopes=[c for c in linked.get('competiciones_participa',[]) if str(c.get('codequipo'))==player['team_id'] and str(c.get('codigo_competicion'))==player['competition_id'] and str(c.get('codgrupo'))==player['group_id']]
        if linked.get('nombre_temporada')!=player['season'] or str(linked.get('codigo_jugador'))!=player['player_id'] or len(scopes)!=1:
            raise ValueError('La ficha individual ya no confirma al jugador con el equipo y competición seguidos')
    url = base + 'competicion/calendario?' + urllib.parse.urlencode({'competicion': player['competition_id'], 'grupo': player['group_id'], 'temporada': player['season_id'], 'tipojuego': 1})
    cal = client.next_props(url)['calendar']
    matches = []
    host = str(team.get('host', 'https://www.rffm.es/'))
    if not host.startswith('https://'):
        host = base
    logo = urllib.parse.urljoin(host, team.get('escudo_club', ''))
    summary = new_stats()
    pdata = client.next_props(player['source'])['player']
    competition = next((c for c in pdata.get('competiciones_participa', []) if str(c.get('codigo_competicion')) == player['competition_id'] and str(c.get('codequipo',player['team_id']))==player['team_id']), {})
    visible = competition.get('ver_estadisticas') == '1'
    if visible and len(pdata.get('competiciones_participa', [])) == 1:
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
            if not player.get('_calendar_only') and date and today <= date and m.get('codigo_campo'):
                try:
                    field = client.next_props(base + 'campo/' + m['codigo_campo'])['field']
                    for dest, src in [('address', 'direccion'), ('locality', 'localidad'), ('latitude', 'latitud'), ('longitude', 'longitud')]:
                        match[dest] = field.get(src) or None
                except Exception:
                    pass  # Keep fixture even if optional location enrichment is unavailable.
            matches.append(match)
    # Only closed acts yield individual participation; bench is never assumed played.
    completed = sorted([m for m in matches if m['status'] == 'finished'], key=lambda m: m['date'] or '', reverse=True)
    if player.get('_calendar_only'):
        return {'matches':matches,'stats':summary,'logo':logo,'stats_note':'Calendario verificado. Las actas individuales se completan en las actualizaciones deportivas.'}
    selected_reports = report_plan(matches, player, player.get('_previous', []))
    for m in completed:
        if m['id'] not in selected_reports:
            continue
        try:
            game = client.next_props(m['source'])['game']
            side = 'local' if str(game['codigo_equipo_local']) == player['team_id'] else 'visitante'
            rows = game.get('jugadores_equipo_' + side, [])
            row = next((r for r in rows if str(r.get('codjugador')) == player['player_id']), None)
            if game.get('acta_cerrada') != '1' or len(rows) < 7:
                continue
            if not row:
                m['participation'][player['id']] = absent()
                report_checked(m, player['id'])
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
            report_checked(m, player['id'])
        except Exception:
            continue
    return {'matches': matches, 'stats': summary, 'logo': logo, 'stats_note': 'Convocado = titular o suplente en el acta. Los minutos calculados usan tiempo reglamentario, sin añadido.'+(' Ficha federativa: '+str(player.get('registration_team') or 'otro equipo')+'. Calendario y estadísticas limitados al equipo seguido: '+player['team']+'.' if player.get('player_source') else '')}


def team_matches(matches,scope):
    tid=str(scope.get('team_id') or '')
    return [m for m in matches if tid in (str(m.get('home_team_id')),str(m.get('away_team_id'))) and (not m.get('group_id') or not scope.get('group_id') or str(m['group_id'])==str(scope['group_id']))]


def madrid(client, player):
    result=_madrid_team(client,player)
    extras=[]
    for scope in (player.get('additional_teams') or []):
        derived={**player,**scope,'additional_teams':[]}
        item=copy.deepcopy(scope)
        try:
            extra=_madrid_team(client,derived)
            if not extra['matches']:raise ValueError('Calendario del segundo equipo vacío')
            result['matches'].extend(extra['matches'])
            item.update(calendar_status='ok',updated_at=now())
        except Exception:
            previous=team_matches(player.get('_previous',[]),scope)
            result['matches'].extend(copy.deepcopy(previous))
            item.update(calendar_status='pending',updated_at=max((m.get('updated_at') or '' for m in previous),default=None))
            result['source_warning']=True
        extras.append(item)
    if extras:result['additional_teams']=extras
    return result


def catalunya(client, player):
    data = initial_data(client.get(player['source']))
    wanted = normalized(player['name'])
    if not any(normalized(p.get('NOMBRE')) == wanted for p in data.get('players', [])):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    escudos = 'https://files.fcf.cat/escudos/clubes/escudos/'
    matches = []
    reports = {}
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
        if closed and not player.get('_calendar_only'):
            slug = lambda text: re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()).strip('-')
            path = f"ca/partit/{player.get('season', '2026-2027')}/{slug(m['NOMBRE_COMPETICION'])}/{slug(m['GRUPO'])}/jornada-{m['JORNADA']}/{m['SLUG_CASA']}-vs-{m['SLUG_FUERA']}"
            reports[matches[-1]['id']] = 'https://www.fcf.cat/' + path
    selected_reports = set() if player.get('_calendar_only') else report_plan(matches, player, player.get('_previous', []))
    for match in matches:
        if match['id'] not in selected_reports:continue
        try:
            match['participation'][player['id']] = parse_catalunya_act(client.get(reports[match['id']]), player)
            match['source'] = reports[match['id']]
            report_checked(match, player['id'])
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
    from murcia_recovery import previous_calendar, transient, report_url, validate_report
    previous=previous_calendar(player)
    known_reports={m['id']:report_url(m.get('participation_source',{}).get(player['id'])) or report_url(m.get('source')) for m in previous}
    warnings=[];team=None;retained=False
    print('murcia: '+player.get('name',player['official_name'])+' · comprobando datos deportivos',flush=True)
    team_url = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?' + urllib.parse.urlencode({'Codigo_Equipo':player['team_id'], 'cod_primaria':'3001860'})
    try:team = BeautifulSoup(client.get(team_url), 'html.parser')
    except Exception as error:
        if not transient(error) or not previous or player.get('_calendar_only'):raise
        warnings.append('La plantilla no ha respondido; se conserva el calendario anterior.')
        retained=True
    if team is not None and normalized(player['official_name']) not in normalized(team.get_text(' ', strip=True)):
        raise ValueError('El jugador ya no figura en la plantilla configurada; revisar asignación')
    # Keep the public calendar form's season and journey filters. Without
    # CodJornada this portal can return an empty HTTP 200 for a new group.
    url = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisCalendario_Vis?' + urllib.parse.urlencode({'cod_primaria':'1000120','codtemporada':player['season_id'],'codcompeticion':player['competition_id'],'codgrupo':player['group_id'],'CodJornada':'1','CDetalle':'1'})
    if retained:matches=previous
    else:
        try:matches = parse_murcia_calendar(client.get(url), player, url)
        except Exception as error:
            if not transient(error) or not previous or player.get('_calendar_only'):raise
            matches=previous;retained=True
            warnings.append('El calendario no ha respondido; se conserva su última lectura.')
    image = team.select_one('img[src*="/Clubes/"]') if team is not None else None
    logo = urllib.parse.urljoin(player['source'], image['src']) if image else None
    if not logo and retained:
        logo=next((m.get('home_logo') if m.get('home_team_id')==player['team_id'] else m.get('away_logo') for m in previous if m.get('home_logo') or m.get('away_logo')),None)
    if logo:
        for match in matches:
            if normalized(match['home']) == normalized(player['team']):
                match['home_logo'] = logo
            if normalized(match['away']) == normalized(player['team']):
                match['away_logo'] = logo
    today = datetime.now(MADRID).date().isoformat()
    selected_reports = set() if player.get('_calendar_only') else report_plan(matches, player, player.get('_previous', []))
    for match in matches:
        if player.get('_calendar_only'):
            continue
        if match['status']=='finished' and match['id'] not in selected_reports:
            continue
        if retained and match['status']!='finished':continue
        if match['status'] != 'finished' and (not match.get('date') or abs((datetime.fromisoformat(match['date']).date() - datetime.now(MADRID).date()).days) > 7):
            continue
        try:
            direct=report_url(match.get('source')) or known_reports.get(match['id'])
            report = {'url':direct,'alternate_url':direct} if direct else murcia_round(client, player, match['round'])
            candidate_source=report['url']
            try:
                html = client.get(report['url'])
            except ValueError as error:
                if 'respuesta vacía' not in str(error) or report['alternate_url']==report['url']:
                    raise
                html = client.get(report['alternate_url'])
                candidate_source=report['alternate_url']
            if match['status'] == 'finished':
                validate_report(html,player,match)
                record=parse_murcia_act(html, player)
            match.update({k: v for k, v in report.items() if k not in ('url','alternate_url') and v})
            match['source']=candidate_source
            if match['status']=='finished':
                match['participation'][player['id']] = record
                report_checked(match, player['id'])
                match.setdefault('participation_source',{})[player['id']]=match['source']
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
            warnings.append('Acta J'+str(match['round'])+': '+str(error)[:120])
            print('::warning::Murcia acta J' + str(match['round']) + ': ' + type(error).__name__ + ': ' + str(error)[:160])
    result={'matches': matches, 'stats': new_stats(), 'logo': logo,
            'stats_note': 'Convocatorias y participación según actas. Minutos calculados con la duración reglamentaria de la categoría, sin añadido.'}
    if warnings:result['source_warning']=' '.join(warnings)
    if retained:
        result['checked_at']=max((m.get('updated_at') or '' for m in previous),default='') or None
        result['stats_note']+=' Calendario conservado de la última lectura válida; las actas se comprueban por separado.'
    return result


def valencia(client, player):
    from valencia_data import load_valencia
    return load_valencia(client, player)


ADAPTERS = {'madrid': madrid, 'catalunya': catalunya, 'murcia': murcia, 'valencia': valencia}


def collect_player(client, secondary_client, player, previous=()):
    from official_sources import PROVIDERS, client_for, adapter as official_adapter
    if player.get('provider') in PROVIDERS:
        return official_adapter(client_for(secondary_client,player['provider']),player,previous)
    from besoccer_data import PublicBeSoccer, adapter, enrich_official
    api = PublicBeSoccer(secondary_client)
    if player.get('provider') == 'besoccer':
        return adapter(api, player, previous)
    result = ADAPTERS[player['federation']](client, {**player, '_previous':previous})
    if player.get('besoccer_team_source') and not player.get('_calendar_only'):
        try:
            secondary = adapter(api, player)
            result = enrich_official(result, secondary, player)
            result['secondary_stats'] = {'provider':'besoccer', 'source':player['besoccer_player_source'],
                'team':player['besoccer_team'], 'competition':player['besoccer_competition_label'],
                'season':player['season'], 'stats':secondary['stats'], 'checked_at':now()}
        except Exception:
            result['secondary_warning'] = 'BeSoccer no está disponible o no confirma la plantilla; se conservan los datos de la federación.'
    return result


def retain_participation(match, previous, player_id, allow_secondary=True):
    """Retain missing fields only while the result and known identity facts agree."""
    if not previous or match.get('status') != previous.get('status') or match.get('status') != 'finished' or (match.get('score_home'),match.get('score_away')) != (previous.get('score_home'),previous.get('score_away')):
        return
    before = previous.get('participation', {}).get(player_id)
    if before is None:
        return
    old_source = previous.get('participation_source', {}).get(player_id)
    if old_source and 'besoccer.com' in old_source and not allow_secondary:
        return
    current = match.setdefault('participation', {}).get(player_id) or {}
    if any(current.get(k) is not None and before.get(k) is not None and current[k] != before[k] for k in ('called_up','starts','bench','played')):
        return
    missing = {k:v for k,v in before.items() if current.get(k) is None and v is not None}
    if not current or missing:
        match['participation'][player_id] = {**current, **missing}
        match.setdefault('participation_checked_at', {})[player_id] = previous.get('participation_checked_at', {}).get(player_id, previous.get('updated_at'))
        if old_source: match.setdefault('participation_source', {})[player_id] = old_source


def _sync(browser=False, registry_changes=False, intake=False, federation=None):
    roster = json.loads((ROOT / 'data/roster.json').read_text())
    path = ROOT / 'docs/data/feed.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    old_players = {p['id']:p for p in previous.get('players', [])}
    status_path=ROOT/'docs/data/registry-status.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else {}
    status_rows={p['id']:p for p in status.get('players',[])}
    focus = None
    if registry_changes:
        identity_fields = ('source','player_source','besoccer_team_source','besoccer_player_source','official_adapter_version')
        with_matches={id for m in previous.get('matches',[]) for id in m['player_ids']}
        focus = {p['id'] for p in roster['players'] if p.get('active',True) and (p['id'] not in old_players or not old_players[p['id']].get('updated_at') or p['id'] not in with_matches or any(p.get(k) != old_players[p['id']].get(k) for k in identity_fields))}
    if intake:focus=set(status.get('intake_ids',[]))
    if federation:
        regional={p['id'] for p in roster['players'] if p['federation']==federation}
        focus=regional if focus is None else focus & regional
    if browser:
        run = subprocess.run(['node', 'scripts/valencia.mjs'], cwd=ROOT, timeout=360, check=False)
        if run.returncode:
            print('::warning::Valencia: consulta de navegador incompleta; se conservarán datos anteriores')
    feed = {'schema_version': 1, 'generated_at': now(), 'season': roster['season'], 'registry_revision': roster.get('registry_revision', 0), 'federations': [], 'players': [], 'matches': []}
    old_matches = previous.get('matches', [])
    total_success = 0
    preempted = False
    secondary_client = Client('https://es.besoccer.com')
    for fid, (label, acronym, base) in FEDERATIONS.items():
        client = Client(base)
        configs = [p for p in roster['players'] if p['federation'] == fid and p.get('active', True)]
        if fid == 'valencia':
            dates = {p['id']: p.get('updated_at') or '' for p in previous.get('players', [])}
            configs.sort(key=lambda p: dates.get(p['id'], ''))
        if fid == 'murcia':
            def recovery_priority(p):
                own=[m for m in old_matches if p['id'] in m['player_ids']]
                has_report=any(p['id'] in m.get('participation',{}) for m in own)
                attempted=max((m.get('participation_attempted_at',{}).get(p['id'],'') for m in own),default='')
                return has_report,attempted or old_players.get(p['id'],{}).get('updated_at','')
            configs.sort(key=recovery_priority)
        # Normal public landing establishes the same public session as website navigation.
        try:
            if not preempted and fid not in ('valencia', 'murcia') and (focus is None or any(p['id'] in focus for p in configs)):
                client.get(base)
        except IntakeYield:
            preempted=True
        except Exception:
            pass
        old_fed = next((f for f in previous.get('federations', []) if f['id'] == fid), {})
        errors = []
        successes = 0
        for config in configs:
            config = {**config, 'season': roster['season']}
            old_player = next((p for p in previous.get('players', []) if p['id'] == config['id']), {})
            public = {k: config[k] for k in ('id', 'name', 'federation', 'collaborator', 'team', 'competition_label', 'source')}
            public['provider'] = config.get('provider', 'federation')
            public.update({k:copy.deepcopy(config[k]) for k in ('team_id','competition_id','group_id','additional_teams') if config.get(k)})
            public.update({k:config[k] for k in ('age_category','team_age_category','source_acronym','official_adapter_version','official_display_name') if config.get(k)})
            public.update({k:config[k] for k in ('besoccer_team_source','besoccer_player_source','player_source','team_source','registration_team','participation_evidence') if config.get(k)})
            if preempted or (focus is not None and config['id'] not in focus):
                public.update({k:old_player[k] for k in ('stats','logo','stats_note','updated_at','coverage','secondary_stats','secondary_warning','additional_teams','calendar_complete') if k in old_player})
                if old_player.get('updated_at'):feed['players'].append(public)
                feed['matches'].extend(copy.deepcopy(m) for m in old_matches if config['id'] in m['player_ids'])
                continue
            if intake:
                config.update(_calendar_only=True,_intake=True)
                if config['id'] in status_rows:status_rows[config['id']]['calendar_attempted_at']=now()
            try:
                same_secondary = old_player.get('besoccer_player_source') == config.get('besoccer_player_source')
                result = collect_player(client, secondary_client, config, old_matches if same_secondary else ())
                if not result['matches']:
                    raise ValueError('Calendario vacío inesperado; se conservan los datos anteriores')
                public.update({k: result.get(k) for k in ('stats', 'logo', 'stats_note')})
                public.update({k:result[k] for k in ('secondary_stats','secondary_warning','additional_teams') if k in result})
                public['calendar_complete']=result.get('calendar_complete',True)
                if result.get('secondary_warning') and same_secondary and old_player.get('secondary_stats'):
                    public['secondary_stats'] = old_player['secondary_stats']
                public['updated_at'] = result.get('checked_at') or now()
                for m in result['matches']:
                    checked = m.setdefault('participation_checked_at', {})
                    for player_id in m.get('participation', {}):
                        checked.setdefault(player_id, public['updated_at'])
                    previous_match = next((old for old in old_matches if old['id'] == m['id']), None)
                    retain_participation(m, previous_match, config['id'], allow_secondary=bool(config.get('besoccer_team_source')) and same_secondary)
                    m['updated_at'] = public['updated_at']
                    feed['matches'].append(m)
                successes += 1
                total_success += 1
                if intake and config['id'] in status_rows:status_rows[config['id']]['priority_calendar']=False
                if result.get('source_warning'):errors.append(config['id'])
                print(fid + ': ' + str(len(result['matches'])) + ' partidos verificados')
            except (Exception, IntakeYield) as error:
                if isinstance(error,IntakeYield):preempted=True
                message = f'{type(error).__name__}: {str(error)[:180]}'
                print('::warning::' + fid + ': ' + message)
                errors.append(config['id'])
                public.update({k: old_player.get(k) for k in ('stats', 'logo', 'stats_note', 'updated_at', 'coverage', 'secondary_stats','additional_teams','calendar_complete')})
                if old_player.get('besoccer_player_source') != config.get('besoccer_player_source'):
                    public.pop('secondary_stats', None)
                public['stats'] = public.get('stats') or new_stats()
                if public.get('additional_teams') is None: public.pop('additional_teams', None)
                if not old_player.get('updated_at') or not any(config['id'] in m['player_ids'] for m in old_matches):
                    continue  # A failed first refresh must not publish an empty profile.
                feed['matches'].extend(copy.deepcopy(m) for m in old_matches if config['id'] in m['player_ids'])
            feed['players'].append(public)
        meta = {'id': fid, 'label': label, 'acronym': acronym, 'source': base,
            'status': 'empty' if not configs else 'ok' if successes and not errors else 'partial' if successes else 'error',
            'checked_at': now(), 'last_success': now() if successes and not errors else old_fed.get('last_success'),
            'message': 'Sin jugadores activos' if not configs else 'Consulta automática completada' if successes and not errors else 'No se pudo completar la consulta. Se conserva el último dato válido.', 'failed_players': errors}
        if getattr(client, 'retry_after', None):
            meta['retry_after'] = client.retry_after
        if preempted and not successes and old_fed:
            meta=copy.deepcopy(old_fed)
        elif focus is not None and configs and all(p['id'] not in focus for p in configs):
            meta = copy.deepcopy(old_fed)
        elif focus is not None and any(p['id'] not in focus for p in configs):
            meta['last_success'] = old_fed.get('last_success')
            if old_fed.get('status') not in ('ok','empty') and meta['status']=='ok':meta['status']='partial'
        feed['federations'].append(meta)
    feed = apply_roster(feed, roster)
    for player in feed['players']:
        own = [m for m in feed['matches'] if player['id'] in m['player_ids']]
        if own:
            primary=team_matches(own,player) if player.get('additional_teams') else own
            player['stats'], player['coverage'] = summarize(primary, player['id'], player.get('stats'),calendar_complete=player.get('calendar_complete') is not False)
            for scope in (player.get('additional_teams') or []):
                scope['stats'],scope['coverage']=summarize(team_matches(own,scope),player['id'])
    path.parent.mkdir(exist_ok=True, parents=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)
    if intake and status_path.exists():
        status['intake_mode']='processed'
        status_path.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
    print(f'Actualizadas {total_success}/{sum(p.get("active", True) for p in roster["players"])} fichas; {len(feed["matches"])} partidos publicados.')
    if preempted:print('Avance guardado. La siguiente sincronización continuará el trabajo pendiente.')
    if not total_success and not preempted and feed['players'] and (focus is None or focus):
        raise SystemExit(1)


def sync(browser=False, registry_changes=False, intake=False, watch_intake=False, federation=None):
    global REQUEST_GUARD
    original=REQUEST_GUARD
    watch=None
    if watch_intake:
        from registry_remote import fetch_registry
        roster=json.loads((ROOT/'data/roster.json').read_text())
        watch=IntakeWatch(fetch_registry,roster.get('registry_revision',0))
        status_path=ROOT/'docs/data/registry-status.json'
        status=json.loads(status_path.read_text()) if status_path.exists() else {}
        intake=intake or (not federation and status.get('intake_mode') in ('priority','controls'))
    deadline=execution_deadline()
    def checkpoint():
        if time.monotonic()>=deadline:raise IntakeYield('Se guarda el avance antes del límite de ejecución')
        if watch:watch()
        elif original:original()
    REQUEST_GUARD=checkpoint
    try:return _sync(browser,registry_changes,intake,federation)
    finally:REQUEST_GUARD=original


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
        m['participation_attempted_at'] = {id: stamp for id, stamp in m.get('participation_attempted_at', {}).items() if id in active}
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
                # Calendar freshness and report freshness are independent. A
                # teammate's retained fixture must not replace a newer report.
                for field in ('participation','participation_checked_at','participation_source','participation_attempted_at'):combined[field]={}
                for pid in set(older['participation']) | set(newer['participation']):
                    candidates=[g for g in (older,newer) if pid in g['participation']]
                    chosen=max(candidates,key=lambda g:g.get('participation_checked_at',{}).get(pid) or g.get('updated_at') or '')
                    combined['participation'][pid]=copy.deepcopy(chosen['participation'][pid])
                    for field in ('participation_checked_at','participation_source'):
                        if pid in chosen.get(field,{}):combined[field][pid]=chosen[field][pid]
                for field in ('participation_checked_at','participation_attempted_at'):
                    for pid in set(older.get(field,{})) | set(newer.get(field,{})):
                        stamp=max(older.get(field,{}).get(pid,'') or '',newer.get(field,{}).get(pid,'') or '')
                        if stamp:combined[field][pid]=stamp
            merged[key] = combined
        else:
            merged[key] = m
    for match in merged.values():
        for side in ('home', 'away'):
            def same_team(p):
                for scope in [p,*(p.get('additional_teams') or [])]:
                    if scope.get('besoccer_team_id') and match.get(side+'_besoccer_team_id'):
                        if str(scope['besoccer_team_id'])==str(match[side+'_besoccer_team_id']):return True
                    elif scope.get('team_id') and match.get(side+'_team_id'):
                        if str(scope['team_id'])==str(match[side+'_team_id']):return True
                    elif normalized(scope['team'])==normalized(match[side]):
                        if scope.get('group_id') and match.get('group_id') and str(scope['group_id'])!=str(match['group_id']):
                            continue
                        return True
                return False
            players = [p['id'] for p in configs if p['federation'] == match['federation'] and same_team(p)]
            match[side + '_player_ids'] = players
        match['player_ids'] = sorted(set(match['player_ids'] + match['home_player_ids'] + match['away_player_ids']))
        match['is_internal_matchup'] = bool(match['home_player_ids'] and match['away_player_ids'])
    feed['matches'] = sorted(merged.values(), key=lambda m: (m['date'] or '9999', m['time'] or '99:99', m['id']))
    return feed


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', action='store_true', help='Recoger Valencia con Chromium estándar')
    parser.add_argument('--registry-changes', action='store_true', help='Actualizar solo altas y cambios de fuentes, conservando fechas de las demás fichas')
    parser.add_argument('--intake',action='store_true',help='Publicar primero calendarios de altas y tandas pequeñas de pendientes')
    parser.add_argument('--watch-intake',action='store_true',help='Guardar el avance y ceder el turno si Antonio registra un cambio nuevo')
    parser.add_argument('--federation',choices=tuple(FEDERATIONS),help='Actualizar una federación conservando los datos de las demás')
    args = parser.parse_args()
    sync(args.browser, args.registry_changes,args.intake,args.watch_intake,args.federation)
