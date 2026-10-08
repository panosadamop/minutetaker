import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from minutetaker.audio import SR, save_wav  # noqa: E402
from minutetaker.config import Config  # noqa: E402

SEGMENTS_EN = [
    {"start": 0.5, "end": 3.0, "text": "Good morning everyone, let's review the migration status."},
    {"start": 3.5, "end": 6.0, "text": "The database cutover is ready, but there is a risk with the reports module."},
    {"start": 6.5, "end": 9.0, "text": "We decided to go live on the 20th of October."},
    {"start": 9.5, "end": 12.0, "text": "Maria will prepare the rollback plan by Friday."},
    {"start": 12.5, "end": 15.0, "text": "I'll send the updated schedule to the client tomorrow."},
]


def bursts(regions, total):
    x = np.zeros(int(total * SR), np.float32)
    rng = np.random.default_rng(0)
    for a, b in regions:
        n = int((b - a) * SR)
        t = np.arange(n) / SR
        x[int(a * SR): int(a * SR) + n] = 0.3 * np.sin(2 * np.pi * 220 * t) * (0.6 + 0.4 * rng.random(n))
    return x


@pytest.fixture
def cfg(tmp_path):
    c = Config(tmp_path / "data")
    c.update(stt_provider="mock", llm_provider="mock", diarization="tracks")
    return c


@pytest.fixture
def sample_wav(tmp_path):
    p = tmp_path / "standup.wav"
    save_wav(p, bursts([(s["start"], s["end"]) for s in SEGMENTS_EN], 16))
    Path(str(p) + ".transcript.json").write_text(json.dumps({"language": "en", "segments": SEGMENTS_EN}))
    return p
