"""RGB panel - one local web page that controls every device on the OpenRGB SDK server.

Run:  uv run python panel.py [--host 127.0.0.1] [--port 6780]
Then open http://127.0.0.1:6780 (with --host 0.0.0.0 it is reachable from other machines too).
Only the standard library plus openrgb-python is used. Software effects live in effects.py.
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from openrgb import OpenRGBClient
except ImportError:
    # Started with the base interpreter (the scheduled task does this to avoid the uv venv launcher,
    # whose pythonw.exe spawns a console python.exe child): borrow the venv's packages.
    _venv_site = Path(__file__).parent / ".venv" / "Lib" / "site-packages"
    if _venv_site.exists():
        sys.path.append(str(_venv_site))
    from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

import effects

OPENRGB_TASK = "OpenRGB Server"
OPENRGB_PORT = 6742
HEALTH = {"openrgb": "unknown", "last_restart": 0.0, "restarts": 0}
LOCK = threading.RLock()
CLIENT: OpenRGBClient | None = None
BASE: dict[str, list[RGBColor]] = {}      # device name -> last colours the user asked for (unscaled)
MODE_BASE: dict[tuple[str, str], list[RGBColor]] = {}   # (device, mode) -> unscaled colours of an animated mode
SOFT_BRIGHT: dict[str, int] = {}          # device name -> software brightness 0-100 (Direct mode)


# ----------------------------------------------------------------------------- files and settings

def resource_dir() -> Path:
    """Folder holding panel.html, labels.json, app.ico: the source tree, or the PyInstaller bundle."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


def user_dir() -> Path:
    """Folder next to the running program, where labels.json and settings.json may live."""
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent


HTML = (resource_dir() / "panel.html").read_text(encoding="utf-8")
LABELS_FILE = user_dir() / "labels.json" if (user_dir() / "labels.json").exists() else resource_dir() / "labels.json"
SETTINGS_FILE = user_dir() / "settings.json"


def labels() -> dict:
    try:
        return json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(**changes):
    s = load_settings()
    s.update(changes)
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")
    except OSError as exc:
        print("settings not saved:", exc)


# ----------------------------------------------------------------------------- OpenRGB client

def client() -> OpenRGBClient:
    global CLIENT
    if CLIENT is None:
        CLIENT = OpenRGBClient(name="rgb-panel")
        for d in CLIENT.devices:
            SOFT_BRIGHT.setdefault(d.name, 100)
    return CLIENT


def reset_client():
    global CLIENT
    try:
        if CLIENT:
            CLIENT.disconnect()
    finally:
        CLIENT = None


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket()
    s.settimeout(0.8)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def start_openrgb_task() -> bool:
    """Ask Task Scheduler to (re)start the elevated OpenRGB server task. Returns True if accepted."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(["schtasks", "/run", "/tn", OPENRGB_TASK], capture_output=True, text=True,
                           creationflags=flags, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print("schtasks failed:", exc)
        return False
    if r.returncode != 0:
        print("schtasks:", r.stdout.strip(), r.stderr.strip())
    return r.returncode == 0


def watchdog(stop: threading.Event):
    """Poll the SDK port; when it is down, restart the task, at most once a minute."""
    while not stop.is_set():
        up = port_open(OPENRGB_PORT)
        HEALTH["openrgb"] = "up" if up else "down"
        if not up and time.time() - HEALTH["last_restart"] > 60:
            HEALTH["last_restart"] = time.time()
            HEALTH["restarts"] += 1
            HEALTH["openrgb"] = "restarting"
            if start_openrgb_task():
                with LOCK:
                    reset_client()
        stop.wait(5)


def start_watchdog() -> threading.Event:
    stop = threading.Event()
    threading.Thread(target=watchdog, args=(stop,), name="openrgb-watchdog", daemon=True).start()
    return stop


# ----------------------------------------------------------------------------- helpers

def hexcolor(c: RGBColor) -> str:
    return f"#{c.red:02x}{c.green:02x}{c.blue:02x}"


def parse_hex(text: str) -> RGBColor:
    t = text.lstrip("#")
    if len(t) != 6:
        raise ValueError(f"bad colour {text!r}")
    return RGBColor(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))


def scaled(c: RGBColor, pct: int) -> RGBColor:
    k = max(0, min(100, pct)) / 100
    return RGBColor(int(c.red * k), int(c.green * k), int(c.blue * k))


def clamp_mode(m):
    """Clamp reported mode values into the declared range (MSI GPU Direct reports brightness 12 of 0-5)."""
    if m.brightness is not None and m.brightness_min is not None and m.brightness_max is not None:
        lo, hi = sorted((m.brightness_min, m.brightness_max))
        m.brightness = min(max(m.brightness, lo), hi)
    if m.speed is not None and m.speed_min is not None and m.speed_max is not None:
        lo, hi = sorted((m.speed_min, m.speed_max))
        m.speed = min(max(m.speed, lo), hi)
    return m


def mode_named(device, name: str):
    return next((m for m in device.modes if m.name.lower() == name.lower()), None)


def active_mode(device):
    return device.modes[device.active_mode] if device.modes else None


def set_direct(device):
    m = mode_named(device, "Direct") or device.modes[0]
    device.set_mode(clamp_mode(m))


def pct(value, lo, hi):
    """Map a raw mode value onto 0-100 (None when the mode has no such control). Ranges may be inverted."""
    if value is None or lo is None or hi is None or hi == lo:
        return None
    return round(max(0.0, min(100.0, (value - lo) * 100 / (hi - lo))))


def raw(pct_value, lo, hi):
    return lo + (hi - lo) * int(pct_value) // 100


UNDERSIDE_TAG = "underside"          # LED name marker for single-colour on/off LED groups (MSI GPU)


def underside_index(device) -> int | None:
    for led in device.leds:
        if UNDERSIDE_TAG in led.name.lower():
            return led.id
    return None


UNDERSIDE_MODES = ("auto", "on", "off")
FX_UNDERSIDE = {"on": False}         # decision for the running effect in auto mode (set at effect start)


def underside_mode() -> str:
    v = load_settings().get("gpu_underside", "auto")
    if v is True:
        return "on"
    if v is False:
        return "off"
    return v if v in UNDERSIDE_MODES else "auto"


def reddish(r: int, g: int, b: int) -> bool:
    """Does this colour read as red/orange/pink? Yellow, purple and everything cool count as no."""
    return r >= 100 and g <= 0.6 * r and r >= 0.8 * b


def underside_now(logo: RGBColor | None = None) -> bool:
    mode = underside_mode()
    if mode != "auto":
        return mode == "on"
    if ENGINE.status()["running"]:
        return FX_UNDERSIDE["on"]
    return bool(logo) and reddish(logo.red, logo.green, logo.blue)


def with_underside(device, cols: list[RGBColor]) -> list[RGBColor]:
    """Force the on/off-only LED group to plain on (red) or off, whatever colour the rest gets."""
    i = underside_index(device)
    if i is None or i >= len(cols):
        return cols
    cols = list(cols)
    logo = cols[0] if cols else None
    cols[i] = RGBColor(255, 0, 0) if underside_now(logo) else RGBColor(0, 0, 0)
    return cols


def decide_fx_underside(name: str, speed: int) -> bool:
    """Sample the effect's first seconds: the underside joins in when the card would look red a good
    part of the time (Soviet, America, Police, Fire...), stays dark for Sweden, Ocean, Matrix...
    An effect can pin the answer with an `underside` attribute (India: orange is not red)."""
    import random
    desc_fn = effects.EFFECTS.get(name)
    if not desc_fn:
        return False
    fn = desc_fn[1]
    pinned = getattr(fn, "underside", None)
    if pinned is not None:
        return bool(pinned)
    try:
        layout, _interval, uniform = _layout()
    except Exception:  # noqa: BLE001
        return False
    gpu = [i for i, ref in enumerate(layout) if ref.device in uniform]
    if not gpu:
        return False
    rng = random.Random(7)
    if getattr(fn, "__defaults__", None):
        fn.__defaults__[0].clear()
    hits = total = 0
    for k in range(72):
        frame = fn(k / 6.0, layout, speed / 100, rng)
        n = len(gpu)
        r = sum(frame[i][0] for i in gpu) / n * 255
        g = sum(frame[i][1] for i in gpu) / n * 255
        b = sum(frame[i][2] for i in gpu) / n * 255
        total += 1
        hits += reddish(int(r), int(g), int(b))
    if getattr(fn, "__defaults__", None):
        fn.__defaults__[0].clear()
    return hits / total >= 0.3


def push_base(device):
    """Send the device's stored base colours scaled by its software brightness (Direct mode)."""
    base = BASE.get(device.name)
    if not base or len(base) != len(device.leds):
        base = list(device.colors)
        BASE[device.name] = base
    device.set_colors(with_underside(device, [scaled(c, SOFT_BRIGHT.get(device.name, 100)) for c in base]))


# ----------------------------------------------------------------------------- effects engine

def _layout():
    c = client()
    refs: list[effects.LedRef] = []
    total = sum(len(d.leds) for d in c.devices)
    i = 0
    for di, d in enumerate(c.devices):
        n = len(d.leds)
        for z in d.zones:
            for led in z.leds:
                refs.append(effects.LedRef(di, z.id, led.id, i / max(1, total - 1), led.id / max(1, n - 1)))
                i += 1
    interval = {}
    uniform = set()
    for di, d in enumerate(c.devices):
        interval[di] = {"GPU": 0.8, "DRAM": 0.12}.get(d.type.name, 0.05)
        if d.type.name == "GPU":
            uniform.add(di)
    return refs, interval, uniform


def _send(frame: dict[int, list[tuple[int, int, int]]]):
    with LOCK:
        c = client()
        for di, cols in frame.items():
            d = c.devices[di]
            if active_mode(d) is None or active_mode(d).name != "Direct":
                set_direct(d)
            d.set_colors(with_underside(d, [RGBColor(*rgb) for rgb in cols]), fast=True)


ENGINE = effects.Engine(_send, _layout)
MUSIC_FOR = {                   # effect -> recording in <program dir>\music (fetched with fetch_music.py)
    "Sweden": "sweden.wav",
    "Soviet Union": "soviet.wav",
    "America": "america.wav",
    "Police": "police.wav",
    "India": "india.wav",
    "Syria (Assad)": "syria.wav",
    "Israel": "israel.wav",
    "France": "france.wav",
}
MUSIC_NOTE = {"status": ""}


def music_dir() -> Path:
    """music\\ next to the program wins; the bundle's copy (PyInstaller datas) is the fallback."""
    local = user_dir() / "music"
    return local if local.exists() else resource_dir() / "music"


def envelope(path: Path) -> list[float]:
    """Loudness per 50 ms window, 0..1, cached next to the WAV. Pure stdlib; samples every 4th frame."""
    cache = path.with_suffix(path.suffix + ".env.json")
    try:
        if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            return json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        pass
    import array
    import wave
    with wave.open(str(path), "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        if sw != 2:
            return []
        step = int(rate * effects.ENV_STEP)
        levels = []
        while True:
            frames = w.readframes(step)
            if not frames:
                break
            a = array.array("h", frames[: len(frames) // 2 * 2])
            sub = a[::4 * ch]
            if not sub:
                break
            rms = (sum(x * x for x in sub) / len(sub)) ** 0.5
            levels.append(rms)
    if not levels:
        return []
    ref = sorted(levels)[int(len(levels) * 0.97)] or 1.0
    out = [round(min(1.0, v / ref), 3) for v in levels]
    try:
        cache.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def play_music(name: str):
    """Play the recording tied to an effect (async). Sweden falls back to the synthesized anthem."""
    MUSIC_NOTE["status"] = ""
    if name not in MUSIC_FOR or sys.platform != "win32":
        return
    import winsound
    path = music_dir() / MUSIC_FOR[name]
    if not path.exists() and name == "Sweden":
        import anthem
        path = user_dir() / "anthem.wav"
        if not path.exists():
            anthem.render_wav(path)
        effects.set_music(anthem.timeline())
        MUSIC_NOTE["status"] = "synthesized anthem (music\\sweden.wav not found)"
    elif not path.exists():
        MUSIC_NOTE["status"] = f"no music: {path.name} missing in {music_dir()}"
        return
    else:
        try:
            effects.set_music([], envelope(path))
        except Exception as exc:  # noqa: BLE001
            effects.set_music([], [])
            MUSIC_NOTE["status"] = f"envelope failed: {exc}"
    winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)


def stop_music():
    effects.set_music([])
    if sys.platform == "win32":
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)


STOPPERS = {"color", "mode", "off", "profile_load", "effect", "effect_stop"}   # actions that end an effect


def stop_effect(persist=True):
    """Stop music and the effect thread. Call this OUTSIDE LOCK: the effect thread needs LOCK to finish
    its current frame, so joining it while holding LOCK would stall for the join timeout."""
    was_running = ENGINE.status()["running"] or bool(effects.MUSIC_ENV) or bool(effects.MUSIC)
    stop_music()
    if ENGINE.status()["running"]:
        ENGINE.stop()
    if persist and (was_running or load_settings().get("effect")):
        save_settings(effect=None)


def resume_effect_later():
    """After start-up, resume the effect saved in settings.json once OpenRGB answers."""
    s = load_settings()
    name = s.get("effect")
    if not name or name not in effects.EFFECTS:
        return

    def worker():
        for _ in range(60):
            if port_open(OPENRGB_PORT):
                try:
                    with LOCK:
                        client()
                        FX_UNDERSIDE["on"] = decide_fx_underside(name, int(s.get("effect_speed") or 50))
                    ENGINE.start(name, s.get("effect_speed"), s.get("effect_brightness"))
                    return
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(3)
    threading.Thread(target=worker, name="fx-resume", daemon=True).start()


# ----------------------------------------------------------------------------- state and actions

def state(refresh: bool = True) -> dict:
    c = client()
    if refresh:
        c.update()
    all_labels = labels()
    devices = []
    for d in c.devices:
        modes = []
        for m in d.modes:
            modes.append({
                "name": m.name,
                "speed": pct(m.speed, m.speed_min, m.speed_max),
                "brightness": pct(m.brightness, m.brightness_min, m.brightness_max),
                "colors": m.colors_max or 0,
                "per_led": bool(m.color_mode and m.color_mode.name == "PER_LED"),
            })
        dev_labels = all_labels.get(d.name, {})
        zones = []
        for z in d.zones:
            first = d.colors[z.leds[0].id] if z.leds else None
            zones.append({"id": z.id, "name": z.name, "leds": len(z.leds),
                          "label": dev_labels.get(z.name, ""),
                          "color": hexcolor(first) if first else "#000000",
                          "resizable": z.name.lower().find("addressable") >= 0})
        am = active_mode(d)
        devices.append({"id": d.id, "name": d.name, "type": d.type.name,
                        "note": dev_labels.get("_note", ""),
                        "underside": None if underside_index(d) is None else underside_mode(),
                        "underside_now": None if underside_index(d) is None else underside_now(d.colors[0] if d.colors else None),
                        "active_mode": am.name if am else None,
                        "soft_brightness": SOFT_BRIGHT.get(d.name, 100),
                        "modes": modes, "zones": zones})
    return {"devices": devices, "profiles": [p.name for p in c.profiles],
            "effect": dict(ENGINE.status(), music=MUSIC_NOTE["status"]),
            "effects": [{"name": n, "desc": desc} for n, (desc, _f) in effects.EFFECTS.items()]}


def targets_for(c, ref):
    return c.devices if ref in (None, "all") else [c.devices[int(ref)]]


def apply(action: str, body: dict) -> dict:
    c = client()
    if action == "color":
        stop_effect()
        col = parse_hex(body["color"])
        for d in targets_for(c, body.get("device")):
            set_direct(d)
            base = BASE.get(d.name)
            if not base or len(base) != len(d.leds):
                base = list(d.colors)
            if body.get("zone") is None:
                base = [col] * len(d.leds)
            else:
                for led in d.zones[int(body["zone"])].leds:
                    base[led.id] = col
            BASE[d.name] = base
            push_base(d)
    elif action == "brightness":
        value = max(0, min(100, int(body["value"])))
        for d in targets_for(c, body.get("device")):
            m = active_mode(d)
            SOFT_BRIGHT[d.name] = value
            if ENGINE.status()["running"]:
                continue
            if m is not None and m.brightness is not None and m.name != "Direct":
                m.brightness = raw(value, m.brightness_min, m.brightness_max)     # real hardware brightness
                d.set_mode(clamp_mode(m))
            elif m is None or m.name == "Direct":
                push_base(d)                                                      # software: rescale colours
            elif m.colors_max:
                base = MODE_BASE.get((d.name, m.name)) or list(m.colors)          # animated mode: dim its colour
                MODE_BASE[(d.name, m.name)] = base
                m.colors = [scaled(col, value) for col in base]
                d.set_mode(clamp_mode(m))
            # modes without colours (Rainbow, Spectrum Cycle) have nothing to dim; value is kept for later
        if ENGINE.status()["running"] and body.get("device") in (None, "all"):
            ENGINE.update(brightness=value)
            save_settings(effect_brightness=value)
    elif action == "speed":
        value = max(0, min(100, int(body["value"])))
        for d in targets_for(c, body.get("device")):
            m = active_mode(d)
            if m is not None and m.speed is not None:
                m.speed = raw(value, m.speed_min, m.speed_max)
                d.set_mode(clamp_mode(m))
    elif action == "mode":
        stop_effect()
        for d in targets_for(c, body.get("device")):
            m = mode_named(d, body["mode"])
            if m is None:
                continue
            if body.get("speed") is not None and m.speed is not None:
                m.speed = raw(body["speed"], m.speed_min, m.speed_max)
            if body.get("brightness") is not None and m.brightness is not None:
                m.brightness = raw(body["brightness"], m.brightness_min, m.brightness_max)
            if body.get("color") and m.colors_max:
                m.colors = [parse_hex(body["color"])] * max(m.colors_min or 1, 1)
                MODE_BASE[(d.name, m.name)] = list(m.colors)
            elif m.colors_max and not m.colors:
                m.colors = [RGBColor(255, 255, 255)] * max(m.colors_min or 1, 1)
            d.set_mode(clamp_mode(m))
            if m.name == "Direct":
                push_base(d)
    elif action == "off":
        stop_effect()
        for d in targets_for(c, body.get("device")):
            if mode_named(d, "Off") is not None:
                d.set_mode(mode_named(d, "Off"))
            else:
                set_direct(d)
                d.set_color(RGBColor(0, 0, 0))
    elif action == "resize":
        d = c.devices[int(body["device"])]
        d.zones[int(body["zone"])].resize(max(0, min(int(body["count"]), 120)))
        BASE.pop(d.name, None)
    elif action == "profile_save":
        c.save_profile(body["name"])
    elif action == "profile_load":
        stop_effect()
        c.load_profile(body["name"])
        BASE.clear()
    elif action == "effect":
        stop_music()
        FX_UNDERSIDE["on"] = decide_fx_underside(body["name"], int(body.get("speed") or ENGINE.speed))
        ENGINE.start(body["name"], body.get("speed"), body.get("brightness"))
        play_music(body["name"])
        st = ENGINE.status()
        save_settings(effect=st["name"], effect_speed=st["speed"], effect_brightness=st["brightness"])
    elif action == "effect_update":
        ENGINE.update(body.get("speed"), body.get("brightness"))
        st = ENGINE.status()
        save_settings(effect_speed=st["speed"], effect_brightness=st["brightness"])
    elif action == "effect_stop":
        stop_effect()
    elif action == "underside":
        mode = body.get("mode")
        if mode is None:
            mode = "on" if body.get("on", True) else "off"
        if mode not in UNDERSIDE_MODES:
            raise ValueError(f"underside mode must be one of {UNDERSIDE_MODES}")
        save_settings(gpu_underside=mode)
        for d in c.devices:
            if underside_index(d) is not None and not ENGINE.status()["running"]:
                m = active_mode(d)
                if m is not None and m.name == "Direct":
                    push_base(d)
    elif action == "reconnect":
        reset_client()
    else:
        raise ValueError(f"unknown action {action}")
    return state(refresh=action in {"resize", "profile_load", "reconnect", "mode", "off"})


def with_retry(fn, *args):
    """Run fn; if the SDK socket died (server restarted), reconnect once and retry."""
    try:
        return fn(*args)
    except (ValueError, IndexError, KeyError):
        raise
    except Exception:  # noqa: BLE001
        reset_client()
        return fn(*args)


# ----------------------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A002  quieter console
        pass

    def _json(self, payload, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/health":
            return self._json(dict(HEALTH, port_up=port_open(OPENRGB_PORT), effect=ENGINE.status()))
        if self.path == "/api/state":
            with LOCK:
                try:
                    self._json(with_retry(state))
                except Exception as exc:  # noqa: BLE001
                    reset_client()
                    self._json({"error": f"OpenRGB error: {exc or 'connection lost'}"}, 503)
            return
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid JSON"}, 400)
        action = self.path[len("/api/"):]
        if action in STOPPERS:
            stop_effect(persist=action != "effect")   # outside LOCK, see stop_effect()
        with LOCK:
            try:
                self._json(with_retry(apply, self.path[len("/api/"):], body))
            except (ValueError, IndexError, KeyError) as exc:
                self._json({"error": str(exc)}, 400)
            except Exception as exc:  # noqa: BLE001
                reset_client()
                self._json({"error": f"OpenRGB error: {exc or 'connection lost'}"}, 503)


def setup_logging():
    """pythonw has no console: send prints and tracebacks to panel.log next to the program."""
    import faulthandler
    import io
    log_path = user_dir() / "panel.log"
    try:
        if log_path.exists() and log_path.stat().st_size > 2_000_000:
            log_path.unlink()
        f = open(log_path, "a", encoding="utf-8", buffering=1)
    except OSError:
        return
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False) or sys.executable.lower().endswith("pythonw.exe"):
        sys.stdout = sys.stderr = f
        faulthandler.enable(f)
    f.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} start pid {__import__('os').getpid()} {sys.executable} ===\n")


def main():
    setup_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6780)
    args = p.parse_args()
    try:
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
        print(f"rgb panel on http://{args.host}:{args.port}")
        stop = start_watchdog()
        resume_effect_later()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            ENGINE.stop()
            reset_client()
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        raise
    finally:
        print(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} exit ===")


if __name__ == "__main__":
    main()
