"""Audio helpers: decoding/normalising (ffmpeg → libsndfile → PyAV), mixing, simple VAD."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 16000
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".oga", ".opus", ".flac", ".wma", ".aiff", ".aif",
             ".amr", ".caf", ".mka", ".weba", ".ac3", ".spx"}
VIDEO_EXT = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".asf", ".flv", ".f4v", ".3gp", ".3g2",
             ".ts", ".mts", ".m2ts", ".mpg", ".mpeg", ".vob", ".ogv", ".mxf"}
SUPPORTED_IMPORT = AUDIO_EXT | VIDEO_EXT


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def load_audio(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode any audio/video file to mono float32 at `sr`.

    Uses ffmpeg when on PATH; otherwise libsndfile (wav/flac/ogg/mp3) and then PyAV, whose
    wheels bundle FFmpeg — so mp4/mkv/mov/avi/wmv/... work without a separate install."""
    path = str(path)
    ff = ffmpeg_path()
    if ff:
        cmd = [ff, "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace").strip().splitlines()
            if any("does not contain any stream" in e or "matches no streams" in e for e in err):
                raise ValueError(f"{Path(path).name} has no audio track")
            raise ValueError(f"Could not decode {Path(path).name}: {err[-1] if err else 'ffmpeg failed'}")
        if not r.stdout:
            raise ValueError(f"{Path(path).name} has no audio track")
        return np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768.0
    try:
        data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    except Exception:
        return _load_av(path, sr)
    return resample(data.mean(axis=1), file_sr, sr)


def _load_av(path: str, sr: int) -> np.ndarray:
    try:
        import av  # type: ignore
    except ImportError as e:
        raise RuntimeError("Decoding this file needs ffmpeg or PyAV: pip install av") from e
    name = Path(path).name
    chunks: list[np.ndarray] = []
    try:
        with av.open(path) as c:
            if not c.streams.audio:
                raise ValueError(f"{name} has no audio track")
            rs = av.AudioResampler(format="s16", layout="mono", rate=sr)
            for frame in c.decode(c.streams.audio[0]):
                chunks += [f.to_ndarray().reshape(-1) for f in rs.resample(frame)]
            chunks += [f.to_ndarray().reshape(-1) for f in rs.resample(None)]
    except av.FFmpegError as e:
        raise ValueError(f"Could not decode {name}: {e}") from e
    if not chunks:
        raise ValueError(f"{name} has no audio track")
    return np.concatenate(chunks).astype(np.float32) / 32768.0


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(x) == 0:
        return x.astype(np.float32)
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def save_wav(path: str | Path, x: np.ndarray, sr: int = SR) -> None:
    sf.write(str(path), np.clip(x, -1, 1), sr, subtype="PCM_16")


def duration(path: str | Path) -> float:
    try:
        info = sf.info(str(path))
        return info.frames / info.samplerate
    except Exception:
        pass
    try:
        import av  # type: ignore
        with av.open(str(path)) as c:
            if c.duration and c.streams.audio:
                return c.duration / 1_000_000
    except Exception:
        pass
    return len(load_audio(path)) / SR


def mix(paths: list[str | Path], out: str | Path) -> float:
    """Mix several tracks (any sr) into one 16 kHz mono WAV. Returns duration in s."""
    tracks = [load_audio(p) for p in paths if p and Path(p).exists()]
    if not tracks:
        raise ValueError("no tracks to mix")
    n = max(len(t) for t in tracks)
    mixed = np.zeros(n, np.float32)
    for t in tracks:
        mixed[: len(t)] += t
    peak = float(np.max(np.abs(mixed))) if n else 0
    if peak > 0.99:
        mixed /= peak / 0.99
    save_wav(out, mixed)
    return n / SR


def frame_energy(x: np.ndarray, start: float, end: float, sr: int = SR) -> float:
    a, b = int(start * sr), int(end * sr)
    seg = x[max(0, a): max(a + 1, b)]
    return float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0


def speech_regions(x: np.ndarray, sr: int = SR, win: float = 0.03, thresh_db: float = -40,
                   min_gap: float = 0.6, min_len: float = 0.3) -> list[tuple[float, float]]:
    """Very small energy-based VAD, used for track attribution and tests."""
    hop = int(win * sr)
    if len(x) < hop:
        return []
    frames = x[: len(x) // hop * hop].reshape(-1, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    active = db > thresh_db
    regions, start = [], None
    for i, a in enumerate(active):
        t = i * win
        if a and start is None:
            start = t
        elif not a and start is not None:
            regions.append([start, t])
            start = None
    if start is not None:
        regions.append([start, len(active) * win])
    merged: list[list[float]] = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(round(a, 2), round(b, 2)) for a, b in merged if b - a >= min_len]
