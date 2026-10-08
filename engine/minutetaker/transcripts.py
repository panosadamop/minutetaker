"""Transcript & chat import: Teams / Zoom / Meet exports, VTT, SRT, TXT, DOCX, PDF,
WhatsApp chat exports (.txt / .zip) and pasted text → timed, speaker-labelled segments.

Imported text skips speech-to-text and feeds the same minutes / summary / export
pipeline as recordings. Formats are detected from content, not just the extension:
1. WhatsApp lines ("05/10/2026, 10:02 - Name: msg" / "[05/10/26, 10:02:33] Name: msg")
2. Cue files with "-->" timing lines (VTT, SRT, old Teams .docx)
3. Line-based transcripts ("Name: text", "Name   0:03" + text, "[00:01:02] Name: text",
   Meet "00:05:00" markers, Zoom chat "10:02:33 From Name to Everyone:"),
   falling back to plain paragraphs attributed to "Speaker 1".
Missing timestamps are estimated from text length (~150 words/min).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

SUPPORTED = {".vtt", ".srt", ".txt", ".docx", ".pdf", ".zip"}
DEFAULT_SPEAKER = "Speaker 1"
WORDS_PER_S = 2.5
MAX_TEXT_BYTES = 200 << 20


@dataclass
class Parsed:
    segments: list[dict]                    # [{start, end, text, speaker}]
    kind: str = "transcript"                # transcript | chat
    platform: Optional[str] = None          # set only when the format identifies it
    started_at: Optional[str] = None
    attendees: list[str] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        return list(dict.fromkeys(s["speaker"] for s in self.segments))

    @property
    def duration(self) -> float:
        return max((s["end"] for s in self.segments), default=0.0)


# ------------------------------------------------------------------ reading --
def decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    for enc in ("utf-8-sig", "cp1253"):     # cp1253: Greek Windows exports
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


def _docx_text(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    out = []
    for item in Document(str(path)).iter_inner_content():
        if isinstance(item, Table):
            out += ["  ".join(c.text.strip() for c in row.cells) for row in item.rows]
        else:
            out.append(item.text)
    return "\n".join(out)


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("PDF import needs pypdf: pip install pypdf") from e
    text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
    if not text.strip():
        raise ValueError("This PDF has no text layer (scanned?) — OCR it first or paste the text")
    return text


def _zip_text(path: Path) -> str:
    """WhatsApp 'Export chat → Attach media' zips hold one chat .txt plus media files."""
    with zipfile.ZipFile(path) as z:
        txts = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith(".txt")]
        if not txts:
            raise ValueError("No chat .txt found in the zip (expected a WhatsApp chat export)")
        pick = (next((i for i in txts if Path(i.filename).name.lower() == "_chat.txt"), None)
                or next((i for i in txts if "whatsapp" in i.filename.lower()), None)
                or max(txts, key=lambda i: i.file_size))
        if pick.file_size > MAX_TEXT_BYTES:
            raise ValueError("Chat text in the zip is too large")
        return decode(z.read(pick))


def parse_file(path: str | Path) -> Parsed:
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported transcript type {path.suffix}")
    if ext == ".docx":
        return parse_text(_docx_text(path))
    if ext == ".pdf":
        return parse_text(_pdf_text(path))
    if ext == ".zip":
        return parse_text(_zip_text(path))
    if path.stat().st_size > MAX_TEXT_BYTES:
        raise ValueError("Transcript file is too large")
    text = decode(path.read_bytes())
    if ext in (".vtt", ".srt"):
        return parse_cues(_clean(text), name_lines=False)
    return parse_text(text)


def parse_text(text: str) -> Parsed:
    text = _clean(text)
    if not text.strip():
        raise ValueError("No transcript text found")
    return parse_whatsapp(text) or (parse_cues(text, name_lines=True) if len(_TIMING.findall(text)) >= 2
                                    else parse_lines(text))


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    text = re.sub(r"[​-‏‪-‮⁦-⁩]", "", text)   # bidi / zero-width marks
    return text.replace(" ", " ").replace(" ", " ")


# -------------------------------------------------------------------- shared --
_TS = r"(?:\d{1,2}:)?\d{1,2}:\d{1,2}(?:[.,]\d{1,3})?"
_NAME_BLOCK = {"note", "notes", "decision", "decisions", "action", "actions", "action item", "action items",
               "todo", "risk", "risks", "agenda", "date", "time", "subject", "summary", "attendees",
               "participants", "location", "next steps", "http", "https", "re", "fw", "σημείωση",
               "σημειώσεις", "απόφαση", "αποφάσεις", "ημερομηνία", "ώρα", "θέμα", "συμμετέχοντες"}
_PARTICLES = {"de", "da", "di", "del", "van", "von", "der", "la", "le", "bin", "al", "του", "της"}


def to_seconds(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def is_name(s: str) -> bool:
    """Heuristic: does this look like a speaker label rather than prose?"""
    s = s.strip()
    words = s.split()
    if not (1 <= len(s) <= 60 and 1 <= len(words) <= 6) or not s[0].isalpha() or not s[0].isupper():
        return False
    if s.endswith((".", "?", "!", ",", ";")) or s.casefold() in _NAME_BLOCK:
        return False
    if sum(c.isdigit() for c in s) > 2 and not re.fullmatch(r"(?i)speaker[ _]?\d+", s):
        return False
    lower = [w for w in words[1:] if w[0].isalpha() and w[0].islower() and w.casefold() not in _PARTICLES]
    return not lower


def _split_name(text: str) -> tuple[Optional[str], str]:
    m = re.match(r"^([^:]{1,60}):\s+(.+)$", text, re.S)
    if m and is_name(m.group(1)):
        return m.group(1).strip(), m.group(2).strip()
    return None, text


def _estimate(text: str) -> float:
    return max(1.0, min(60.0, len(text.split()) / WORDS_PER_S))


def _timeline(items: list[dict]) -> list[dict]:
    """items: [{speaker, text, ts?, end?}] in document order → monotonic segments.

    Missing starts continue from the previous segment; estimated ends are clipped at the
    next start so the transcript never overlaps itself."""
    out: list[dict] = []
    cursor = 0.0
    for it in items:
        text = re.sub(r"\s+", " ", it["text"]).strip()
        if not text:
            continue
        start = it["ts"] if it.get("ts") is not None else cursor
        if out:
            # same stamp as the previous line (chat minute resolution) → place it right after
            start = out[-1]["end"] if start <= out[-1]["start"] else start
        end, estimated = it.get("end"), it.get("end") is None
        end = start + _estimate(text) if estimated or end < start else end
        out.append({"start": start, "end": end, "text": text, "speaker": it["speaker"] or DEFAULT_SPEAKER,
                    "media": it.get("media"), "_est": estimated})
        cursor = end
    for a, b in zip(out, out[1:]):
        if a["_est"] and a["end"] > b["start"] >= a["start"]:
            a["end"] = b["start"]
    return [{"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"],
             "speaker": s["speaker"], **({"media": s["media"]} if s["media"] else {})} for s in out]


def extract_media(zip_path: Path, names: set[str], dest: Path) -> dict[str, Path]:
    """Copy the named attachments (matched by basename, case-insensitive) out of a chat zip.

    Only the basename is used for the target, so crafted member paths cannot escape `dest`.
    A `<name>.transcript.json` sidecar next to a file is copied too (mock STT / demos)."""
    wanted = {n.casefold() for n in names}
    found: dict[str, Path] = {}
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = Path(info.filename).name
            key = base.casefold().removesuffix(".transcript.json")
            if info.is_dir() or key not in wanted or info.file_size > MAX_TEXT_BYTES:
                continue
            dest.mkdir(parents=True, exist_ok=True)
            (dest / base).write_bytes(z.read(info))
            if base.casefold() == key:
                found[key] = dest / base
    return {n: found[n.casefold()] for n in names if n.casefold() in found}


# ---------------------------------------------------------------------- cues --
_TIMING = re.compile(rf"^[ \t]*({_TS})[ \t]*-->[ \t]*({_TS})", re.M)
_VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")
_TAG = re.compile(r"</?[^>\n]+>")
_CUE_ID = re.compile(r"^(\d+|[0-9a-fA-F-]{8,}(?:/\d+-\d+)?|[\w-]*\d[\w-]*-\d+)$")


def parse_cues(text: str, name_lines: bool = False) -> Parsed:
    """WebVTT / SRT. Speakers come from Teams <v Name> tags, Zoom "Name: text" cue text or —
    for text pasted from old Teams .docx exports — a short name line above the caption."""
    cues: list[tuple[float, float, list[str]]] = []
    body: Optional[list[str]] = None
    for line in text.split("\n"):
        m = _TIMING.match(line)
        if m:
            if body and _CUE_ID.match(body[-1].strip()):
                body.pop()
            body = []
            cues.append((to_seconds(m.group(1)), to_seconds(m.group(2)), body))
        elif body is not None and line.strip() and not line.startswith(("NOTE", "STYLE")):
            body.append(line)
    if not cues:
        raise ValueError("No caption cues found")

    items, voiced, last = [], False, None
    for start, end, lines in cues:
        joined = "\n".join(lines)
        v = _VOICE.search(joined)
        speaker = v.group(1).strip() if v else None
        voiced |= bool(v)
        rows = [r for r in (_TAG.sub("", ln).strip() for ln in lines) if r]
        if not speaker and name_lines and len(rows) >= 2 and ":" not in rows[0] and is_name(rows[0]):
            speaker = rows.pop(0)
        said = " ".join(rows)
        if not speaker:
            speaker, said = _split_name(said)
        speaker = speaker or last
        last = speaker
        items.append({"speaker": speaker, "text": said, "ts": start, "end": end})
    zoomish = text.lstrip().startswith("WEBVTT") and any(i["speaker"] for i in items) and not voiced
    return Parsed(_timeline(items), platform="MS Teams" if voiced else "Zoom" if zoomish else None)


# --------------------------------------------------------------------- lines --
_N = r"[^\W\d_][^:\t\[\]]{0,59}?"
_L_TS_ONLY = re.compile(rf"^[\[(]?(?P<ts>{_TS})[\])]?$")
_L_ZOOM_CHAT = re.compile(rf"^(?P<ts>{_TS})\s+From\s+(?P<name>.+?)(?:\s+to\s+.+?)?\s*:\s*(?P<text>.*)$", re.I)
_L_TS_NAME = re.compile(rf"^[\[(]?(?P<ts>{_TS})[\])]?\s*[-–—|]?\s*(?P<name>{_N})\s*:\s*(?P<text>.*)$")
_L_NAME_TS = re.compile(rf"^\[?(?P<name>{_N})\]?\s*[\[(](?P<ts>{_TS})[\])]\s*:?\s*(?P<text>.*)$")
_L_HEADER = re.compile(rf"^(?:\[(?P<bname>[^\]]{{1,60}})\]|(?P<name>{_N}))(?:\s+|\s*[-–|]\s*)(?P<ts>{_TS})$")
_L_NAME_TEXT = re.compile(rf"^(?P<name>{_N})\s*:(?:\s+(?P<text>.+))?$")
_L_TS_TEXT = re.compile(rf"^[\[(]?(?P<ts>{_TS})[\])]?\s+(?P<text>\S.*)$")
_SKIP = re.compile(r"(?i)\b(started|stopped) transcription$|^meeting ended after\b|"
                   r"^this editable transcript was computer generated|^transcript$|^μεταγραφή$")
_ATTENDEES = {"attendees", "participants", "συμμετέχοντες"}


def _match_line(line: str) -> Optional[dict]:
    if m := _L_TS_ONLY.match(line):
        return {"ts": to_seconds(m["ts"])}
    if m := _L_ZOOM_CHAT.match(line):
        return {"ts": to_seconds(m["ts"]), "name": m["name"].strip(), "text": m["text"], "platform": "Zoom"}
    for rx in (_L_TS_NAME, _L_NAME_TS, _L_HEADER, _L_NAME_TEXT):
        m = rx.match(line)
        if not m:
            continue
        g = m.groupdict()
        name = (g.get("bname") or g.get("name") or "").strip()
        if is_name(name):
            return {"ts": to_seconds(g["ts"]) if g.get("ts") else None, "name": name, "text": g.get("text") or ""}
    if m := _L_TS_TEXT.match(line):
        return {"ts": to_seconds(m["ts"]), "text": m["text"]}
    return None


def parse_lines(text: str) -> Parsed:
    lines = [ln.strip() for ln in text.split("\n")]
    matches = [_match_line(ln) if ln else None for ln in lines]
    nonempty = sum(1 for ln in lines if ln)
    n_spk = sum(1 for m in matches if m and m.get("name"))
    speaker_mode = (n_spk >= 2 and n_spk >= 0.25 * nonempty) or (n_spk == 1 and nonempty <= 2)

    items: list[dict] = []
    cur: Optional[dict] = None
    pending_ts: Optional[float] = None
    preamble: list[str] = []
    platform = None
    for line, m in zip(lines, matches):
        if not line:
            if not speaker_mode:
                cur = None                       # paragraph break
            continue
        if _SKIP.search(line):
            if "transcription" in line.lower():
                platform = platform or "MS Teams"
            continue
        if m and set(m) == {"ts"}:              # bare timestamp marker (Meet every 5 min)
            pending_ts, cur = m["ts"], (cur if speaker_mode else None)
            continue
        if speaker_mode and m and m.get("name"):
            cur = {"speaker": m["name"], "text": m["text"], "ts": m["ts"] if m["ts"] is not None else pending_ts}
            platform = platform or m.get("platform")
            items.append(cur)
            pending_ts = None
        elif m and m.get("ts") is not None and "name" not in m:
            cur = {"speaker": items[-1]["speaker"] if speaker_mode and items else None, "text": m["text"],
                   "ts": m["ts"]}
            items.append(cur)
            pending_ts = None
        elif speaker_mode:
            if items:
                items[-1]["text"] += " " + line   # continuation of the current speaker turn
            else:
                preamble.append(line)
        elif cur:
            cur["text"] += " " + line
        else:
            cur = {"speaker": None, "text": line, "ts": pending_ts}
            items.append(cur)
            pending_ts = None

    stamps = [i["ts"] for i in items if i.get("ts") is not None]
    if stamps and min(stamps) >= 3600:          # wall-clock times (Zoom chat, captions) → offsets
        base = min(stamps)
        for i in items:
            if i.get("ts") is not None:
                i["ts"] -= base

    attendees: list[str] = []
    for a, b in zip(preamble, preamble[1:]):
        if a.casefold().rstrip(":") in _ATTENDEES:
            attendees = [x.strip() for x in b.split(",") if x.strip()]
            platform = platform or "Google Meet"
    return Parsed(_timeline(items), platform=platform, attendees=attendees)


# ------------------------------------------------------------------ whatsapp --
_WA_D = r"\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}"
_WA_T = r"\d{1,2}[:.]\d{2}(?:[:.]\d{2})?"
_WA_AP = r"[AaPp]\.?\s?[Mm]\.?|[πμ]\.?\s?μ\.?"
_WA_ANDROID = re.compile(rf"^(?P<d>{_WA_D}),?\s(?P<t>{_WA_T})(?:\s?(?P<ap>{_WA_AP}))?\s[-–]\s(?P<rest>.*)$")
_WA_IOS = re.compile(rf"^\[(?P<d>{_WA_D}),?\s(?P<t>{_WA_T})(?:\s?(?P<ap>{_WA_AP}))?\]\s(?P<rest>.*)$")
_WA_SKIP = re.compile(r"(?i)^<[^<>]*(omitted|παραλείφθηκ)[^<>]*>$|\b(image|video|audio|sticker|gif|document|"
                      r"contact card) omitted$|^<attached: [^>]+>$|\(file attached\)$|\(συνημμένο αρχείο\)$|"
                      r"^(this message was deleted|you deleted this message|το μήνυμα (αυτό )?διαγράφηκε|"
                      r"διαγράψατε αυτό το μήνυμα)\.?$|^null$")
_WA_EDITED = re.compile(r"\s*<[^<>]*(edited|επεξεργασ)[^<>]*>$", re.I)
# exports *with media*: Android "PTT-20261005-WA0003.opus (file attached)" (localised wording),
# iOS "<attached: 00000012-AUDIO-2026-10-05-10-20-11.opus>"
_WA_ATTACH = re.compile(r"^(?:(?P<a>[^\s<>()]+\.\w{2,4}) \([^()]{3,40}\)|<[^:<>]{1,30}: (?P<i>[^<>]+\.\w{2,4})>)$")
VOICE_EXT = {".opus", ".ogg", ".m4a", ".mp3", ".aac", ".amr", ".wav", ".3gp", ".caf"}
VOICE_TAG = "[voice note]"
VOICE_MISSING = "[voice note — not included in the export]"


def _wa_match(line: str):
    return _WA_ANDROID.match(line) or _WA_IOS.match(line)


def _wa_datetime(d: str, t: str, ap: Optional[str], order: str) -> datetime:
    f = [int(x) for x in re.split(r"[/.\-]", d)]
    y, mo, day = (f[0], f[1], f[2]) if order == "ymd" else (f[2], f[1], f[0]) if order == "dmy" else (f[2], f[0], f[1])
    if y < 100:
        y += 2000
    tp = [int(x) for x in re.split(r"[:.]", t)]
    h, mi, s = tp[0], tp[1], tp[2] if len(tp) > 2 else 0
    if ap:
        pm = re.sub(r"[.\s]", "", ap).lower() in ("pm", "μμ")
        h = h % 12 + (12 if pm else 0)
    return datetime(y, mo, day, h, mi, s)


def parse_whatsapp(text: str) -> Optional[Parsed]:
    lines = text.split("\n")
    heads = [(i, m) for i, ln in enumerate(lines) if (m := _wa_match(ln.strip()))]
    nonempty = sum(1 for ln in lines if ln.strip())
    if len(heads) < 2 or len(heads) < 0.3 * nonempty:
        return None
    fields = [[x for x in re.split(r"[/.\-]", m["d"])] for _, m in heads]
    if all(len(f[0]) == 4 for f in fields):
        order = "ymd"
    elif any(int(f[0]) > 12 for f in fields):
        order = "dmy"
    elif any(int(f[1]) > 12 for f in fields):
        order = "mdy"
    else:
        order = "dmy"

    msgs: list[dict] = []
    cur: Optional[dict] = None
    for ln in lines:
        m = _wa_match(ln.strip())
        if not m:
            if cur and ln.strip():
                cur["text"] += " " + ln.strip()
            continue
        cur = None
        nm = re.match(r"^([^:]{1,80}):\s?(.*)$", m["rest"])
        if not nm:                               # system line: "X created group", encryption notice
            continue
        try:
            when = _wa_datetime(m["d"], m["t"], m["ap"], order)
        except ValueError:
            continue
        body = nm.group(2).strip()
        att = _WA_ATTACH.match(body)
        cur = {"speaker": nm.group(1).strip(), "text": "" if att else body, "when": when,
               "attachment": (att["a"] or att["i"]).strip() if att else None}
        msgs.append(cur)

    kept = []
    for msg in msgs:
        msg["text"] = _WA_EDITED.sub("", msg["text"]).strip()
        if msg["attachment"] and Path(msg["attachment"]).suffix.lower() in VOICE_EXT:
            msg["text"], msg["media"] = VOICE_TAG, msg["attachment"]   # transcribed later by the engine
            kept.append(msg)
        elif msg["text"] and not _WA_SKIP.search(msg["text"]):
            kept.append(msg)                                           # text, or a photo's caption
    if not kept:
        raise ValueError("The chat export has no text messages or voice notes")
    first = kept[0]["when"]
    items = [{"speaker": k["speaker"], "text": k["text"], "ts": (k["when"] - first).total_seconds(),
              "media": k.get("media")} for k in kept]
    return Parsed(_timeline(items), kind="chat", platform="WhatsApp",
                  started_at=first.isoformat(timespec="seconds"))


# ------------------------------------------------------------------ language --
def detect_language(segments: list[dict]) -> Optional[str]:
    """'el' / 'en' from the written text; None when there is none (e.g. only voice notes)."""
    sample = " ".join(s["text"] for s in segments if not s.get("media"))[:20000]
    if not any(c.isalpha() for c in sample):
        return None
    greek = sum(1 for c in sample if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿")
    latin = sum(1 for c in sample if c.isascii() and c.isalpha())
    return "el" if greek and greek >= 0.5 * latin else "en"
