"""'Du gamla, du fria' (traditional melody, 1844, public domain) as a small stdlib synthesizer.

Notes follow Frank Nordberg's ABC transcription (Musica Viva): key B-flat, 4/4, eighth-note unit,
with the last line repeated. render_wav() writes a 16-bit mono WAV; timeline() gives note onsets
so the lights can follow the tune. No third-party modules.
"""
from __future__ import annotations

import array
import math
import wave
from pathlib import Path

BPM = 72                      # maestoso
EIGHTH = 60.0 / BPM / 2       # seconds per eighth note
RATE = 22050

# (midi note or None for a rest, length in eighth notes)
_LINE_1_6 = [
    (74, 1),                                                   # pickup: Du
    (74, 2), (70, 1), (70, 1), (70, 2), (72, 1), (74, 1),      # gam-la, du fri-a, du
    (74, 2), (72, 1), (70, 1), (69, 2), (None, 1), (72, 1),    # fjäll-hö-ga Nord, du
    (72, 2), (69, 1), (70, 1), (72, 1), (69, 1), (74, 1), (70, 1),  # tys-ta, du gläd-je-ri-ka
    (67, 4), (65, 2), (None, 1), (65, 1),                      # skö-na! Jag
    (70, 2), (70, 1), (72, 1), (69, 2), (69, 1), (70, 1),      # häl-sar dig, vä-nas-te
    (67, 1.5), (65, 0.5), (67, 1), (69, 1), (65, 2), (None, 1),  # land up-på jord,
]
_REFRAIN = [
    (65, 1),                                                   # din
    (70, 1.5), (69, 0.5), (70, 1), (72, 1), (74, 1), (70, 1), (75, 1), (74, 1),  # sol, din him-mel, di-na äng-der
    (72, 4), (70, 2), (None, 1),                               # grö-na.
]
NOTES = _LINE_1_6 + _REFRAIN + _REFRAIN


def timeline(offset: float = 0.0) -> list[tuple[float, float, int]]:
    """[(onset_seconds, duration_seconds, midi)] for every sounding note."""
    out, t = [], offset
    for midi, eighths in NOTES:
        dur = eighths * EIGHTH
        if midi is not None:
            out.append((t, dur, midi))
        t += dur
    return out


def duration() -> float:
    return sum(e for _m, e in NOTES) * EIGHTH


def _freq(midi: int) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _voice(freq: float, n: int, amp: float, attack: float, release: float, harmonics) -> list[float]:
    """Additive tone with a soft envelope and slight vibrato."""
    out = [0.0] * n
    two_pi = 2 * math.pi
    a_n = max(1, int(attack * RATE))
    r_n = max(1, int(release * RATE))
    for i in range(n):
        t = i / RATE
        env = min(1.0, i / a_n) * min(1.0, (n - i) / r_n)
        vib = 1.0 + 0.004 * math.sin(two_pi * 5.5 * t)
        ph = two_pi * freq * vib * t
        s = 0.0
        for k, h in enumerate(harmonics, start=1):
            s += h * math.sin(ph * k)
        out[i] = s * env * amp
    return out


def render_wav(path: Path, gain: float = 0.35) -> Path:
    total = int((duration() + 1.0) * RATE)
    mix = [0.0] * total
    lead = (1.0, 0.55, 0.30, 0.18, 0.10, 0.06)     # brass-like
    pad = (1.0, 0.35, 0.12)                          # soft octave below
    t = 0.0
    for midi, eighths in NOTES:
        dur = eighths * EIGHTH
        if midi is not None:
            start = int(t * RATE)
            n = int(dur * RATE * 0.97)
            v1 = _voice(_freq(midi), n, 0.75, 0.02, 0.06, lead)
            v2 = _voice(_freq(midi - 12), n, 0.35, 0.05, 0.10, pad)
            for i in range(n):
                mix[start + i] += v1[i] + v2[i]
        t += dur
    peak = max(1e-6, max(abs(x) for x in mix))
    scale = gain * 32767 / peak
    data = array.array("h", (int(max(-32767, min(32767, x * scale))) for x in mix))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data.tobytes())
    return path


if __name__ == "__main__":
    import sys
    p = render_wav(Path(sys.argv[1] if len(sys.argv) > 1 else "anthem.wav"))
    print(f"wrote {p} ({duration():.1f} s, {len(NOTES)} notes)")
