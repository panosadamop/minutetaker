# MinuteTaker

Desktop app that listens to meetings on **MS Teams, Google Meet, Zoom, Viber, WhatsApp** (or in person), transcribes them, separates speakers, and produces **Minutes of Meeting + summaries** exported to **Word (.docx)** — plus PDF, Markdown, TXT and SRT.

It works with every platform the same way: it records **your microphone** and the **system audio** (what the other participants say) on your own computer. No bot joins the call and audio stays local unless you choose a cloud engine.

```
minutetaker/                      ← git repository root (github.com/panosadamop/minutetaker)
├── SPECS.md                      Functional & technical specification
├── project-log.md                Project log / decisions
├── engine/                       Python engine (FastAPI on 127.0.0.1) + CLI
│   ├── minutetaker/              capture · stt · diarize · transcripts · llm · minutes · export · db · api
│   ├── tests/                    pytest suite (runs offline with mock providers)
│   └── samples/                  Greek demo meeting + sample_minutes_el.docx
├── desktop/                      Electron + React/TypeScript UI (spawns ../engine in development)
└── .claude/skills/run-minutetaker/  Agent skill + Playwright driver to launch and drive the app
```

Not in git (see `.gitignore`), recreated by the steps below: `.venv/`, `desktop/node_modules/`
(Electron alone is ~172 MB, over GitHub's 100 MB file limit), `desktop/dist/` (UI build), caches.
Meetings, audio and API keys live outside the repo in `%APPDATA%\MinuteTaker` (or `MINUTETAKER_DATA`).

## Quick start (development)

**Requirements:** Python 3.10+, Node 18+. ffmpeg is optional (audio/video decoding falls back to the FFmpeg
bundled with PyAV). LibreOffice optional (PDF export).

```bash
git clone https://github.com/panosadamop/minutetaker.git && cd minutetaker
python -m venv .venv

# 1. Engine
cd engine
../.venv/Scripts/python -m pip install -e ".[all,dev]"   # Linux/macOS: ../.venv/bin/python
../.venv/Scripts/python -m pytest                        # offline, mock providers

# 2. Desktop app
cd ../desktop
npm install
npm run build                    # UI → desktop/dist (needed by `npm start`; `npm run dev` serves it live)
MINUTETAKER_PYTHON=../.venv/Scripts/python npm run dev   # Vite + Electron; Electron spawns the engine
```

Electron starts the engine with `python -m minutetaker serve` on a random local port with a per-session token. It uses `python` from PATH unless `MINUTETAKER_PYTHON` points to a specific interpreter/venv.

### First run
1. **Settings → API keys**: paste your Anthropic key (Claude writes the minutes). Keys go to the OS keychain.
2. **Settings → Speech-to-text**: `Local · faster-whisper`, model `Auto` (default: `base` on CPU, `small` on an NVIDIA GPU), or pick `small` for more accuracy on CPU, `medium`/`large-v3` for better Greek (GPU recommended). The model downloads once on first use.
3. **Record**: pick title/platform, enter participants (your name first), press *Start*, confirm the consent notice, join your call as usual. Press *Stop & process* when done.
4. The meeting opens with progress; then review **Transcript** (rename speakers, fix text, click a timestamp to play), **Minutes** (edit every section, regenerate any section), **Summary**.
5. **Export** → DOCX (or PDF/MD/TXT/SRT), with/without transcript appendix.

You can also **import** instead of recording (Record → *Import a recording or transcript*):
- **Audio/video**: mp3, m4a, wav, ogg/opus, flac, wma, … and mp4, mov, mkv, webm, avi, wmv, … (e.g. a Teams/Zoom cloud recording).
- **Transcripts**: Teams (.vtt, .docx), Zoom (.vtt, .txt), Google Meet (.docx/.pdf/.txt), any .srt/.vtt/.txt/.docx/.pdf — speakers and timestamps are detected, no speech-to-text needed.
- **WhatsApp chat exports**: .txt, or the .zip *with media* — voice notes inside are transcribed and added under their sender.
- **Pasted text**: a transcript, chat or plain notes.

## Audio capture per OS

| OS | System audio | Notes |
|---|---|---|
| Windows 10/11 | WASAPI loopback (built in) | Works for every app's call audio. |
| Linux | PulseAudio/PipeWire monitor | Pick the "Monitor of …" device. |
| macOS | Virtual device needed | Install [BlackHole](https://existential.audio/blackhole/), create a Multi-Output Device (speakers + BlackHole), choose BlackHole as *System audio*. |

Use headphones when possible; MinuteTaker also drops mic segments that are just echo of the speakers, and
lines Whisper "hears" in silence. With *Default device*, the microphone follows the headset you record from
(e.g. a Jabra's own mic, not the laptop's built-in array); the Record screen shows which device that is.

## Speakers
- Your mic track is always **"Me"** (renamed to the first name in *Participants*).
- Remote speakers: install `pip install pyannote.audio` and add a Hugging Face token (accept the `pyannote/speaker-diarization-3.1` terms) to split them into Speaker 1, 2 …; otherwise they appear as **Participants** and you can reassign lines per segment.

## Providers
| Stage | Default | Alternatives |
|---|---|---|
| Speech-to-text | faster-whisper (local) | OpenAI Whisper API |
| Minutes & summaries | Claude (`claude-sonnet-5-5`, editable) | OpenAI, Ollama (local) |
| Demo/testing | `mock` STT + `mock` LLM | — |

Long meetings (> ~60k characters of transcript) are summarised with map-reduce automatically.

## CLI (headless)
```bash
python -m minutetaker process meeting.m4a --platform "Zoom" --participants "Panos, Maria" --format docx
python -m minutetaker devices
python -m minutetaker record --title "Standup" --platform "MS Teams"    # Ctrl+C to stop
# offline demo:
python samples/make_demo.py && python -m minutetaker process samples/demo_el.wav --stt mock --llm mock
```

## Packaging
```bash
cd desktop
npm run dist        # builds UI, bundles the engine with PyInstaller, then electron-builder (NSIS / dmg / AppImage)
```

## Legal
Recording a conversation without participants' knowledge is a criminal offence in Greece (Penal Code art. 370A) and requires a lawful basis under GDPR. The app shows a consent notice at every start (EN/EL text to paste in the meeting chat); obtaining consent is the user's responsibility. Use *Settings → Storage* to auto-delete audio after N days.
