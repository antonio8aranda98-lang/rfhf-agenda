"""BeSoccer public HTML, scoped to one verified player, team and season.

No remote JavaScript is executed. Only sporting fields enter the public feed.
"""
import copy
import json
import re
import unicodedata
from datetime import datetime
from urllib.parse import urlparse, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from player_stats import participation

BASE = 'https://es.besoccer.com'
FIELDS = ('besoccer_team_source', 'besoccer_player_source')
TEAM = r'/equipo/(?:plantilla/|partidos/)?([a-zA-Z0-9_-]+)'
PLAYER = r'/jugador/([a-zA-Z0-9_-]+-\d+)'
GAME = r'/partido/([a-zA-Z0-9_-]+)/([a-zA-Z0-9_-]+)/(\d+)(?:/(?:alineaciones|informe|eventos|previa))?'


def url(value, kind='team'):
    try:
        u = urlparse(str(value))
        pattern = {'team': TEAM, 'player': PLAYER, 'match': GAME}[kind]
        match = re.fullmatch(pattern, u.path.rstrip('/'))
        if u.scheme != 'https' or u.hostname != 'es.besoccer.com' or u.port not in (None, 443) or u.username or u.password or u.fragment or u.query or len(str(value)) > 600 or not match:
            raise ValueError()
    except (ValueError, KeyError):
        raise ValueError('Usa el enlace HTTPS del equipo o jugador en es.besoccer.com, sin filtros ni parámetros')
    return BASE + ('/equipo/' + match[1] if kind == 'team' else '/jugador/' + match[1] if kind == 'player' else '/partido/' + '/'.join(match.groups()))


def is_besoccer(value):
    return urlparse(str(value)).hostname == 'es.besoccer.com'


def key(value):
    return re.sub(r'[^A-Z0-9]+', ' ', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().upper()).strip()


def name_key(value):
    return sorted(key(value).split())


def number(value):
    value = str(value).strip().rstrip("'’")
    return int(value) if re.fullmatch(r'\d+', value) else None


def jsonld(soup, kind):
    result = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.get_text())
        except (ValueError, TypeError):
            continue
        for record in data if isinstance(data, list) else [data]:
            if isinstance(record, dict) and record.get('@type') == kind:
                result.append(record)
    return result


class PublicBeSoccer:
    def __init__(self, client):
        self.client = client

    def get(self, value, kind='team', section=None):
        canonical = url(value, kind)
        if kind == 'team' and section:
            canonical = BASE + '/equipo/' + section + '/' + canonical.rsplit('/', 1)[1]
        elif kind == 'player' and section:
            canonical = BASE + '/jugador/' + section + '/' + canonical.rsplit('/', 1)[1]
        elif kind == 'match' and section:
            canonical += '/' + section
        html = self.client.get(canonical, headers={'Accept': 'text/html'})
        soup = BeautifulSoup(html, 'html.parser')
        link = soup.select_one('link[rel="canonical"]')
        if not link or url(link.get('href'), kind) != url(value, kind):
            raise ValueError('BeSoccer ha devuelto otra ficha; no se incorpora el dato')
        return html


def parse_roster(html, team_source, season):
    soup = BeautifulSoup(html, 'html.parser')
    selected = soup.select_one('#season option[selected]')
    years = season.split('-')
    if len(years) != 2 or not selected or selected.get('value') != years[1]:
        raise ValueError('La plantilla de BeSoccer no corresponde a la temporada de la agenda')
    competition = soup.select_one('#competition option[selected]')
    teams = jsonld(soup, 'SportsTeam')
    if len(teams) != 1 or not competition or not str(competition.get('value', '')).isdigit():
        raise ValueError('BeSoccer no identifica un equipo y competición únicos')
    team = teams[0]
    logo = team.get('image', '')
    code = re.search(r'/(\d+)\.(?:png|jpg)', str(logo))
    if not code or not team.get('name'):
        raise ValueError('Falta el identificador del equipo en BeSoccer')
    members = {}
    for row in soup.select('tr.row-body'):
        link = row.select_one('td.name a[href]')
        if not link:
            continue
        try:
            source = url(urljoin(BASE, link['href']), 'player')
        except ValueError:
            continue
        members[source] = link.get_text(' ', strip=True)
    if not members:
        raise ValueError('BeSoccer no devuelve una plantilla verificable')
    return {'team': team['name'], 'team_id': code[1], 'logo': logo,
            'competition_id': str(competition['value']), 'competition_label': competition.get_text(' ', strip=True),
            'team_source': url(team_source), 'members': members}


def parse_profile(html, requested, team, season):
    soup = BeautifulSoup(html, 'html.parser')
    names = [n.get_text(' ', strip=True) for n in soup.select('.panel-subtitle')]
    exact = [n for n in names if name_key(n) == name_key(requested)]
    if len(exact) != 1:
        raise ValueError('La ficha de BeSoccer no confirma el nombre completo. Revisa nombre y enlace individual')
    expected = season.split('-')[0] + '/' + season.split('-')[1][2:]
    parents = []
    for row in soup.select('table.table_parents tr.parent_row'):
        cells = row.select(':scope > td')
        img = row.select_one('td:first-child img')
        if len(cells) >= 2 and img and re.search(r'/' + re.escape(team['team_id']) + r'\.(?:png|jpg)(?:\?|$)', img.get('src', '')) and cells[1].get_text(' ', strip=True) == expected:
            parents.append(row)
    if len(parents) != 1:
        raise ValueError('La ficha no confirma este equipo en la temporada seleccionada')
    children = []
    for row in parents[0].find_next_siblings('tr'):
        if 'parent_row' in row.get('class', []):
            break
        link = row.select_one('a[onclick]')
        click = link.get('onclick', '') if link else ''
        comp = re.search(r"clickedTrajectoryComp['\"]\s*,\s*(\d+)", click)
        year = re.search(r"clickedTrajectoryYear['\"]\s*,\s*(\d+)", click)
        if comp and year and comp[1] == team['competition_id'] and year[1] == season.split('-')[1]:
            children.append(row)
    stats = {}
    if len(children) == 1:
        row = children[0]
        perf = [number(c.get_text(' ', strip=True)) for c in row.select('[data-content-tab="tprc1"]')]
        part = [number(c.get_text(' ', strip=True)) for c in row.select('[data-content-tab="tptc1"]')]
        if len(perf) == 5 and len(part) == 4:
            # PS means appearances as substitute, not unused bench or call-ups.
            stats = {'played': part[0], 'starts': part[1], 'minutes': part[3], 'goals': perf[1]}
    return {'official_name': exact[0], 'stats': stats}


def candidate_names(short, requested):
    short_tokens, full_tokens = key(short).split(), key(requested).split()
    return len(short_tokens) >= 2 and short_tokens[0][0] == full_tokens[0][0] and all(t in full_tokens[1:] for t in short_tokens[1:])


def resolve(api, request, season):
    team_source = url(request.get('besoccer_team_source') or request.get('source'))
    team = parse_roster(api.get(team_source, section='plantilla'), team_source, season)
    provided = request.get('besoccer_player_source')
    if provided:
        candidates = [url(provided, 'player')]
        if candidates[0] not in team['members']:
            raise ValueError('El jugador enlazado no figura en la plantilla de BeSoccer de este equipo')
    else:
        candidates = [source for source, short in team['members'].items() if name_key(short) == name_key(request['name']) or candidate_names(short, request['name'])]
    if not candidates or len(candidates) > 5:
        raise ValueError('Añade el enlace individual de BeSoccer para identificar al jugador sin confusiones')
    found = []
    for source in candidates:
        try:
            profile = parse_profile(api.get(source, 'player'), request['name'], team, season)
            found.append((source, profile))
        except ValueError:
            if provided:
                raise
    if len(found) != 1:
        raise ValueError('No se identifica un único jugador. Añade o revisa su enlace individual de BeSoccer')
    source, profile = found[0]
    slug = team_source.rsplit('/', 1)[1]
    matches = parse_calendar(api.get(team_source, section='partidos'), {'id': 'verify', 'federation': request['federation'], 'season': season, 'besoccer_team_source': team_source, 'besoccer_competition_label': team['competition_label']})
    if not matches:
        raise ValueError('BeSoccer no publica un calendario verificable para esta temporada y competición')
    return {'besoccer_team_source': team_source, 'besoccer_player_source': source,
            'besoccer_team_id': team['team_id'], 'besoccer_team_slug': slug,
            'besoccer_team': team['team'], 'besoccer_competition_id': team['competition_id'],
            'besoccer_competition_label': team['competition_label'], 'official_name': profile['official_name'],
            'besoccer_requested_player_source': url(provided, 'player') if provided else ''}


def parse_calendar(html, player):
    from sync import fixture
    soup = BeautifulSoup(html, 'html.parser')
    slug = url(player['besoccer_team_source']).rsplit('/', 1)[1]
    year = player['season'].split('-')[1]
    competition = key(player['besoccer_competition_label'])
    result = {}
    for card in soup.select('a.match-link[href]'):
        try:
            source = url(card['href'], 'match')
        except ValueError:
            continue
        path = urlparse(source).path.split('/')
        if slug not in path[2:4] or not path[4].startswith(year):
            continue
        label = card.select_one('.middle-info')
        label = label.get_text(' ', strip=True) if label else ''
        comp_name = re.split(r'\.\s*(?:Jornada|Grupo|Jor\.)\b', label)[0]
        if key(comp_name) != competition:
            continue
        names = card.select('.team-name .name')
        if len(names) != 2:
            continue
        try:
            start = datetime.fromisoformat(card.get('starttime', '').replace('Z', '+00:00'))
        except ValueError:
            continue
        if start.tzinfo is None:
            continue
        start = start.astimezone(ZoneInfo('Europe/Madrid'))
        if not f'{int(year)-1}-07-01' <= start.date().isoformat() < f'{year}-07-01':
            continue
        hour = start.strftime('%H:%M') if card.select_one('.match_hour.time') else None
        r1, r2 = card.select_one('.r1'), card.select_one('.r2')
        sh, sa = number(r1.get_text()) if r1 else None, number(r2.get_text()) if r2 else None
        status = 'scheduled' if hour else 'time_pending'
        tag = key(card.select_one('.match-status-label').get_text(' ', strip=True) if card.select_one('.match-status-label') else '')
        if tag == 'FIN' and sh is not None and sa is not None:
            status = 'finished'
        elif 'APLAZ' in tag:
            status = 'postponed'
        elif 'CANCEL' in tag or 'SUSPEND' in tag:
            status = 'cancelled'
        else:
            sh = sa = None
        rnd = re.search(r'Jornada\s+(\d+)', label)
        m = fixture(player['federation'], player, 'besoccer-' + path[4], names[0].get_text(' ', strip=True), names[1].get_text(' ', strip=True), start.date().isoformat(), hour, source,
                    status=status, score_home=sh, score_away=sa, round=int(rnd[1]) if rnd else None,
                    provider='besoccer', besoccer_match_id=path[4], competition_id='besoccer-' + str(player.get('besoccer_competition_id', '')),
                    home_besoccer_slug=path[2], away_besoccer_slug=path[3], participation_source={})
        images = card.select('.team-info img.team-shield')
        for index, side in enumerate(('home', 'away')):
            if len(images) == 2:
                m[side + '_logo'] = images[index].get('src')
                code = re.search(r'/(\d+)\.(?:png|jpg)', images[index].get('src', ''))
                if code:
                    m[side + '_besoccer_team_id'] = code[1]
        # Generic placeholder locations are not real grounds.
        for event in jsonld(card, 'SportsEvent'):
            place = event.get('location', {}).get('name')
            if place and key(place) not in ('ESTADIO', 'NONE', 'NULL'):
                m['venue'] = place
        result[m['id']] = m
    return list(result.values())


def parse_lineup(html, player, match):
    soup = BeautifulSoup(html, 'html.parser')
    canonical = soup.select_one('link[rel="canonical"]')
    if not canonical or url(canonical.get('href'), 'match') != url(match['source'], 'match'):
        raise ValueError('BeSoccer ha devuelto otro partido al consultar la alineación')
    side = 'local' if match.get('home_besoccer_slug') == player['besoccer_team_slug'] else 'visitor'
    starters = soup.select(f'a[data-cy="starterPlayer"].{side}')
    bench = soup.select(f'a[data-cy="benchPlayer"].{side}')
    if len(starters) != 11:
        return None
    source = url(player['besoccer_player_source'], 'player')
    targets = [a for a in starters + bench if urljoin(BASE, a.get('href', '')) == source]
    if not targets:
        # A partial bench list cannot prove absence from a squad.
        return None
    if len(targets) != 1:
        return None
    node = targets[0]
    entries, exits, reds, goals = [], [], [], 0
    for icon in node.select('.info-wrapper img[alt]'):
        label = key(icon['alt'])
        minute = icon.parent.select_one('.min')
        value = minute.get_text(' ', strip=True) if minute else ''
        if label == 'ENTRA': entries.append(value)
        elif label == 'SALE': exits.append(value)
        elif label in ('TARJETA ROJA', 'DOBLE AMARILLA', 'SEGUNDA AMARILLA'): reds.append(value)
        elif label == 'GOL':
            count = number(value[1:]) if re.fullmatch(r'\+\d+', value) else None
            goals += count if count is not None else 1
    return participation(node in starters, player['match_duration'], entries, exits, reds, goals)


def adapter(api, player, previous=()):
    team = parse_roster(api.get(player['besoccer_team_source'], section='plantilla'), player['besoccer_team_source'], player['season'])
    if team['team_id'] != player['besoccer_team_id'] or team['competition_id'] != player['besoccer_competition_id'] or player['besoccer_player_source'] not in team['members']:
        raise ValueError('La plantilla o competición de BeSoccer ha cambiado; revisa las fuentes del jugador')
    profile = parse_profile(api.get(player['besoccer_player_source'], 'player'), player['name'], team, player['season'])
    matches = parse_calendar(api.get(player['besoccer_team_source'], section='partidos'), player)
    old = {m['id']:m for m in previous}
    completed = sorted((m for m in matches if m['status']=='finished'), key=lambda m:m['date'], reverse=True)
    latest = {m['id'] for m in completed[:2]}
    budget = 10
    for m in completed:
        before = old.get(m['id'], {})
        if before.get('status')=='finished' and (before.get('score_home'), before.get('score_away')) == (m['score_home'], m['score_away']) and before.get('participation', {}).get(player['id']) is not None:
            m['participation'][player['id']] = copy.deepcopy(before['participation'][player['id']])
            for field in ('participation_source', 'participation_checked_at'):
                if player['id'] in before.get(field, {}): m.setdefault(field,{})[player['id']] = before[field][player['id']]
            if m['id'] not in latest:
                continue
        if budget <= 0:
            continue
        budget -= 1
        try:
            stats = parse_lineup(api.get(m['source'], 'match', 'alineaciones'), player, m)
            if stats is not None:
                m['participation'][player['id']] = stats
                m['participation_source'][player['id']] = m['source'] + '/alineaciones'
                m.setdefault('participation_checked_at', {}).pop(player['id'], None)
        except Exception:
            pass
    # Fetch a small number of upcoming match pages for an actual published ground.
    upcoming = sorted((m for m in matches if m['status'] in ('scheduled', 'time_pending')), key=lambda m:m['date'])[:3]
    for m in upcoming:
        try:
            soup = BeautifulSoup(api.get(m['source'], 'match', 'informe'), 'html.parser')
            for event in jsonld(soup, 'SportsEvent'):
                if url(event.get('url'), 'match') != m['source']:
                    continue
                location = event.get('location', {})
                place = location.get('name')
                if place and key(place) not in ('ESTADIO', 'NONE', 'NULL'):
                    m['venue'] = place
                    address = location.get('address', {})
                    if isinstance(address, dict):
                        m['address'] = address.get('streetAddress')
                        m['locality'] = address.get('addressLocality')
        except Exception:
            pass
    return {'matches': matches, 'stats': profile['stats'], 'logo': team['logo'], 'provider':'besoccer',
            'stats_note': 'Fuente BeSoccer: este equipo, competición y temporada. Convocatorias y suplencias solo con alineación verificable. Totales publicados por BeSoccer o calculados con alineaciones completas; los minutos por partido excluyen el añadido.'}


def enrich_official(result, secondary, player):
    """Fill only an identical fixture; never join opponents by fuzzy name."""
    result = copy.deepcopy(result)
    own_slug = player['besoccer_team_slug']
    for primary in result['matches']:
        candidates = []
        for other in secondary['matches']:
            own_side = 'home' if other.get('home_besoccer_slug') == own_slug else 'away'
            opponent = 'away' if own_side == 'home' else 'home'
            if (primary.get('date'), primary.get('round'), key(primary.get(opponent))) == (other.get('date'), other.get('round'), key(other.get(opponent))) and key(primary.get(own_side)) == key(player['team']):
                candidates.append(other)
        if len(candidates) != 1:
            continue
        other = candidates[0]
        if primary['status'] == other['status'] == 'finished' and (primary.get('score_home'), primary.get('score_away')) == (other.get('score_home'), other.get('score_away')):
            stats = other['participation'].get(player['id'])
            if stats is not None:
                existing = primary['participation'].get(player['id']) or {}
                missing = {k:v for k,v in stats.items() if existing.get(k) is None and v is not None}
                if missing:
                    primary['participation'][player['id']] = {**existing, **missing}
                    primary.setdefault('participation_source', {})[player['id']] = other['source'] + '/alineaciones'
        for field in ('venue', 'locality', 'address', 'home_logo', 'away_logo'):
            if not primary.get(field) and other.get(field):
                primary[field] = other[field]
        for field in ('besoccer_match_id','home_besoccer_team_id','away_besoccer_team_id','home_besoccer_slug','away_besoccer_slug'):
            if other.get(field): primary[field] = other[field]
    return result
