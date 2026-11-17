// A normal public browser session. No stealth plugins, credentials or CAPTCHA handling.
import { chromium } from 'playwright';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
const roster = JSON.parse(await readFile(new URL('../data/roster.json', import.meta.url)));
const browser = await chromium.launch({ headless: true });
const result = { checked_at: new Date().toISOString(), players: {} };
try {
  for (const p of roster.players.filter(p => p.federation === 'valencia' && p.active !== false)) {
    const page = await browser.newPage({ locale: 'es-ES', timezoneId: 'Europe/Madrid' });
    try {
      const base = 'https://ffcv.es/competiciones/';
      await page.goto(base, { waitUntil: 'domcontentloaded', timeout: 45000 });
      const reject = page.getByRole('button', { name: 'No consentir', exact: true });
      if (await reject.isVisible()) await reject.click();
      await page.getByRole('textbox', { name: 'Buscar club', exact: true }).fill(p.club_search || 'EAF');
      await page.getByRole('option', { name: p.club_option || 'EAF Valencia C.F. Valencia', exact: true }).click({ timeout: 30000 });
      await page.getByRole('link', { name: 'Equipos', exact: true }).click();
      await page.locator(`a[href*="cod_equipo=${p.team_id}&"]`).click();
      await page.getByText(p.browser_competition || 'Primera FFCV Juvenil · Grup - 2', { exact: true }).waitFor({ timeout: 25000 });
      await page.getByLabel('Submenú equipo').getByRole('link', { name: 'Plantilla', exact: true }).click();
      await page.getByText(p.official_name, { exact: true }).waitFor({ timeout: 25000 });
      // Keep HTML in ignored cache for the allowlisted Python parser, never in the public repo.
      const team = await page.content();
      await page.getByText(p.official_name, { exact: true }).click();
      await page.getByRole('heading', { name: p.official_name, exact: true }).waitFor({ timeout: 25000 });
      const player = await page.content();
      await page.goBack({ waitUntil: 'domcontentloaded' });
      await page.getByText(p.browser_competition || 'Primera FFCV Juvenil · Grup - 2', { exact: true }).waitFor({ timeout: 25000 });
      await page.getByLabel('Submenú equipo').getByRole('link', { name: 'Partidos', exact: true }).click();
      await page.locator('a .match-card').first().waitFor({ timeout: 25000 });
      const games = await page.content();
      result.players[p.id] = { team_html: team, player_html: player, matches_html: games };
    } catch (error) {
      result.players[p.id] = { error: 'No se ha podido completar la consulta pública con el navegador estándar.' };
      console.warn('Valencia: consulta no disponible (' + error.name + '). Se conserva el último dato válido.');
    } finally {
      await page.close();
    }
  }
} finally {
  await browser.close();
}
await mkdir(new URL('../.cache/', import.meta.url), { recursive: true });
await writeFile(new URL('../.cache/valencia-browser.json', import.meta.url), JSON.stringify(result));
// Parsing is deliberately outside the browser, and exports only sporting fields.
const { spawnSync } = await import('node:child_process');
const python = process.env.PYTHON || 'python3';
const parsed = spawnSync(python, ['scripts/parse_valencia.py'], { stdio: 'inherit' });
process.exitCode = parsed.status ?? 1;
