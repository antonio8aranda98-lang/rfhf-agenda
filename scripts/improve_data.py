"""Recompute confirmed evidence and optionally prove one bounded live refresh."""
import argparse
import json
import os
from player_stats import summarize
from sync import ROOT, Client, madrid, apply_roster, retain_participation, now, team_matches


def recompute(feed):
    for player in feed['players']:
        own = [m for m in feed['matches'] if player['id'] in m['player_ids']]
        primary = team_matches(own,player) if player.get('additional_teams') else own
        player['stats'],player['coverage'] = summarize(primary,player['id'],player.get('stats'),calendar_complete=player.get('calendar_complete') is not False)
        for scope in player.get('additional_teams') or []:
            scope['stats'],scope['coverage'] = summarize(team_matches(own,scope),player['id'])
    return feed


def refresh_one(feed, roster, desired):
    entries={p['id']:p for p in desired['players']}
    configs={p['id']:p for p in roster['players']}
    candidates=[]
    for public in feed['players']:
        config=configs.get(public['id'],{});entry=entries.get(public['id'],{})
        if public['federation']!='madrid' or config.get('provider') or entry.get('active',True) is False or not entry:continue
        if entry.get('_identity_revision') and entry['_identity_revision']!=config.get('identity_revision'):continue
        own=[m for m in feed['matches'] if public['id'] in m['player_ids']]
        missing=[m for m in own if m['status']=='finished' and m.get('participation',{}).get(public['id']) is None]
        if missing:candidates.append((public,config,own))
    if not candidates:return False
    candidates.sort(key=lambda row:any(row[0].get('stats',{}).get(k) is None for k in ('called_up','starts','bench','minutes','goals')),reverse=True)
    public,config,previous=candidates[0]
    result=madrid(Client('https://www.rffm.es/'),{**config,'season':roster['season'],'_previous':previous})
    if not result.get('matches'):raise ValueError('La fuente no devuelve un calendario verificable')
    stamp=now()
    for match in result['matches']:
        before=next((m for m in previous if m['id']==match['id']),None)
        retain_participation(match,before,config['id'])
        match['updated_at']=stamp
    feed['matches'].extend(result['matches'])
    public.update({k:result[k] for k in ('stats','logo','stats_note') if k in result},updated_at=stamp)
    apply_roster(feed,roster)
    print('Relectura dirigida:',public['name'])
    return True


def main(refresh=False):
    path=ROOT/'docs/data/feed.json';feed=json.loads(path.read_text())
    if refresh:
        from registry_remote import fetch_registry
        roster=json.loads((ROOT/'data/roster.json').read_text())
        try:refresh_one(feed,roster,fetch_registry())
        except Exception as error:print('Relectura pendiente; se conserva la evidencia anterior:',type(error).__name__,str(error)[:180])
    recompute(feed)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n');temporary.replace(path)
    count=sum(any(p.get('stats',{}).get(k) is None and p['coverage']['confirmed'].get(k) is not None for k in ('called_up','starts','bench','minutes','goals')) for p in feed['players'])
    print('Fichas con sumas parciales confirmadas:',count)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--refresh-one',action='store_true');args=parser.parse_args()
    main(args.refresh_one or os.environ.get('RFHF_REFRESH_EVIDENCE')=='true')
