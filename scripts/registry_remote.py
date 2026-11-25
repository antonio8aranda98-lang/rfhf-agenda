"""Pull Antonio's desired portfolio from the read-only public registry."""
import argparse
import copy
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from registry import resolve_player, text
from sync import ROOT, ADAPTERS, FEDERATIONS, Client, apply_roster, now
from besoccer_data import FIELDS, PublicBeSoccer, resolve as resolve_besoccer
from intake_priority import plan as intake_plan, fingerprint, IntakeWatch, IntakeYield

REGISTRY = 'https://rfhf-control-antonio.opalescentpaper1.chatgpt.site/api/registry'
RESOLVER_VERSION = 11


def fetch_registry():
    request = urllib.request.Request(REGISTRY, headers={'User-Agent':'RFHF-Agenda/1.0', 'Accept':'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.url != REGISTRY:
            raise ValueError('La fuente del registro ha redirigido fuera del endpoint autorizado')
        data = json.loads(response.read(2_000_000))
    if data.get('initialized') is not True or data.get('schema_version') != 1 or type(data.get('revision')) is not int or data['revision'] < 1 or not isinstance(data.get('players'), list) or len(data['players']) > 2000:
        raise ValueError('Registro remoto no válido; no se modifica la cartera')
    ids = [p.get('id') for p in data['players']]
    if any(not isinstance(id, str) or not 2 <= len(id) <= 180 for id in ids) or len(ids) != len(set(ids)):
        raise ValueError('El registro contiene identificadores inválidos o duplicados')
    return data


def reconcile(current, desired, resolver=resolve_player, revalidate=None, selected_ids=None, previous_status=None):
    if current['season'] != desired['season']:
        raise ValueError('El registro remoto tiene otra temporada; revisar la configuración')
    updated = copy.deepcopy(current)
    known = {p['id']:p for p in updated['players']}
    results = []
    clients = {}
    previous_rows={p['id']:p for p in (previous_status or {}).get('players',[])}
    stop_network=False
    ordered=sorted(desired['players'],key=lambda p:selected_ids is not None and p['id'] not in selected_ids)
    for entry in ordered:
        id = entry['id']; existing = known.get(id)
        if entry.get('active', True) is False:
            if existing:
                existing['active'] = False
            results.append({'id':id,'state':'inactive'})
            continue
        try:
            before=previous_rows.get(id,{})
            if selected_ids is not None and (id not in selected_ids or stop_network):
                corrected=existing and entry.get('_identity_revision') and entry['_identity_revision']!=existing.get('identity_revision')
                if corrected:existing['active']=False
                if existing and existing.get('active',True) and not corrected:
                    existing['collaborator']=text(entry.get('collaborator'),'Colaborador')
                    if entry.get('age_category'):existing['age_category']=entry['age_category']
                state='verified' if existing and existing.get('active',True) and not corrected else 'pending'
                if before.get('state')=='pending':state='pending'
                pending_control=entry.get('_verification_revision',0)>(previous_status or {}).get('revision',0)
                if pending_control:state='pending'
                row={**before,'id':id,'state':state}
                if state=='pending':row.setdefault('message','Comprobación automática pendiente; se procesan primero las altas nuevas.')
                if not before or corrected or pending_control or entry.get('_activation_revision',0)>(previous_status or {}).get('revision',0):row['waiting_priority']=True
                if before.get('state')=='pending' and not row.get('checked_at'):
                    row['checked_at']=(previous_status or {}).get('checked_at')
                results.append(row)
                continue
            if existing and entry.get('_identity_revision') and entry['_identity_revision']!=existing.get('identity_revision'):
                existing['active']=False
                request={k:entry.get(k) for k in ('name','federation','collaborator','source','player_source','match_duration','competition_source','age_category',*FIELDS) if entry.get(k) is not None}
                without_self={**updated,'players':[p for p in updated['players'] if p['id']!=id]}
                verified=resolver(request,without_self)
                verified.update(id=id,identity_revision=entry['_identity_revision'])
                existing.clear();existing.update(verified)
            from official_sources import PROVIDERS,ADAPTER_VERSION
            if existing and existing.get('provider') in PROVIDERS and existing.get('official_adapter_version')!=ADAPTER_VERSION:
                request={k:entry.get(k) for k in ('name','federation','collaborator','source','player_source','match_duration','age_category') if entry.get(k) is not None}
                fid='official-upgrade'
                if fid not in clients:clients[fid]=Client('https://es.besoccer.com')
                verified=resolver(request,updated,client=clients[fid]);verified['id']=id
                existing.clear();existing.update(verified)
            if existing:
                if existing.get('active', True) is False:
                    if revalidate:
                        revalidate(existing, current['season'])
                    else:
                        from sync import collect_player
                        fid = existing['federation']
                        verified = collect_player(Client(FEDERATIONS[fid][2]), Client('https://es.besoccer.com'), {**existing, 'season':current['season'], **({'_calendar_only':True,'_intake':True} if selected_ids is not None else {})})
                        if not verified.get('matches'):
                            raise ValueError('No se ha podido volver a verificar el calendario')
                links_changed = entry.get('besoccer_team_source', '') != existing.get('besoccer_team_source', '') or entry.get('besoccer_player_source', '') != existing.get('besoccer_requested_player_source', existing.get('besoccer_player_source', ''))
                migrated = existing.get('source_request') == entry.get('source')
                if links_changed and not migrated:
                    if entry.get('besoccer_team_source'):
                        linked = resolve_besoccer(PublicBeSoccer(Client('https://es.besoccer.com')), entry, current['season'])
                        existing.update({k:v for k,v in linked.items() if k.startswith('besoccer_')})
                    elif existing.get('provider') == 'besoccer':
                        raise ValueError('El jugador usa BeSoccer como fuente principal; conserva su enlace del equipo')
                    else:
                        for k in list(existing):
                            if k.startswith('besoccer_'): existing.pop(k)
                existing['collaborator'] = text(entry.get('collaborator'), 'Colaborador')
                if entry.get('age_category') in ('senior','juvenil','cadete','infantil'):
                    existing['age_category'] = entry['age_category']
                existing['active'] = True
            else:
                request = {k:entry.get(k) for k in ('name','federation','collaborator','source','player_source','match_duration','competition_source','age_category',*FIELDS) if entry.get(k) is not None}
                # Never trust identifiers supplied by a browser for a new player.
                if resolver is resolve_player:
                    from besoccer_data import is_besoccer
                    fid = 'besoccer' if is_besoccer(request.get('source')) else request['federation']
                    if fid not in clients: clients[fid] = Client('https://es.besoccer.com' if fid=='besoccer' else FEDERATIONS[fid][2])
                    verified = resolver(request, updated, client=clients[fid])
                else:
                    verified = resolver(request, updated)
                verified['id'] = id
                if entry.get('_identity_revision'):verified['identity_revision']=entry['_identity_revision']
                updated['players'].append(verified)
                known[id] = verified
            resolved=known.get(id)
            if resolved and (entry.get('additional_team_sources',[])!=resolved.get('additional_team_sources',[]) or (entry.get('additional_team_sources') and not resolved.get('additional_teams'))):
                from additional_teams import resolve as resolve_additional
                sources=entry.get('additional_team_sources',[])
                fid=resolved['federation']
                if fid not in clients:clients[fid]=Client(FEDERATIONS[fid][2])
                extra=resolve_additional(clients[fid],resolved,sources,current['season']) if sources else []
                resolved['additional_teams']=extra
                resolved['additional_team_sources']=copy.deepcopy(sources)
            results.append({'id':id,'state':'verified','checked_at':now(),'control_fingerprint':fingerprint(entry),
                            'priority_calendar':bool(before.get('priority_calendar')) or (selected_ids is not None and id in selected_ids)})
        except IntakeYield:
            stop_network=True
            results.append({**previous_rows.get(id,{}),'id':id,'state':'pending','waiting_priority':True,
                            'message':'Esta comprobación continuará automáticamente en la siguiente ejecución.'})
        except Exception as error:
            message = str(error)[:350] if isinstance(error, ValueError) else 'La fuente oficial no está disponible. Volveremos a intentarlo automáticamente.'
            results.append({'id':id,'state':'pending','message':message,'checked_at':now(),'control_fingerprint':fingerprint(entry)})
    desired_ids = {p['id'] for p in desired['players']}
    for p in updated['players']:
        if p['id'] not in desired_ids:
            p['active'] = False
    updated['registry_revision'] = desired['revision']
    status = {'schema_version':1,'resolver_version':RESOLVER_VERSION,'revision':desired['revision'],'checked_at':now(),'players':results}
    if getattr(clients.get('valencia'), 'retry_after', None):
        status['valencia_retry_after'] = clients['valencia'].retry_after
    return updated, status


def needed(desired, status):
    if status.get('resolver_version') != RESOLVER_VERSION:
        return True
    if desired['revision'] != status.get('revision'):
        return True
    pending = any(p['state']=='pending' for p in status.get('players', []))
    if not pending:
        return False
    try:
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(status['checked_at'])).total_seconds()
        return age >= 1800
    except (KeyError, ValueError):
        return True


def calendars_due(desired, status, feed, settings=None, at=None):
    """Resume a verified registration whose first calendar is still missing."""
    at = at or datetime.now(timezone.utc)
    try:
        if (at - datetime.fromisoformat(status['checked_at'])).total_seconds() < 300:
            return False
    except (KeyError, ValueError):
        pass
    verified = {p['id'] for p in status.get('players', []) if p['state'] == 'verified'}
    published = {p['id'] for p in feed.get('players', []) if p.get('updated_at')}
    pauses = {f['id']: f.get('retry_after') for f in feed.get('federations', [])}
    for region, deadline in (settings or {}).get('source_pauses', {}).items():
        if not pauses.get(region) or datetime.fromisoformat(deadline) > datetime.fromisoformat(pauses[region]):
            pauses[region] = deadline
    for player in desired['players']:
        if player.get('active', True) is False or player['id'] not in verified or player['id'] in published:
            continue
        deadline = pauses.get(player['federation'])
        if not deadline or datetime.fromisoformat(deadline) <= at:
            return True
    return False


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def main(check=False, priority=False, watch_intake=False):
    desired = fetch_registry()
    path = ROOT/'docs/data/registry-status.json'
    status = json.loads(path.read_text()) if path.exists() else {}
    feed_path = ROOT/'docs/data/feed.json'
    previous = json.loads(feed_path.read_text())
    settings_path = ROOT/'docs/data/settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    intake=intake_plan(desired,status,previous,settings)
    changed = needed(desired, status) or calendars_due(desired, status, previous, settings) or intake['mode']=='priority'
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('changed='+str(changed).lower()+'\n')
    print('Registro de Antonio: revisión '+str(desired['revision'])+(' pendiente de aplicar' if changed else ' al día'))
    if check or not changed:
        return
    current = json.loads((ROOT/'data/roster.json').read_text())
    selected=set(intake['resolve_ids']) if priority else None
    import sync as sync_module
    guard=sync_module.REQUEST_GUARD
    if watch_intake:sync_module.REQUEST_GUARD=IntakeWatch(fetch_registry,desired['revision'])
    try:
        updated, status = reconcile(current, desired, selected_ids=selected, previous_status=status)
    finally:sync_module.REQUEST_GUARD=guard
    if priority:
        verified={p['id'] for p in status['players'] if p['state']=='verified'}
        status.update(intake_mode=intake['mode'],intake_ids=[id for id in intake['calendar_ids'] if id in verified])
    by_id={p['id']:p for p in current['players']}
    corrected={p['id'] for p in desired['players'] if p.get('_identity_revision') and p['id'] in by_id and p['_identity_revision']!=by_id[p['id']].get('identity_revision')}
    if corrected:
        previous=apply_roster(previous,{**updated,'players':[p for p in updated['players'] if p['id'] not in corrected]})
    feed = apply_roster(previous, updated)
    assignments = {p['id']:p['collaborator'] for p in updated['players']}
    for p in feed['players']:
        p['collaborator'] = assignments[p['id']]
    feed['registry_revision'] = desired['revision']
    feed['generated_at'] = now()
    if status.get('valencia_retry_after'):
        for federation in feed.get('federations', []):
            if federation['id'] == 'valencia': federation['retry_after'] = status['valencia_retry_after']
    atomic_json(ROOT/'data/roster.json', updated)
    atomic_json(feed_path, feed)
    atomic_json(path, status)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true')
    parser.add_argument('--priority',action='store_true');parser.add_argument('--watch-intake',action='store_true')
    args=parser.parse_args();main(args.check,args.priority,args.watch_intake)
