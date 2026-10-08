# MinuteTaker — Functional & Technical Specification

**Version:** 1.0 (FROZEN)
**Date:** 2026-10-05
**Status:** Approved by client — decisions in §11

---

## 1. Purpose

A desktop application that listens to online meetings and conversations held on **MS Teams, Google Meet, Zoom, Viber and WhatsApp**, transcribes them, identifies speakers, and produces:

1. **Minutes of Meeting (MoM)** — structured, formal record (attendees, agenda, discussion, decisions, action items).
2. **Summaries** — executive summary plus a short TL;DR.
3. **Export** to a Word document (`.docx`), with optional PDF and Markdown.

## 2. Key Design Decision — How We "Hear" Meetings

The five platforms have very different integration options:

| Platform | Official bot / recording API | Desktop client |
|---|---|---|
| MS Teams | Graph API (tenant admin consent, complex) | Yes |
| Google Meet | Meet REST API (Workspace only, post-meeting) | Browser |
| Zoom | Meeting SDK / RTMS (app approval needed) | Yes |
| Viber | **None** for calls | Yes |
| WhatsApp | **None** for calls | Yes |

Viber and WhatsApp offer no programmatic access to call audio, so per-platform bots cannot cover every requirement.

**Approach: platform-agnostic local audio capture.** The app records two streams on the user's own computer:

- **System audio (loopback)** — what the other participants say, regardless of which app plays it.
- **Microphone** — what the user says.

Advantages: works identically for all five platforms (and phone calls via desktop, in-person meetings via mic only), no bot joins the call, no admin consent, no third-party API approvals, audio never needs to leave the machine.

Trade-off: the user must run the app on the device attending the meeting. Speaker names are not supplied by the platform, so they are inferred by diarization and the user relabels them (labels can be remembered per meeting series).

## 3. Users & Use Cases

| ID | Use case |
|---|---|
| UC-01 | User starts recording before/when a meeting begins; stops when it ends. |
| UC-02 | User imports an existing audio/video file (e.g. a Teams/Zoom recording) and processes it. |
| UC-07 | User imports a transcript or chat instead of audio (Teams/Zoom/Meet export, VTT/SRT/TXT/DOCX/PDF, WhatsApp chat export, or pasted text) and gets the same minutes, summaries and exports. |
| UC-03 | User reviews the transcript, renames speakers (e.g. "Speaker 2" → "Maria K."), fixes errors. |
| UC-04 | User generates MoM and summaries, edits them, and exports to `.docx`. |
| UC-05 | User browses, searches and re-opens past meetings. |
| UC-06 | User records an in-person meeting via microphone only. |

## 4. Functional Requirements

### 4.1 Capture
- FR-01 Record microphone and system loopback audio simultaneously, mixed and also stored as separate tracks (separate tracks improve "me vs. others" attribution).
- FR-02 Select input/output devices; show live level meters.
- FR-03 Pause / resume / stop; show elapsed time.
- FR-04 Optional meeting metadata before or after recording: title, platform (Teams/Meet/Zoom/Viber/WhatsApp/In-person/Other), date, participants, agenda.
- FR-05 Consent reminder on every recording start (GDPR — see §8), with a ready-to-paste notice text for the meeting chat.
- FR-06 Import audio/video files: wav, mp3, m4a, m4b, aac, ogg, opus, flac, wma, aiff, amr, caf, mka; video mp4, m4v, mov, mkv, webm, avi, wmv, flv, 3gp, ts/mts/m2ts, mpg, vob, ogv, mxf. Decoding uses ffmpeg when installed, otherwise the FFmpeg bundled with PyAV, so no separate install is needed. Videos without an audio track are rejected with a clear message.
- FR-06a Import transcripts and chats, skipping speech-to-text: Teams (.vtt with voice tags, .docx), Zoom (.vtt, .txt, meeting chat), Google Meet (.docx/.pdf/.txt with attendee list and time markers), generic .srt/.vtt/.txt/.docx/.pdf, WhatsApp chat exports (.txt or .zip; Android/iOS, EN/EL, 12/24 h, d/m and m/d dates), and pasted text. Speakers, timestamps and platform are detected from content; missing times are estimated from text length. Chats keep real send times.
- FR-06b WhatsApp voice notes: when the chat is exported *with media* (.zip), audio attachments (opus/m4a/mp3/aac/amr…; Android `(file attached)` and iOS `<attached: …>` forms in any language) are extracted and transcribed with the configured STT provider. Each becomes a `[voice note] …` message from its sender, at its send time, and can be played back from the transcript. Notes missing from the export are marked as such.
- FR-07 Crash safety: audio is written to disk in chunks during recording; nothing is lost if the app closes.

### 4.2 Transcription
- FR-10 Speech-to-text with timestamps per segment.
- FR-11 Languages: Greek and English at minimum, auto-detected; mixed Greek/English meetings supported.
- FR-12 Speaker diarization ("Speaker 1, 2 …"); microphone track labelled as the user.
- FR-13 Speaker renaming, applied across the whole transcript.
- FR-14 Inline transcript editing.
- FR-15 Live (near real-time) transcript during recording — **deferred to v2** (§11).

### 4.3 Minutes & Summaries
- FR-20 Generate MoM with sections: Header (title, date, time, duration, platform), Attendees, Agenda, Discussion points per topic, **Decisions**, **Action items** (task, owner, due date if mentioned), Open issues / risks, Next meeting.
- FR-21 Generate summaries: TL;DR (3–5 bullets) and Executive summary (1–2 paragraphs).
- FR-22 Output language selectable (same as meeting / Greek / English).
- FR-23 Templates: Formal MoM, Standup, Client meeting, Interview (editable prompt templates).
- FR-24 Regenerate any section; all generated content is editable before export.
- FR-25 Long meetings (2h+) handled by chunked summarisation (map-reduce).

### 4.4 Export
- FR-30 Export to `.docx` with a professional layout: cover header, tables for attendees / decisions / action items, page numbers.
- FR-31 Export options: include/exclude full transcript (appendix), summaries, timestamps.
- FR-32 Optional exports: PDF, Markdown, plain-text transcript, SRT.
- FR-33 Optional company logo / branding on the document.

### 4.5 Library
- FR-40 List of meetings with title, date, platform, duration, status.
- FR-41 Full-text search across transcripts and minutes.
- FR-42 Delete meetings (audio + data), with an optional "delete audio after N days" retention setting.

## 5. Non-Functional Requirements

| ID | Requirement |
|---|---|
| NFR-01 | Runs on Windows 10/11 (primary) and macOS 13+; Linux best-effort. |
| NFR-02 | Privacy: audio and transcripts stored locally by default; any cloud call is explicit and configurable. |
| NFR-03 | Transcription of 1h meeting in ≤ 15 min on a mid-range laptop (local mode) or ≤ 3 min (cloud mode). |
| NFR-04 | API keys stored in OS keychain, never in plain files. |
| NFR-05 | UI in English and Greek. |
| NFR-06 | Dark, high-density UI, JetBrains Mono, gold/cyan accents on near-black (house style). |

## 6. Architecture

```
┌──────────────────────────── Desktop shell (Electron) ────────────────────────────┐
│  React + TypeScript UI                                                           │
│  Record │ Library │ Meeting (Transcript / Minutes / Summary) │ Settings           │
└───────────────▲──────────────────────────────────────────────────────────────────┘
                │ HTTP + WebSocket (localhost)
┌───────────────┴──────────────── Python engine (FastAPI) ─────────────────────────┐
│ Capture        │ sounddevice + WASAPI loopback (Win) / ScreenCaptureKit (macOS)  │
│ Transcription  │ faster-whisper (local)  ─or─  cloud STT adapter                 │
│ Diarization    │ pyannote / simple clustering; mic track = "Me"                  │
│ Summarisation  │ LLM adapter (Claude / OpenAI / Ollama local)                    │
│ Export         │ python-docx (+ docx→PDF)                                        │
│ Storage        │ SQLite (+FTS5) + audio files in user data folder                │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Rationale: Python has the best audio/ML ecosystem (Whisper, pyannote, python-docx); React gives a modern UI; the engine can also run headless (CLI / web mode) for file processing on a server later.

### 6.1 Processing pipeline
`Record/Import → normalise (16 kHz mono + tracks) → VAD → transcribe → diarize → merge → (user review) → LLM: MoM + summaries → .docx`

Transcript/chat import enters at *merge*: `parse (transcripts.py) → participants + segments → (user review) → LLM → .docx`.

### 6.2 Data model (SQLite)
- `meeting(id, title, platform, started_at, duration_s, language, status, audio_path, source[recording|media|transcript|chat], created_at)`
- `participant(id, meeting_id, label, display_name, is_self)`
- `segment(id, meeting_id, participant_id, start_s, end_s, text, edited, media)`
- `minutes(id, meeting_id, template, language, content_json, updated_at)`
- `summary(id, meeting_id, kind[tldr|executive], content, updated_at)`
- `action_item(id, meeting_id, task, owner, due, status)`
- `segment_fts` (FTS5 virtual table)

### 6.3 API (engine, localhost only)
| Method | Path | Purpose |
|---|---|---|
| GET | /devices | List audio devices |
| POST | /recordings/start · /pause · /resume · /stop | Capture control |
| WS | /recordings/live | Levels + live transcript |
| POST | /meetings/import | Import audio/video, transcript or chat file |
| POST | /meetings/import-text | Import pasted transcript / chat text |
| GET/PATCH/DELETE | /meetings/{id} | Meeting CRUD |
| POST | /meetings/{id}/transcribe | Run STT + diarization (job) |
| PATCH | /meetings/{id}/participants/{pid} | Rename speaker |
| POST | /meetings/{id}/minutes · /summaries | Generate (job) |
| GET | /meetings/{id}/export?format=docx | Download document |
| GET | /meetings/{id}/segments/{sid}/media | Play a voice note |
| GET | /jobs/{id} | Job progress |
| GET | /search?q= | Full-text search |

## 7. UI Screens
1. **Record** — device pickers, level meters, big Start/Stop, timer, metadata form, consent reminder, optional live transcript.
2. **Library** — searchable table of meetings.
3. **Meeting** — tabs: *Transcript* (speaker-coloured, editable, rename speakers), *Minutes* (editable sections, action-items table), *Summary*; toolbar with Generate / Regenerate / Export.
4. **Settings** — STT engine & model size, LLM provider & key, languages, templates, storage & retention, branding.

## 8. Legal & Compliance (Greece / EU)
- Recording conversations without the knowledge of participants is a criminal offence in Greece (Penal Code art. 370A) and processing requires a lawful basis under GDPR. The app therefore shows a consent reminder at every start and offers a notice text to post in the meeting chat; responsibility for obtaining consent stays with the user.
- Local-first storage, retention settings and delete-all support data-minimisation obligations.
- When cloud STT/LLM is used, the provider acts as processor — settings must clearly show which provider receives the data.

## 9. Out of Scope (v1)
- Bots that join calls automatically.
- Mobile apps (WhatsApp/Viber calls on a phone cannot be captured by a desktop app — user would need the desktop clients or import a recording).
- Calendar integration, auto-sending minutes by email (candidates for v2).

## 10. Delivery Plan
| Phase | Content |
|---|---|
| P1 | Engine: import file → transcribe → diarize → MoM + summaries → .docx (CLI + API) |
| P2 | Live capture (mic + loopback), storage, library |
| P3 | Electron/React UI, editing, speaker renaming, settings |
| P4 | Packaging (Windows installer, macOS dmg), tests, docs |

## 11. Decisions (confirmed 2026-10-05)
| # | Topic | Decision |
|---|---|---|
| D1 | App form | Desktop app: Electron + React/TypeScript UI, Python FastAPI engine on localhost |
| D2 | Transcription | Local faster-whisper by default; cloud engine (OpenAI) optional, configurable |
| D3 | LLM | Claude API default; OpenAI and local Ollama as alternatives (pluggable adapter) |
| D4 | Live transcript | Not in v1 — transcription runs after Stop; live view planned for v2 |
| D5 | Export | Word .docx primary; Markdown, TXT, SRT, PDF (via LibreOffice when installed) |
| D6 | Languages | Greek + English, auto-detected; output language selectable |

### 11.1 Implementation notes
- System-audio loopback uses the `soundcard` library: native WASAPI loopback on Windows, PulseAudio/PipeWire monitor on Linux. macOS needs a virtual loopback device (e.g. BlackHole) selected as the "system" source — documented in README.
- Diarization: the microphone track is always attributed to the user ("Me"); remote speakers are separated with pyannote.audio when installed and a Hugging Face token is configured, otherwise remote speech is labelled "Participants" and can be split/renamed manually.
- API keys: stored via `keyring` (OS keychain) when available; environment variables are also honoured.
- A deterministic `mock` STT/LLM provider exists for tests and demos without models or keys.
