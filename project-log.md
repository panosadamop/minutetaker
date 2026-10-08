# MinuteTaker — Project Log

## 2026-10-05

### Kick-off
- **Request:** App that listens to meetings/conversations (MS Teams, Google Meet, Zoom, Viber, WhatsApp), creates minutes of meeting and summaries, and exports them to a document file.
- **Process agreed:** Specs first → questions/proposals to the client → specs in Markdown → build the app.

### Analysis
- Viber and WhatsApp expose no call-audio API; Teams/Meet/Zoom bot APIs require tenant/app approvals.
- **Decision:** platform-agnostic local capture of system loopback + microphone on the user's desktop. One mechanism covers all five platforms plus in-person meetings.
- Legal note recorded: Greek Penal Code 370A + GDPR → consent reminder and local-first storage built in.

### Deliverables (spec phase)
- `SPECS.md` v0.1 (draft) — use cases, functional/non-functional requirements, architecture, data model, API, UI, compliance, delivery plan, open questions.
- `project-log.md` — this file.

### Client decisions (all proposals accepted)
| # | Topic | Decision |
|---|---|---|
| D1 | App form | Desktop: Electron + React/TS UI, Python FastAPI engine |
| D2 | Transcription | Local faster-whisper default, OpenAI cloud optional |
| D3 | LLM | Claude default; OpenAI / Ollama alternatives |
| D4 | Live transcript | v2; v1 transcribes after Stop |
| D5 | Export format | .docx primary (+ PDF / Markdown / TXT / SRT) |
| D6 | Languages | Greek + English, auto-detect |

- `SPECS.md` frozen as **v1.0** with §11 Decisions + implementation notes.

### Build — Phase P1–P3 delivered
**Engine (`engine/minutetaker`)**
- `capture.py` — mic + system loopback via `soundcard` (WASAPI / PulseAudio; BlackHole on macOS), separate WAV per track, flushed every 3 s (FR-07), pause/resume, live levels.
- `stt.py` — faster-whisper (VAD, auto language, model cache), OpenAI Whisper (10-min Opus chunks), mock provider.
- `diarize.py` — mic track = "Me", echo removal, pyannote 3.1 for remote speakers when available, fallback labels.
- `llm.py` + `minutes.py` — Claude / OpenAI / Ollama / mock; 4 templates (formal, standup, client, interview) + custom; output language selectable; map-reduce for long meetings; per-section regeneration; normalisation of model output.
- `export.py` — branded A4 .docx (meta strip, tables for attendees/decisions/actions with repeating header rows, page X of Y, EN/EL labels, optional logo/company, transcript appendix); PDF via LibreOffice; MD, TXT, SRT.
- `db.py` — SQLite + FTS5, accent/case-insensitive Greek search.
- `api.py` — REST + WebSocket on 127.0.0.1 with per-session token; `cli.py` — serve / process / devices / record.

**Desktop (`desktop/`)**
- Electron main spawns the engine on a free port with a random token; save dialogs via IPC.
- Screens: Record (devices, meters, timer, consent modal, import drop zone), Library (table + full-text search), Meeting (Transcript with speaker rename/reassign/inline edit/audio seek, Minutes editor, Summary editor, Export menu, job progress), Settings (providers, models, keys, templates, branding, retention, UI language EN/EL).
- House style: dark near-black, JetBrains Mono, gold/cyan accents, high density.

### Verification
- `pytest`: 9 tests pass (audio/VAD/mix, echo removal, diarization assignment, Greek FTS, JSON extraction, map-reduce, full pipeline → docx/md/srt, Greek labels, API flow incl. auth, edit, regenerate, export, delete).
- HTTP end-to-end against a running engine: import → process → rename speaker → edit minutes → export docx/pdf/md/srt; 401 without token.
- Generated document reviewed visually (LibreOffice render); fixed column widths and sub-minute durations.
- UI: `tsc` strict type-check + Vite production build pass.
- **Not verifiable in the build sandbox** (no network to Hugging Face / no audio devices / no GUI): real faster-whisper and pyannote model runs, live loopback capture, and the Electron window. These need a first run on a Windows/macOS machine.

### Next steps
- Client smoke test on Windows with a real Teams/Zoom call; tune Whisper model size for Greek.
- P4: `npm run dist` installers, code signing.
- v2 backlog: live transcript (FR-15), calendar integration, email minutes to attendees, speaker voice profiles per meeting series.

### Transcript & chat import, wider video support
- **Request:** import transcripts (Teams, Zoom, Meet, VTT/SRT, TXT, DOCX, PDF, WhatsApp chat exports, pasted text) and widen video support, all going through the same minutes / summaries / export pipeline.
- `transcripts.py` (new): detects the format from content and returns speaker-labelled, timed segments. Handles Teams VTT `<v>` tags and the .docx layout, Zoom VTT, transcript and chat, Meet docs (attendees, 5-minute markers), SRT, bracketed timestamps, WhatsApp Android/iOS (EN/EL AM/PM, d/m vs m/d detection, multi-line messages, media/deleted/edited markers, .zip exports), and plain paragraphs. Missing times are estimated at about 150 words/min. Language is detected as EL/EN.
- Engine: `import_file` routes by extension; `import_text` handles pasted text. Transcript meetings are stored with `source=transcript|chat` (with a DB migration) and status `transcribed`. `process_all` skips straight to minutes, and `/transcribe` returns 400 for them. The LLM header states the source; chats show real send dates so relative due dates resolve correctly.
- Audio: about 38 container types. When ffmpeg is missing (as on the dev laptop) decoding falls back from libsndfile to PyAV, whose wheels bundle FFmpeg. Cloud STT without ffmpeg uploads WAV chunks. A video with no audio track now fails cleanly and no longer leaves an orphaned meeting.
- UI: the import card accepts every type (the list comes from `/settings.import_types`) and has a paste box. The Meeting view labels the source, shows chat send times, and hides re-transcribe when there's no audio.
- New deps: `av`, `pypdf`. Tests: 27 pass (18 new), `tsc` and `vite build` pass.

### WhatsApp voice notes
- The chat parser recognises attachments (Android `(file attached)` in any language, iOS `<attached: …>`). Audio attachments become `[voice note]` messages linked to their file. Photo captions are kept; photos without captions are still dropped.
- On import of a `.zip`, the voice notes are extracted to `<meeting>/voice/`, using basenames only (protects against zip-slip). The meeting status becomes `imported`. `process_all` transcribes the pending notes (no diarization, since the sender is known) and then generates the minutes. `/transcribe` re-transcribes all of a chat's notes. A note referenced in the chat but missing from the zip, or one that can't be decoded, is labelled rather than causing a failure. A chat made up only of voice notes takes its language from speech, weighted by the amount of text per language.
- DB: `segment.media` column with a migration. Machine-written transcription text is not flagged as a user edit. Retention clears `media` links.
- UI: voice-note rows get a ▶ play button (`GET /meetings/{id}/segments/{sid}/media`), and Re-transcribe is shown for chats with voice notes.
- Tests: 31 pass, 4 new, using real Opus files encoded with PyAV, including a hostile zip member path.

### Real-Whisper check of voice notes + local STT fix
- Ran end to end with real faster-whisper (`small`, CPU int8) on a WhatsApp-style export: an Android `.zip`, two Opus voice notes (~10 s each, synthesised with Windows TTS David/Zira, 48 kHz / 24 kbps) and text messages. Both notes were transcribed almost word for word (one slip: "Hi team" came out as "High team"). The decision, the action (owner Maria, due Friday) and the risk all reached the minutes. Language was detected as EN.
- **Bug found & fixed:** faster-whisper 1.2.1 (the latest) calls `av.open(metadata_errors=...)`, which PyAV 19 rejects, so local transcription failed for *every* input. `LocalWhisper` now decodes with `audio.load_audio` and passes 16 kHz samples to Whisper. This also avoids a second decode for the duration.
- Speed on the dev laptop (CPU, `small`): ~21 s of speech in 13–16 s, roughly 0.65× real time. A 1 h meeting would take about 40 min, over the NFR-03 target of 15 min. Consider `base` as the default on CPU-only machines.
- Not yet verified: Greek speech (no Greek TTS voice on this machine). It needs a real Greek voice note.

### Default Whisper model: `auto` (base on CPU, small on GPU)
- New `whisper_model="auto"` default resolves by device: `base` on CPU and `small` on CUDA. An explicitly chosen model still overrides it. Settings UI gains the "Auto" option; README updated.
- Measured on the same two voice notes (21 s of speech, CPU int8, model in memory): `small` 13.4 s, `base` 6.1 s, about 2.2× faster, or ~0.29× real time (a 1 h meeting ≈ 17 min, close to the NFR-03 target). Accuracy on clear English was about the same: one extra slip ("report's module"). Greek accuracy with `base` is still to be checked with a real recording; switch to `small`/`medium` if it falls short.

### Live capture test + silence filter + headset mic pairing
- **Live test (dev laptop, Jabra Link 370 headset):** recorded through the real `/recordings/*` API while Windows TTS played through the headset (standing in for a remote Teams participant). The loopback capture of the headset output was transcribed word for word and attributed to "Participants". No capture errors, 48 kHz tracks, the live meters moved.
- **Bug: Whisper invents speech on a silent mic.** The laptop-array mic at -57…-68 dBFS produced "Me: For the first part." (no_speech_prob 0.43, avg_logprob -1.25, so Whisper's own thresholds keep it). Fix: `stt.drop_silent` drops segments whose loudest 50 ms frame is below -48 dBFS; it uses the loudest frame, not the average, so pauses in soft speech don't count against it. Applied to local and OpenAI STT. Re-run on that recording: nothing kept.
- **Default mic now follows the recorded output's hardware:** `capture.paired_mic` matches the bracketed hardware name ("Headset Earphone (Jabra Link 370)" → "Headset Microphone (Jabra Link 370)"), falling back to the OS default. Explicit choices still win. The Record screen shows which device "Default device" means. Verified live: it recorded from the Jabra mic.
- Second live run: the Jabra mic picked up the user talking during the test (≈-36 dBFS), so it was correctly kept. It was partial and overheard, which explains the unclear wording. Test recordings deleted at the user's request.
- Tests: 34 pass.

## 2026-10-08

### Git repository fix
- **Problem:** pushing to github.com/panosadamop/minutetaker was rejected (GH001: `node_modules/electron/dist/electron.exe` is 172 MB, over the 100 MB limit). Cause: the repo had been initialised inside `desktop/` and its only commit included all of `node_modules/` (16,575 files) and `dist/`. The engine, docs and skill were not versioned, so a clone could not run (Electron spawns `../engine`).
- **Fix (decided with the client: the whole project goes in the repo):** nothing had reached GitHub, so the repo was re-created at the project root; the old `desktop/.git` was kept as a local backup. A new root `.gitignore` excludes node_modules, `desktop/dist`, the venv, Python caches, build bundles, local data/secrets and editor files. A new `.gitattributes` stores text with LF and marks audio/zip/docx as binary. 50 files committed (largest: the 1.5 MB demo WAV); staged content was scanned for keys and tokens with none found.
- README: repo layout, what is not in git and why, and a clone-first quick start (`npm run build` is now required before `npm start` because `dist/` is no longer committed). The import list is updated for transcripts, chats and voice notes; the headset mic default is documented.

### "It did not listen to my Teams meeting": diagnosis and fix
- **What happened:** the recording *was* capturing audio (soundcard capture threads were active, with "data discontinuity" warnings), but the Record screen's timer and level meters never moved. The engine had logged `No supported WebSocket library detected`: uvicorn needs the `websockets` package for `/recordings/live`, and it was never a declared dependency. Processing then failed with `mic.wav` not found, because the meeting was deleted while its processing job was still reading the files.
- **Capture path confirmed correct** (volume-only probe during the live Teams call; nothing stored): Teams plays on `Headset Earphone (Jabra Link 370)` at -23.7 dBFS RMS, the default device that MinuteTaker records. Realtek speakers were silent.
- **Fixes:** added `websockets>=12` to the engine dependencies. The Record screen now polls `/recordings/status` if the live socket errors or closes. `DELETE /meetings/{id}` returns 409 while a job for that meeting is queued or running, and the Meeting screen shows the message. Verified on a real uvicorn server (live messages received, no warnings); 35 tests pass.
