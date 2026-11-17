export const TZ = 'Europe/Madrid';
export function madridToday(date = new Date()) {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-CA', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(date).map(p => [p.type, p.value]));
  return `${p.year}-${p.month}-${p.day}`;
}
export function shiftDate(iso, days) {
  const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10);
}
export function weekend(today = madridToday(), offset = 0) {
  const dow = new Date(`${today}T12:00:00Z`).getUTCDay();
  const monday = shiftDate(today, -(dow === 0 ? 6 : dow - 1));
  const friday = shiftDate(monday, 4 + offset * 7);
  return [friday, shiftDate(friday, 1), shiftDate(friday, 2)];
}
export function filterMatches(matches, playerIds, dates, query = '', planned = null) {
  const ids = new Set(playerIds); const days = dates && new Set(dates);
  const q = query.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase().trim();
  return matches.filter(m => m.player_ids.some(id => ids.has(id)) && (!days || days.has(m.date)) && (!planned || planned.has(m.id)) && (!q || [m.home, m.away, m.venue, m.locality, ...(m.search_names || [])].join(' ').normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase().includes(q)));
}
export function overlaps(a, b) {
  if (a.id === b.id || a.date !== b.date || !a.time || !b.time || ['cancelled', 'postponed', 'finished'].includes(a.status) || ['cancelled', 'postponed', 'finished'].includes(b.status)) return false;
  const minutes = s => Number(s.slice(0, 2)) * 60 + Number(s.slice(3, 5));
  return Math.abs(minutes(a.time) - minutes(b.time)) < 120;
}
export function displayStat(value) { return value === null || value === undefined ? '—' : String(value); }
export function matchups(matches, players, dates) {
  const active = new Map(players.filter(p=>p.active!==false).map(p=>[p.id,p]));
  const days = new Set(dates);
  const seen = new Set();
  return matches.filter(m=>days.has(m.date)&&!['cancelled','postponed'].includes(m.status)).flatMap(m=>{
    const home=(m.home_player_ids||[]).filter(id=>active.has(id));
    const away=(m.away_player_ids||[]).filter(id=>active.has(id));
    const key=[m.federation,m.date,m.home,m.away].join('|');
    if(!home.length||!away.length||seen.has(key))return [];
    seen.add(key);return [{...m,home_players:home.map(id=>active.get(id)),away_players:away.map(id=>active.get(id))}];
  });
}
export function escapeHTML(s) { return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
export function safeURL(url) { try { const u = new URL(url); return u.protocol === 'https:' ? u.href : ''; } catch { return ''; } }
export function icsEscape(s) { return String(s ?? '').replace(/\\/g, '\\\\').replace(/\r?\n/g, '\\n').replace(/,/g, '\\,').replace(/;/g, '\\;'); }
export function calendarICS(matches, now = new Date()) {
  const stamp = now.toISOString().replace(/[-:]/g, '').slice(0, 15) + 'Z';
  // Floating local times would be ambiguous at DST boundaries: ship an explicit Europe/Madrid zone.
  const lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//RFHF//Agenda de scouting//ES', 'CALSCALE:GREGORIAN', 'BEGIN:VTIMEZONE', 'TZID:Europe/Madrid', 'BEGIN:DAYLIGHT', 'DTSTART:19700329T020000', 'RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU', 'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0200', 'END:DAYLIGHT', 'BEGIN:STANDARD', 'DTSTART:19701025T030000', 'RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU', 'TZOFFSETFROM:+0200', 'TZOFFSETTO:+0100', 'END:STANDARD', 'END:VTIMEZONE'];
  for (const m of matches.filter(m => m.date && m.time && m.status === 'scheduled')) {
    const date = m.date.replaceAll('-', ''); const clock = m.time.replace(':', '') + '00';
    lines.push('BEGIN:VEVENT', `UID:${icsEscape(m.id)}@rfhf-agenda`, `DTSTAMP:${stamp}`, `DTSTART;TZID=Europe/Madrid:${date}T${clock}`, 'DURATION:PT2H', `SUMMARY:${icsEscape(`${m.home} – ${m.away}`)}`, `LOCATION:${icsEscape([m.venue, m.locality].filter(Boolean).join(', '))}`, `DESCRIPTION:${icsEscape('Partido del equipo. Convocatoria pendiente de confirmar. Consulta oficial: ' + m.source)}`, 'END:VEVENT');
  }
  lines.push('END:VCALENDAR');
  // RFC 5545 folds content lines at 75 octets, preserving multibyte Spanish names.
  return lines.flatMap(line => {
    const out = []; let part = '';
    for (const char of line) { if (new TextEncoder().encode(part + char).length > 75) { out.push(part); part = ' '; } part += char; }
    out.push(part); return out;
  }).join('\r\n') + '\r\n';
}
