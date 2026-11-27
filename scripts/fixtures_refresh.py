"""Read upcoming team calendars independently of rosters, statistics and acts."""
import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin

import sync
from sync import ROOT, FEDERATIONS, Client, now, normalized, fixture, integer, iso_date, http_time
from valencia_fixtures import refresh as refresh_valencia, merge_fixture
from valencia_data import PublicFFCV, BASE
from federation_acts import parse_murcia_calendar
from registry_remote import fetch_registry, atomic_json
from intake_priority import IntakeWatch, IntakeYield


def madrid_calendar(client,p):
    url='https://www.rffm.es/competicion/calendario?'+urlencode(dict(competicion=p['competition_id'],grupo=p['group_id'],temporada=p['season_id'],tipojuego=1))
    data=client.next_props(url)['calendar']
    if data.get('temporada') and data['temporada']!=p['season']:raise ValueError('Calendario de otra temporada')
    games=[]
    for rnd in data.get('rounds',[]):
        for m in rnd.get('equipos',[]):
            if p['team_id'] not in (str(m.get('codigo_equipo_local')),str(m.get('codigo_equipo_visitante'))):continue
            home,away=integer(m.get('goles_casa')),integer(m.get('goles_visitante'))
            games.append(fixture('madrid',p,m['codacta'],m['equipo_local'],m['equipo_visitante'],iso_date(m.get('fecha')),http_time(m.get('hora')),
                'https://www.rffm.es/acta-partido/'+str(m['codacta']),round=integer(rnd.get('codjornada')),venue=m.get('campo') or None,
                home_team_id=str(m['codigo_equipo_local']),away_team_id=str(m['codigo_equipo_visitante']),score_home=home,score_away=away,
                home_logo=urljoin('https://www.rffm.es/',m.get('escudo_equipo_local') or ''),away_logo=urljoin('https://www.rffm.es/',m.get('escudo_equipo_visitante') or ''),
                status='finished' if home is not None and away is not None else 'scheduled' if http_time(m.get('hora')) else 'time_pending'))
    if not games:raise ValueError('No se confirma el equipo en su calendario')
    return games


def read_calendar(client,p):
    if p.get('provider'):
        from official_sources import calendar,client_for
        return calendar(client_for(client,p['provider']),p)[0]
    if p['federation']=='madrid':return madrid_calendar(client,p)
    if p['federation']=='murcia':
        url='https://www.ffrm.es/pnfg/NPcd/NFG_VisCalendario_Vis?'+urlencode(dict(cod_primaria='1000120',codtemporada=p['season_id'],codcompeticion=p['competition_id'],codgrupo=p['group_id'],CodJornada='1',CDetalle='1'))
        return parse_murcia_calendar(client.get(url),p,url)
    # FCF's public interface works in ordinary Chrome; do not retry or solve a challenge.
    from official_sources import browser_page
    if p['source'] not in client.cache:client.cache[p['source']]=browser_page(p['source'])
    data=sync.initial_data(client.cache[p['source']])
    games=[]
    for m in data.get('matches',[]):
        if p['team_id'] not in (str(m.get('CODEQUIPO_CASA')),str(m.get('CODEQUIPO_FUERA'))):continue
        if str(m.get('CODGRUPO'))!=str(p['group_id']):continue
        start=str(m.get('COMIENZO1') or '').split(' ');closed=str(m.get('CERRADA'))=='1'
        hour=http_time(start[1]) if len(start)>1 else None
        games.append(fixture('catalunya',p,m['CODACTA'],m['NOMBRE_CASA'],m['NOMBRE_FUERA'],iso_date(start[0]),hour,
            'https://www.fcf.cat/ca/competicio/acta/'+str(m['CODACTA']),round=integer(m.get('JORNADA')),venue=m.get('CAMPO') or None,
            home_team_id=str(m['CODEQUIPO_CASA']),away_team_id=str(m['CODEQUIPO_FUERA']),status='finished' if closed else 'scheduled' if hour else 'time_pending',
            score_home=integer(m.get('GOLES_CASA')) if closed else None,score_away=integer(m.get('GOLES_FUERA')) if closed else None))
    if not games:raise ValueError('La fuente no devuelve el calendario del equipo y grupo verificados')
    return games


def targets(roster,desired,feed,fid):
    controls={p['id']:p for p in desired['players']};published={p['id'] for p in feed['players']};groups=defaultdict(list)
    for p in roster['players']:
        e=controls.get(p['id'],{})
        if p['federation']!=fid or not p.get('active',True) or p['id'] not in published or not e or e.get('active') is False or e.get('_identity_revision',0)!=p.get('identity_revision',0):continue
        for scope in [p,*p.get('additional_teams',[])]:
            item={**p,**scope,'season':roster['season']}
            if scope.get('team_source'):item['source']=scope['team_source']
            key=(item.get('provider',''),item['team_id'],item.get('competition_id'),item.get('group_id'))
            groups[key].append(item)
    return groups


def refresh_region(feed,roster,desired,fid,client=None,reader=read_calendar,clock=now,today=None):
    today=today or datetime.now(sync.MADRID).date();start=(today-timedelta(days=2)).isoformat();end=(today+timedelta(days=14)).isoformat()
    result=copy.deepcopy(feed);groups=targets(roster,desired,feed,fid);client=client or Client(FEDERATIONS[fid][2])
    games={m['id']:copy.deepcopy(m) for m in feed['matches']};fresh={};failed=[];errors=[];success=0
    # Oldest unchecked teams first, including after a time-budget checkpoint.
    checked={p['id']:p.get('fixtures_checked_at') or '' for p in feed['players']}
    ordered=sorted(groups.values(),key=lambda owners:min(checked.get(p['id'],'') for p in owners))
    def event(m):return (str(m.get('group_id')),m.get('round'),normalized(m['home']),normalized(m['away']))
    known={event(m):m['id'] for m in feed['matches'] if m['federation']==fid}
    for owners in ordered:
        p=owners[0]
        try:
            matches=reader(client,p)
            if not matches:raise ValueError('Calendario vacío; se conserva el anterior')
            scoped=[m for m in matches if start<=(m.get('date') or '')<=end]
            stamp=clock()
            for m in scoped:
                if fid=='murcia':m['id']=known.get(event(m),m['id'])
                m['player_ids']=[o['id'] for o in owners]
                if m['id'] in fresh:m['player_ids']=sorted(set(m['player_ids']+fresh[m['id']]['player_ids']))
                fresh[m['id']]=m
            for public in result['players']:
                if public['id'] in {p['id'] for p in owners}:public['fixtures_checked_at']=stamp
            success+=1
            print(fid+' horarios: '+p['team']+' · '+str(len(scoped))+' partidos próximos',flush=True)
        except IntakeYield:break
        except Exception as error:
            failed.append(p['team_id']);errors.append({'team':p['team'],'error':str(error)[:140]})
            print('::warning::'+fid+' horarios '+p['team']+': '+str(error)[:140],flush=True)
    all_scopes=[p for owners in groups.values() for p in owners]
    failed_scopes=[p for p in all_scopes if p['team_id'] in failed]
    for m in games.values():
        if m['federation']!=fid or not today.isoformat()<=(m.get('date') or '')<=end:continue
        if any(p['id'] in m.get('player_ids',[]) and str(p.get('group_id'))==str(m.get('group_id')) for p in failed_scopes):
            m['schedule_status']='unconfirmed'
    for m in fresh.values():
        old=games.get(m['id'])
        if old and old.get('venue')==m.get('venue'):
            for k in ('address','locality','latitude','longitude'):
                if old.get(k) and not m.get(k):m[k]=old[k]
        for side in ('home','away'):
            if old and not m.get(side+'_team_id') and normalized(old[side])==normalized(m[side]):m[side+'_team_id']=old.get(side+'_team_id')
            m[side+'_player_ids']=sorted({p['id'] for p in all_scopes if str(p['team_id'])==str(m.get(side+'_team_id')) or (normalized(p['team'])==normalized(m[side]) and str(p.get('group_id'))==str(m.get('group_id')))})
        m['player_ids']=sorted(set(m['player_ids']+m['home_player_ids']+m['away_player_ids']))
        m['is_internal_matchup']=bool(m['home_player_ids'] and m['away_player_ids'])
        games[m['id']]=merge_fixture(old,m,clock())
    meta=next(f for f in result['federations'] if f['id']==fid)
    meta.update(fixtures_checked_at=clock(),fixtures_status='ok' if success==len(groups) and groups else 'partial' if success else 'error',fixtures_groups_checked=success,fixtures_groups_total=len(groups),fixtures_failed_groups=failed,fixtures_errors=errors)
    if success:meta['fixtures_updated_at']=clock()
    if success==len(groups) and groups:meta['fixtures_last_success']=clock()
    result['matches']=sorted(games.values(),key=lambda m:(m.get('date') or '9999',m.get('time') or '99:99',m['id']))
    result['generated_at']=clock()
    return result


def main(watch=False):
    desired=fetch_registry();roster=json.loads((ROOT/'data/roster.json').read_text());path=ROOT/'docs/data/feed.json';feed=json.loads(path.read_text())
    if not (desired['season']==roster['season']==feed['season']):raise ValueError('Temporadas distintas')
    previous=sync.REQUEST_GUARD
    if watch:sync.REQUEST_GUARD=IntakeWatch(fetch_registry,desired['revision'])
    try:
        order=sorted(['murcia','madrid','catalunya','valencia'],key=lambda fid:next((f.get('fixtures_checked_at') or '' for f in feed['federations'] if f['id']==fid),''))
        for fid in order:
            if fid=='valencia':
                try:feed=refresh_valencia(feed,roster,desired,PublicFFCV(Client(BASE)))
                except IntakeYield:break
                except Exception as e:
                    meta=next(f for f in feed['federations'] if f['id']==fid);meta.update(fixtures_status='error',fixtures_checked_at=now(),fixtures_errors=[{'error':str(e)[:140]}])
            else:feed=refresh_region(feed,roster,desired,fid)
            atomic_json(path,feed)
    finally:sync.REQUEST_GUARD=previous


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--watch-intake',action='store_true');main(parser.parse_args().watch_intake)
