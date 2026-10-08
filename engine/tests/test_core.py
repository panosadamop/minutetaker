import json
import time

import numpy as np
from docx import Document
from fastapi.testclient import TestClient

from minutetaker import audio, diarize, minutes as mom
from minutetaker.api import create_app
from minutetaker.db import Database
from minutetaker.export import to_srt
from minutetaker.llm import extract_json
from minutetaker.pipeline import Engine

from conftest import SEGMENTS_EN, bursts


# ------------------------------------------------------------------ audio --
def test_vad_and_mix(tmp_path):
    a = bursts([(1, 2), (4, 5)], 6)
    regions = audio.speech_regions(a)
    assert len(regions) == 2 and abs(regions[0][0] - 1) < 0.1
    p1, p2 = tmp_path / "a.wav", tmp_path / "b.wav"
    audio.save_wav(p1, a)
    audio.save_wav(p2, bursts([(2.5, 3.5)], 8))
    dur = audio.mix([p1, p2], tmp_path / "m.wav")
    assert abs(dur - 8) < 0.01


# ---------------------------------------------------------------- diarize --
def test_echo_removed_and_tracks(cfg):
    mic = [{"start": 0, "end": 2, "text": "Hello, can you hear me?"},
           {"start": 3, "end": 5, "text": "the budget is approved"}]          # echo of the speaker
    system = [{"start": 3.1, "end": 5, "text": "The budget is approved."}]
    parts, segs = diarize.build_transcript(cfg, mic=mic, system=system)
    assert [s["label"] for s in segs] == ["Me", "Participants"]
    assert parts[0]["is_self"]


def test_assign_speakers():
    segs = [{"start": 0, "end": 2, "text": "a"}, {"start": 5, "end": 7, "text": "b"}]
    out = diarize.assign_speakers(segs, [(0, 3, "Speaker 1"), (4.5, 8, "Speaker 2")], "X")
    assert [s["label"] for s in out] == ["Speaker 1", "Speaker 2"]


# --------------------------------------------------------------------- db --
def test_db_search_greek(tmp_path):
    db = Database(tmp_path / "t.db")
    m = db.create_meeting("Σύσκεψη έργου", "Teams")
    db.replace_transcript(m["id"], [{"label": "Speaker 1", "display_name": "Speaker 1"}],
                          [{"label": "Speaker 1", "start": 0, "end": 1, "text": "Αποφασίσαμε τη μετάπτωση"}])
    assert db.search("μεταπτωση")            # diacritics-insensitive
    assert db.search("Σύσκεψη")
    pid = db.participants(m["id"])[0]["id"]
    db.rename_participant(pid, "Μαρία")
    assert db.segments(m["id"])[0]["speaker"] == "Μαρία"


# -------------------------------------------------------------------- llm --
def test_extract_json_fenced():
    assert extract_json('Sure:\n```json\n{"a": 1}\n```') == {"a": 1}


def test_map_reduce_long_transcript(cfg):
    segs = [{"start_s": i * 5, "speaker": "A", "text": ("We decided item %d. " % i) * 40} for i in range(120)]
    res = mom.generate(cfg, {"title": "Long", "language": "en"}, segs)
    assert len(res["decisions"]) > 50          # all chunks merged


# ---------------------------------------------------------------- pipeline --
def test_full_pipeline_and_docx(cfg, sample_wav, tmp_path):
    from minutetaker.export import to_docx, to_markdown
    eng = Engine(cfg)
    m = eng.import_file(sample_wav, "Weekly sync", "Zoom", participants_hint="Panos, Maria")
    assert m["duration_s"] > 15
    eng.process_all(m["id"])
    mt = eng.db.get_meeting(m["id"])
    assert mt["status"] == "ready" and mt["language"] == "en"
    mins = eng.db.get_minutes(m["id"])["content"]
    assert any("go live" in d for d in mins["decisions"])
    assert any(a["due"] for a in mins["action_items"])
    assert eng.db.action_items(m["id"])
    assert any("risk" in i for i in mins["open_issues"])

    out = to_docx(tmp_path / "out.docx", mt, mins, eng.db.summaries(m["id"]), eng.db.segments(m["id"]),
                  company="Netcompany")
    doc = Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    for h in ("Minutes of Meeting".upper(), "Decisions", "Action Items", "Appendix — Full Transcript"):
        assert h in text
    assert len(doc.tables) >= 3
    md = to_markdown(mt, mins, {}, eng.db.segments(m["id"]))
    assert "| A1 |" in md
    assert "-->" in to_srt(eng.db.segments(m["id"]))


def test_greek_labels(cfg, tmp_path):
    from minutetaker.export import to_docx
    meeting = {"title": "Σύσκεψη", "platform": "Viber", "started_at": "2026-10-05T10:00:00+00:00",
               "duration_s": 1800, "language": "el"}
    mins = mom.normalise({"decisions": ["Έγκριση"], "action_items": [{"task": "Αποστολή", "owner": "Νίκος"}]},
                         meeting, "el")
    doc = Document(str(to_docx(tmp_path / "el.docx", meeting, mins, {}, [])))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Αποφάσεις" in text and "Ενέργειες" in text


# --------------------------------------------------------------------- api --
def _wait(client, jid, headers):
    for _ in range(200):
        j = client.get(f"/jobs/{jid}", headers=headers).json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timeout")


def test_api_flow(cfg, sample_wav):
    app = create_app(cfg, token="secret")
    c = TestClient(app)
    H = {"X-MT-Token": "secret"}
    assert c.get("/meetings").status_code == 401
    with open(sample_wav, "rb") as f:
        # sidecar travels via filename lookup, so post the file from its folder
        r = c.post("/meetings/import", headers=H, files={"file": ("standup.wav", f, "audio/wav")},
                   data={"title": "API sync", "platform": "Teams"})
    assert r.status_code == 200, r.text
    mid = r.json()["meeting"]["id"]
    # mock STT without sidecar produces placeholder segments from VAD
    assert _wait(c, r.json()["job"]["id"], H)["status"] == "done"
    data = c.get(f"/meetings/{mid}", headers=H).json()
    assert data["segments"] and data["minutes"]
    pid = data["participants"][0]["id"]
    assert c.patch(f"/meetings/{mid}/participants/{pid}", headers=H, json={"display_name": "Eleni"}).is_success
    sid = data["segments"][0]["id"]
    assert c.patch(f"/meetings/{mid}/segments/{sid}", headers=H, json={"text": "We decided to ship."}).is_success
    j = c.post(f"/meetings/{mid}/minutes", headers=H, json={"template": "standup"}).json()
    assert _wait(c, j["id"], H)["status"] == "done"
    mins = c.get(f"/meetings/{mid}", headers=H).json()["minutes"]["content"]
    mins["decisions"].append("Manual decision")
    assert "Manual decision" in c.put(f"/meetings/{mid}/minutes", headers=H, json=mins).json()["decisions"]
    j = c.post(f"/meetings/{mid}/minutes/regenerate/tldr", headers=H).json()
    assert _wait(c, j["id"], H)["status"] == "done"
    r = c.get(f"/meetings/{mid}/export?format=docx", headers=H)
    assert r.status_code == 200 and r.content[:2] == b"PK"
    assert c.get(f"/meetings/{mid}/export?format=md&token=secret").status_code == 200
    assert c.get("/search?q=ship", headers=H).json()
    assert c.delete(f"/meetings/{mid}", headers=H).is_success
    assert c.get(f"/meetings/{mid}", headers=H).status_code == 404


# -------------------------------------------------------------------- stt --
def test_whisper_auto_model_by_device(cfg, monkeypatch):
    from minutetaker import stt
    assert cfg.settings.whisper_model == "auto"
    w = stt.LocalWhisper(cfg)
    assert callable(getattr(w, "transcribe", None))       # real provider API intact (tests use mock STT)
    monkeypatch.setattr(stt, "_cuda_devices", lambda: 0)
    assert w.resolve() == ("base", "cpu")
    monkeypatch.setattr(stt, "_cuda_devices", lambda: 1)
    assert w.resolve() == ("small", "cuda")
    cfg.update(whisper_device="cpu")
    assert w.resolve() == ("base", "cpu")                  # forced CPU even with a GPU present
    cfg.update(whisper_model="medium")
    assert w.resolve() == ("medium", "cpu")                # explicit choice wins


def test_headset_mic_paired_with_output():
    from minutetaker.capture import paired_mic
    mics = ["Microphone Array (AMD Audio Device)", "Headset Microphone (Jabra Link 370)"]   # real names, dev laptop
    assert paired_mic("Headset Earphone (Jabra Link 370)", mics) == "Headset Microphone (Jabra Link 370)"
    assert paired_mic("Speakers (Realtek(R) Audio)", mics) is None          # no matching mic → OS default
    assert paired_mic(None, mics) is None


def test_silent_segments_dropped():
    from minutetaker.stt import drop_silent
    sr = audio.SR
    rng = np.random.default_rng(1)
    db = lambda d: 10 ** (d / 20)                                            # noqa: E731
    x = (rng.standard_normal(12 * sr) * db(-60)).astype(np.float32)         # room noise, as measured live
    t = np.arange(2 * sr) / sr
    x[3 * sr:5 * sr] += (np.sin(2 * np.pi * 200 * t) * np.sqrt(2) * db(-25)).astype(np.float32)  # normal speech
    quiet = (np.sin(2 * np.pi * 200 * t) * np.sqrt(2) * db(-42)).astype(np.float32)
    quiet[int(0.3 * sr):int(1.7 * sr)] = 0                                   # soft talker, mostly pause
    x[8 * sr:10 * sr] += quiet
    segs = [{"start": 0.5, "end": 2.5, "text": "For the first part."},       # hallucination on noise
            {"start": 3.0, "end": 5.0, "text": "We decided to ship."},
            {"start": 8.0, "end": 10.0, "text": "Okay."}]
    assert [s["text"] for s in drop_silent(segs, x)] == ["We decided to ship.", "Okay."]


def test_delete_blocked_while_processing(cfg):
    import threading
    app = create_app(cfg, token="")
    c = TestClient(app)
    engine = app.state.engine
    mid = engine.db.create_meeting("Busy")["id"]
    gate = threading.Event()
    job = engine.jobs.submit("process", mid, lambda p: gate.wait(5))   # stands in for a long transcription
    r = c.delete(f"/meetings/{mid}")
    assert r.status_code == 409 and "still being processed" in r.json()["detail"]
    gate.set()
    for _ in range(100):
        if engine.jobs.get(job["id"])["status"] == "done":
            break
        time.sleep(0.02)
    assert c.delete(f"/meetings/{mid}").status_code == 200
