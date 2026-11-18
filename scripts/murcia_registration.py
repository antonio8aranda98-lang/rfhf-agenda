"""Discover a team's current competition using its public FFRM history link."""
from urllib.parse import urljoin, urlparse, parse_qs
from bs4 import BeautifulSoup


def official_link(base, href, path):
    url = urljoin(base, href)
    u = urlparse(url)
    if (u.scheme != 'https' or u.hostname != 'www.ffrm.es' or u.port not in (None, 443)
            or u.username or u.password or u.fragment or u.path != '/pnfg/NPcd/' + path):
        raise ValueError('La ficha de competición sale de la fuente pública oficial')
    return url, parse_qs(u.query)


def discover_scope(client, soup, source, team_id, season):
    links = []
    for a in soup.select('a[href*="NFG_VisCompeticiones_Equipo"]'):
        url, q = official_link(source, a['href'], 'NFG_VisCompeticiones_Equipo')
        if q.get('codequipo') == [team_id] and len(q.get('codtemporada', [])) == 1 and q['codtemporada'][0].isdigit():
            links.append((url, q['codtemporada'][0]))
    links = list(dict.fromkeys(links))
    if len(links) != 1:
        raise ValueError('No se identifica una ficha de competición y temporada del equipo; alta pendiente')
    teams = {h.get_text(' ', strip=True) for h in soup.select('span.la_roja_regular_titulo1') if h.get_text(' ',strip=True)}
    if len(teams) != 1:
        raise ValueError('No se identifica un único equipo en la ficha oficial')
    history_url, season_id = links[0]
    history = BeautifulSoup(client.get(history_url), 'html.parser')
    scopes = []
    for row in history.select('tr'):
        table = row.find_parent('table')
        heading = table.find_previous('h4') if table else None
        if not heading or heading.get_text(' ', strip=True) != season:
            continue
        comp = row.select_one('a[href*="NFG_VisCompeticiones_Vis"]')
        group = row.select_one('a[href*="NFG_VisCompeticiones_Grupo"]')
        label = row.select_one('a[href*="NFG_VisGrupos_Vis"]')
        if not comp or not group or not label:
            continue
        _, c = official_link(history_url, comp['href'], 'NFG_VisCompeticiones_Vis')
        group_url, g = official_link(history_url, group['href'], 'NFG_VisCompeticiones_Grupo')
        _, l = official_link(history_url, label['href'], 'NFG_VisGrupos_Vis')
        if (g.get('codequipo') == [team_id] and len(g.get('codgrupo', [])) == 1
                and g['codgrupo'][0].isdigit() and l.get('codgrupo') == g['codgrupo']
                and len(c.get('codcompeticion', [])) == 1 and c['codcompeticion'][0].isdigit()):
            scopes.append({'competition_id':c['codcompeticion'][0], 'group_id':g['codgrupo'][0],
                           'season_id':season_id, 'competition_label':comp.get_text(' ',strip=True)+' · '+label.get_text(' ',strip=True)})
    if len(scopes) != 1:
        raise ValueError('No se identifica una única competición del equipo en la temporada actual; alta pendiente')
    result = scopes[0]
    result.update(team_id=team_id, team=teams.pop())
    return result
