"""Owner-authorized roster changes. Resolve identities before writing anything."""
import copy
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from bs4 import BeautifulSoup
from sync import ROOT, Client, FEDERATIONS, ADAPTERS, initial_data, normalized, now, apply_roster
from besoccer_data import is_besoccer, PublicBeSoccer, resolve as resolve_besoccer
from categories import team_category, verify_category


def text(value, label, limit=100):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= limit or any(ord(c) < 32 for c in value):
        raise ValueError(label + ': introduce un texto válido')
    return value.strip()


def official_url(value, federation, competition=False):
    """Never let a public issue turn the runner into an arbitrary URL fetcher."""
    u = urlparse(str(value))
    hosts = {'madrid': {'www.rffm.es', 'rffm.es'}, 'catalunya': {'www.fcf.cat', 'fcf.cat'},
             'murcia': {'www.ffrm.es', 'ffrm.es'}, 'valencia': {'ffcv.es', 'www.ffcv.es'}}
    if federation not in hosts or u.scheme != 'https' or u.hostname not in hosts[federation] or u.port not in (None, 443) or u.username or u.password or u.fragment:
        raise ValueError('Usa un enlace HTTPS de la federación seleccionada')
    patterns = {'madrid': r'/fichaequipo/\d+', 'catalunya': r'/ca/clubs/[a-z0-9-]+/categories/[a-z0-9-]+',
                'murcia': r'/pnfg/NPcd/NFG_VisEquipos', 'valencia': r'/competiciones/equipos/equipo.php'}
    pattern = r'/competicion/calendario' if competition and federation == 'madrid' else r'/pnfg/NPcd/NFG_CmpJornada' if competition and federation == 'murcia' else patterns[federation]
    if not re.fullmatch(pattern, u.path) or len(str(value)) > 600:
        raise ValueError('El enlace debe ser la ficha oficial del equipo y categoría concretos')
    return u


def name_key(name):
    return sorted(normalized(name).split())


def unique_name(names, requested):
    found = [name for name in names if name_key(name) == name_key(requested)]
    if len(found) != 1:
        raise ValueError('No se identifica un único jugador con ese nombre completo en la plantilla. Revisa apellidos y equipo; el alta queda pendiente.')
    return found[0]


def rffm_player_url(value):
    u=urlparse(str(value))
    if u.scheme!='https' or u.hostname not in {'www.rffm.es','rffm.es'} or u.username or u.password or u.port not in (None,443) or u.query or u.fragment or not re.fullmatch(r'/fichajugador/\d+',u.path):
        raise ValueError('Usa la ficha individual HTTPS de la RFFM, sin filtros')
    return 'https://www.rffm.es'+u.path


def rffm_identity_matches(requested, official, player_id, team_id, season):
    if name_key(requested)==name_key(official):return True
    # Antonio confirmed this exact official spelling error on 18/11/2026.
    return (str(player_id)=='27492835' and str(team_id)=='12325489' and season=='2026-2027'
        and name_key(requested)==name_key('Jesus Alejandro Rosales Barrios')
        and name_key(official)==name_key('ROSALES BARRIOS, JESUS ALEJADRO'))


def prove_rffm_participation(client,player,matches):
    for match in sorted((m for m in matches if m['status']=='finished'),key=lambda m:m.get('date') or '',reverse=True):
        try:game=client.next_props(match['source'])['game']
        except Exception:continue
        if game.get('acta_cerrada')!='1':continue
        side='local' if str(game.get('codigo_equipo_local'))==player['team_id'] else 'visitante' if str(game.get('codigo_equipo_visitante'))==player['team_id'] else None
        if side and any(str(row.get('codjugador'))==player['player_id'] for row in game.get('jugadores_equipo_'+side,[])):
            return match['source']
    raise ValueError('La ficha identifica al jugador, pero aún no se confirma participación con el equipo seguido en sus actas')


def resolve_player(request, roster, client=None):
    fid = request.get('federation')
    if fid not in FEDERATIONS:
        raise ValueError('Selecciona una federación de la agenda')
    name = text(request.get('name'), 'Nombre completo')
    collaborator = text(request.get('collaborator'), 'Colaborador')
    duration = request.get('match_duration')
    if type(duration) is not int or duration not in (60, 70, 80, 90):
        raise ValueError('Selecciona la duración reglamentaria de la categoría')
    from official_sources import resolve as resolve_official
    alternative = resolve_official(client or Client('https://es.besoccer.com'), request, roster['season'])
    if alternative:
        return alternative
    if is_besoccer(request.get('source')):
        linked = resolve_besoccer(PublicBeSoccer(client or Client('https://es.besoccer.com')), request, roster['season'])
        result = {**linked, 'provider':'besoccer', 'source':linked['besoccer_team_source'],
                  'team':linked['besoccer_team'], 'team_id':'besoccer-'+linked['besoccer_team_id'],
                  'player_id':'besoccer-'+linked['besoccer_player_source'].rsplit('-',1)[1],
                  'competition_label':linked['besoccer_competition_label']}
        category = team_category(linked['besoccer_team']+' '+linked['besoccer_competition_label'])
        duration = verify_category(request.get('age_category'), category)
        result['team_age_category'] = category
        if request.get('age_category'): result['age_category'] = request['age_category']
        result.update(id=re.sub(r'[^a-z0-9]+', '-', normalized(name).lower()).strip('-')+'-'+fid+'-'+result['player_id'],
                      name=name, federation=fid, collaborator=collaborator, match_duration=duration, active=True)
        if any(p['federation']==fid and name_key(p['name'])==name_key(name) for p in roster['players']):
            raise ValueError('El jugador ya está registrado. Utiliza reactivar o cambiar sus fuentes.')
        return result
    u = official_url(request.get('source'), fid)
    client = client or Client(FEDERATIONS[fid][2])
    try:
        if fid != 'murcia':
            client.get(FEDERATIONS[fid][2])
    except Exception:
        pass
    q = parse_qs(u.query)
    if fid == 'madrid':
        team_id = u.path.rsplit('/', 1)[1]
        team = client.next_props(u.geturl())['team']
        members = team.get('jugadores_equipo', [])
        player_source=request.get('player_source')
        if player_source:
            source=rffm_player_url(player_source);player_id=source.rsplit('/',1)[1]
            pdata=client.next_props(source)['player'];official_name=pdata.get('nombre_jugador','')
            if not rffm_identity_matches(name,official_name,player_id,team_id,roster['season']):
                raise ValueError('El nombre facilitado no coincide con la ficha individual RFFM')
            if str(pdata.get('codigo_jugador'))!=player_id:raise ValueError('La ficha no confirma el identificador individual')
        else:
            official_name = unique_name([p['nombre'] for p in members], name)
            member = next(p for p in members if p['nombre'] == official_name)
            player_id = str(member['cod_jugador'])
            source = 'https://www.rffm.es/fichajugador/' + player_id
            pdata = client.next_props(source)['player']
        listed=any(str(p['cod_jugador'])==player_id for p in members)
        if pdata.get('nombre_temporada') != roster['season']:
            raise ValueError('La ficha no corresponde a la temporada de la agenda')
        scopes = [c for c in pdata.get('competiciones_participa', []) if str(c.get('codequipo')) == team_id]
        if not scopes and request.get('competition_source'):
            scope=official_url(request['competition_source'],fid,competition=True)
            params=parse_qs(scope.query)
            if set(params)-{'competicion','grupo','temporada','tipojuego'} or any(len(params.get(k,[]))!=1 or not params[k][0].isdigit() for k in ('competicion','grupo','temporada','tipojuego')) or params['tipojuego']!=['1']:
                raise ValueError('Revisa los filtros del calendario oficial RFFM')
            cal=client.next_props(scope.geturl())['calendar']
            present=any(team_id in (str(m.get('codigo_equipo_local')),str(m.get('codigo_equipo_visitante'))) for rnd in cal.get('rounds',[]) for m in rnd.get('equipos',[]))
            if cal.get('temporada')!=roster['season'] or params['temporada'][0]!=str(pdata['codigo_temporada']) or not present:
                raise ValueError('El calendario no confirma ese equipo y temporada')
            scopes=[{'codigo_competicion':params['competicion'][0],'codgrupo':params['grupo'][0],'nombre_competicion':cal['competicion'],'nombre_grupo':cal['grupo']}]
        if len(scopes) != 1:
            raise ValueError('La ficha no identifica una única competición para ese equipo')
        c = scopes[0]
        category = team_category(team.get('categoria', '')+' '+c['nombre_competicion'])
        duration = verify_category(request.get('age_category'), category)
        result = {'team_id': team_id, 'player_id': player_id, 'team': team['nombre_equipo'], 'source': source,
                  'competition_id': str(c['codigo_competicion']), 'group_id': str(c['codgrupo']),
                  'season_id': str(pdata['codigo_temporada']), 'official_name': official_name,
                  'competition_label': c['nombre_competicion'] + ' · ' + c['nombre_grupo'], 'team_age_category':category}
        if player_source:
            result.update(player_source=source,team_source=u.geturl(),registration_team=pdata.get('equipo'),requires_participation=not listed)
            other=[x for x in pdata.get('competiciones_participa',[]) if str(x.get('codequipo'))!=team_id and x.get('nombre_club') and normalized(x['nombre_club'])==normalized(c.get('nombre_club'))]
            if len(other)==1 and str(other[0].get('codequipo') or '').isdigit():
                x=other[0];registered=str(x['codequipo']);other_category=team_category(x['nombre_competicion'])
                result['additional_teams']=[{'team_id':registered,'team':x['nombre_equipo'],'competition_id':str(x['codigo_competicion']),'group_id':str(x['codgrupo']),'season_id':str(pdata['codigo_temporada']),'competition_label':x['nombre_competicion']+' · '+x['nombre_grupo'],'team_age_category':other_category,'match_duration':verify_category(request.get('age_category'),other_category),'team_source':'https://www.rffm.es/fichaequipo/'+registered,'role':'additional'}]
    elif fid == 'catalunya':
        data = initial_data(client.get(u.geturl()))
        member_name = unique_name([p['NOMBRE'] for p in data.get('players', [])], name)
        team_slug = u.path.rsplit('/', 1)[1]
        sides = [(m, side) for m in data.get('matches', []) for side in ('CASA', 'FUERA') if m.get('SLUG_' + side) == team_slug]
        team_ids = {str(m['CODEQUIPO_' + side]) for m, side in sides}
        groups = {str(m['CODGRUPO']) for m, _ in sides}
        if len(team_ids) != 1 or len(groups) != 1:
            raise ValueError('No se puede verificar un calendario y grupo únicos del equipo')
        m, side = sides[0]
        # Team roster uses given-name order; match reports use surname order.
        # Verify the player's report identity before activating the record.
        from federation_acts import flight_players
        report_members = {}
        slug = lambda s: re.sub(r'[^a-z0-9]+', '-', normalized(s).lower()).strip('-')
        for game, _ in sides:
            if str(game.get('CERRADA')) != '1':
                continue
            report = f"https://www.fcf.cat/ca/partit/{roster['season']}/{slug(game['NOMBRE_COMPETICION'])}/{slug(game['GRUPO'])}/jornada-{game['JORNADA']}/{game['SLUG_CASA']}-vs-{game['SLUG_FUERA']}"
            report_members, _ = flight_players(client.get(report))
            candidates = [p for p in report_members.values() if name_key(p['nombre']) == name_key(member_name)]
            if len(candidates) == 1:
                target = candidates[0]
                break
        else:
            raise ValueError('Plantilla localizada; falta una identidad individual verificable en las actas. Alta pendiente.')
        result = {'team_id': next(iter(team_ids)), 'club_id': str(data['info']['CODCLUB']), 'group_id': next(iter(groups)),
                  'player_id': str(target['id']), 'team': m['NOMBRE_' + side], 'source': u.geturl(),
                  'official_name': target['nombre'], 'competition_label': m['NOMBRE_COMPETICION'] + ' · ' + m['GRUPO']}
    elif fid == 'murcia':
        team_id = q.get('Codigo_Equipo', [''])[0]
        if not team_id.isdigit():
            raise ValueError('El enlace no incluye el código oficial del equipo')
        canonical = 'https://www.ffrm.es/pnfg/NPcd/NFG_VisEquipos?Codigo_Equipo=' + team_id + '&cod_primaria=3001860'
        soup = BeautifulSoup(client.get(canonical), 'html.parser')
        header = soup.find(string=re.compile(r'Jugadores\s*\('))
        table = header.find_parent('table') if header else None
        if not table:
            raise ValueError('La federación no devuelve una plantilla verificable; alta pendiente')
        official_name = unique_name([td.get_text(' ', strip=True) for td in table.select('td')], name)
        # Reuse a verified competition only for the very same official team.
        known = next((p for p in roster['players'] if p['federation'] == fid and p.get('team_id') == team_id), None)
        if known:
            result = {k: known[k] for k in ('team_id', 'team', 'competition_id', 'group_id', 'season_id', 'competition_label')}
        else:
            comp = official_url(request.get('competition_source'), fid, competition=True)
            params = parse_qs(comp.query)
            values = [params.get(k, [''])[0] for k in ('CodCompeticion', 'CodGrupo', 'CodTemporada')]
            if not all(v.isdigit() for v in values):
                raise ValueError('Para un equipo murciano nuevo hace falta el enlace de una jornada de su competición')
            comp_html = client.get(comp.geturl())
            comp_soup = BeautifulSoup(comp_html, 'html.parser')
            link = next((a for a in comp_soup.select('a[href*="NFG_VisEquipos"]') if parse_qs(urlparse(a['href']).query).get('Codigo_Equipo') == [team_id]), None)
            selected = comp_soup.select_one('select[name="temporada"] option[selected]')
            if not link or not selected or roster['season'] not in selected.get_text():
                raise ValueError('No se verifica el equipo en esa jornada y temporada; alta pendiente')
            comp_name = comp_soup.select_one('select[name="competicion"] option[selected]')
            group_name = comp_soup.select_one('select[name="grupo"] option[selected]')
            result = {'team_id': team_id, 'team': link.get_text(' ', strip=True), 'competition_id': values[0], 'group_id': values[1], 'season_id': values[2],
                      'competition_label': ' · '.join(x.get_text(' ', strip=True) for x in (comp_name, group_name) if x)}
        result.update(official_name=official_name, source=canonical)
    else:
        from valencia_data import PublicFFCV, resolve_ffcv
        result = resolve_ffcv(PublicFFCV(client), request, roster['season'], name_key)
        from categories import DURATION
        duration = DURATION[result['team_age_category']]
    result.update(id=re.sub(r'[^a-z0-9]+', '-', normalized(name).lower()).strip('-') + '-' + fid + '-' + result.get('player_id', result['team_id']),
                  name=name, federation=fid, collaborator=collaborator, match_duration=duration, active=True)
    if request.get('age_category'): result['age_category'] = request['age_category']
    if any(p['id'] == result['id'] or (p['federation'] == fid and name_key(p['official_name']) == name_key(result['official_name'])) for p in roster['players']):
        raise ValueError('El jugador ya está registrado. Utiliza cambiar colaborador o reactivar, según corresponda.')
    # A roster name alone is insufficient: check its real normalized calendar.
    verified = ADAPTERS[fid](client, {**result, 'season': roster['season'], '_calendar_only':True})
    if not verified.get('matches'):
        raise ValueError('No se ha verificado el calendario; el alta permanece pendiente')
    if fid=='madrid' and result.get('requires_participation'):
        result['participation_evidence']=prove_rffm_participation(client,{**result,'season':roster['season']},verified['matches'])
    if request.get('besoccer_team_source'):
        linked = resolve_besoccer(PublicBeSoccer(Client('https://es.besoccer.com')), request, roster['season'])
        result.update({k:v for k,v in linked.items() if k.startswith('besoccer_')})
    elif request.get('besoccer_player_source'):
        raise ValueError('Incluye también el enlace del equipo en BeSoccer')
    return result


def change(roster, request, resolver=resolve_player):
    if not isinstance(request, dict) or request.get('version') != 1:
        raise ValueError('Formato de solicitud no válido')
    action = request.get('action')
    result = copy.deepcopy(roster)
    if action == 'add':
        result['players'].append(resolver(request, roster))
    elif action in ('deactivate', 'reactivate', 'assign'):
        player = next((p for p in result['players'] if p['id'] == request.get('player_id')), None)
        if not player:
            raise ValueError('El jugador ya no existe en el registro. Recarga el formulario.')
        if action == 'assign':
            player['collaborator'] = text(request.get('collaborator'), 'Colaborador')
        elif action == 'deactivate':
            player['active'] = False
        else:
            # Reactivation must recheck membership; old players may have moved.
            client = Client(FEDERATIONS[player['federation']][2])
            verified = ADAPTERS[player['federation']](client, {**player, 'season': roster['season']})
            if not verified.get('matches'):
                raise ValueError('No se pudo volver a verificar el calendario')
            player['active'] = True
    else:
        raise ValueError('Operación desconocida')
    result['updated_at'] = now()
    return result


def request_from_event(event, repository):
    owner = repository.split('/')[0]
    issue = event.get('issue', {})
    # Repeat the workflow guard in code; edited/reopened issues must still be
    # owned by Antonio. No user content is evaluated or interpolated into shell.
    if event.get('sender', {}).get('login') != owner or issue.get('user', {}).get('login') != owner:
        raise ValueError('Solo el propietario del repositorio puede gestionar la cartera')
    if not issue.get('title', '').startswith('[RFHF] ') or 'pull_request' in issue:
        raise ValueError('Esta incidencia no es una solicitud del formulario')
    body = issue.get('body') or ''
    if len(body) > 10000:
        raise ValueError('Solicitud demasiado grande')
    block = re.fullmatch(r'RFHF-ROSTER-V1\s*```json\s*(\{.*\})\s*```\s*', body, re.S)
    if not block:
        raise ValueError('No se encuentra una solicitud válida del formulario')
    return json.loads(block[1])


def main():
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    outcome = {'state': 'pending', 'message': 'Pendiente de verificación'}
    try:
        request = request_from_event(event, os.environ['GITHUB_REPOSITORY'])
        path = ROOT / 'data/roster.json'
        roster = json.loads(path.read_text())
        updated = change(roster, request)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)
        # A failed optional refresh must never keep a deactivated player visible.
        feed_path = ROOT / 'docs/data/feed.json'
        feed = apply_roster(json.loads(feed_path.read_text()), updated)
        assignments = {p['id']: p['collaborator'] for p in updated['players']}
        for player in feed['players']:
            player['collaborator'] = assignments[player['id']]
        feed['generated_at'] = now()
        feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + '\n')
        outcome = {'state': 'applied', 'message': 'Registro validado. La agenda se publicará al terminar esta ejecución.'}
    except Exception as error:
        # Never print raw HTML, secrets or personal fields returned by sources.
        message = str(error) if isinstance(error, ValueError) else 'La fuente oficial no está disponible o ha cambiado de formato. Reintenta la solicitud más tarde.'
        outcome['message'] = message[:500]
    (ROOT / '.cache').mkdir(exist_ok=True)
    (ROOT / '.cache/management-result.json').write_text(json.dumps(outcome, ensure_ascii=False))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        output.write('applied=' + str(outcome['state'] == 'applied').lower() + '\n')
    print(outcome['state'] + ': ' + outcome['message'])


if __name__ == '__main__':
    main()
