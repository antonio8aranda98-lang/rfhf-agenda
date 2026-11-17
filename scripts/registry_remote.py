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

REGISTRY = 'https://rfhf-control-antonio.opalescentpaper1.chatgpt.site/api/registry'


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


def reconcile(current, desired, resolver=resolve_player, revalidate=None):
    if current['season'] != desired['season']:
        raise ValueError('El registro remoto tiene otra temporada; revisar la configuración')
    updated = copy.deepcopy(current)
    known = {p['id']:p for p in updated['players']}
    results = []
    for entry in desired['players']:
        id = entry['id']; existing = known.get(id)
        if entry.get('active', True) is False:
            if existing:
                existing['active'] = False
            results.append({'id':id,'state':'inactive'})
            continue
        try:
            if existing:
                if existing.get('active', True) is False:
                    if revalidate:
                        revalidate(existing, current['season'])
                    else:
                        fid = existing['federation']
                        verified = ADAPTERS[fid](Client(FEDERATIONS[fid][2]), {**existing, 'season':current['season']})
                        if not verified.get('matches'):
                            raise ValueError('No se ha podido volver a verificar el calendario')
                existing['collaborator'] = text(entry.get('collaborator'), 'Colaborador')
                existing['active'] = True
            else:
                request = {k:entry.get(k) for k in ('name','federation','collaborator','source','match_duration','competition_source') if entry.get(k) is not None}
                # Never trust identifiers supplied by a browser for a new player.
                verified = resolver(request, updated)
                verified['id'] = id
                updated['players'].append(verified)
                known[id] = verified
            results.append({'id':id,'state':'verified'})
        except Exception as error:
            message = str(error)[:350] if isinstance(error, ValueError) else 'La fuente oficial no está disponible. Volveremos a intentarlo automáticamente.'
            results.append({'id':id,'state':'pending','message':message})
    desired_ids = {p['id'] for p in desired['players']}
    for p in updated['players']:
        if p['id'] not in desired_ids:
            p['active'] = False
    updated['registry_revision'] = desired['revision']
    return updated, {'schema_version':1,'revision':desired['revision'],'checked_at':now(),'players':results}


def needed(desired, status):
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


def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def main(check=False):
    desired = fetch_registry()
    path = ROOT/'docs/data/registry-status.json'
    status = json.loads(path.read_text()) if path.exists() else {}
    changed = needed(desired, status)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as output:
            output.write('changed='+str(changed).lower()+'\n')
    print('Registro de Antonio: revisión '+str(desired['revision'])+(' pendiente de aplicar' if changed else ' al día'))
    if check or not changed:
        return
    current = json.loads((ROOT/'data/roster.json').read_text())
    updated, status = reconcile(current, desired)
    feed_path = ROOT/'docs/data/feed.json'
    feed = apply_roster(json.loads(feed_path.read_text()), updated)
    assignments = {p['id']:p['collaborator'] for p in updated['players']}
    for p in feed['players']:
        p['collaborator'] = assignments[p['id']]
    feed['registry_revision'] = desired['revision']
    feed['generated_at'] = now()
    atomic_json(ROOT/'data/roster.json', updated)
    atomic_json(feed_path, feed)
    atomic_json(path, status)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args();main(args.check)
