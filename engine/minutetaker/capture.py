"""Live capture of microphone + system audio (loopback).

Uses the `soundcard` library:
  * Windows  – WASAPI loopback of any output device (Teams, Zoom, Viber, WhatsApp, browser…)
  * Linux    – PulseAudio / PipeWire "monitor" sources
  * macOS    – no native loopback; select a virtual device such as BlackHole as system source

Each stream is written straight to its own WAV file and flushed every few seconds,
so a crash never loses more than a few seconds (FR-07).
"""
from __future__ import annotations

import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

CAPTURE_SR = 48000
BLOCK = 4800          # 100 ms
FLUSH_EVERY = 3.0     # seconds


def _sc():
    try:
        import soundcard  # type: ignore
        return soundcard
    except Exception as e:  # pragma: no cover - depends on host
        raise RuntimeError(
            "Audio capture needs the 'soundcard' package (pip install soundcard) "
            f"and a working audio system: {e}")


def _com_init():  # pragma: no cover - Windows only
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0)


def _hardware(name: str) -> Optional[str]:
    """Hardware part of a Windows endpoint name: 'Headset Earphone (Jabra Link 370)' → 'jabra link 370'."""
    m = re.search(r"\((.*)\)\s*$", name or "")
    return m.group(1).strip().casefold() if m else None


def paired_mic(output_name: Optional[str], mic_names: list[str]) -> Optional[str]:
    """The microphone on the same hardware as the output being recorded (a headset's own mic), if any.

    In a call you talk into the headset mic; the laptop's built-in array (often the OS default)
    hears you faintly plus the room."""
    hw = _hardware(output_name or "")
    if not hw:
        return None
    return next((n for n in mic_names if _hardware(n) == hw), None)


def list_devices() -> dict:
    sc = _sc()
    mics, loops = [], []
    try:
        default_spk = sc.default_speaker().name
    except Exception:
        default_spk = None
    try:
        names = [m.name for m in sc.all_microphones()]
        default_mic = paired_mic(default_spk, names) or sc.default_microphone().name
    except Exception:
        default_mic = None
    for m in sc.all_microphones(include_loopback=True):
        entry = {"id": str(m.id), "name": m.name}
        if getattr(m, "isloopback", False):
            entry["default"] = m.name == default_spk
            loops.append(entry)
        else:
            entry["default"] = m.name == default_mic
            mics.append(entry)
    return {"microphones": mics, "system": loops, "platform": sys.platform,
            "note": "On macOS install a loopback device (e.g. BlackHole) and pick it as System audio."
            if sys.platform == "darwin" else ""}


@dataclass
class _Stream:
    kind: str
    device: object
    path: Path
    level: float = 0.0
    frames: int = 0
    error: Optional[str] = None
    thread: Optional[threading.Thread] = None


@dataclass
class Recorder:
    out_dir: Path
    mic_id: Optional[str] = None
    system_id: Optional[str] = None
    use_mic: bool = True
    use_system: bool = True
    streams: list[_Stream] = field(default_factory=list)
    state: str = "idle"
    _stop: threading.Event = field(default_factory=threading.Event)
    _paused: threading.Event = field(default_factory=threading.Event)
    _t0: float = 0.0
    _paused_total: float = 0.0
    _pause_started: float = 0.0

    def _resolve(self):
        sc = _sc()
        devs = []
        if self.system_id:
            loop = sc.get_microphone(self.system_id, include_loopback=True)
        else:
            loop = sc.get_microphone(str(sc.default_speaker().name), include_loopback=True)
        if self.use_mic:
            if self.mic_id:
                mic = sc.get_microphone(self.mic_id)
            else:  # no explicit choice: the mic of the headset we record from, else the OS default
                name = paired_mic(loop.name, [m.name for m in sc.all_microphones()])
                mic = sc.get_microphone(name) if name else sc.default_microphone()
            devs.append(("mic", mic))
        if self.use_system:
            devs.append(("system", loop))
        return devs

    def start(self) -> None:
        if self.state != "idle":
            raise RuntimeError("recorder already started")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for kind, dev in self._resolve():
            s = _Stream(kind, dev, self.out_dir / f"{kind}.wav")
            s.thread = threading.Thread(target=self._run, args=(s,), daemon=True)
            self.streams.append(s)
        self._t0 = time.time()
        self.state = "recording"
        for s in self.streams:
            s.thread.start()

    def _run(self, s: _Stream) -> None:
        _com_init()
        try:
            with sf.SoundFile(str(s.path), "w", CAPTURE_SR, 1, "PCM_16") as f, \
                    s.device.recorder(samplerate=CAPTURE_SR, blocksize=BLOCK) as rec:
                last_flush = time.time()
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    mono = data.mean(axis=1) if data.ndim == 2 else data
                    s.level = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
                    if self._paused.is_set():
                        continue
                    f.write(np.clip(mono, -1, 1))
                    s.frames += len(mono)
                    if time.time() - last_flush > FLUSH_EVERY:
                        f.flush()
                        last_flush = time.time()
        except Exception as e:  # pragma: no cover - device specific
            s.error = str(e)

    def pause(self) -> None:
        if self.state == "recording":
            self._paused.set()
            self._pause_started = time.time()
            self.state = "paused"

    def resume(self) -> None:
        if self.state == "paused":
            self._paused_total += time.time() - self._pause_started
            self._paused.clear()
            self.state = "recording"

    def stop(self) -> dict[str, str]:
        self.resume()
        self._stop.set()
        for s in self.streams:
            if s.thread:
                s.thread.join(timeout=5)
        self.state = "stopped"
        return {s.kind: str(s.path) for s in self.streams if s.frames > 0}

    def status(self) -> dict:
        elapsed = 0.0
        if self._t0:
            ref = self._pause_started if self.state == "paused" else time.time()
            elapsed = ref - self._t0 - self._paused_total
        return {"state": self.state, "elapsed": round(elapsed, 1),
                "levels": {s.kind: round(s.level, 4) for s in self.streams},
                "errors": {s.kind: s.error for s in self.streams if s.error}}
