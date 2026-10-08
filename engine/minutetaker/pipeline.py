"""Background jobs and the processing pipeline."""
from __future__ import annotations

import shutil
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

from . import audio, diarize, minutes as mom, transcripts
from .config import Config
from .db import Database, new_id
from .stt import get_stt


class Jobs:
    def __init__(self, workers: int = 2):
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, kind: str, meeting_id: str, fn: Callable[[Callable[[float, str], None]], object]) -> dict:
        jid = new_id()
        job = {"id": jid, "kind": kind, "meeting_id": meeting_id, "status": "queued",
               "progress": 0.0, "message": "Queued", "error": None, "created": time.time()}
        with self.lock:
            self.jobs[jid] = job

        def progress(p: float, msg: str) -> None:
            job["progress"], job["message"] = round(max(0.0, min(1.0, p)), 3), msg

        def run():
            job["status"] = "running"
            try:
                fn(progress)
                job.update(status="done", progress=1.0, message="Done")
            except Exception as e:
                job.update(status="error", error=str(e), message=str(e))
                traceback.print_exc()

        self.pool.submit(run)
        return job

    def get(self, jid: str) -> Optional[dict]:
        return self.jobs.get(jid)

    def for_meeting(self, mid: str) -> list[dict]:
        return [j for j in self.jobs.values() if j["meeting_id"] == mid]


TEXT_SOURCES = ("transcript", "chat")   # imported text: no audio, skip speech-to-text


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Database(cfg.db_path)
        self.jobs = Jobs()
        self.apply_retention()

    # ---- ingestion ------------------------------------------------------
    def meeting_dir(self, mid: str) -> Path:
        d = self.cfg.audio_dir / mid
        d.mkdir(parents=True, exist_ok=True)
        return d

    def import_file(self, src: Path, title: str = "", platform: str = "Other", **meta) -> dict:
        """Import a recording (audio/video) or a transcript / chat export, chosen by extension."""
        ext = src.suffix.lower()
        if ext in transcripts.SUPPORTED:
            return self._import_transcript(transcripts.parse_file(src), title or src.stem, platform, src=src, **meta)
        if ext not in audio.SUPPORTED_IMPORT:
            raise ValueError(f"Unsupported file type {src.suffix or '(none)'}")
        m = self.db.create_meeting(title or src.stem, platform, status="imported", source="media", **meta)
        d = self.meeting_dir(m["id"])
        dst = d / f"original{ext}"
        shutil.copy2(src, dst)
        side = Path(str(src) + ".transcript.json")
        if side.exists():  # demo/test sidecar for the mock STT
            shutil.copy2(side, str(dst) + ".transcript.json")
        try:
            dur = audio.mix([dst], d / "mixed.wav")
        except Exception:
            self.delete(m["id"])  # e.g. a video without an audio track
            raise
        return self.db.update_meeting(m["id"], audio_path=str(dst), duration_s=dur)

    def import_text(self, text: str, title: str = "", platform: str = "Other", **meta) -> dict:
        """Import pasted transcript / chat / notes text."""
        return self._import_transcript(transcripts.parse_text(text), title or "Pasted transcript", platform,
                                       text=text, **meta)

    def _import_transcript(self, parsed: transcripts.Parsed, title: str, platform: str,
                           src: Optional[Path] = None, text: Optional[str] = None, **meta) -> dict:
        if not parsed.segments:
            raise ValueError("No transcript text found")
        s = self.cfg.settings
        lang = s.language if s.language != "auto" else transcripts.detect_language(parsed.segments)
        hint = meta.pop("participants_hint", "") or ", ".join(parsed.attendees)
        m = self.db.create_meeting(title, parsed.platform or platform, status="transcribed", source=parsed.kind,
                                   language=lang, duration_s=parsed.duration, started_at=parsed.started_at,
                                   participants_hint=hint, **meta)
        d = self.meeting_dir(m["id"])
        if src:
            shutil.copy2(src, d / f"source{src.suffix.lower()}")
        else:
            (d / "source.txt").write_text(text or "", "utf-8")
        segs = [{**seg, "label": seg["speaker"]} for seg in parsed.segments]
        notes = {seg["media"] for seg in segs if seg.get("media")}
        found = transcripts.extract_media(src, notes, d / "voice") if notes and src and src.suffix.lower() == ".zip" else {}
        for seg in segs:
            if seg.get("media"):
                f = found.get(seg["media"])
                seg["media"] = f"voice/{f.name}" if f else None
                seg["text"] = seg["text"] if f else transcripts.VOICE_MISSING
        me = hint.split(",")[0].strip().casefold() if hint else ""
        participants = [{"label": n, "display_name": n, "is_self": bool(me) and n.casefold() == me}
                        for n in parsed.speakers]
        self.db.replace_transcript(m["id"], participants, segs)
        if found:  # voice notes still need speech-to-text (done by the processing job)
            self.db.update_meeting(m["id"], status="imported")
        return self.db.get_meeting(m["id"])

    def register_recording(self, mid: str, tracks: dict[str, str]) -> dict:
        d = self.meeting_dir(mid)
        mixed = d / "mixed.wav"
        dur = audio.mix(list(tracks.values()), mixed)
        return self.db.update_meeting(mid, audio_path=str(mixed), mic_path=tracks.get("mic"),
                                      system_path=tracks.get("system"), duration_s=dur, status="recorded")

    # ---- processing -----------------------------------------------------
    def transcribe(self, mid: str, progress=lambda p, m: None) -> None:
        m = self.db.get_meeting(mid)
        if not m:
            raise KeyError(mid)
        if m.get("source") in TEXT_SOURCES:
            if not self.voice_notes(mid):
                raise ValueError("This meeting was imported from a transcript — there is no audio to transcribe")
            return self.transcribe_voice_notes(mid, progress)
        self.db.update_meeting(mid, status="transcribing", error=None)
        try:
            stt = get_stt(self.cfg)
            lang = None if self.cfg.settings.language == "auto" else self.cfg.settings.language
            tracks = {k: m.get(f"{k}_path") for k in ("mic", "system")}
            tracks = {k: v for k, v in tracks.items() if v and Path(v).exists()}
            if tracks:
                results, n = {}, len(tracks)
                for i, (kind, path) in enumerate(tracks.items()):
                    results[kind] = stt.transcribe(
                        path, lang, lambda p, msg, i=i, kind=kind: progress((i + p) / n * 0.85, f"{kind}: {msg}"))
                detected = (results.get("system") or results.get("mic"))["language"]
                progress(0.9, "Attributing speakers")
                participants, segs = diarize.build_transcript(
                    self.cfg, mic=results.get("mic", {}).get("segments"),
                    system=results.get("system", {}).get("segments"), system_path=tracks.get("system"))
            else:
                src = m["audio_path"]
                res = stt.transcribe(src, lang, lambda p, msg: progress(p * 0.85, msg))
                detected = res["language"]
                progress(0.9, "Identifying speakers")
                mixed = str(Path(src).parent / "mixed.wav")
                participants, segs = diarize.build_transcript(self.cfg, single=res["segments"],
                                                              single_path=mixed if Path(mixed).exists() else src)
            self._apply_hint_names(m, participants)
            self.db.replace_transcript(mid, participants, segs)
            self.db.update_meeting(mid, status="transcribed", language=detected)
            progress(1.0, f"{len(segs)} segments")
        except Exception as e:
            self.db.update_meeting(mid, status="error", error=str(e))
            raise

    def voice_notes(self, mid: str, pending_only: bool = False) -> list[dict]:
        """Chat segments backed by an audio attachment; pending = not transcribed yet."""
        return [s for s in self.db.segments(mid)
                if s.get("media") and (not pending_only or s["text"] == transcripts.VOICE_TAG)]

    def transcribe_voice_notes(self, mid: str, progress=lambda p, m: None, pending_only: bool = False) -> int:
        """Speech-to-text for WhatsApp voice notes. The sender is known, so no diarization."""
        m = self.db.get_meeting(mid)
        notes = self.voice_notes(mid, pending_only)
        if not notes:
            return 0
        self.db.update_meeting(mid, status="transcribing", error=None)
        try:
            stt = get_stt(self.cfg)
            lang = None if self.cfg.settings.language == "auto" else self.cfg.settings.language
            d, n = self.cfg.audio_dir / mid, len(notes)
            texts, langs = {}, {}
            for i, s in enumerate(notes):
                path = d / s["media"]
                label = f"Voice note {i + 1}/{n}"
                progress(i / n, label)
                if not path.exists():  # removed by retention
                    continue
                try:
                    res = stt.transcribe(str(path), lang, lambda p, msg, i=i: progress((i + p) / n, f"{label}: {msg}"))
                except ValueError:     # undecodable / empty attachment
                    texts[s["id"]] = f"{transcripts.VOICE_TAG} (could not be decoded)"
                    continue
                said = " ".join(x["text"].strip() for x in res["segments"]).strip()
                texts[s["id"]] = f"{transcripts.VOICE_TAG} {said}" if said else f"{transcripts.VOICE_TAG} (no speech)"
                if said:  # weight by amount of speech, so one short note can't decide the language
                    langs[res["language"]] = langs.get(res["language"], 0) + len(said)
            self.db.set_segment_texts(mid, texts)
            done = {"status": "transcribed"}
            if not m.get("language") and langs:  # chat had no written text to detect from
                done["language"] = max(langs, key=langs.get)
            self.db.update_meeting(mid, **done)
            progress(1.0, f"{len(texts)} voice notes transcribed")
            return len(texts)
        except Exception as e:
            self.db.update_meeting(mid, status="error", error=str(e))
            raise

    @staticmethod
    def _apply_hint_names(meeting: dict, participants: list[dict]) -> None:
        """If the user typed 'Me' name first in participants hint, use it for the self track."""
        hint = [h.strip() for h in (meeting.get("participants_hint") or "").split(",") if h.strip()]
        for p in participants:
            if p["is_self"] and hint:
                p["display_name"] = hint[0]

    def generate_minutes(self, mid: str, template: str = None, output_language: str = None,
                         progress=lambda p, m: None) -> dict:
        m = self.db.get_meeting(mid)
        template = template or self.cfg.settings.default_template
        output_language = output_language or self.cfg.settings.output_language
        prev = m["status"]
        self.db.update_meeting(mid, status="summarising", error=None)
        try:
            result = mom.generate(self.cfg, m, self.db.segments(mid), template, output_language, progress)
            self.db.save_minutes(mid, template, result["language"], result)
            self.db.save_summary(mid, "tldr", "\n".join(f"• {t}" for t in result["tldr"]))
            self.db.save_summary(mid, "executive", result["executive_summary"])
            self.db.update_meeting(mid, status="ready")
            return result
        except Exception as e:
            self.db.update_meeting(mid, status=prev if prev != "summarising" else "transcribed", error=str(e))
            raise

    def regenerate_section(self, mid: str, section: str) -> dict:
        m = self.db.get_meeting(mid)
        cur = self.db.get_minutes(mid)
        if not cur:
            raise ValueError("Generate minutes first")
        result = mom.regenerate_section(self.cfg, m, self.db.segments(mid), cur["content"], section,
                                        cur["template"], cur["language"] or "same")
        self.save_minutes_edit(mid, result)
        return result

    def save_minutes_edit(self, mid: str, content: dict) -> dict:
        cur = self.db.get_minutes(mid)
        template = cur["template"] if cur else self.cfg.settings.default_template
        lang = content.get("language") or (cur or {}).get("language") or "en"
        content = mom.normalise(content, self.db.get_meeting(mid), lang)
        self.db.save_minutes(mid, template, lang, content)
        self.db.save_summary(mid, "tldr", "\n".join(f"• {t}" for t in content["tldr"]))
        self.db.save_summary(mid, "executive", content["executive_summary"])
        return content

    def process_all(self, mid: str, template: str = None, progress=lambda p, m: None) -> None:
        if self.db.get_meeting(mid).get("source") in TEXT_SOURCES:
            if self.voice_notes(mid, pending_only=True):
                self.transcribe_voice_notes(mid, lambda p, msg: progress(p * 0.6, msg), pending_only=True)
                self.generate_minutes(mid, template, None, lambda p, msg: progress(0.6 + p * 0.4, msg))
            else:
                self.generate_minutes(mid, template, None, progress)
            return
        self.transcribe(mid, lambda p, msg: progress(p * 0.6, msg))
        self.generate_minutes(mid, template, None, lambda p, msg: progress(0.6 + p * 0.4, msg))

    # ---- housekeeping ---------------------------------------------------
    def delete(self, mid: str) -> None:
        self.db.delete_meeting(mid)
        shutil.rmtree(self.cfg.audio_dir / mid, ignore_errors=True)

    def apply_retention(self) -> int:
        days = self.cfg.settings.retention_days
        if not days:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        removed = 0
        for m in self.db.list_meetings():
            try:
                created = datetime.fromisoformat(m["created_at"])
            except Exception:
                continue
            d = self.cfg.audio_dir / m["id"]
            if created < cutoff and d.exists():
                shutil.rmtree(d, ignore_errors=True)
                self.db.clear_media(m["id"])
                self.db.update_meeting(m["id"], audio_path=None, mic_path=None, system_path=None)
                removed += 1
        return removed
