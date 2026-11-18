"""Football participation rules shared by the federation adapters."""
import re

STAT_FIELDS = ('team_played', 'called_up', 'starts', 'bench', 'minutes', 'goals')


def minute(value, duration):
    """Use the regulation clock; added time is deliberately excluded."""
    match = re.fullmatch(r'\s*(\d+)(?:\s*\+\s*\d+)?\s*[\x27’]?\s*', str(value if value is not None else ''))
    return min(int(match[1]), duration) if match else None


def participation(starter, duration, entries=(), exits=(), dismissals=(), goals=None):
    """An unused substitute is called up, on the bench and has zero minutes."""
    stats = {'called_up': 1, 'starts': int(starter), 'bench': int(not starter), 'played': None, 'minutes': None, 'goals': goals}
    if len(entries) > 1 or len(exits) > 1:
        return stats  # Re-entry competitions need a different interval model.
    start = 0 if starter else minute(entries[0], duration) if entries else None
    if not starter and not entries:
        stats.update(played=0, minutes=0)
        return stats
    stats['played'] = 1
    stops = [minute(v, duration) for v in [*exits, *dismissals]]
    if start is None or any(v is None for v in stops):
        return stats
    end = min(stops) if stops else duration
    if end >= start:
        stats['minutes'] = end - start
    return stats


def absent():
    return {k: 0 for k in ('called_up', 'starts', 'bench', 'played', 'minutes', 'goals')}


def summarize(matches, player_id, published=None, calendar_complete=True):
    """Keep season totals separate from field-by-field confirmed partial sums."""
    completed = [m for m in matches if m.get('status') == 'finished']
    records = [m.get('participation', {}).get(player_id) for m in completed]
    stats = dict(published or {})
    stats['team_played'] = len(completed)
    coverage = {'team_played': len(completed), 'acts_checked': sum(r is not None for r in records),
                'minutes_checked': sum(r is not None and r.get('minutes') is not None for r in records),
                'minutes_method': 'Tiempo reglamentario según acta; no incluye añadido.'}
    coverage['confirmed'] = {}
    coverage['field_checked'] = {}
    coverage['calendar_complete'] = calendar_complete
    for key in ('called_up', 'starts', 'bench', 'played', 'minutes', 'goals'):
        values = [r[key] for r in records if r is not None and r.get(key) is not None]
        coverage['field_checked'][key] = len(values)
        coverage['confirmed'][key] = sum(values) if values else None
    if all(r is not None for r in records):
        for key in ('called_up', 'starts', 'bench', 'played', 'minutes', 'goals'):
            if all(r.get(key) is not None for r in records):
                stats[key] = sum(r[key] for r in records)
    for key in STAT_FIELDS:
        stats.setdefault(key, None)
    if not calendar_complete:
        for key in (*STAT_FIELDS,'played'):stats[key]=None
        coverage['confirmed']['team_played']=len(completed) if completed else None
    if stats.get('called_up') is not None and stats.get('starts') is not None:
        if stats['called_up'] >= stats['starts'] and stats.get('bench') is None:
            stats['bench'] = stats['called_up'] - stats['starts']
    return stats, coverage
