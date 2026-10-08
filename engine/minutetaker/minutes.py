"""Minutes-of-meeting + summary generation (with map-reduce for long meetings)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Callable, Optional

from .config import Config
from .llm import extract_json, get_llm

MAX_DIRECT_CHARS = 60_000   # ≈ 15k tokens; beyond this use map-reduce (FR-25)
CHUNK_CHARS = 40_000

SECTIONS = ["attendees", "agenda", "discussion", "decisions", "action_items", "open_issues",
            "next_meeting", "tldr", "executive_summary"]

SCHEMA = """{
  "title": "short meeting title",
  "attendees": [{"name": "string", "role": "string or empty"}],
  "agenda": ["agenda item"],
  "discussion": [{"topic": "string", "points": ["concise point"]}],
  "decisions": ["decision taken"],
  "action_items": [{"task": "string", "owner": "person or empty", "due": "date/timeframe or empty"}],
  "open_issues": ["open issue or risk"],
  "next_meeting": "date/time/purpose or empty",
  "tldr": ["3-5 bullets"],
  "executive_summary": "1-2 paragraphs"
}"""

TEMPLATES: dict[str, str] = {
    "formal": "Produce formal Minutes of Meeting suitable for an official record. Neutral, factual tone; "
              "attribute decisions and commitments to people.",
    "standup": "This is a daily stand-up. Organise discussion per person (yesterday / today / blockers). "
               "Keep it very short; blockers go to open_issues.",
    "client": "This is a client meeting. Highlight client requirements, commitments made to the client, "
              "commercial points and follow-ups. Use a professional, client-ready tone.",
    "interview": "This is an interview. Discussion topics are the question areas; points capture the "
                 "candidate's answers. Decisions = evaluation outcome if stated; no speculation.",
}

LANG_NAMES = {"el": "Greek", "en": "English"}

SOURCE_NOTES = {
    "transcript": "Source: transcript imported from the meeting platform (captions may contain recognition errors).",
    "chat": "Source: exported text chat — written messages with their send time, not speech. Treat each message "
            "as a contribution by its author; resolve relative dates (e.g. 'Friday') against the message date.",
}

Progress = Callable[[float, str], None]


def fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def transcript_text(segments: list[dict], meeting: Optional[dict] = None) -> str:
    stamp = fmt_ts
    if meeting and meeting.get("source") == "chat" and meeting.get("started_at"):
        try:  # chats span hours or days: show the real send time, not an offset
            base = datetime.fromisoformat(meeting["started_at"])
            stamp = lambda sec: (base + timedelta(seconds=sec)).strftime("%Y-%m-%d %H:%M")  # noqa: E731
        except ValueError:
            pass
    return "\n".join(f"[{stamp(s['start_s'])}] {s.get('speaker') or 'Unknown'}: {s['text']}" for s in segments)


def resolve_language(output_language: str, meeting_language: Optional[str]) -> str:
    if output_language and output_language != "same":
        return output_language
    return meeting_language if meeting_language in LANG_NAMES else (meeting_language or "en")


def _system(cfg: Config, template: str, lang: str, only_key: Optional[str] = None) -> str:
    instr = cfg.settings.custom_templates.get(template) or TEMPLATES.get(template, TEMPLATES["formal"])
    lang_name = LANG_NAMES.get(lang, lang)
    s = (f"You are an expert minute-taker and business analyst. {instr}\n"
         f"Write ALL content in {lang_name}. Use only facts present in the transcript; never invent "
         "names, dates or decisions. Use the speaker names exactly as given. Transcripts come from "
         "speech recognition and may contain errors — interpret sensibly.\n"
         f"Return ONLY a JSON object with this structure:\n{SCHEMA}")
    if only_key:
        s += f"\nReturn a JSON object containing only the key \"{only_key}\". ONLY_KEY={only_key}"
    return s


def _header(meeting: dict) -> str:
    parts = [f"Meeting title: {meeting.get('title')}", f"Platform: {meeting.get('platform')}",
             f"Date: {(meeting.get('started_at') or '')[:10]}"]
    if meeting.get("participants_hint"):
        parts.append(f"Known participants: {meeting['participants_hint']}")
    if meeting.get("agenda"):
        parts.append(f"Planned agenda: {meeting['agenda']}")
    return "\n".join(parts)


def _chunks(text: str, size: int = CHUNK_CHARS) -> list[str]:
    lines, out, cur = text.split("\n"), [], ""
    for ln in lines:
        if len(cur) + len(ln) > size and cur:
            out.append(cur)
            cur = ""
        cur += ln + "\n"
    if cur:
        out.append(cur)
    return out


def generate(cfg: Config, meeting: dict, segments: list[dict], template: str = "formal",
             output_language: str = "same", progress: Progress = lambda p, m: None) -> dict:
    llm = get_llm(cfg)
    lang = resolve_language(output_language, meeting.get("language"))
    text = transcript_text(segments, meeting)
    if not text.strip():
        raise ValueError("Transcript is empty — nothing to summarise")
    header = _header(meeting)
    system = _system(cfg, template, lang)

    if len(text) <= MAX_DIRECT_CHARS:
        progress(0.2, "Generating minutes")
        result = extract_json(llm.complete(system, f"{header}\n\nTRANSCRIPT:\n{text}"))
    else:
        parts = _chunks(text)
        notes = []
        for i, part in enumerate(parts):
            progress(0.1 + 0.7 * i / len(parts), f"Analysing part {i + 1}/{len(parts)}")
            notes.append(extract_json(llm.complete(
                system + "\nThis is PART of a longer meeting; extract everything relevant from this part.",
                f"{header}\n\nTRANSCRIPT PART {i + 1}/{len(parts)}:\n{part}")))
        progress(0.85, "Merging parts")
        result = extract_json(llm.complete(
            system + "\nYou receive partial minutes extracted from consecutive parts of one meeting. "
                     "Merge them into one coherent set: deduplicate, keep chronological topic order.",
            f"{header}\n\nPARTIAL MINUTES (JSON):\n{json.dumps(notes, ensure_ascii=False)}"))
    progress(1.0, "Done")
    return normalise(result, meeting, lang)


def regenerate_section(cfg: Config, meeting: dict, segments: list[dict], current: dict, section: str,
                       template: str = "formal", output_language: str = "same") -> dict:
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section}")
    lang = resolve_language(output_language, meeting.get("language"))
    text = transcript_text(segments, meeting)
    if len(text) > MAX_DIRECT_CHARS:
        text = text[:MAX_DIRECT_CHARS]
    reply = extract_json(get_llm(cfg).complete(_system(cfg, template, lang, only_key=section),
                                               f"{_header(meeting)}\n\nTRANSCRIPT:\n{text}"))
    merged = {**current, section: reply.get(section, current.get(section))}
    return normalise(merged, meeting, lang)


def normalise(r: dict, meeting: dict, lang: str) -> dict:
    def strs(v):
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x).strip() for x in (v or []) if str(x).strip()]

    att = []
    for a in r.get("attendees") or []:
        att.append({"name": a, "role": ""} if isinstance(a, str) else
                   {"name": str(a.get("name", "")), "role": str(a.get("role", "") or "")})
    disc = []
    for d in r.get("discussion") or []:
        if isinstance(d, str):
            disc.append({"topic": d, "points": []})
        else:
            disc.append({"topic": str(d.get("topic", "")), "points": strs(d.get("points"))})
    acts = []
    for a in r.get("action_items") or []:
        if isinstance(a, str):
            a = {"task": a}
        acts.append({"task": str(a.get("task", "")), "owner": str(a.get("owner", "") or ""),
                     "due": str(a.get("due", "") or "")})
    es = r.get("executive_summary") or ""
    if isinstance(es, list):
        es = "\n\n".join(map(str, es))
    return {"title": r.get("title") or meeting.get("title") or "", "language": lang,
            "attendees": att, "agenda": strs(r.get("agenda")), "discussion": disc,
            "decisions": strs(r.get("decisions")), "action_items": acts,
            "open_issues": strs(r.get("open_issues")), "next_meeting": str(r.get("next_meeting") or ""),
            "tldr": strs(r.get("tldr")), "executive_summary": str(es)}
