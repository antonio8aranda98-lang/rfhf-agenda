"""Reviewed official alternatives for the BeSoccer teams in Antonio's portfolio.

The view/collaborator stays independent of the data publisher. No browser IDs or
untrusted URLs select an endpoint: mappings are reviewed, identities are rechecked.
"""
import copy
import re
import json
import subprocess
import atexit
import hashlib
from datetime import datetime,timezone
from urllib.parse import urlencode, urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from federation_acts import norm, public_digits
from player_stats import absent, participation

PROVIDERS = {
    'rfef': {'label':'RFEF', 'base':'https://rfef.es', 'reports':'https://resultados.rfef.es', 'competition':'33836116','group':'33836121','season':'22'},
    'ffcm': {'label':'FFCM', 'base':'https://www.ffcm.es', 'competition':'22916199','group':'22916200','season':'22'},
    'rfcylf': {'label':'RFCYLF', 'base':'https://www.rfcylf.es', 'competition':'24218934','group':'24218935','season':'22'},
    'frf': {'label':'FRF', 'base':'https://www.frfutbol.com', 'competition':'21959328','group':'21959329','season':'22'},
}
# Exact source + full-name mappings. A new club/season needs its own review.
TEAMS = {
    'trival-valderas-juvenil': ('rfef','23289692','CF Trival Valderas Alcorcón', {'Sidi Neculae Sinayoko Budaca':'SINAYOKO BUDACA, SIDI NECULAE'}),
    'ad-sporting-hortaleza-a-juvenil': ('rfef','23289693','AD Sporting Hortaleza', {'Tiago Arzeno Rosso':'ARZENO ROSSO, TIAGO','Brodie David Briceno':'BRICENO, BRODIE DAVID'}),
    'cd-alameda-mesa-team-juvenil': ('ffcm','1857647','C.D. ALAMEDA DE LA SAGRA E.M.F.', {'Alex Silva Lareu':'SILVA LAREU, ALEX'}),
    'cd-azuqueca': ('ffcm','33272','C.D. AZUQUECA SAD', {'Alvaro Contera Gil':'CONTERA GIL, ALVARO'}),
    'cd-isoba-juvenil': ('rfcylf','15245','C.D. Isoba', {'Tihago Edu Uribe Faiffer':'URIBE FAIFFER, TIHAGO EDU'}),
    'cd-alfaro': ('frf','2007200301','ALFARO', {'Timoteo Mba Edu Masa':'MBA EDU MASA, TIMOTEO','Jordi Julia Urchaga':'JULIA I URCHAGA, JORDI'}),
    'cdfc-calzada': ('frf','2007214201','LA CALZADA', {'Javier Rullan Serrano':'RULLAN SERRANO, JAVIER'}),
}
IDENTITY_REPORTS = {
    'RULLAN SERRANO JAVIER':'https://www.frfutbol.com/pnfg/NPcd/NFG_CmpPartido?cod_primaria=1000120&CodActa=258627&cod_acta=258627',
    'CONTERA GIL ALVARO':'https://www.ffcm.es/pnfg/NPcd/NFG_CmpPartido?cod_primaria=1000120&CodActa=592872&cod_acta=592872',
}
ADAPTER_VERSION=2


def alternative(request, season):
    u = urlparse(str(request.get('source','')))
    if season != '2026-2027' or u.scheme != 'https' or u.hostname != 'es.besoccer.com' or u.query or u.fragment or u.username or u.password or u.port not in (None,443):
        return None
    m = re.fullmatch(r'/equipo/([a-zA-Z0-9_-]+)/?',u.path)
    entry = TEAMS.get(m[1]) if m else None
    if not entry:return None
    provider, team_id, team, names = entry
    official = [v for k,v in names.items() if norm(k)==norm(request.get('name'))]
    if len(official)!=1:return None
    return {'provider':provider,'external_team_id':team_id,'team_id':provider+'-'+team_id,
            'team':team,'official_name':official[0], 'source_request':request['source'],
            'source_acronym':PROVIDERS[provider]['label'],'official_season':season}


def client_for(shared, provider):
    from sync import Client
    if not hasattr(shared,'official_clients'):shared.official_clients={}
    if provider not in shared.official_clients:shared.official_clients[provider]=Client(PROVIDERS[provider]['base'])
    return shared.official_clients[provider]


_browser=None


def browser_page(url):
    """One ordinary Chrome process per sync, only for empty public responses."""
    global _browser
    from sync import ROOT
    if _browser is None or _browser.poll() is not None:
        _browser=subprocess.Popen(['node',str(ROOT/'scripts/official-browser.mjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,bufsize=1)
    _browser.stdin.write(json.dumps({'url':url})+'\n');_browser.stdin.flush()
    line=_browser.stdout.readline(12_000_000)
    if not line:raise ValueError('No se ha podido iniciar el lector público de navegador')
    result=json.loads(line)
    if not isinstance(result.get('html'),str):raise ValueError(result.get('error','Consulta de navegador incompleta'))
    return result['html']


def close_browser():
    global _browser
    if _browser is not None:
        try:_browser.stdin.close()
        except OSError:pass
        try:_browser.wait(timeout=8)
        except subprocess.TimeoutExpired:_browser.terminate()
        _browser=None


atexit.register(close_browser)


def page(client, url):
    """No browser retry for a denied request or an authentication challenge."""
    try:return client.get(url)
    except ValueError as error:
        if 'respuesta vacía' not in str(error):raise
        html=browser_page(url)
        client.cache[url]=html
        return html


def round_url(provider, number):
    p=PROVIDERS[provider]
    if provider=='rfef':
        return p['base']+'/es/resultados?'+urlencode({'competition':p['competition'],'group':p['group'],'journey':number,'season':p['season']})
    return p['base']+'/pnfg/NPcd/NFG_CmpJornada?'+urlencode({'cod_primaria':'1000120','CodCompeticion':p['competition'],'CodGrupo':p['group'],'CodTemporada':p['season'],'CodJornada':number})


def report_url(value, provider):
    p=PROVIDERS[provider];u=urlparse(urljoin(p.get('reports',p['base']),value))
    act=parse_qs(u.query).get('CodActa',parse_qs(u.query).get('cod_acta',['']))[0]
    if u.scheme!='https' or u.hostname!=urlparse(p.get('reports',p['base'])).hostname or u.path!='/pnfg/NPcd/NFG_CmpPartido' or not act.isdigit():
        raise ValueError('Enlace de acta oficial no válido')
    return u.geturl(),act


def displayed_score(node, soup):
    node=copy.deepcopy(node)
    for text in list(node.find_all(string=True)):
        if text.parent.name not in ('style','script') and str(text).strip()=='-':text.replace_with('')
    return public_digits(node,soup)


def parse_round(html, player, number, source):
    from sync import fixture, iso_date, http_time
    soup=BeautifulSoup(html,'html.parser');provider=player['provider'];result=[]
    if provider=='rfef':
        cards=[]
        for a in soup.select('a[href*="NFG_CmpPartido"]'):
            card=a.find_parent('div',class_='row')
            if card:cards.append((a,card.parent))
        for a,card in cards:
            names=card.select('img[alt]')
            if len(names)!=2 or norm(player['team']) not in [norm(n.get('alt')) for n in names]:continue
            teams=[n['alt'] for n in names]
            dt=re.search(r'(\d{2}/\d{2}/\d{4})(?:\s*-\s*(\d{1,2}:\d{2}))?',card.get_text(' ',strip=True))
            if not dt:raise ValueError('Partido RFEF sin fecha verificable')
            scores=card.select_one('.text-lg');score=re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*',scores.get_text() if scores else '')
            url,act=report_url(a['href'],provider)
            loc=card.select_one('.col-md-3 .d-flex')
            ids=[re.search(r'/(\d+)_50x50',n.get('src','')) for n in names]
            if not all(ids):raise ValueError('RFEF no identifica los equipos del encuentro')
            result.append(fixture(player['federation'],player,provider+'-'+act,*teams,iso_date(dt[1]),http_time(dt[2]),url,
                provider=provider,round=number,venue=loc.get_text(' ',strip=True) if loc else None,
                status='finished' if score else 'scheduled' if http_time(dt[2]) else 'time_pending',score_home=int(score[1]) if score else None,score_away=int(score[2]) if score else None,
                home_team_id=provider+'-'+ids[0][1],away_team_id=provider+'-'+ids[1][1],
                home_logo=urljoin(source,names[0]['src']),away_logo=urljoin(source,names[1]['src'])))
    else:
        for a in soup.select('a[href*="NFG_CmpPartido"]'):
            row=a.find_parent('tr')
            if not row:continue
            teams=row.select('a[href*="NFG_VisEquipos"]')
            ids=[parse_qs(urlparse(x['href']).query).get('Codigo_Equipo',[''])[0] for x in teams]
            if len(ids)!=2 or player['external_team_id'] not in ids:continue
            times=[n.get_text(' ',strip=True) for n in row.select('.horario')]
            date=next((iso_date(t) for t in times if iso_date(t)),None)
            hour=next((http_time(t) for t in times if http_time(t)),None)
            if not date:raise ValueError('Partido oficial sin fecha verificable')
            scores=row.select('.wid2_resultado_cerrada');values=[displayed_score(n,soup) for n in scores]
            closed=len(values)==2 and all(x is not None for x in values)
            if scores and not closed:raise ValueError('Marcador oficial no verificable')
            url,act=report_url(a['href'],provider);venue_row=row.find_next_sibling('tr')
            field=venue_row.select_one('a[href*="NFG_VisCampos"]') if venue_row else None
            logos=row.select('.escudo_widgetL img,.escudo_widgetV img')
            result.append(fixture(player['federation'],player,provider+'-'+act,teams[0].get_text(' ',strip=True),teams[1].get_text(' ',strip=True),date,hour,url,
                provider=provider,round=number,status='finished' if closed else 'scheduled' if hour else 'time_pending',
                score_home=values[0] if closed else None,score_away=values[1] if closed else None,
                venue=field.get_text(' ',strip=True) if field else None,home_team_id=provider+'-'+ids[0],away_team_id=provider+'-'+ids[1],
                home_logo=urljoin(source,logos[0]['src']) if len(logos)==2 else None,away_logo=urljoin(source,logos[1]['src']) if len(logos)==2 else None))
    return result


def calendar_url(provider, extended=True):
    p=PROVIDERS[provider]
    url=p.get('reports',p['base'])+'/pnfg/NPcd/NFG_VisCalendario_Vis?'+urlencode({'cod_primaria':'1000120','codcompeticion':p['competition'],'codgrupo':p['group'],'codtemporada':p['season']})
    return url+('&CDetalle=1' if extended else '')


def stable_id(player, number, home, away):
    return player['federation']+'-'+player['provider']+'-'+PROVIDERS[player['provider']]['group']+'-'+str(number)+'-'+norm(home).replace(' ','-')+'-'+norm(away).replace(' ','-')


def parse_calendar(html, player, source, extended=True):
    from sync import fixture, iso_date, http_time
    soup=BeautifulSoup(html,'html.parser');games=[]
    title=next((h for h in soup.select('h4') if re.search(r'Temporada\s+'+re.escape(player['season']),h.get_text(' ',strip=True))),None)
    if not title:raise ValueError('La federación no confirma la temporada actual del calendario')
    label=re.sub(r'\s*Temporada\s+'+re.escape(player['season'])+r'.*$','',title.get_text(' ',strip=True))
    if extended:
        records=[]
        for card in soup.select('.card-body'):
            h=card.select_one('h5.card-title');rnd=re.search(r'Jornada\s+(\d+)',h.get_text() if h else '')
            if not rnd:continue
            records.extend((int(rnd[1]),row,None) for row in card.select('div.row') if len(row.select('table tr td'))==3)
    else:
        records=[];rnd=None;date=None
        for row in soup.select('tr'):
            header=row.find('th');m=re.search(r'Jornada\s+(\d+)\s*\((\d{2}-\d{2}-\d{4})\)',header.get_text(' ',strip=True) if header else '')
            if m:rnd=int(m[1]);date=iso_date(m[2])
            if rnd and len(row.find_all('td',recursive=False))==3:records.append((rnd,row,date))
    for number,row,round_date in records:
        cells=row.select('table tr td') if extended else row.find_all('td',recursive=False)
        home,away=(cells[i].get_text(' ',strip=True) for i in (0,2))
        if norm(player['team']) not in (norm(home),norm(away)):continue
        scores=cells[1].find_all('strong',recursive=False);values=[public_digits(n,soup) for n in scores] if len(scores)==2 else [None,None]
        closed=all(v is not None for v in values)
        details=row.select_one('.right') if extended else None;text=details.get_text(' ',strip=True) if details else ''
        dt=re.search(r'(\d{2}-\d{2}-\d{4})(?:\s*-\s*(\d{1,2}:\d{2}))?',text)
        date=iso_date(dt[1]) if dt else round_date;hour=http_time(dt[2]) if dt else None
        if not date:raise ValueError('Partido oficial sin fecha verificable')
        game=fixture(player['federation'],player,'temporary',home,away,date,hour,source,
            provider=player['provider'],round=number,status='finished' if closed else 'scheduled' if hour else 'time_pending',
            venue=text[:dt.start()].strip(' -\xa0') if dt else None,score_home=values[0] if closed else None,score_away=values[1] if closed else None,
            date_precision='match' if dt else 'round')
        game['id']=stable_id(player,number,home,away)
        for side in ('home','away'):
            if norm(game[side])==norm(player['team']):game[side+'_team_id']=player['team_id']
        games.append(game)
    if len(games)<20:raise ValueError('Calendario oficial incompleto o equipo no identificado')
    return games,label


def calendar(client, player):
    failure=None
    for extended in (True,False):
        source=calendar_url(player['provider'],extended)
        try:return parse_calendar(page(client,source),player,source,extended)
        except Exception as error:failure=error
    if player['provider']!='rfef':
        p=PROVIDERS[player['provider']]
        source=p['base']+'/pnfg/NPcd/NFG_VisCompeticiones_Grupo?'+urlencode({'cod_primaria':'1000123','codequipo':player['external_team_id'],'codgrupo':p['group']})
        try:return parse_team_calendar(page(client,source),player,source)
        except Exception as error:failure=error
    raise failure


def parse_team_calendar(html, player, source):
    from sync import fixture,iso_date,http_time
    soup=BeautifulSoup(html,'html.parser');games=[]
    title=next((h for h in soup.select('h5') if 'Temporada' in h.get_text() and player['season'] in h.get_text()),None)
    team=next((h for h in soup.select('h4') if norm(h.get_text(' ',strip=True))==norm(player['team'])),None)
    if not title or not team:raise ValueError('Ficha de grupo sin equipo y temporada verificables')
    label=re.sub(r'\s*Temporada.*$','',title.get_text(' ',strip=True)).replace('Grupo:','·')
    for row in soup.select('tr'):
        cells=row.find_all('td',recursive=False)
        if len(cells)!=3:continue
        number=cells[0].get_text(strip=True);lines=[h.get_text(' ',strip=True) for h in cells[1].select('h5')]
        if not number.isdigit() or len(lines)!=3:continue
        dt=re.search(r'(\d{2}-\d{2}-\d{4})(?:\s+(\d{1,2}:\d{2}))?',lines[2])
        if not dt:raise ValueError('Ficha de grupo con partido sin fecha')
        home,away=lines[:2]
        if norm(player['team']) not in (norm(home),norm(away)):raise ValueError('La ficha de grupo mezcla otro equipo')
        values=cells[2].select('b');score=[public_digits(n,soup) for n in values] if len(values)==2 else [None,None]
        closed=all(n is not None for n in score);hour=http_time(dt[2])
        m=fixture(player['federation'],player,'temporary',home,away,iso_date(dt[1]),hour,source,provider=player['provider'],round=int(number),
            status='finished' if closed else 'scheduled' if hour else 'time_pending',score_home=score[0] if closed else None,score_away=score[1] if closed else None,date_precision='match' if hour else 'round')
        m['id']=stable_id(player,int(number),home,away)
        for side in ('home','away'):
            if norm(m[side])==norm(player['team']):m[side+'_team_id']=player['team_id']
        games.append(m)
    if len(games)<20:raise ValueError('Ficha de grupo sin calendario completo')
    return games,label


def sides_in_act(soup):
    return [d for d in soup.select('div.details') if d.select_one('.number') and any(h.get_text(' ',strip=True)=='Titulares' for h in d.select('h4,h5'))]


def lineup(side):
    result={}
    for label in ('Titulares','Suplentes'):
        h=next((h for h in side.select('h4,h5') if h.get_text(' ',strip=True)==label),None)
        if not h:raise ValueError('Acta sin alineación completa')
        table=h.find_next('table');names=[]
        for tr in table.select('tr'):
            cells=tr.find_all('td',recursive=False)
            if len(cells)>=2 and cells[0].get_text(strip=True).isdigit():names.append(cells[-1].get_text(' ',strip=True))
        result[label]=names
    if len(result['Titulares'])!=11:raise ValueError('Acta sin once titulares verificables')
    return result


def clean_name(text):
    return norm(re.sub(r'^\([^)]*\)\s*','',text))


def parse_act(html, player):
    soup=BeautifulSoup(html,'html.parser');sides=sides_in_act(soup)
    if len(sides)!=2:raise ValueError('Acta sin dos equipos verificables')
    indexes=[i for i,s in enumerate(sides) if norm(s.select_one('.number').get_text(' ',strip=True))==norm(player['team'])]
    if len(indexes)!=1:raise ValueError('El acta no corresponde al equipo configurado')
    index=indexes[0];side=sides[index];names=lineup(side);wanted=norm(player['official_name'])
    starter=wanted in [norm(x) for x in names['Titulares']];bench=wanted in [norm(x) for x in names['Suplentes']]
    if not starter and not bench:return absent()
    if starter and bench:raise ValueError('Jugador duplicado en el acta')
    headers={h.get_text(' ',strip=True):h for h in side.select('h4,h5')}
    if player['provider']=='rfef':
        substitutions=[h for h in soup.select('h4') if h.get_text(' ',strip=True)=='Sustituciones']
        cards=[h for h in soup.select('h4') if h.get_text(' ',strip=True)=='Tarjetas']
        sub_header=substitutions[index] if len(substitutions)==2 else None
        card_scope=cards[index].find_next('table') if len(cards)==2 else None
    else:
        sub_header=headers.get('Sustituciones')
        card_scope=headers['Tarjetas'].find_next('table') if 'Tarjetas' in headers else None
    entries=[];exits=[];reds=[]
    substitutions_complete=sub_header is not None
    if sub_header:
        tables=[]
        for node in sub_header.next_siblings:
            if getattr(node,'name',None) in ('h4','h5'):break
            if getattr(node,'name',None)=='table':tables.append(node)
        for table in tables:
            enters=table.select('i.fa-arrow-left,i.fa-arrow-up-long');leaves=table.select('i.fa-arrow-right,i.fa-arrow-down-long')
            if len(enters)!=1 or len(leaves)!=1:
                substitutions_complete=False;continue
            erow=enters[0].find_parent('tr');lrow=leaves[0].find_parent('tr')
            m=re.search(r"(\d+)(?:['’]?\s*\+\s*\d+)?['’]",table.get_text(' ',strip=True));minute=m[1] if m else '?'
            if any(clean_name(td.get_text(' ',strip=True))==wanted for td in erow.find_all('td',recursive=False)):entries.append(minute)
            if any(clean_name(td.get_text(' ',strip=True))==wanted for td in lrow.find_all('td',recursive=False)):exits.append(minute)
    if card_scope:
        for row in card_scope.select('tr'):
            cells=row.find_all('td',recursive=False)
            if not cells or clean_name(cells[-1].get_text(' ',strip=True))!=wanted:continue
            markers=' '.join(im.get('src','') for im in row.select('img'))
            if re.search(r'tarj_(?:roja|roja2|doble)',markers):
                m=re.search(r'(\d+)',row.get_text(' ',strip=True));reds.append(m[1] if m else '?')
            elif not re.search(r'tarj_amar',markers):reds.append('?')
    goals=None
    block=next((d for d in soup.select('div.details') if d.select_one('.number') and d.select_one('.number').get_text(strip=True)=='Goles'),None)
    if block:
        goals=0
        for row in block.select('tr'):
            cells=row.find_all('td',recursive=False)
            if len(cells)<2 or clean_name(cells[-1].get_text(' ',strip=True))!=wanted:continue
            marker=row.find('a',title=True)
            if marker and 'propia' in marker['title'].lower():continue
            if not marker or marker['title'] not in ('Gol normal','Gol de penalti','Gol penalti'):goals=None;break
            goals+=1
    result=participation(starter,player['match_duration'],entries,exits,reds,goals)
    if not substitutions_complete or card_scope is None:result.update(minutes=None,played=None)
    return result


def adapter(client, player, previous=()):
    if player.get('official_season')!=player['season']:raise ValueError('Revisar la fuente oficial para la nueva temporada')
    if not player.get('_verify_identity') and not any(player['id'] in m.get('player_ids',[]) for m in previous):
        cached=initial_snapshot(player)
        if cached:return cached
    games,label=calendar(client,player);calendar_source=games[0]['source'];identity=False;logo=None;warnings=[]
    from sync import MADRID
    today=datetime.now(MADRID).date()
    for game in games:
        # Calendar gives the real date/field when extended. Journals supply report
        # links and refresh upcoming details; an unavailable report is not zero.
        if game['status']=='finished' or abs((datetime.fromisoformat(game['date']).date()-today).days)<=7:
            try:
                refs=parse_round(page(client,round_url(player['provider'],game['round'])),player,game['round'],round_url(player['provider'],game['round']))
                ref=next((r for r in refs if norm(r['home'])==norm(game['home']) and norm(r['away'])==norm(game['away'])),None)
                if ref:
                    identity_id=game['id'];game.update(ref);game['id']=identity_id;game['date_precision']='match'
            except Exception:pass
        if game.get('home_team_id')==player['team_id']:logo=game.get('home_logo') or logo
        else:logo=game.get('away_logo') or logo
        if game['status']!='finished':continue
        try:
            if '/NFG_CmpPartido' not in game['source']:raise ValueError('Acta no disponible en la jornada')
            html=page(client,game['source']);soup=BeautifulSoup(html,'html.parser')
            if not any(re.search(r'Temporada\s*'+re.escape(player['season']),h.get_text(' ',strip=True)) for h in soup.select('h4,h5')):
                raise ValueError('Acta de otra temporada')
            record=parse_act(html,player);game['participation'][player['id']]=record
            if record['called_up']==1:identity=True
        except Exception:
            warnings.append(game['round'])
    if player.get('_verify_identity'):
        # Membership at the exact official club is also enough when the player
        # has not yet been called up. It never supplies appearance/minute totals.
        provider=player['provider']
        anchor=IDENTITY_REPORTS.get(norm(player['official_name']))
        if anchor and not identity:
            try:
                html=page(client,anchor);soup=BeautifulSoup(html,'html.parser')
                if any(re.search(r'Temporada\s*'+re.escape(player['season']),h.get_text(' ',strip=True)) for h in soup.select('h4,h5')):
                    identity=parse_act(html,player)['called_up']==1
            except Exception:pass
        if provider!='rfef' and not identity:
            u=PROVIDERS[provider]['base']+'/pnfg/NPcd/NFG_VisEquipos?'+urlencode({'cod_primaria':'1000119','Codigo_Equipo':player['external_team_id']})
            soup=BeautifulSoup(page(client,u),'html.parser')
            for table in soup.select('table'):
                if table.find(string=lambda t:t and re.fullmatch(r'\s*Jugadores\s*\(\d+\)\s*',t)):
                    names=[td.get_text(' ',strip=True) for td in table.select('td')]
                    if sum(norm(n)==norm(player['official_name']) for n in names)==1:identity=True
        if not identity:raise ValueError('Calendario localizado; falta confirmar la identidad en plantilla o actas oficiales')
    from sync import new_stats
    return {'matches':games,'stats':new_stats(),'logo':logo,'competition_label':label,'source':calendar_source,
            'stats_note':'Datos de '+PROVIDERS[player['provider']]['label']+'. Convocatorias, titulares, suplentes, minutos reglamentarios y goles según actas verificadas. Sin añadido.'+(' Las fechas sin hora del calendario básico son fechas de jornada; el día del encuentro queda por confirmar.' if any(m.get('date_precision')=='round' for m in games) else '')+(' Hay actas pendientes de lectura.' if warnings else '')}


def resolve(shared, request, season):
    config=alternative(request,season)
    if not config:return None
    from categories import verify_category,team_category
    config.update(id='verify',federation=request['federation'],name=request['name'],collaborator=request['collaborator'],season=season,match_duration=90)
    config['source']=round_url(config['provider'],1)
    result=adapter(client_for(shared,config['provider']),{**config,'_verify_identity':True})
    config.update(source=result['source'],competition_label=result['competition_label'],team_age_category=team_category(result['competition_label']),active=True)
    config['match_duration']=verify_category(request.get('age_category'),config['team_age_category'])
    if request.get('age_category'):config['age_category']=request['age_category']
    config['official_adapter_version']=ADAPTER_VERSION
    save_initial_snapshot(config,result)
    config.pop('season')
    return config


def snapshot_path(player):
    from sync import ROOT
    identity=[player['provider'],player['team_id'],player['official_name'],player.get('season') or player['official_season'],player['source_request']]
    key=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
    return ROOT/'.cache'/'official-initial'/(key+'.json')


def save_initial_snapshot(player,result):
    from sync import now
    path=snapshot_path(player);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'read_at':now(),'player_id':player['id'],'result':result},ensure_ascii=False))


def initial_snapshot(player):
    path=snapshot_path(player)
    if not path.exists():return None
    try:
        snapshot=json.loads(path.read_text());stamp=datetime.fromisoformat(snapshot['read_at'])
        age=(datetime.now(timezone.utc)-stamp).total_seconds()
        if not 0<=age<1800:return None
        result=snapshot['result'];old=snapshot['player_id'];new=player['id']
        for match in result['matches']:
            match['player_ids']=[new if id==old else id for id in match['player_ids']]
            for field in ('participation','participation_checked_at','participation_source'):
                if old in match.get(field,{}):match[field][new]=match[field].pop(old)
        result['checked_at']=snapshot['read_at']
        return result
    except (ValueError,KeyError,TypeError):return None
