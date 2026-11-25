"""Prioritize new owner changes and checkpoint background work cooperatively."""
import hashlib
import json
import time
import os
from datetime import datetime, timezone, timedelta


class IntakeYield(BaseException):
    """Not a source failure: stop at a safe checkpoint for a newer owner change."""


def execution_deadline(clock=time.monotonic):
    remaining=25*60
    try:
        if os.environ.get('RFHF_WORK_DEADLINE'):
            remaining=min(remaining,max(0,float(os.environ['RFHF_WORK_DEADLINE'])-time.time()))
    except ValueError:pass
    return clock()+remaining


def fingerprint(entry):
    keys=('name','federation','source','player_source','competition_source','age_category','match_duration',
          'besoccer_team_source','besoccer_player_source','_identity_revision','_activation_revision')
    value={k:entry.get(k) for k in keys}
    if entry.get('additional_team_sources'):value['additional_team_sources']=entry['additional_team_sources']
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def timestamp(value):
    try:
        stamp=datetime.fromisoformat(value)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None


def source_ready(entry,feed,settings=None,at=None):
    at=at or datetime.now(timezone.utc)
    deadlines=[f.get('retry_after') for f in feed.get('federations',[]) if f['id']==entry['federation']]
    deadlines.append((settings or {}).get('source_pauses',{}).get(entry['federation']))
    return all(not timestamp(d) or timestamp(d)<=at for d in deadlines)


def plan(desired,status,feed,settings=None,at=None):
    """Fresh changes first. Only a small rotating retry batch when no fresh work exists."""
    at=at or datetime.now(timezone.utc)
    rows={p['id']:p for p in status.get('players',[])}
    published={p['id'] for p in feed.get('players',[]) if p.get('updated_at')}
    entries=[p for p in desired['players'] if p.get('active',True)]
    urgent=[]
    for p in entries:
        previous=rows.get(p['id'])
        fresh=(previous is None or previous.get('waiting_priority') or
               (previous.get('control_fingerprint') and previous['control_fingerprint']!=fingerprint(p)) or
               (p.get('additional_team_sources') and not previous.get('control_fingerprint')) or
               max(p.get('_identity_revision',0),p.get('_activation_revision',0),p.get('_verification_revision',0))>status.get('revision',0))
        first_calendar=previous and previous.get('priority_calendar') and p['id'] not in published
        if (fresh or first_calendar) and source_ready(p,feed,settings,at):urgent.append(p['id'])
    if urgent:return {'mode':'priority','resolve_ids':urgent,'calendar_ids':urgent}
    # Assignment/removal-only revisions must never wait behind older retries.
    if desired.get('revision')!=status.get('revision'):
        return {'mode':'controls','resolve_ids':[],'calendar_ids':[]}
    pending=[];calendars=[]
    for p in entries:
        row=rows.get(p['id'],{})
        if not source_ready(p,feed,settings,at):continue
        checked=timestamp(row.get('checked_at') or status.get('checked_at'))
        if row.get('state')=='pending' and (not checked or at-checked>=timedelta(minutes=30)):
            pending.append((row.get('checked_at') or '',p['id']))
        if row.get('state')=='verified' and p['id'] not in published:
            calendars.append((row.get('calendar_attempted_at') or '',p['id']))
    resolve=[id for _,id in sorted(pending)[:2]]
    calendar=[id for _,id in sorted(calendars)[:max(1,3-len(resolve))]]
    return {'mode':'backfill','resolve_ids':resolve,'calendar_ids':list(dict.fromkeys(resolve+calendar))}


class IntakeWatch:
    def __init__(self,fetch,revision,interval=30,clock=time.monotonic):
        self.fetch=fetch;self.revision=revision;self.interval=interval;self.clock=clock;self.last=None;self.yielded=False
        self.deadline=execution_deadline(clock)

    def __call__(self):
        if self.yielded:raise IntakeYield('Se cede el turno a un cambio nuevo de Antonio')
        current=self.clock()
        if current>=self.deadline:raise IntakeYield('Se guarda el avance antes del límite de ejecución')
        if self.last is not None and current-self.last<self.interval:return
        self.last=current
        try:new=self.fetch()
        except Exception:return  # A registry outage cannot discard valid sporting evidence.
        if new['revision']>self.revision:
            self.yielded=True
            raise IntakeYield('Se cede el turno a un cambio nuevo de Antonio')
