"""Command line: serve the API, process files headless, list devices, record."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .config import Config


def _engine(args):
    from .pipeline import Engine
    cfg = Config(Path(args.data) if args.data else None)
    if getattr(args, "stt", None):
        cfg.settings.stt_provider = args.stt
    if getattr(args, "llm", None):
        cfg.settings.llm_provider = args.llm
    return cfg, Engine(cfg)


def _progress(p: float, msg: str) -> None:
    sys.stderr.write(f"\r[{int(p * 100):3d}%] {msg[:70]:<70}")
    sys.stderr.flush()


def _export(engine, cfg, mid, out: Path, fmt: str, transcript: bool):
    from . import export as exp
    m, db = engine.db.get_meeting(mid), engine.db
    mins = db.get_minutes(mid)
    content = mins["content"] if mins else None
    if fmt in ("docx", "pdf"):
        path = exp.to_docx(out.with_suffix(".docx"), m, content, db.summaries(mid), db.segments(mid),
                           include_transcript=transcript, company=cfg.settings.company_name,
                           logo=cfg.settings.logo_path)
        if fmt == "pdf":
            path = exp.docx_to_pdf(path)
        return path
    text = {"md": lambda: exp.to_markdown(m, content, db.summaries(mid), db.segments(mid), transcript),
            "txt": lambda: exp.to_txt(db.segments(mid)), "srt": lambda: exp.to_srt(db.segments(mid))}[fmt]()
    out.with_suffix(f".{fmt}").write_text(text, "utf-8")
    return out.with_suffix(f".{fmt}")


def cmd_serve(args):
    import uvicorn
    from .api import create_app
    cfg = Config(Path(args.data) if args.data else None)
    app = create_app(cfg)
    print(json.dumps({"event": "ready", "port": args.port}), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


def cmd_process(args):
    cfg, engine = _engine(args)
    if args.file == "-":  # transcript / chat text on stdin
        stem = "pasted"
        m = engine.import_text(sys.stdin.read(), args.title or "", args.platform,
                               participants_hint=args.participants or "")
    else:
        src = Path(args.file)
        stem = src.stem
        m = engine.import_file(src, args.title or src.stem, args.platform, participants_hint=args.participants or "")
    engine.process_all(m["id"], args.template, _progress)
    sys.stderr.write("\n")
    out = Path(args.out) if args.out else Path.cwd() / f"{stem}_minutes"
    path = _export(engine, cfg, m["id"], out, args.format, not args.no_transcript)
    print(path)


def cmd_devices(args):
    from .capture import list_devices
    print(json.dumps(list_devices(), indent=2, ensure_ascii=False))


def cmd_record(args):
    from .capture import Recorder
    cfg, engine = _engine(args)
    m = engine.db.create_meeting(args.title or "Recording", args.platform, status="recording", source="recording")
    rec = Recorder(engine.meeting_dir(m["id"]), args.mic, args.system, not args.no_mic, not args.no_system)
    rec.start()
    print("Recording… press Ctrl+C to stop. Make sure all participants consented.", file=sys.stderr)
    try:
        while True:
            st = rec.status()
            lv = " ".join(f"{k}:{'█' * int(min(v * 60, 20)):<20}" for k, v in st["levels"].items())
            sys.stderr.write(f"\r{st['elapsed']:7.1f}s {lv}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    tracks = rec.stop()
    engine.register_recording(m["id"], tracks)
    print(f"\nSaved meeting {m['id']}", file=sys.stderr)
    if not args.no_process:
        engine.process_all(m["id"], None, _progress)
        print(_export(engine, cfg, m["id"], Path(args.out or f"{m['id']}_minutes"), "docx", True))


def main(argv=None):
    p = argparse.ArgumentParser(prog="minutetaker", description="Meeting minutes from any call")
    p.add_argument("--data", help="data folder (default: per-user app data)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the local API for the desktop app")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("process", help="audio/video, transcript or chat export → minutes document")
    s.add_argument("file", help="recording, transcript (vtt/srt/txt/docx/pdf), WhatsApp export (txt/zip) or - for stdin")
    s.add_argument("--title")
    s.add_argument("--platform", default="Other")
    s.add_argument("--participants", help="comma-separated names (first = you)")
    s.add_argument("--template", default=None, choices=["formal", "standup", "client", "interview"])
    s.add_argument("--format", default="docx", choices=["docx", "pdf", "md", "txt", "srt"])
    s.add_argument("--out")
    s.add_argument("--no-transcript", action="store_true")
    s.add_argument("--stt", choices=["local", "openai", "mock"])
    s.add_argument("--llm", choices=["claude", "openai", "ollama", "mock"])
    s.set_defaults(fn=cmd_process)

    s = sub.add_parser("devices", help="list capture devices")
    s.set_defaults(fn=cmd_devices)

    s = sub.add_parser("record", help="record mic + system audio from the terminal")
    s.add_argument("--title"); s.add_argument("--platform", default="Other")
    s.add_argument("--mic"); s.add_argument("--system")
    s.add_argument("--no-mic", action="store_true"); s.add_argument("--no-system", action="store_true")
    s.add_argument("--no-process", action="store_true"); s.add_argument("--out")
    s.add_argument("--stt", choices=["local", "openai", "mock"]); s.add_argument("--llm", choices=["claude", "openai", "ollama", "mock"])
    s.set_defaults(fn=cmd_record)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
