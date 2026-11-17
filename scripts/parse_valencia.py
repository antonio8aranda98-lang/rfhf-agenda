"""Parse the public FFCV cards, as verified in its public browser UI."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup
from sync import new_stats, integer, iso_date, http_time, fixture, normalized

ROOT = Path(__file__).resolve().parents[1]
MONTHS = {m: n for n, m in enumerate(['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'], 1)}


def parse_team(html, p):
    soup = BeautifulSoup(html, 'html.parser')
    games = []
    for card in soup.select('a .match-card'):
        anchor = card.find_parent('a')
        meta = card.select_one('.m-meta')
        teams = card.select('.team-row')
        if not meta or len(teams) != 2:
            continue
        dt = re.search(r'(\d{1,2})\s+([a-z]+)\s+de\s+(\d{4})\s*·\s*Jornada\s*(\d+)', meta.get_text(' ', strip=True), re.I)
        if not dt or dt[2].lower() not in MONTHS:
            continue
        # Ignore the source weekday labels: some disagree with its numeric date.
        date = iso_date(f'{int(dt[1]):02}-{MONTHS[dt[2].lower()]:02}-{dt[3]}')
        key = parse_qs(urlparse(anchor['href']).query).get('cod_partido', [None])[0]
        if not date or not key:
            continue
        right = card.select_one('.match-right')
        text = right.get_text(' ', strip=True) if right else ''
        clock = re.search(r'\d{1,2}:\d{2}', text)
        scores = [integer(t.select_one('.team-goals').get_text(strip=True)) if t.select_one('.team-goals') else None for t in teams]
        finished = 'Finalizado' in text and all(s is not None for s in scores)
        hour = http_time(clock[0]) if clock else None
        game = fixture('valencia', p, key, teams[0].select_one('.team-name').get_text(' ', strip=True), teams[1].select_one('.team-name').get_text(' ', strip=True),
                       date, hour, urljoin('https://ffcv.es/competiciones/equipos/equipo.php', anchor['href']), round=int(dt[4]),
                       status='finished' if finished else 'postponed' if 'Aplazado' in text else 'cancelled' if 'Suspendido' in text else 'scheduled' if hour else 'time_pending',
                       score_home=scores[0] if finished else None, score_away=scores[1] if finished else None,
                       home_logo=teams[0].img.get('src') if teams[0].img else None, away_logo=teams[1].img.get('src') if teams[1].img else None)
        games.append(game)
    if not games:
        raise ValueError('La fuente no ha devuelto tarjetas de partidos inequívocas')
    return games


def parse_player(html, p):
    soup = BeautifulSoup(html, 'html.parser')
    heading = soup.find('h1')
    if not heading or normalized(heading.get_text()) != normalized(p['official_name']):
        raise ValueError('La ficha individual no coincide con el jugador configurado')
    area = soup.select_one('#stats')
    if not area:
        raise ValueError('La ficha no publica el bloque de estadísticas esperado')
    tokens = list(area.stripped_strings)
    mapping = {'Convocados':'called_up','Suplente':'bench','Jugados':'played','Titular':'starts','Goles':'goals','Amarillas':'yellow','Rojas':'red'}
    stats = new_stats()
    for i, token in enumerate(tokens):
        if token in mapping and i:
            value = integer(tokens[i-1])
            if value is not None:
                stats[mapping[token]] = value
    return stats


def main():
    raw = json.loads((ROOT / '.cache/valencia-browser.json').read_text())
    roster = json.loads((ROOT / 'data/roster.json').read_text())
    out = {'checked_at': raw['checked_at'], 'players': {}}
    for p in roster['players']:
        if p['federation'] != 'valencia':
            continue
        record = raw['players'].get(p['id'], {})
        try:
            if record.get('error'):
                raise ValueError(record['error'])
            matches = parse_team(record['matches_html'], p)
            stats = parse_player(record['player_html'], p)
            team = BeautifulSoup(record['matches_html'], 'html.parser').select_one('.team-row.is-team img')
            out['players'][p['id']] = {'matches': matches, 'stats': stats, 'logo': team.get('src') if team else None,
                                     'stats_note': 'Resumen individual publicado por FFCV. Minutos y asistencias no disponibles.'}
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            out['players'][p['id']] = {'error': str(error)}
    (ROOT / '.cache/valencia.json').write_text(json.dumps(out, ensure_ascii=False))


if __name__ == '__main__':
    main()
