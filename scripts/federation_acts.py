"""Read public match reports without executing their JavaScript."""
import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from player_stats import participation, absent


def norm(value):
    return re.sub(r'[^A-Z0-9]+', ' ', unicodedata.normalize('NFKD', str(value)).encode('ascii', 'ignore').decode().upper()).strip()


def parse_murcia_act(html, player):
    soup = BeautifulSoup(html, 'html.parser')
    sides = [d for d in soup.select('div.details') if d.select_one('.number') and d.find(['h4', 'h5'])]
    side = next((d for d in sides if norm(d.select_one('.number').get_text()) == norm(player['team'])), None)
    if not side:
        raise ValueError('No se encuentra el equipo en el acta')
    headers = {h.get_text(' ', strip=True): h for h in side.find_all(['h4', 'h5'])}
    if not {'Titulares', 'Suplentes'}.issubset(headers):
        raise ValueError('El acta no publica una alineación completa')
    starters = headers['Titulares'].find_next('table')
    bench = headers['Suplentes'].find_next('table')
    if len(starters.find_all('tr')) < 7:
        raise ValueError('Alineación incompleta o encuentro sin cerrar')
    wanted = norm(player['official_name'])
    def present(table):
        return any(norm(td.get_text(' ', strip=True)) == wanted for td in table.find_all('td'))
    starter, substitute = present(starters), present(bench)
    if not starter and not substitute:
        return absent()
    entries, exits, reds = [], [], []
    for table in side.find_all('table'):
        enter = table.select_one('i.fa-arrow-left')
        leave = table.select_one('i.fa-arrow-right')
        if not enter or not leave:
            continue
        erow, lrow = enter.find_parent('tr'), leave.find_parent('tr')
        minutes = re.search(r'\((\d+(?:\+\d+)?)[\x27’]\)', lrow.get_text(' ', strip=True))
        def row_name(row):
            cells = row.find_all('td')
            text = cells[1].get_text(' ', strip=True) if len(cells) > 1 else ''
            return norm(re.sub(r'^\([^)]*\)\s*', '', text))
        if row_name(erow) == wanted:
            entries.append(minutes[1] if minutes else '?')
        if row_name(lrow) == wanted:
            exits.append(minutes[1] if minutes else '?')
    cards = headers.get('Tarjetas')
    if cards:
        for row in cards.find_next('table').find_all('tr'):
            if wanted not in norm(row.get_text(' ', strip=True)):
                continue
            images = ' '.join(str(i.get('src', '')) for i in row.find_all('img'))
            if re.search(r'tarj_(?:roja|roja2|doble)', images, re.I):
                m = re.search(r'\((\d+(?:\+\d+)?)[\x27’]\)', row.get_text(' ', strip=True))
                reds.append(m[1] if m else '?')
    goals = None
    goal_block = next((d for d in soup.select('div.details') if d.select_one('.number') and d.select_one('.number').get_text(strip=True) == 'Goles'), None)
    if goal_block:
        goals = 0
        for row in goal_block.select('tr'):
            cells = row.find_all('td')
            if len(cells) < 2 or wanted not in norm(cells[1].get_text(' ', strip=True)):
                continue
            marker = row.find('a', title=True)
            if not marker or marker['title'] not in ('Gol normal', 'Gol de penalti', 'Gol penalti'):
                if marker and 'propia' in marker['title'].lower():
                    continue
                goals = None
                break
            goals += 1
    return participation(starter, player['match_duration'], entries, exits, reds, goals)


def murcia_round(client, player, round_number):
    base = 'https://www.ffrm.es/pnfg/'
    url = base + 'NPcd/NFG_CmpJornada?cod_primaria=1000120&CodCompeticion=' + player['competition_id'] + '&CodGrupo=' + player['group_id'] + '&CodTemporada=' + player['season_id'] + '&CodJornada=' + str(round_number)
    soup = BeautifulSoup(client.get(url), 'html.parser')
    for anchor in soup.select('a[href*="NFG_CmpPartido"]'):
        row = anchor.find_parent('tr')
        teams = row.select('a[href*="NFG_VisEquipos"]')
        ids = [parse_qs(urlparse(a['href']).query).get('Codigo_Equipo', [''])[0] for a in teams]
        if player['team_id'] not in ids:
            continue
        return {'url': urljoin(url, anchor['href']), 'home_team_id': ids[0], 'away_team_id': ids[1],
                'home_logo': (row.select_one('.escudo_widgetL img') or {}).get('src'),
                'away_logo': (row.select_one('.escudo_widgetV img') or {}).get('src')}
    raise ValueError('No se encuentra el partido del equipo en la jornada')


def flight_players(html):
    result = {}
    soup = BeautifulSoup(html, 'html.parser')
    def walk(obj):
        if isinstance(obj, dict):
            if isinstance(obj.get('player'), dict) and obj['player'].get('nombre'):
                p = obj['player']; key = str(p.get('id') or p['nombre'])
                if key not in result or str(p.get('titular')) == '1':
                    result[key] = p
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)
    for script in soup.find_all('script'):
        text = script.get_text()
        if 'self.__next_f.push(' not in text:
            continue
        try:
            record = json.loads(text[text.index('(') + 1:text.rindex(')')])
            if len(record) < 2 or not isinstance(record[1], str):
                continue
            for line in record[1].splitlines():
                try:
                    walk(json.loads(line.split(':', 1)[1]))
                except (ValueError, IndexError):
                    pass
        except (ValueError, IndexError):
            pass
    return result, soup


def parse_catalunya_act(html, player):
    players, soup = flight_players(html)
    main = soup.find('main')
    if not main or 'FINALITZAT' not in main.get_text(' ', strip=True) or len(players) < 14:
        raise ValueError('Acta catalana sin alineaciones cerradas verificables')
    candidates = [p for p in players.values() if norm(p['nombre']) == norm(player['official_name'])]
    target = next((p for p in candidates if str(p.get('titular')) == '1'), candidates[0] if candidates else None)
    if not target:
        return absent()
    stats = {'called_up': 1, 'starts': int(str(target.get('titular')) == '1'), 'bench': int(str(target.get('titular')) != '1'),
             'played': None, 'minutes': None, 'goals': None}
    # The Catalan web publishes lineups but does not consistently expose substitution
    # intervals. Missing substitutions must not turn into 90/0 invented minutes.
    goals_header = next((h for h in main.find_all('h3') if h.get_text(strip=True) == 'GOLS'), None)
    if goals_header:
        container = goals_header.parent.parent
        target_name = norm(player['official_name'])
        rows = [t for t in container.stripped_strings if norm(t) == target_name]
        stats['goals'] = len(rows)
    return stats
