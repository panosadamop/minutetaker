"""Create a demo meeting (Greek) that runs fully offline with the mock providers.

    python samples/make_demo.py            -> samples/demo_el.wav (+ .transcript.json sidecar)
    python -m minutetaker process samples/demo_el.wav --stt mock --llm mock --platform "MS Teams"
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from minutetaker.audio import SR, save_wav  # noqa: E402

LINES = [
    ("Παναγιώτης", "Καλημέρα σε όλους. Σήμερα εξετάζουμε την πρόοδο της μετάπτωσης και το χρονοδιάγραμμα."),
    ("Μαρία", "Η μετάπτωση της βάσης δεδομένων ολοκληρώθηκε στο περιβάλλον δοκιμών χωρίς σφάλματα."),
    ("Νίκος", "Υπάρχει κίνδυνος με το υποσύστημα αναφορών, οι χρόνοι απόκρισης είναι αυξημένοι."),
    ("Παναγιώτης", "Αποφασίσαμε η παραγωγική λειτουργία να ξεκινήσει στις 20 Οκτωβρίου."),
    ("Μαρία", "Θα ετοιμάσω το σχέδιο επαναφοράς μέχρι την Παρασκευή."),
    ("Νίκος", "Θα κάνω δοκιμές φόρτου στις αναφορές έως την Τετάρτη."),
    ("Παναγιώτης", "Συμφωνήσαμε επίσης να ενημερώσουμε τον πελάτη με εβδομαδιαία αναφορά προόδου."),
    ("Μαρία", "Ένα ανοιχτό θέμα είναι η πρόσβαση στο δίκτυο του πελάτη για την ομάδα υποστήριξης."),
]


def main():
    out = Path(__file__).with_name("demo_el.wav")
    t, segs, audio = 0.5, [], []
    rng = np.random.default_rng(1)
    for spk, text in LINES:
        dur = max(2.5, len(text) / 14)
        segs.append({"start": round(t, 2), "end": round(t + dur, 2), "text": text, "speaker_hint": spk})
        t += dur + 0.6
    x = np.zeros(int((t + 0.5) * SR), np.float32)
    for i, s in enumerate(segs):
        n = int((s["end"] - s["start"]) * SR)
        tt = np.arange(n) / SR
        f = 140 + 60 * (i % 3)
        x[int(s["start"] * SR): int(s["start"] * SR) + n] = 0.25 * np.sin(2 * np.pi * f * tt) * (0.5 + 0.5 * rng.random(n))
    save_wav(out, x)
    # sidecar lines carry speaker names so the demo transcript looks real
    Path(str(out) + ".transcript.json").write_text(json.dumps(
        {"language": "el", "segments": [{**s, "text": s["text"]} for s in segs]}, ensure_ascii=False, indent=1), "utf-8")
    print(out)


if __name__ == "__main__":
    main()
