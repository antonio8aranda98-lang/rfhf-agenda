"""Resolve owner-selected second teams without changing a player's registration."""
import copy
from urllib.parse import parse_qs, urlparse
from bs4 import BeautifulSoup


def resolve(client, player, sources, season):
    from registry import official_url, name_key
    from categories import team_category, verify_category
    from sync import normalized
    if not isinstance(sources, list) or len(sources)>2 or len(set(sources))!=len(sources):
        raise ValueError('Selecciona como máximo dos equipos adicionales distintos')
    if player['federation'] not in ('valencia','murcia'):
        raise ValueError('La selección de equipos adicionales admite FFCV y FFRM')
    extras=[]
    if player['federation']=='valencia':
        from valencia_data import PublicFFCV
        api=PublicFFCV(client)
        data=api.get('jugadores/jugador_api.php',codigo=player['player_id'],cod_temporada=player['season_id'])
        if data.get('nombre_temporada')!=season or name_key(data.get('nombre_jugador',''))!=name_key(player['official_name']):
            raise ValueError('La ficha individual no confirma identidad y temporada')
        primary=api.get('equipos/ver_equipo.php',codequipo=player['team_id'])
        for source in sources:
            u=official_url(source,'valencia');tid=parse_qs(u.query).get('cod_equipo',[''])[0]
            if not tid.isdigit() or tid==player['team_id']:raise ValueError('El segundo equipo debe ser distinto del equipo principal')
            team=api.get('equipos/ver_equipo.php',codequipo=tid)
            scopes=[c for c in data.get('competiciones_participa',[]) if str(c.get('codequipo'))==tid]
            if str(team.get('codigo_equipo'))!=tid or not primary.get('codigo_club') or team.get('codigo_club')!=primary['codigo_club'] or len(scopes)!=1:
                raise ValueError('La ficha aún no confirma una competición del segundo equipo del mismo club')
            c=scopes[0]
            extras.append(dict(team_id=tid,team=c['nombre_equipo'],competition_id=str(c['codigo_competicion']),group_id=str(c['codgrupo']),season_id=player['season_id'],competition_label=c['nombre_competicion']+' · '+c['nombre_grupo'],team_source=u.geturl(),participation_evidence='official-player-scope'))
    else:
        from murcia_registration import discover_scope
        def page(source):return BeautifulSoup(client.get(source),'html.parser')
        def club(soup):
            ids={parse_qs(urlparse(a['href']).query).get('codigo_club',[''])[0] for a in soup.select('a[href*="NFG_VerClub"]')}
            return next(iter(ids)) if len(ids)==1 and all(ids) else None
        primary=page(player['source']);club_id=club(primary)
        if normalized(player['official_name']) not in normalized(primary.get_text(' ',strip=True)):
            raise ValueError('La plantilla principal no confirma al jugador')
        for source in sources:
            u=official_url(source,'murcia');tid=parse_qs(u.query).get('Codigo_Equipo',[''])[0]
            if not tid.isdigit() or tid==player['team_id']:raise ValueError('El segundo equipo debe ser distinto del equipo principal')
            soup=page(u.geturl())
            if not club_id or club(soup)!=club_id:raise ValueError('No se verifica que ambos equipos pertenezcan al mismo club')
            scope=discover_scope(client,soup,u.geturl(),tid,season)
            scope.update(team_source=u.geturl(),participation_evidence='owner-confirmed')
            extras.append(scope)
    for item in extras:
        category=team_category(item['competition_label'])
        item.update(team_age_category=category,match_duration=verify_category(player.get('age_category'),category),role='additional',owner_selected=True)
    return extras


def collect(client, player, result, adapter):
    from sync import team_matches, now
    extras=[]
    for scope in player.get('additional_teams',[]):
        item=copy.deepcopy(scope)
        derived={**player,**scope,'source':scope['team_source'],'additional_teams':[],
                 '_additional_scope':True,'_previous':team_matches(player.get('_previous',[]),scope)}
        try:
            extra=adapter(client,derived)
            if not extra['matches']:raise ValueError('Calendario adicional vacío')
            result['matches'].extend(extra['matches'])
            item.update(calendar_status='ok',updated_at=now(),calendar_complete=extra.get('calendar_complete',True))
        except Exception:
            previous=derived['_previous']
            result['matches'].extend(copy.deepcopy(previous))
            item.update(calendar_status='pending',updated_at=max((m.get('updated_at') or '' for m in previous),default=None))
            result['source_warning']=True
        extras.append(item)
    if extras:result['additional_teams']=extras
    return result
