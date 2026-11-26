"""Refresh upcoming FFCV fixtures by group, independently of player statistics."""
import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import sync
from sync import ROOT, MADRID, Client, now, iso_date, retain_participation
from intake_priority import IntakeYield, IntakeWatch
from registry_remote import fetch_registry, atomic_json
from valencia_data import BASE, PublicFFCV, round_matches


def scopes_for(roster, desired, feed):
    controls={p['id']:p for p in desired['players']}
    published={p['id'] for p in feed['players']}
    groups=defaultdict(list)
    for p in roster['players']:
        entry=controls.get(p['id'])
        if (p['federation']!='valencia' or not p.get('active',True) or p['id'] not in published or
                not entry or entry.get('active') is False or
                entry.get('_identity_revision',0)!=p.get('identity_revision',0)):
            continue
        for scope in [p,*p.get('additional_teams',[])]:
            ids=[str(scope.get(k,'')) for k in ('season_id','competition_id','group_id','team_id')]
            if not all(x.isdigit() for x in ids):continue
            groups[tuple(ids[:3])].append({**p,**scope,'season':roster['season']})
    return groups


def select_rounds(rounds, previous, key, today):
    start=(today-timedelta(days=7)).isoformat();end=(today+timedelta(days=14)).isoformat()
    # Include old rounds whose match was moved into the coming fortnight.
    known={str(m.get('round')) for m in previous if m.get('federation')=='valencia' and
           str(m.get('competition_id'))==key[1] and str(m.get('group_id'))==key[2] and
           start<=(m.get('date') or '')<=end and m.get('status')!='finished'}
    return [r for r in rounds if str(r.get('codjornada','')).isdigit() and
            (start<=(iso_date(r.get('fecha_jornada')) or '')<=end or str(r['codjornada']) in known)]


def merge_fixture(previous, fresh, checked_at):
    if previous and (previous.get('competition_id')!=fresh['competition_id'] or previous.get('group_id')!=fresh['group_id'] or previous.get('season')!=fresh['season']):
        raise ValueError('El identificador del partido corresponde a otra competición o temporada')
    result=copy.deepcopy(fresh)
    for pid in fresh['player_ids']:
        retain_participation(result,previous,pid)
    if previous and previous.get('participation_attempted_at'):
        result['participation_attempted_at']={pid:stamp for pid,stamp in previous['participation_attempted_at'].items() if pid in fresh['player_ids']}
    result.update(schedule_checked_at=checked_at,schedule_status='ok',updated_at=checked_at)
    return result


def refresh(feed, roster, desired, api, today=None, clock=now):
    today=today or datetime.now(MADRID).date()
    result=copy.deepcopy(feed)
    groups=scopes_for(roster,desired,feed)
    games={m['id']:copy.deepcopy(m) for m in feed['matches']}
    players={p['id']:p for p in result['players']}
    failed=[];success=0;changed=0;yielded=False
    for key,scopes in groups.items():
        try:
            rounds=api.get('filtros/jornadas_fetch.php',cod_grupo=key[2]).get('jornadas',[])
            if not rounds:raise ValueError('La FFCV no devuelve jornadas verificables')
            chosen=select_rounds(rounds,feed['matches'],key,today)
            if not chosen:raise ValueError('No se identifica una jornada cercana; se conserva el calendario')
            for rnd in chosen:
                data=api.get('partidos/resultados_por_grupo_jornada_data.php',cod_temporada=key[0],cod_competicion=key[1],cod_grupo=key[2],cod_jornada=rnd['codjornada'])
                if str(data.get('jornada'))!=str(rnd['codjornada']) or not data.get('partidos'):
                    raise ValueError('Jornada vacía o distinta; no se sustituyen sus horarios')
                fresh={}
                for p in scopes:
                    for m in round_matches(data,rnd,p):
                        if not m['date'] or not m['id'].removeprefix('valencia-').isdigit():
                            raise ValueError('Partido sin fecha o identificador verificable')
                        if m['id'] in fresh:fresh[m['id']]['player_ids'].append(p['id'])
                        else:fresh[m['id']]=m
                stamp=clock()
                for m in fresh.values():
                    m['player_ids']=sorted(set(m['player_ids']))
                    for side in ('home','away'):
                        m[side+'_player_ids']=sorted({p['id'] for p in scopes if p['team_id']==m[side+'_team_id']})
                    m['is_internal_matchup']=bool(m['home_player_ids'] and m['away_player_ids'])
                    old=games.get(m['id'])
                    if old and any(old.get(k)!=m.get(k) for k in ('date','time','venue','status')):changed+=1
                    games[m['id']]=merge_fixture(old,m,stamp)
                # A missing fixture is not proof of cancellation. Keep it visibly unconfirmed.
                for m in games.values():
                    if (m.get('federation')=='valencia' and str(m.get('competition_id'))==key[1] and
                            str(m.get('group_id'))==key[2] and str(m.get('round'))==str(rnd['codjornada']) and
                            m.get('status')!='finished' and m['id'] not in fresh):
                        m['schedule_status']='unconfirmed'
            success+=1
            for p in scopes:players[p['id']]['fixtures_checked_at']=clock()
            print('FFCV horarios: grupo '+key[2]+' · '+str(len(chosen))+' jornadas',flush=True)
        except IntakeYield:
            yielded=True;break
        except Exception as error:
            failed.append(key[2]);print('::warning::FFCV horarios '+key[2]+': '+str(error)[:160],flush=True)
    meta=next(f for f in result['federations'] if f['id']=='valencia')
    meta.update(fixtures_checked_at=clock(),fixtures_status='ok' if success==len(groups) and groups else 'partial' if success else 'error',
                fixtures_failed_groups=failed,fixtures_groups_checked=success,fixtures_groups_total=len(groups))
    if success:meta['fixtures_updated_at']=clock()
    if success==len(groups) and groups:meta['fixtures_last_success']=clock()
    if yielded:meta['fixtures_status']='partial'
    if getattr(api.client,'retry_after',None):meta['retry_after']=api.client.retry_after
    result['matches']=sorted(games.values(),key=lambda m:(m.get('date') or '9999',m.get('time') or '99:99',m['id']))
    result['generated_at']=clock()
    print('FFCV horarios: '+str(success)+'/'+str(len(groups))+' grupos; '+str(changed)+' horarios/campos/estados corregidos.',flush=True)
    return result


def main(watch=False):
    desired=fetch_registry()
    roster=json.loads((ROOT/'data/roster.json').read_text())
    path=ROOT/'docs/data/feed.json';feed=json.loads(path.read_text())
    if roster['season']!=desired['season'] or feed['season']!=roster['season']:
        raise ValueError('Las temporadas no coinciden; no se actualiza la agenda')
    client=Client(BASE)
    previous=sync.REQUEST_GUARD
    if watch:sync.REQUEST_GUARD=IntakeWatch(fetch_registry,desired['revision'])
    try:
        result=refresh(feed,roster,desired,PublicFFCV(client))
    except IntakeYield:
        return
    except Exception as error:
        result=copy.deepcopy(feed);meta=next(f for f in result['federations'] if f['id']=='valencia')
        meta.update(fixtures_checked_at=now(),fixtures_status='error')
        if client.retry_after:meta['retry_after']=client.retry_after
        print('::warning::FFCV horarios: '+str(error)[:200],flush=True)
    finally:sync.REQUEST_GUARD=previous
    atomic_json(path,result)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--watch-intake',action='store_true')
    main(parser.parse_args().watch_intake)
