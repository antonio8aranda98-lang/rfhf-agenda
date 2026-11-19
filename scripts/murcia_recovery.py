"""Recover public FFRM reports independently of transient calendar failures."""
import copy
import re
import urllib.error
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from federation_acts import norm, public_digits


def transient(error):
    if isinstance(error, urllib.error.HTTPError):return error.code in (500,502,503,504)
    return isinstance(error,(urllib.error.URLError,TimeoutError,ConnectionError)) or (
        isinstance(error,ValueError) and 'respuesta vacía' in str(error))


def previous_calendar(player):
    """Only this verified player's exact team, competition and season qualify."""
    matches=[copy.deepcopy(m) for m in player.get('_previous',[]) if
            player['id'] in m.get('player_ids',[]) and m.get('federation')=='murcia' and
            m.get('season')==player.get('season') and
            str(m.get('competition_id'))==str(player.get('competition_id')) and
            str(m.get('group_id'))==str(player.get('group_id')) and
            player['team_id'] in (m.get('home_team_id'),m.get('away_team_id')) and
            type(m.get('round')) is int and m['round']>0]
    for match in matches:
        match['player_ids']=[player['id']]
        for field in ('participation','participation_checked_at','participation_attempted_at','participation_source'):
            match[field]={pid:value for pid,value in match.get(field,{}).items() if pid==player['id']}
    return matches


def report_url(value):
    """A previously found public report can be read without its round index."""
    u=urlparse(str(value or ''));q=parse_qs(u.query)
    ids=q.get('CodActa',q.get('cod_acta',[]))
    if (u.scheme!='https' or u.hostname!='www.ffrm.es' or u.username or u.password or
        u.port not in (None,443) or u.fragment or u.path!='/pnfg/NPcd/NFG_CmpPartido' or
        set(q)-{'cod_primaria','CodActa','cod_acta'} or any(len(v)!=1 for v in q.values()) or
        q.get('cod_primaria',['1000120'])!=['1000120'] or len(ids)!=1 or not ids[0].isdigit() or
        any(v!=ids[0] for k in ('CodActa','cod_acta') for v in q.get(k,[]))):return None
    return u.geturl()


def validate_report(html,player,match):
    """Never attach stats from a default round, other season or changed score."""
    soup=BeautifulSoup(html,'html.parser')
    heading=next((h.get_text(' ',strip=True) for h in soup.select('h5')
                  if re.search(r'Temporada\s+\d{4}-\d{4}',h.get_text())), '')
    season=re.search(r'Temporada\s+(\d{4}-\d{4})',heading)
    rnd=re.search(r'Jornada\s+(\d+)\b',heading)
    date=re.search(r'\b(\d{2}-\d{2}-\d{4})\b',heading)
    if (not season or season[1]!=player.get('season') or not rnd or
        int(rnd[1])!=match.get('round') or not date or
        datetime.strptime(date[1],'%d-%m-%Y').date().isoformat()!=match.get('date')):
        raise ValueError('El acta no confirma temporada, jornada y fecha del partido')
    sides=[d for d in soup.select('div.details') if d.select_one('.number') and
           any(h.get_text(' ',strip=True)=='Titulares' for h in d.find_all(['h4','h5']))]
    names=[norm(d.select_one('.number').get_text(' ',strip=True)) for d in sides]
    if names!=[norm(match['home']),norm(match['away'])]:
        raise ValueError('El acta no confirma los dos equipos del partido')
    score=soup.select_one('h2.ntype')
    glyphs=score.select('strong > i') if score else []
    if len(glyphs)==2:
        values=[public_digits(node,soup) for node in glyphs]
    else:
        text=score.get_text(' ',strip=True) if score else ''
        plain=re.fullmatch(r'(\d+)\s*-\s*(\d+)',text)
        values=[int(plain[1]),int(plain[2])] if plain else [None,None]
    if None in values or values!=[match.get('score_home'),match.get('score_away')]:
        raise ValueError('El marcador del acta no coincide con el calendario; se conserva la participación anterior')
    return soup
