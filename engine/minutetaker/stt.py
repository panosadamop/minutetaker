"""Speech-to-text adapters: local faster-whisper, OpenAI cloud, deterministic mock."""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

import httpx

from .audio import SR, duration, ffmpeg_path, load_audio, save_wav, speech_regions
from .config import Config

Progress = Callable[[float, str], None]


def _noop(p: float, msg: str) -> None:  # pragma: no cover
    pass


class Transcript(dict):
    """{'language': str, 'segments': [{'start','end','text'}]}"""


SILENCE_DBFS = -48.0   # loudest 50 ms frame of a segment below this = no one spoke
_FRAME = int(0.05 * SR)


def drop_silent(segments: list[dict], pcm, threshold: float = SILENCE_DBFS) -> list[dict]:
    """Drop segments whose audio is only background noise.

    Whisper invents text on near-silent audio (seen live: a silent laptop mic at -57…-68 dBFS gave
    "For the first part." with no_speech_prob 0.43, which its own thresholds keep). Speech peaks well
    above -40 dBFS even when quiet, so judge each segment by its *loudest* frame, not its average
    (pauses inside real speech would drag an average down)."""
    import numpy as np
    kept = []
    for s in segments:
        a, b = int(s["start"] * SR), int(s["end"] * SR)
        x = pcm[max(0, a):max(a + _FRAME, b)]
        n = len(x) // _FRAME * _FRAME
        frames = x[:n].reshape(-1, _FRAME) if n else x.reshape(1, -1)
        peak = float(np.sqrt((frames.astype(np.float64) ** 2).mean(axis=1)).max()) if len(x) else 0.0
        if 20 * np.log10(peak + 1e-9) >= threshold:
            kept.append(s)
    return kept


def _cuda_devices() -> int:
    try:
        import ctranslate2  # type: ignore
        return ctranslate2.get_cuda_device_count()
    except Exception:
        return 0


class LocalWhisper:
    _cache: dict = {}

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _model(self):
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except ImportError as e:
            raise RuntimeError("Local transcription needs faster-whisper: pip install faster-whisper") from e
        key = self.resolve()
        if key not in self._cache:
            model, device = key
            compute = "float16" if device == "cuda" else "int8"
            self._cache[key] = WhisperModel(model, device=device, compute_type=compute,
                                            download_root=str(self.cfg.data_dir / "models"))
        return self._cache[key]

    def resolve(self) -> tuple[str, str]:
        """(model, device) after 'auto': `small` runs ~0.65× real time on a laptop CPU, so CPU gets
        `base` (about 2× faster, somewhat less accurate) and a CUDA GPU keeps `small`."""
        s = self.cfg.settings
        device = s.whisper_device
        if device == "auto":
            device = "cuda" if _cuda_devices() > 0 else "cpu"
        model = s.whisper_model if s.whisper_model != "auto" else ("small" if device == "cuda" else "base")
        return model, device

    def transcribe(self, path: str, language: Optional[str] = None, progress: Progress = _noop) -> Transcript:
        model = self._model()
        # decode with our own chain (ffmpeg → libsndfile → PyAV) and hand Whisper 16 kHz samples:
        # faster-whisper's built-in decoder breaks on newer PyAV (av.open(metadata_errors=...))
        pcm = load_audio(path)
        total = max(len(pcm) / SR, 0.1)
        segs, info = model.transcribe(pcm, language=language, vad_filter=True, beam_size=5,
                                      condition_on_previous_text=False)
        out = []
        for s in segs:
            out.append({"start": s.start, "end": s.end, "text": s.text.strip()})
            progress(min(s.end / total, 1.0), f"Transcribing {int(s.end)}/{int(total)} s")
        return Transcript(language=info.language, segments=drop_silent([s for s in out if s["text"]], pcm))


class OpenAIWhisper:
    CHUNK_S = 600  # 10 min chunks keep uploads well under the 25 MB API limit

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def transcribe(self, path: str, language: Optional[str] = None, progress: Progress = _noop) -> Transcript:
        key = self.cfg.get_secret("openai_api_key")
        if not key:
            raise RuntimeError("OpenAI API key not set (Settings → API keys)")
        ff = ffmpeg_path()
        # without ffmpeg: decode once (PyAV) and upload 16 kHz WAV chunks (10 min ≈ 19 MB < 25 MB)
        pcm = None if ff else load_audio(path)
        total = duration(path) if ff else len(pcm) / SR
        segments, lang = [], language
        with tempfile.TemporaryDirectory() as tmp:
            n = max(1, int(total // self.CHUNK_S) + (1 if total % self.CHUNK_S else 0))
            for i in range(n):
                off = i * self.CHUNK_S
                if ff:
                    chunk, mime = Path(tmp) / f"c{i}.ogg", "audio/ogg"
                    subprocess.run([ff, "-nostdin", "-v", "error", "-ss", str(off), "-t", str(self.CHUNK_S),
                                    "-i", path, "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "32k",
                                    str(chunk)], check=True)
                else:
                    chunk, mime = Path(tmp) / f"c{i}.wav", "audio/wav"
                    save_wav(chunk, pcm[off * SR:(off + self.CHUNK_S) * SR])
                data = {"model": self.cfg.settings.openai_stt_model, "response_format": "verbose_json"}
                if language:
                    data["language"] = language
                with open(chunk, "rb") as f:
                    r = httpx.post("https://api.openai.com/v1/audio/transcriptions",
                                   headers={"Authorization": f"Bearer {key}"}, data=data,
                                   files={"file": (chunk.name, f, mime)}, timeout=600)
                r.raise_for_status()
                body = r.json()
                lang = lang or body.get("language")
                for s in body.get("segments") or [{"start": 0, "end": min(self.CHUNK_S, total - off),
                                                   "text": body.get("text", "")}]:
                    if s["text"].strip():
                        segments.append({"start": s["start"] + off, "end": s["end"] + off,
                                         "text": s["text"].strip()})
                progress((i + 1) / n, f"Transcribed chunk {i + 1}/{n}")
        return Transcript(language=_norm_lang(lang), segments=drop_silent(segments, pcm if pcm is not None else load_audio(path)))


class MockSTT:
    """Deterministic provider for tests/demos.

    If `<audio>.transcript.json` exists next to the file it is returned as-is
    (format: {"language": "en", "segments": [{"start","end","text"}]}); otherwise one
    placeholder segment is produced per detected speech region.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def transcribe(self, path: str, language: Optional[str] = None, progress: Progress = _noop) -> Transcript:
        side = Path(str(path) + ".transcript.json")
        if side.exists():
            data = json.loads(side.read_text("utf-8"))
            progress(1.0, "Loaded sidecar transcript")
            return Transcript(language=data.get("language", language or "en"), segments=data["segments"])
        x = load_audio(path)
        regions = speech_regions(x)
        progress(1.0, "Mock transcription")
        return Transcript(language=language or "en",
                          segments=[{"start": a, "end": b, "text": f"[speech {a:.1f}-{b:.1f}s]"} for a, b in regions])


_LANG_NAMES = {"english": "en", "greek": "el"}


def _norm_lang(lang: Optional[str]) -> str:
    if not lang:
        return "en"
    return _LANG_NAMES.get(lang.lower(), lang.lower()[:2])


def get_stt(cfg: Config):
    return {"local": LocalWhisper, "openai": OpenAIWhisper, "mock": MockSTT}[cfg.settings.stt_provider](cfg)


__all__ = ["get_stt", "Transcript", "SR"]
