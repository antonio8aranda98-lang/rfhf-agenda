"""Bounded, persistent retries for missing or incomplete public match reports."""
import copy
from datetime import datetime, timezone, timedelta

FIELDS = ('called_up', 'starts', 'bench', 'minutes', 'goals')


def stamp(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def report_plan(matches, player, previous=(), *, at=None, retry_limit=3):
    """Keep valid evidence and rotate older gaps, with six hours between retries."""
    at = at or datetime.now(timezone.utc)
    pid = player['id']
    old = {m['id']:m for m in previous}
    completed = sorted((m for m in matches if m.get('status') == 'finished'), key=lambda m:(m.get('date') or '', m['id']), reverse=True)
    missing = []
    recent = []
    for index, match in enumerate(completed):
        before = old.get(match['id'], {})
        same = before.get('status') == 'finished' and (before.get('score_home'), before.get('score_away')) == (match.get('score_home'), match.get('score_away'))
        if same:
            record = before.get('participation', {}).get(pid)
            if record is not None:
                match.setdefault('participation', {})[pid] = copy.deepcopy(record)
            for key in ('participation_checked_at', 'participation_attempted_at', 'participation_source'):
                value = before.get(key, {}).get(pid)
                if value:match.setdefault(key, {})[pid] = value
            if record is not None and not match.get('participation_checked_at', {}).get(pid) and before.get('updated_at'):
                match.setdefault('participation_checked_at', {})[pid] = before['updated_at']
        record = match.get('participation', {}).get(pid)
        checked = stamp(match.get('participation_checked_at', {}).get(pid))
        attempted = stamp(match.get('participation_attempted_at', {}).get(pid))
        last = max((x for x in (checked, attempted) if x), default=None)
        incomplete = record is None or any(record.get(k) is None for k in FIELDS)
        if incomplete:
            if last is None or at - last >= timedelta(hours=6):
                missing.append((last or datetime.min.replace(tzinfo=timezone.utc), match.get('date') or '', match['id']))
        elif index < 2 and (last is None or at - last >= timedelta(hours=1)):
            recent.append(match['id'])
    chosen = set(recent + [item[2] for item in sorted(missing)[:retry_limit]])
    for match in completed:
        if match['id'] in chosen:
            match.setdefault('participation_attempted_at', {})[pid] = at.isoformat(timespec='seconds')
    return chosen


def checked(match, player_id):
    match.setdefault('participation_checked_at', {})[player_id] = datetime.now(timezone.utc).isoformat(timespec='seconds')
