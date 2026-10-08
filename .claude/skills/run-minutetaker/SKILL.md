---
name: run-minutetaker
description: Build, run, launch, drive and screenshot the MinuteTaker desktop app (Electron UI + Python engine), import recordings / transcripts / WhatsApp chat exports with voice notes, and check the result in the real UI. Use when asked to run or start MinuteTaker, try an import in the app, take a screenshot of it, or confirm a UI/engine change works end to end.
---

MinuteTaker = Electron + React UI (`desktop/`) that spawns a Python FastAPI engine (`engine/`) on a free
localhost port with a per-session token. Agents drive it with the Playwright REPL at
`.claude/skills/run-minutetaker/driver.mjs`: commands go in on stdin (piped or typed), screenshots land in
`%TEMP%\minutetaker-shots\`. **All paths below are relative to the repo root.** Verified on Windows 11
(Git Bash) — the window is a real, visible window; no xvfb.

## Prerequisites (one-time)

Python venv at `.venv` (repo root) and Node 18+ on PATH. Then:

```bash
(cd engine && ../.venv/Scripts/python -m pip install -e ".[all,diarization,dev]")
(cd desktop && npm ci && node node_modules/electron/install.js)
(cd .claude/skills/run-minutetaker && npm i --no-save --no-package-lock playwright-core@1)
```

`node node_modules/electron/install.js` is a no-op if the binary is there; it is required if `npm ci` ran with
`ELECTRON_SKIP_BINARY_DOWNLOAD=1` (then `desktop/node_modules/electron/dist/electron.exe` is missing).

## Build

```bash
(cd desktop && npx tsc --noEmit && npx vite build)
```

Electron loads `desktop/dist/index.html` — **rebuild after every UI change** or you are testing stale UI.
Engine changes need no build (editable install).

## Run (agent path)

```bash
printf '%s\n' \
  'launch fresh' 'ss 01-library' \
  'import fixtures/whatsapp-voice.zip' 'wait-ready 300' 'open-latest' 'ss 02-minutes' \
  'tab Transcript' 'segs' 'play-note' 'ss 03-transcript' \
  'paste fixtures/teams.vtt' 'wait-ready 60' 'open-latest' 'tab Transcript' 'segs' \
  'quit' \
| node .claude/skills/run-minutetaker/driver.mjs
```

Expected: the WhatsApp meeting reaches `ready` (≈30 s first time incl. Whisper `base` download, 8–15 s after),
`segs` shows two `▶ … [voice note] …` rows attributed to Panos / Maria, `play-note` prints
`{"status":200,"type":"audio/ogg","seconds":10.8}`. **Open the PNGs and look at them.**

Interactive: run `node .claude/skills/run-minutetaker/driver.mjs` and type commands.

| command | what it does |
|---|---|
| `launch [fresh]` | start app with isolated data dir `%TEMP%\minutetaker-run` (`fresh` wipes its library, keeps `models/`) |
| `ss <name>` | screenshot → `%TEMP%\minutetaker-shots\<name>.png` |
| `nav Record\|Library\|Settings` · `tab Minutes\|Summary\|Transcript` | navigate |
| `import <file>` | Record view → sets the hidden file input (same path as the drop zone / dialog) |
| `paste <file>` | Record view → "Paste a transcript…" box → Import text |
| `wait-ready [secs]` | poll the **engine** until the most recently imported meeting is `ready`/`error` |
| `open-latest` | Library → open the most recently imported meeting |
| `segs` | print transcript rows: `time \| speaker \| text` |
| `play-note` | fetch the first voice note the ▶ button streams and load it in an `<audio>` |
| `api [METHOD] /path` | call the engine REST API with the session token, print JSON |
| `text [sel]` · `eval <js>` · `click-text <t>` · `sleep <ms>` · `quit` | generic |

Env overrides: `MT_STT=local|mock` (default `local` = real faster-whisper), `MT_LLM=mock|claude|openai|ollama`
(default `mock`; real providers need keys set in Settings), `MT_DATA`, `MT_PYTHON`, `SCREENSHOT_DIR`.

Fixtures (`.claude/skills/run-minutetaker/fixtures/`): `whatsapp-voice.zip` — Android export with media, two
~10 s Opus voice notes (Windows TTS, English) + text messages; `teams.vtt` — Teams transcript with `<v>` tags.

## Direct invocation (no UI)

```bash
cd engine
PYTHONIOENCODING=utf-8 ../.venv/Scripts/minutetaker --data "$TEMP/minutetaker-cli" process ../.claude/skills/run-minutetaker/fixtures/teams.vtt --stt mock --llm mock --format md --out "$TEMP/minutetaker-cli/teams"
../.venv/Scripts/python -m pytest -q -p no:cacheprovider
```

`process -` reads transcript/chat text from stdin. Tests use mock STT/LLM — they do **not** exercise real
Whisper; use the driver (default `MT_STT=local`) for that.

## Run (human path — not run during verification)

`cd desktop && npm start` — opens the window using system `python` unless `MINUTETAKER_PYTHON` points at
`.venv`; writes to the real library in `%APPDATA%\MinuteTaker`. Default LLM is Claude, which needs an API key
in Settings (none on the machine this was verified on — hence `MT_LLM=mock` in the driver).

## Gotchas

- **The app opens on Library, not Record.** The import card / paste box live in Record — the driver's
  `import`/`paste` navigate there first.
- **"Latest" ≠ first Library row.** Library and `GET /meetings` sort by *meeting date*; a WhatsApp chat keeps
  its original date, so importing an old chat after anything else puts it lower. The driver picks max
  `created_at`.
- **The window is real — stray clicks change the page.** During one run the view jumped to Record and then
  Settings mid-wait (not the app; someone clicked). So `wait-ready` polls the engine API, never the DOM.
- **`page.fill('textarea')` hits Agenda, not the paste box** (first textarea on Record). The paste box stays
  empty, "Import text" stays disabled, and the click times out after 30 s with no useful call log.
  Target it by placeholder (`/Paste a Teams/`).
- **`ERR_CONNECTION_REFUSED` in the console at startup is normal** — `init()` polls `/health` until the engine
  is up. The driver filters it.
- **Engine needs the venv python.** Electron spawns `python -m minutetaker` from `PATH` unless
  `MINUTETAKER_PYTHON` is set (driver sets it to `.venv`).
- **Whisper model downloads on first local transcription** into `<data>/models` (base ≈ 140 MB). Copying a
  model cache between data dirs with `cp -r` fails on Windows (`File name too long` on HF symlinked blobs) —
  reuse the data dir instead (`launch` without `fresh`).
- **The Re-transcribe button text is `Re-transcribe`** (hyphen); the kicker line renders upper-case via CSS,
  so `innerText` is `… · CHAT EXPORT`.

## Troubleshooting

- **`TypeError: open() got an unexpected keyword argument 'metadata_errors'`** during local transcription —
  faster-whisper 1.2.1's own decoder vs PyAV 19. Fixed in `engine/minutetaker/stt.py` (decode with
  `audio.load_audio`, pass samples). If it reappears, someone passed a file path to `model.transcribe` again.
- **`AttributeError: 'LocalWhisper' object has no attribute 'transcribe'`** — `stt.py` indentation broke (a
  module-level def landed inside the class). Mock-STT tests won't catch it; the driver run will.
- **`waitForSelector('.drop')` timeout right after launch** — you didn't `nav Record` (see first gotcha).
