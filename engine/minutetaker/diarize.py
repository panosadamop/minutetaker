"""Speaker attribution.

Strategy
1. Separate tracks (live recording): the mic track is transcribed as "Me"; the
   system track holds every remote participant. Mic segments that are just echo of
   the speakers (no headphones) are dropped when they duplicate a system segment.
2. Remote speakers are split with pyannote.audio when installed + HF token set.
3. Otherwise remote speech is labelled "Participants" (single file → "Speaker 1")
   and the user can rename / reassign segments in the UI.
"""
from __future__ import annotations

import difflib
from typing import Optional

from .config import Config

SELF_LABEL = "Me"


def pyannote_available(cfg: Config) -> bool:
    if cfg.settings.diarization == "tracks":
        return False
    try:
        import pyannote.audio  # type: ignore  # noqa: F401
    except Exception:
        return False
    return bool(cfg.get_secret("hf_token"))


def run_pyannote(cfg: Config, path: str) -> list[tuple[float, float, str]]:
    from pyannote.audio import Pipeline  # type: ignore
    token = cfg.get_secret("hf_token")
    try:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", use_auth_token=token)
    except TypeError:
        pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=token)
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            pipe.to(torch.device("cuda"))
    except Exception:
        pass
    diar = pipe(path)
    annotation = getattr(diar, "speaker_diarization", diar)
    turns, names = [], {}
    for turn, _, spk in annotation.itertracks(yield_label=True):
        if spk not in names:
            names[spk] = f"Speaker {len(names) + 1}"
        turns.append((turn.start, turn.end, names[spk]))
    return turns


def assign_speakers(segments: list[dict], turns: list[tuple[float, float, str]], default: str) -> list[dict]:
    """Label each segment with the diarization turn it overlaps most."""
    out = []
    for s in segments:
        best, best_ov = s.get("speaker_hint") or default, 0.0
        for a, b, spk in turns:
            ov = min(s["end"], b) - max(s["start"], a)
            if ov > best_ov:
                best, best_ov = spk, ov
        out.append({**s, "label": best})
    return out


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def remove_echo(mic: list[dict], system: list[dict], threshold: float = 0.6) -> list[dict]:
    kept = []
    for m in mic:
        dup = False
        for s in system:
            if min(m["end"], s["end"]) - max(m["start"], s["start"]) > 0 and _similar(m["text"], s["text"]) >= threshold:
                dup = True
                break
        if not dup:
            kept.append(m)
    return kept


def build_transcript(cfg: Config, *, mic: Optional[list[dict]] = None, system: Optional[list[dict]] = None,
                     single: Optional[list[dict]] = None, system_path: Optional[str] = None,
                     single_path: Optional[str] = None) -> tuple[list[dict], list[dict]]:
    """Return (participants, segments) ready for Database.replace_transcript."""
    segs: list[dict] = []
    use_pyannote = pyannote_available(cfg)
    if single is not None:
        turns = run_pyannote(cfg, single_path) if use_pyannote and single_path else []
        segs = assign_speakers(single, turns, "Speaker 1")
    else:
        system = system or []
        mic = remove_echo(mic or [], system)
        turns = run_pyannote(cfg, system_path) if use_pyannote and system_path and system else []
        segs = [{**m, "label": SELF_LABEL} for m in mic]
        segs += assign_speakers(system, turns, "Participants")
    segs.sort(key=lambda s: s["start"])
    labels = []
    for s in segs:
        if s["label"] not in labels:
            labels.append(s["label"])
    participants = [{"label": l, "display_name": l, "is_self": l == SELF_LABEL} for l in labels]
    return participants, segs
