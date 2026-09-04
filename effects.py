"""Software lighting effects rendered by the panel and streamed to every device over the OpenRGB SDK.

Each effect is a function frame(t, layout, speed, rng) -> list of (r, g, b) floats in 0..1, one per
LED in `layout`. `layout` is a list of LedRef spanning all devices in a fixed order; `pos` runs 0..1
across the whole rig so waves travel from the first device to the last. `speed` is 0..1.
"""
from __future__ import annotations

import colorsys
import math
import random
import threading
import time
from dataclasses import dataclass
from typing import Callable

Frame = list[tuple[float, float, float]]


@dataclass(frozen=True)
class LedRef:
    device: int      # index into the client's device list
    zone: int
    led: int         # index within the device
    pos: float       # 0..1 across the whole rig
    dpos: float      # 0..1 within the device


def hsv(h: float, s: float = 1.0, v: float = 1.0) -> tuple[float, float, float]:
    return colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))


def lerp(a, b, k):
    k = max(0.0, min(1.0, k))
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def scale(c, k):
    k = max(0.0, min(1.0, k))
    return (c[0] * k, c[1] * k, c[2] * k)


class Noise:
    """Cheap smooth noise: a sum of sines with per-instance random phases."""

    def __init__(self, rng: random.Random, n: int = 4):
        self.terms = [(rng.uniform(0.5, 2.5), rng.uniform(0, 6.28), rng.uniform(0.3, 1.3)) for _ in range(n)]

    def __call__(self, x: float, t: float) -> float:
        v = sum(math.sin(x * f * 6.28 + p + t * s) for f, p, s in self.terms)
        return (v / len(self.terms) + 1) / 2


def fx_rainbow(t, layout, speed, rng):
    return [hsv(l.pos * 1.5 - t * (0.05 + speed * 0.6)) for l in layout]


def fx_breathe(t, layout, speed, rng):
    hue = (t * (0.01 + speed * 0.08)) % 1.0
    v = (math.sin(t * (0.6 + speed * 3.0)) + 1) / 2
    return [hsv(hue, 1.0, 0.08 + 0.92 * v) for _ in layout]


def fx_police(t, layout, speed, rng):
    period = 1.2 - speed * 0.9
    phase = (t % period) / period
    flash = 1.0 if (phase % 0.25) < 0.12 else 0.15
    left_red = phase < 0.5
    out = []
    for l in layout:
        red = (l.pos < 0.5) == left_red
        out.append(scale((1.0, 0.0, 0.0) if red else (0.0, 0.2, 1.0), flash))
    return out


def fx_fire(t, layout, speed, rng, _state={}):
    noise = _state.setdefault("n", Noise(rng, 5))
    out = []
    for l in layout:
        n = noise(l.pos * 3, t * (2 + speed * 6))
        n = n * 0.7 + rng.random() * 0.3
        out.append(lerp((0.6, 0.02, 0.0), (1.0, 0.75, 0.1), n * n))
    return out


def fx_matrix(t, layout, speed, rng, _state={}):
    drops = _state.setdefault("drops", {})
    out = []
    for i, l in enumerate(layout):
        age = drops.get(i)
        if age is None or t - age > 2.5:
            if rng.random() < 0.02 + speed * 0.08:
                drops[i] = t
                age = t
        v = 0.03 if age is None else max(0.03, 1.0 - (t - age) / (1.2 + (1 - speed) * 2.0))
        out.append((0.0, v, 0.15 * v))
    return out


def fx_disco(t, layout, speed, rng, _state={}):
    beat = 0.9 - speed * 0.75
    slot = int(t / beat)
    if _state.get("slot") != slot:
        _state["slot"] = slot
        _state["colors"] = {}
    cols = _state["colors"]
    out = []
    for l in layout:
        key = (l.device, l.zone)
        if key not in cols:
            cols[key] = hsv(rng.random(), 1.0, 1.0)
        out.append(cols[key])
    return out


def fx_comet(t, layout, speed, rng):
    head = (t * (0.15 + speed * 0.9)) % 1.3 - 0.15
    hue = (t * 0.05) % 1.0
    out = []
    for l in layout:
        d = head - l.pos
        v = math.exp(-d * 14) if d >= 0 else math.exp(d * 60)
        out.append(hsv(hue, 0.9, min(1.0, v)))
    return out


def fx_aurora(t, layout, speed, rng, _state={}):
    n1 = _state.setdefault("a", Noise(rng, 3)); n2 = _state.setdefault("b", Noise(rng, 3))
    out = []
    for l in layout:
        a = n1(l.pos, t * (0.3 + speed * 1.2)); b = n2(l.pos * 2, t * (0.2 + speed))
        c = lerp((0.0, 0.9, 0.5), (0.5, 0.0, 0.9), a)
        out.append(scale(c, 0.25 + 0.75 * b))
    return out


def fx_lava(t, layout, speed, rng, _state={}):
    n = _state.setdefault("n", Noise(rng, 4))
    out = []
    for l in layout:
        k = n(l.pos * 2, t * (0.25 + speed * 1.0))
        out.append(lerp((0.35, 0.0, 0.0), (1.0, 0.45, 0.0), k * k))
    return out


def fx_ocean(t, layout, speed, rng):
    out = []
    for l in layout:
        w = (math.sin(l.pos * 9 - t * (1.0 + speed * 4)) + 1) / 2
        w2 = (math.sin(l.pos * 4 + t * (0.5 + speed * 2)) + 1) / 2
        out.append(lerp((0.0, 0.05, 0.45), (0.0, 0.9, 1.0), w * 0.6 + w2 * 0.4))
    return out


def fx_candle(t, layout, speed, rng, _state={}):
    lvl = _state.setdefault("lvl", {})
    out = []
    for i, l in enumerate(layout):
        cur = lvl.get(i, 0.7)
        cur += (rng.random() - 0.5) * (0.15 + speed * 0.3)
        cur = max(0.35, min(1.0, cur))
        lvl[i] = cur
        out.append(scale((1.0, 0.5, 0.12), cur))
    return out


def fx_cyberpunk(t, layout, speed, rng):
    scan = (t * (0.4 + speed * 2.0)) % 2.0
    scan = scan if scan < 1 else 2 - scan
    out = []
    for l in layout:
        base = (1.0, 0.0, 0.6) if l.pos < scan else (0.0, 0.9, 1.0)
        glow = math.exp(-abs(l.pos - scan) * 25)
        out.append(lerp(scale(base, 0.5), (1.0, 1.0, 1.0), glow))
    return out


def fx_thunder(t, layout, speed, rng, _state={}):
    nxt = _state.get("next", 0.0)
    if t >= nxt:
        _state["flash_until"] = t + 0.12 + rng.random() * 0.2
        _state["next"] = t + 1.0 + rng.random() * (6.0 - speed * 5.0)
    flashing = t < _state.get("flash_until", 0.0)
    out = []
    for l in layout:
        if flashing and rng.random() < 0.8:
            out.append((0.9, 0.95, 1.0))
        else:
            out.append((0.02, 0.03, 0.18))
    return out


def fx_plasma(t, layout, speed, rng):
    s = t * (0.5 + speed * 3)
    out = []
    for l in layout:
        x = l.pos * 6.28
        v = (math.sin(x + s) + math.sin(2 * x - s * 0.7) + math.sin(x * 0.5 + s * 1.3)) / 3
        out.append(hsv((v + 1) / 2 * 0.8 + s * 0.02, 1.0, 1.0))
    return out


def fx_sunset(t, layout, speed, rng):
    k = (math.sin(t * (0.1 + speed * 0.5)) + 1) / 2
    out = []
    for l in layout:
        a = lerp((1.0, 0.35, 0.0), (1.0, 0.0, 0.35), l.pos)
        b = lerp((0.6, 0.0, 0.6), (0.2, 0.0, 0.5), l.pos)
        out.append(lerp(a, b, k))
    return out


def fx_strobe_soft(t, layout, speed, rng):
    period = 0.7 - speed * 0.5
    on = (t % period) < period * 0.5
    hue = (int(t / period) * 0.13) % 1.0
    return [hsv(hue, 0.6, 1.0 if on else 0.08) for _ in layout]


MUSIC: list[tuple[float, float, int]] = []   # (onset s, duration s, midi) of the tune playing with an effect
MUSIC_ENV: list[float] = []                   # loudness 0..1 per ENV_STEP seconds of the playing recording
ENV_STEP = 0.05
MUSIC_LATENCY = 0.15                          # audio starts a little after the effect thread


def set_music(timeline, envelope=None):
    MUSIC[:] = list(timeline)
    MUSIC_ENV[:] = list(envelope or [])


def music_level(t: float) -> float:
    """Loudness 0..1 of the recording at effect time t (0 when nothing is playing)."""
    if not MUSIC_ENV:
        note = music_note(t)
        return 0.0 if note is None else max(0.0, 1.0 - note[0] * 2.5)
    i = int((t - MUSIC_LATENCY) / ENV_STEP)
    if i < 0 or i >= len(MUSIC_ENV):
        return 0.0
    return MUSIC_ENV[i]


def music_hit(t: float) -> float:
    """Onset emphasis: how much louder now than a moment ago (0..1)."""
    if not MUSIC_ENV:
        return music_level(t)
    now = music_level(t)
    before = sum(music_level(t - k * ENV_STEP) for k in range(2, 6)) / 4
    return max(0.0, min(1.0, (now - before) * 3 + now * 0.25))


def music_note(t: float):
    """Current (progress 0..1 within the note, midi) at effect time t, or None outside the tune."""
    tt = t - MUSIC_LATENCY
    for onset, dur, midi in MUSIC:
        if onset <= tt < onset + dur:
            return (tt - onset) / dur, midi
    return None


def fx_sweden(t, layout, speed, rng):
    """Slow blue and yellow stripes; the music only makes them glow brighter, never another colour."""
    shift = (t * (0.03 + speed * 0.18)) % 1.0
    glow = 0.65 + 0.35 * max(music_hit(t), music_level(t) * 0.5)
    out = []
    for l in layout:
        k = (l.pos + shift) % 1.0
        base = (0.0, 0.32, 0.95) if (k % 0.5) < 0.35 else (1.0, 0.78, 0.0)
        out.append(scale(base, glow))
    return out


def fx_soviet(t, layout, speed, rng):
    """Deep red with a golden band marching through, gold surges with the music."""
    band = (t * (0.08 + speed * 0.5)) % 1.0
    surge = music_hit(t)
    lvl = music_level(t)
    out = []
    for l in layout:
        d = min(abs(l.pos - band), 1 - abs(l.pos - band))
        gold = math.exp(-d * 18)
        base = lerp((0.55 + 0.35 * lvl, 0.0, 0.0), (1.0, 0.72, 0.0), gold)
        out.append(lerp(base, (1.0, 0.85, 0.2), surge * 0.9))
    return out


def fx_america(t, layout, speed, rng, _state={}):
    """Red, white and blue stripes on the move with fireworks bursting on the beat."""
    shift = (t * (0.1 + speed * 0.7)) % 1.0
    hit = music_hit(t)
    sparks = _state.setdefault("sparks", {})
    if hit > 0.35:
        for _ in range(1 + int(hit * 4)):
            sparks[rng.randrange(len(layout))] = t
    out = []
    for i, l in enumerate(layout):
        k = (l.pos * 2 + shift) % 1.0
        base = (1.0, 0.05, 0.05) if k < 0.34 else ((1.0, 1.0, 1.0) if k < 0.5 else (0.1, 0.2, 1.0))
        base = scale(base, 0.55 + 0.45 * max(hit, music_level(t) * 0.6))
        born = sparks.get(i)
        if born is not None:
            age = t - born
            if age < 0.5:
                base = lerp(base, (1.0, 1.0, 0.85), 1.0 - age * 2)
            else:
                sparks.pop(i, None)
        out.append(base)
    return out


def fx_india(t, layout, speed, rng, _state={}):
    """Saffron, white and green bands drifting by; the chakra's navy blue spins up and everything
    flares white when the voice on the clip loses it."""
    shift = (t * (0.05 + speed * 0.4)) % 1.0
    hit = music_hit(t)
    lvl = music_level(t)
    flash = _state.get("flash", 0.0)
    if hit > 0.45:
        flash = max(flash, hit)
    _state["flash"] = flash * 0.85
    spin = (t * (1.5 + lvl * 6)) % 1.0
    out = []
    for l in layout:
        k = (l.pos + shift) % 1.0
        if k < 0.4:
            base = (1.0, 0.42, 0.0)          # saffron, kept bold
        elif k < 0.6:
            # a narrow, softened white band so it never washes out the colours, chakra navy on top
            wheel = 0.5 + 0.5 * math.cos((k - 0.4) / 0.2 * math.tau * 2 - spin * math.tau)
            base = lerp((0.7, 0.7, 0.7), (0.0, 0.0, 0.75), wheel * (0.5 + 0.5 * lvl))
        else:
            base = (0.0, 0.7, 0.0)           # green, kept bold
        base = scale(base, 0.6 + 0.4 * max(hit, lvl * 0.7))
        out.append(lerp(base, (1.0, 0.5, 0.0), flash * 0.5))   # the rage flares saffron, not white
    return out


fx_india.underside = False   # saffron would pass the "reddish" test; the red-only underside stays dark


def fx_syria(t, layout, speed, rng):
    """Red, white and black bands of the Assad-era flag, the two green stars sweeping through the white
    band and pulsing with the song; the black band stays dark so the stars really stand out."""
    shift = (t * (0.05 + speed * 0.4)) % 1.0
    hit = music_hit(t)
    lvl = music_level(t)
    star_pos = (t * (0.3 + lvl * 1.2)) % 1.0
    out = []
    for l in layout:
        k = (l.pos + shift) % 1.0
        if k < 0.34:
            base = (1.0, 0.02, 0.0)          # red: no blue at all, LEDs turn it pink
        elif k < 0.66:
            base = (1.0, 1.0, 1.0)           # white with the two stars
            u = (k - 0.34) / 0.32
            star = 0.0
            for centre in (star_pos, (star_pos + 0.5) % 1.0):
                d = min(abs(u - centre), 1 - abs(u - centre))
                star = max(star, math.exp(-d * d * 300))
            base = lerp(base, (0.0, 0.85, 0.15), star * (0.6 + 0.4 * hit))
        else:
            base = (0.0, 0.0, 0.0)           # black: fully off, a faint level reads as purple on LEDs
        out.append(scale(base, 0.55 + 0.45 * max(hit, lvl * 0.7)))
    return out


def fx_israel(t, layout, speed, rng, _state={}):
    """White field with two blue stripes that step to the beat: every hit snaps the pattern a quarter
    turn (with a short ease) so blue and white trade places on the music, plus a six-point star: six
    deep-blue sparks spaced evenly around the rig that burst on the beat and fade between hits."""
    hit = music_hit(t)
    lvl = music_level(t)
    beats = _state.get("beats", 0)
    last = _state.get("last", -1.0)
    if hit > 0.3 and t - last > 0.18:            # one step per onset, debounced
        beats += 1
        last = t
        _state["beats"], _state["last"] = beats, last
    ease = min(1.0, (t - last) / 0.12) if last >= 0 else 1.0
    step = (beats - 1 + ease) * 0.25 if beats else 0.0
    shift = (step + t * (0.01 + speed * 0.05)) % 1.0    # a slow drift between beats, and without music
    burst = max(_state.get("burst", 0.0) * 0.9, hit)
    _state["burst"] = burst
    spin = (t * 0.05) % 1.0
    out = []
    for l in layout:
        k = (l.pos + shift) % 1.0
        stripe = 1.0 if (0.12 < k < 0.28 or 0.62 < k < 0.78) else 0.0
        base = lerp((1.0, 1.0, 1.0), (0.0, 0.22, 0.72), stripe)
        u = (l.pos + spin) % 1.0
        d = min(abs(u * 6 - round(u * 6)), 1.0) / 6
        star = math.exp(-d * d * 4000)
        base = lerp(base, (0.0, 0.12, 0.9), star * (0.3 + 0.7 * burst))
        out.append(scale(base, 0.55 + 0.45 * max(hit, lvl * 0.7)))
    return out


def fx_france(t, layout, speed, rng, _state={}):
    """Blue, white and red bands waving past like the tricolour in wind, and on every beat the rig
    twinkles gold the way the Eiffel Tower does on the hour."""
    shift = (t * (0.05 + speed * 0.4)) % 1.0
    hit = music_hit(t)
    lvl = music_level(t)
    sparks = _state.setdefault("sparks", {})
    if hit > 0.35:
        for _ in range(2 + int(hit * 6)):
            sparks[rng.randrange(len(layout))] = t
    out = []
    for i, l in enumerate(layout):
        wave = 0.04 * math.sin(l.pos * math.tau * 2 + t * 2.5)
        k = (l.pos + shift + wave) % 1.0
        base = (0.0, 0.2, 0.75) if k < 0.34 else ((1.0, 1.0, 1.0) if k < 0.66 else (1.0, 0.02, 0.0))
        base = scale(base, 0.55 + 0.45 * max(hit, lvl * 0.7))
        born = sparks.get(i)
        if born is not None:
            age = t - born
            if age < 0.4:
                base = lerp(base, (1.0, 0.85, 0.3), 1.0 - age * 2.5)
            else:
                sparks.pop(i, None)
        out.append(base)
    return out


EFFECTS: dict[str, tuple[str, Callable]] = {
    "Rainbow wave": ("A rainbow that travels across every device", fx_rainbow),
    "Plasma": ("Classic swirling plasma colours", fx_plasma),
    "Breathe": ("Everything pulses together, slowly changing hue", fx_breathe),
    "Comet": ("A bright head with a fading tail racing around the rig", fx_comet),
    "Cyberpunk": ("Magenta and cyan with a scanning white line", fx_cyberpunk),
    "Aurora": ("Northern lights, green and purple drifting", fx_aurora),
    "Ocean": ("Deep blue with cyan waves", fx_ocean),
    "Lava": ("Slow red and orange blobs", fx_lava),
    "Fire": ("Flickering flames", fx_fire),
    "Candle": ("Warm gentle flicker, easy on the eyes", fx_candle),
    "Matrix": ("Green digital rain", fx_matrix),
    "Disco": ("Every zone jumps to a new colour on the beat", fx_disco),
    "Police": ("Red and blue strobes, left and right. Sir, get down!", fx_police),
    "Thunderstorm": ("Dark blue with random lightning", fx_thunder),
    "Soft strobe": ("Slow colour-changing flash", fx_strobe_soft),
    "Sweden": ("Slow blue and yellow stripes, and the anthem plays", fx_sweden),
    "Soviet Union": ("Red with a marching gold band, 1944 anthem plays", fx_soviet),
    "America": ("Stars, stripes and fireworks to the only song that fits", fx_america),
    "India": ("Saffron, white and green with a spinning chakra. Do NOT redeem the cards!", fx_india),
    "Syria (Assad)": ("Red, white and black with two green stars, and the Bashar song plays", fx_syria),
    "Israel": ("Blue and white stepping to the beat, with a six-point star bursting on it", fx_israel),
    "France": ("The tricolour waving, with Eiffel Tower gold twinkles on the beat", fx_france),
}


class Engine:
    """Runs one effect in a thread. `send(dict[device_index, list[(r,g,b) 0..255]])` pushes a frame.

    Per-device pacing avoids flooding slow buses: the GPU chip needs ~50 ms per LED packet and the
    RAM sits on SMBus, so those get fewer frames than USB devices.
    """

    FPS = 24

    def __init__(self, send: Callable[[dict[int, list[tuple[int, int, int]]]], None],
                 layout_fn: Callable[[], tuple[list[LedRef], dict[int, float], set[int]]]):
        self.send = send
        self.layout_fn = layout_fn
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.stop_evt = threading.Event()
        self.name: str | None = None
        self.speed = 50
        self.brightness = 100
        self.error: str | None = None

    def status(self) -> dict:
        return {"name": self.name, "speed": self.speed, "brightness": self.brightness,
                "running": bool(self.thread and self.thread.is_alive()), "error": self.error}

    def start(self, name: str, speed: int | None = None, brightness: int | None = None):
        if name not in EFFECTS:
            raise ValueError(f"unknown effect {name!r}")
        self.stop()
        with self.lock:
            self.name = name
            if speed is not None:
                self.speed = max(0, min(100, int(speed)))
            if brightness is not None:
                self.brightness = max(0, min(100, int(brightness)))
            self.error = None
            self.stop_evt = threading.Event()
            self.thread = threading.Thread(target=self._run, name=f"fx-{name}", daemon=True)
            self.thread.start()

    def update(self, speed: int | None = None, brightness: int | None = None):
        with self.lock:
            if speed is not None:
                self.speed = max(0, min(100, int(speed)))
            if brightness is not None:
                self.brightness = max(0, min(100, int(brightness)))

    def stop(self):
        t = self.thread
        if t and t.is_alive():
            self.stop_evt.set()
            t.join(timeout=3)
        self.thread = None
        self.name = None

    def _run(self):
        name = self.name or ""
        if name not in EFFECTS:
            return
        _desc, fn = EFFECTS[name]
        rng = random.Random(1234)
        # a fresh copy of the effect's private state for each run
        if hasattr(fn, "__defaults__") and fn.__defaults__:
            fn.__defaults__[0].clear()
        try:
            layout, min_interval, uniform = self.layout_fn()
        except Exception as exc:  # noqa: BLE001
            self.error = f"could not read device layout: {exc}"
            return
        if not layout:
            self.error = "no LEDs to drive"
            return
        last_sent: dict[int, tuple[float, list]] = {}
        t0 = time.monotonic()
        next_frame = t0
        while not self.stop_evt.is_set():
            now = time.monotonic()
            t = now - t0
            with self.lock:
                speed = self.speed / 100
                bright = self.brightness / 100
            try:
                frame = fn(t, layout, speed, rng)
            except Exception as exc:  # noqa: BLE001
                self.error = f"{name}: {exc}"
                return
            per_dev: dict[int, list[tuple[int, int, int]]] = {}
            for ref, (r, g, b) in zip(layout, frame):
                per_dev.setdefault(ref.device, []).append(
                    (int(255 * max(0, min(1, r)) * bright), int(255 * max(0, min(1, g)) * bright), int(255 * max(0, min(1, b)) * bright)))
            due = {}
            for dev, cols in per_dev.items():
                if dev in uniform and cols:
                    # slow chips (the GPU: one paced I2C packet per LED) get one averaged colour
                    n = len(cols)
                    avg = (sum(c[0] for c in cols) // n, sum(c[1] for c in cols) // n, sum(c[2] for c in cols) // n)
                    cols = [avg] * n
                prev = last_sent.get(dev)
                if prev and now - prev[0] < min_interval.get(dev, 0.05):
                    continue
                if prev and prev[1] == cols:
                    continue
                if prev and dev in uniform and max(abs(a - b) for a, b in zip(prev[1][0], cols[0])) < 10:
                    continue
                due[dev] = cols
            if due:
                try:
                    self.send(due)
                except Exception as exc:  # noqa: BLE001
                    self.error = f"send failed: {exc}"
                    self.stop_evt.wait(1.0)
                    continue
                for dev, cols in due.items():
                    last_sent[dev] = (now, cols)
            next_frame += 1 / self.FPS
            delay = next_frame - time.monotonic()
            if delay > 0:
                self.stop_evt.wait(delay)
            else:
                next_frame = time.monotonic()
