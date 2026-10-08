// REPL driver for MinuteTaker (Electron UI + Python engine). Agent tooling, not product code.
//
//   node .claude/skills/run-minutetaker/driver.mjs            (run from the repo root)
//   printf 'launch\nimport fixtures/whatsapp-voice.zip\nwait-ready\nquit\n' | node .claude/skills/run-minutetaker/driver.mjs
//
// Commands are read from stdin one line at a time and run strictly in order (each awaits the
// previous), so a piped script behaves like a typed session. See SKILL.md for the command list.
import { _electron as electron } from 'playwright-core';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import * as readline from 'node:readline';

const SKILL = import.meta.dirname;
const ROOT = path.resolve(SKILL, '../../..');
const DESKTOP = path.join(ROOT, 'desktop');
const WIN = process.platform === 'win32';
const ELECTRON = path.join(DESKTOP, 'node_modules/electron/dist', WIN ? 'electron.exe' : 'electron');
const PYTHON = process.env.MT_PYTHON || path.join(ROOT, '.venv', WIN ? 'Scripts/python.exe' : 'bin/python');
const DATA = process.env.MT_DATA || path.join(os.tmpdir(), 'minutetaker-run');
const SHOTS = process.env.SCREENSHOT_DIR || path.join(os.tmpdir(), 'minutetaker-shots');
fs.mkdirSync(SHOTS, { recursive: true });

let app = null;
let page = null;
const need = () => { if (!page) throw new Error('launch first'); };
const resolveArg = (p) => path.isAbsolute(p) ? p : fs.existsSync(path.join(SKILL, p)) ? path.join(SKILL, p) : path.resolve(p);

// Engine REST call from inside the renderer (uses the per-session token the UI got over IPC).
async function engine(method, route, body) {
  need();
  return page.evaluate(async ({ method, route, body }) => {
    const { base, token } = await window.mt.engineInfo();
    const r = await fetch(base + route, { method, headers: { 'X-MT-Token': token, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined });
    const t = await r.text();
    try { return { status: r.status, body: JSON.parse(t) }; } catch { return { status: r.status, body: t }; }
  }, { method, route, body });
}

// Most recently *imported* meeting. The Library (and GET /meetings) sort by meeting date, and a
// WhatsApp chat keeps its original date, so "first row" is not "what I just imported".
async function latest() {
  const ms = (await engine('GET', '/meetings')).body;
  return ms.reduce((a, m) => (!a || m.created_at > a.created_at ? m : a), null);
}

const COMMANDS = {
  async launch(arg) {
    if (app) return console.log('already launched');
    if (arg === 'fresh' || !fs.existsSync(path.join(DATA, 'settings.json'))) {
      // Isolated library. Keep <data>/models so Whisper doesn't re-download.
      for (const f of ['audio', 'exports', 'minutetaker.db', 'minutetaker.db-wal', 'minutetaker.db-shm'])
        fs.rmSync(path.join(DATA, f), { recursive: true, force: true });
      fs.mkdirSync(DATA, { recursive: true });
      fs.writeFileSync(path.join(DATA, 'settings.json'), JSON.stringify({
        stt_provider: process.env.MT_STT || 'local', whisper_model: 'auto', llm_provider: process.env.MT_LLM || 'mock' }));
    }
    app = await electron.launch({
      executablePath: ELECTRON, args: [DESKTOP], timeout: 60_000,
      env: { ...process.env, MINUTETAKER_PYTHON: PYTHON, MINUTETAKER_DATA: DATA, PYTHONIOENCODING: 'utf-8' },
    });
    app.process().stdout.on('data', (d) => process.stdout.write(`[main] ${d}`));
    app.process().stderr.on('data', (d) => { const s = String(d); if (/Error|Traceback|error:/.test(s)) process.stdout.write(`[main!] ${s}`); });
    page = await app.firstWindow();
    page.on('console', (m) => m.type() === 'error' && !/ERR_CONNECTION_REFUSED/.test(m.text()) && console.log('[console.error]', m.text()));
    await page.waitForSelector('button.nav', { timeout: 90_000 });   // "Starting engine…" until the engine answers
    console.log(`launched. data=${DATA}`);
  },

  async ss(name) {
    need();
    const f = path.join(SHOTS, (name || `ss-${Date.now()}`) + '.png');
    await page.screenshot({ path: f });
    console.log('screenshot:', f);
  },

  async nav(label) { need(); await page.locator('button.nav', { hasText: label }).click(); console.log('nav', label); },
  async tab(label) { need(); await page.locator('button.tab', { hasText: label }).click(); await page.waitForTimeout(300); console.log('tab', label); },

  // Same code path as the import card's file dialog / drop zone.
  async import(file) {
    need();
    await COMMANDS.nav('Record');
    await page.setInputFiles('input[type=file]', resolveArg(file));
    await page.waitForSelector('.badge', { timeout: 60_000 });
    console.log('imported →', (await page.locator('.kicker').first().innerText()).replace(/\s+/g, ' '));
  },

  async paste(file) {
    need();
    await COMMANDS.nav('Record');
    await page.locator('button', { hasText: 'Paste a transcript' }).click();
    // NOT page.fill('textarea'): the first textarea on Record is Agenda → paste box stays empty,
    // "Import text" stays disabled and the click below times out.
    await page.getByPlaceholder(/Paste a Teams/).fill(fs.readFileSync(resolveArg(file), 'utf-8'));
    await page.locator('button', { hasText: 'Import text' }).click();
    await page.waitForSelector('.badge', { timeout: 60_000 });
    console.log('pasted →', (await page.locator('.kicker').first().innerText()).replace(/\s+/g, ' '));
  },

  // Polls the engine, not the DOM: the window is real and a stray click can navigate away.
  async 'wait-ready'(secs) {
    const t0 = Date.now(), limit = (Number(secs) || 300) * 1000;
    let m;
    for (;;) {
      m = await latest();
      if (!m || ['ready', 'error'].includes(m.status) || Date.now() - t0 > limit) break;
      await page.waitForTimeout(1000);
    }
    console.log(`latest meeting: ${m ? `${m.title} | ${m.status}${m.error ? ' | ' + m.error : ''}` : 'none'} (${((Date.now() - t0) / 1000).toFixed(1)}s)`);
  },

  async 'open-latest'() {
    const m = await latest();
    await COMMANDS.nav('Library');
    await page.locator('tbody tr', { hasText: m.title }).first().click();
    await page.waitForSelector('.badge');
    console.log('opened:', await page.locator('.badge').innerText());
  },

  async segs() {
    need();
    const rows = await page.$$eval('.seg', (els) => els.map((e) =>
      `${e.querySelector('.ts')?.innerText} | ${e.querySelector('select')?.selectedOptions[0]?.text} | ${e.querySelector('.txt')?.innerText}`));
    rows.forEach((r) => console.log('  ' + r.replace(/\s+/g, ' ')));
  },

  // Checks what a ▶ button streams: first voice-note segment of the latest meeting.
  async 'play-note'() {
    need();
    const r = await page.evaluate(async () => {
      const { base, token } = await window.mt.engineInfo();
      const h = { 'X-MT-Token': token };
      const ms = await (await fetch(`${base}/meetings`, { headers: h })).json();
      const m = ms.reduce((a, x) => (!a || x.created_at > a.created_at ? x : a), null);
      const d = await (await fetch(`${base}/meetings/${m.id}`, { headers: h })).json();
      const note = d.segments.find((s) => s.media);
      if (!note) return 'no voice notes';
      const res = await fetch(`${base}/meetings/${m.id}/segments/${note.id}/media?token=${token}`);
      const a = new Audio(URL.createObjectURL(await res.blob()));
      await new Promise((ok, bad) => { a.onloadedmetadata = ok; a.onerror = () => bad(new Error('audio element could not load it')); });
      return { status: res.status, type: res.headers.get('content-type'), seconds: Math.round(a.duration * 10) / 10 };
    });
    console.log('voice note:', JSON.stringify(r));
  },

  async api(arg) { const [method, route] = arg.includes(' ') ? arg.split(/\s+/) : ['GET', arg]; console.log(JSON.stringify(await engine(method, route))); },
  async 'click-text'(t) { need(); await page.locator('button, a', { hasText: t }).first().click(); console.log('clicked', JSON.stringify(t)); },
  async text(sel) { need(); console.log(await page.locator(sel || 'main').first().innerText()); },
  async eval(expr) { need(); console.log(JSON.stringify(await page.evaluate(expr))); },
  async sleep(ms) { await new Promise((r) => setTimeout(r, Number(ms) || 1000)); },
  async quit() { if (app) await app.close().catch(() => {}); app = page = null; },
  help() { console.log('commands:', Object.keys(COMMANDS).join(', ')); },
};

const rl = readline.createInterface({ input: process.stdin, terminal: false });
console.log('minutetaker driver — "help" for commands, "launch" to start');
for await (const line of rl) {
  const [cmd, ...rest] = line.trim().split(/\s+/);
  if (!cmd || cmd.startsWith('#')) continue;
  console.log(`> ${line.trim()}`);
  const fn = COMMANDS[cmd];
  if (!fn) { console.log('unknown command:', cmd); continue; }
  try { await fn(rest.join(' ')); } catch (e) {
    const lines = e.message.split('\n');   // keep Playwright's call log: it says *why* it waited
    console.log('ERROR:', [lines[0], ...lines.filter((l) => /^\s+-/.test(l)).slice(-4)].join('\n  '));
  }
  if (cmd === 'quit') break;
}
await COMMANDS.quit();
process.exit(0);
