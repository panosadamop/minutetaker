"""FastAPI engine – listens on 127.0.0.1 only; the Electron shell talks to it."""
from __future__ import annotations

import asyncio
import mimetypes
import os
import secrets
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from . import __version__, audio, capture, export as exp, transcripts
from .config import SECRET_KEYS, Config
from .minutes import SECTIONS, TEMPLATES
from .pipeline import TEXT_SOURCES, Engine

mimetypes.add_type("audio/ogg", ".opus")  # WhatsApp voice notes; unknown to Windows' registry

CONSENT_NOTICE = {
    "en": "Notice: this meeting is being recorded and transcribed to produce minutes. "
          "If you do not consent, please say so now.",
    "el": "Ενημέρωση: η συνάντηση ηχογραφείται και απομαγνητοφωνείται για την τήρηση πρακτικών. "
          "Αν δεν συναινείτε, παρακαλούμε ενημερώστε μας τώρα.",
}


class Secret(BaseModel):
    name: str
    value: str


class StartRec(BaseModel):
    title: str = ""
    platform: str = "Other"
    participants_hint: str = ""
    agenda: str = ""
    mic_id: Optional[str] = None
    system_id: Optional[str] = None
    use_mic: bool = True
    use_system: bool = True


class Rename(BaseModel):
    display_name: str


class SegEdit(BaseModel):
    text: Optional[str] = None
    participant_id: Optional[str] = None


class GenBody(BaseModel):
    template: Optional[str] = None
    output_language: Optional[str] = None


class TextImport(BaseModel):
    text: str
    title: str = ""
    platform: str = "Other"
    participants_hint: str = ""
    agenda: str = ""
    auto_process: bool = True
    template: str = ""



def create_app(cfg: Optional[Config] = None, token: Optional[str] = None) -> FastAPI:
    cfg = cfg or Config()
    engine = Engine(cfg)
    token = token if token is not None else os.environ.get("MINUTETAKER_TOKEN", "")
    app = FastAPI(title="MinuteTaker Engine", version=__version__)
    app.state.engine = engine
    app.state.recorder = None
    app.state.recording_meeting = None
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    def auth(request: Request):
        if token and request.headers.get("x-mt-token") != token and request.query_params.get("token") != token:
            raise HTTPException(401, "invalid token")

    D = [Depends(auth)]
    db = engine.db

    def meeting_or_404(mid: str) -> dict:
        m = db.get_meeting(mid)
        if not m:
            raise HTTPException(404, "meeting not found")
        return m

    # ---------------------------------------------------------------- meta
    @app.get("/health")
    def health():
        return {"ok": True, "version": __version__, "data_dir": str(cfg.data_dir)}

    @app.get("/settings", dependencies=D)
    def get_settings():
        return {"settings": cfg.settings.model_dump(), "secrets": cfg.secret_status(),
                "templates": list(TEMPLATES) + [k for k in cfg.settings.custom_templates if k not in TEMPLATES],
                "template_text": {**TEMPLATES, **cfg.settings.custom_templates},
                "pdf_available": exp.soffice() is not None,
                "import_types": {"media": sorted(audio.SUPPORTED_IMPORT), "transcript": sorted(transcripts.SUPPORTED)}}

    @app.put("/settings", dependencies=D)
    def put_settings(values: dict):
        try:
            return cfg.update(**values).model_dump()
        except Exception as e:
            raise HTTPException(400, str(e))


    @app.put("/secrets", dependencies=D)
    def put_secret(s: Secret):
        if s.name not in SECRET_KEYS:
            raise HTTPException(400, "unknown secret")
        return {"stored_in": cfg.set_secret(s.name, s.value.strip())}

    @app.get("/consent-notice")
    def consent(lang: str = "en"):
        return {"text": CONSENT_NOTICE.get(lang, CONSENT_NOTICE["en"])}

    # ------------------------------------------------------------ capture
    @app.get("/devices", dependencies=D)
    def devices():
        try:
            return capture.list_devices()
        except RuntimeError as e:
            return {"microphones": [], "system": [], "error": str(e)}


    @app.post("/recordings/start", dependencies=D)
    def rec_start(body: StartRec):
        if app.state.recorder and app.state.recorder.state in ("recording", "paused"):
            raise HTTPException(409, "already recording")
        m = db.create_meeting(body.title or "Meeting", body.platform, status="recording", source="recording",
                              participants_hint=body.participants_hint, agenda=body.agenda)
        rec = capture.Recorder(engine.meeting_dir(m["id"]), body.mic_id or cfg.settings.mic_device,
                               body.system_id or cfg.settings.system_device, body.use_mic, body.use_system)
        try:
            rec.start()
        except Exception as e:
            engine.delete(m["id"])
            raise HTTPException(500, f"Could not start capture: {e}")
        app.state.recorder, app.state.recording_meeting = rec, m["id"]
        return {"meeting": m, "status": rec.status()}

    def _rec():
        if not app.state.recorder:
            raise HTTPException(409, "not recording")
        return app.state.recorder

    @app.post("/recordings/pause", dependencies=D)
    def rec_pause():
        r = _rec(); r.pause(); return r.status()

    @app.post("/recordings/resume", dependencies=D)
    def rec_resume():
        r = _rec(); r.resume(); return r.status()

    @app.get("/recordings/status", dependencies=D)
    def rec_status():
        r = app.state.recorder
        return {"meeting_id": app.state.recording_meeting, **(r.status() if r else {"state": "idle"})}

    @app.post("/recordings/stop", dependencies=D)
    def rec_stop(auto_process: bool = True, template: Optional[str] = None):
        r = _rec()
        tracks = r.stop()
        mid = app.state.recording_meeting
        app.state.recorder = app.state.recording_meeting = None
        if not tracks:
            db.update_meeting(mid, status="error", error="No audio captured: " + str(r.status().get("errors")))
            raise HTTPException(500, "No audio was captured — check devices")
        m = engine.register_recording(mid, tracks)
        job = engine.jobs.submit("process", mid, lambda p: engine.process_all(mid, template, p)) if auto_process else None
        return {"meeting": m, "job": job}

    @app.websocket("/recordings/live")
    async def rec_live(ws: WebSocket):
        if token and ws.query_params.get("token") != token:
            await ws.close(code=4401)
            return
        await ws.accept()
        try:
            while True:
                r = app.state.recorder
                await ws.send_json({"meeting_id": app.state.recording_meeting,
                                    **(r.status() if r else {"state": "idle"})})
                await asyncio.sleep(0.15)
        except Exception:
            pass

    # ------------------------------------------------------------ meetings
    @app.get("/meetings", dependencies=D)
    def meetings():
        return db.list_meetings()

    @app.post("/meetings/import", dependencies=D)
    async def import_meeting(file: UploadFile = File(...), title: str = Form(""), platform: str = Form("Other"),
                             participants_hint: str = Form(""), agenda: str = Form(""),
                             auto_process: bool = Form(True), template: str = Form("")):
        suffix = Path(file.filename or "audio.wav").suffix.lower()
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / f"{Path(file.filename or 'audio').stem}{suffix}"
            with open(p, "wb") as f:
                while chunk := await file.read(1 << 20):
                    f.write(chunk)
            try:
                m = engine.import_file(p, title, platform, participants_hint=participants_hint, agenda=agenda)
            except (ValueError, RuntimeError) as e:
                raise HTTPException(400, str(e))
        job = engine.jobs.submit("process", m["id"], lambda pr: engine.process_all(m["id"], template or None, pr)) \
            if auto_process else None
        return {"meeting": m, "job": job}

    @app.post("/meetings/import-text", dependencies=D)
    def import_text(body: TextImport):
        try:
            m = engine.import_text(body.text, body.title, body.platform,
                                   participants_hint=body.participants_hint, agenda=body.agenda)
        except ValueError as e:
            raise HTTPException(400, str(e))
        job = engine.jobs.submit("process", m["id"], lambda pr: engine.process_all(m["id"], body.template or None, pr)) \
            if body.auto_process else None
        return {"meeting": m, "job": job}

    @app.get("/meetings/{mid}", dependencies=D)
    def get_meeting(mid: str):
        m = meeting_or_404(mid)
        mins = db.get_minutes(mid)
        return {"meeting": m, "participants": db.participants(mid), "segments": db.segments(mid),
                "minutes": mins, "summaries": db.summaries(mid),
                "jobs": [j for j in engine.jobs.for_meeting(mid) if j["status"] in ("queued", "running")]}

    @app.patch("/meetings/{mid}", dependencies=D)
    def patch_meeting(mid: str, values: dict):
        meeting_or_404(mid)
        m = db.update_meeting(mid, **{k: v for k, v in values.items()
                                      if k in ("title", "platform", "participants_hint", "agenda", "started_at")})
        db.reindex(mid)
        return m

    @app.delete("/meetings/{mid}", dependencies=D)
    def delete_meeting(mid: str):
        meeting_or_404(mid)
        if any(j["status"] in ("queued", "running") for j in engine.jobs.for_meeting(mid)):
            # deleting removes the audio files the running job is reading
            raise HTTPException(409, "This meeting is still being processed — wait for it to finish, then delete it")
        engine.delete(mid)
        return {"deleted": mid}

    @app.post("/meetings/{mid}/transcribe", dependencies=D)
    def transcribe(mid: str):
        if meeting_or_404(mid).get("source") in TEXT_SOURCES and not engine.voice_notes(mid):
            raise HTTPException(400, "This meeting was imported from a transcript — there is no audio to transcribe")
        return engine.jobs.submit("transcribe", mid, lambda p: engine.transcribe(mid, p))


    @app.patch("/meetings/{mid}/participants/{pid}", dependencies=D)
    def rename(mid: str, pid: str, body: Rename):
        meeting_or_404(mid)
        db.rename_participant(pid, body.display_name.strip())
        db.reindex(mid)
        return db.participants(mid)


    @app.patch("/meetings/{mid}/segments/{sid}", dependencies=D)
    def edit_segment(mid: str, sid: str, body: SegEdit):
        meeting_or_404(mid)
        db.update_segment(sid, body.text, body.participant_id)
        return {"ok": True}


    @app.post("/meetings/{mid}/minutes", dependencies=D)
    def gen_minutes(mid: str, body: GenBody = GenBody()):
        meeting_or_404(mid)
        if not db.segments(mid):
            raise HTTPException(400, "Transcribe the meeting first")
        return engine.jobs.submit("minutes", mid,
                                  lambda p: engine.generate_minutes(mid, body.template, body.output_language, p))

    @app.post("/meetings/{mid}/summaries", dependencies=D)
    def gen_summaries(mid: str, body: GenBody = GenBody()):
        return gen_minutes(mid, body)  # minutes + summaries are produced in one pass

    @app.post("/meetings/{mid}/minutes/regenerate/{section}", dependencies=D)
    def regen(mid: str, section: str):
        meeting_or_404(mid)
        if section not in SECTIONS:
            raise HTTPException(400, f"section must be one of {SECTIONS}")
        return engine.jobs.submit("regenerate", mid, lambda p: engine.regenerate_section(mid, section))

    @app.put("/meetings/{mid}/minutes", dependencies=D)
    def save_minutes(mid: str, content: dict):
        meeting_or_404(mid)
        return engine.save_minutes_edit(mid, content)

    @app.get("/meetings/{mid}/export", dependencies=D)
    def export_meeting(mid: str, format: str = Query("docx", pattern="^(docx|pdf|md|txt|srt)$"),
                       transcript: bool = True, summary: bool = True, timestamps: bool = True):
        m = meeting_or_404(mid)
        mins = db.get_minutes(mid)
        segs, sums = db.segments(mid), db.summaries(mid)
        content = mins["content"] if mins else None
        base = cfg.export_dir / f"{exp.safe_filename(m['title'])}_{(m['started_at'] or '')[:10]}"
        if format in ("docx", "pdf"):
            path = exp.to_docx(base.with_suffix(".docx"), m, content, sums, segs, include_transcript=transcript,
                               include_summary=summary, include_timestamps=timestamps,
                               company=cfg.settings.company_name, logo=cfg.settings.logo_path)
            if format == "pdf":
                try:
                    path = exp.docx_to_pdf(path)
                except RuntimeError as e:
                    raise HTTPException(400, str(e))
            media = ("application/pdf" if format == "pdf" else
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            return FileResponse(path, media_type=media, filename=path.name)
        text = {"md": lambda: exp.to_markdown(m, content, sums, segs, transcript, summary),
                "txt": lambda: exp.to_txt(segs), "srt": lambda: exp.to_srt(segs)}[format]()
        path = base.with_suffix(f".{format}")
        path.write_text(text, "utf-8")
        return FileResponse(path, media_type="text/plain; charset=utf-8", filename=path.name)

    @app.get("/meetings/{mid}/audio", dependencies=D)
    def get_audio(mid: str):
        m = meeting_or_404(mid)
        p = Path(m["audio_path"] or "").parent / "mixed.wav"
        if not p.exists():
            raise HTTPException(404, "audio not available")
        return FileResponse(p, media_type="audio/wav")

    @app.get("/meetings/{mid}/segments/{sid}/media", dependencies=D)
    def get_segment_media(mid: str, sid: str):
        meeting_or_404(mid)
        seg = next((s for s in db.segments(mid) if s["id"] == sid and s.get("media")), None)
        base = (cfg.audio_dir / mid).resolve()
        p = (base / seg["media"]).resolve() if seg else None
        if not p or base not in p.parents or not p.exists():
            raise HTTPException(404, "media not available")
        return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream")

    # ---------------------------------------------------------------- jobs
    @app.get("/jobs/{jid}", dependencies=D)
    def job(jid: str):
        j = engine.jobs.get(jid)
        if not j:
            raise HTTPException(404, "job not found")
        return j

    @app.get("/search", dependencies=D)
    def search(q: str):
        return db.search(q)

    @app.exception_handler(Exception)
    async def errors(request: Request, exc: Exception):  # pragma: no cover
        return PlainTextResponse(str(exc), status_code=500)

    return app


def generate_token() -> str:
    return secrets.token_urlsafe(24)
