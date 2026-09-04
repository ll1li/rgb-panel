"""rgb - command-line control of every RGB device via the local OpenRGB SDK server.

Usage examples:
  rgb list
  rgb set motherboard ff4000            # whole device, Direct mode
  rgb set ram 00ff00 --zone 1
  rgb all 2020ff
  rgb mode mousemat "Color Cycle" --speed 50
  rgb mode all Static --color ff0000
  rgb off [device|all]
  rgb resize motherboard 1 24           # addressable header zone LED count
  rgb profile save night / load night / list
  rgb identify
"""
from __future__ import annotations

import argparse
import sys

from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

ALIASES = {"ram": "DRAM", "memory": "DRAM", "mb": "MOTHERBOARD", "motherboard": "MOTHERBOARD",
           "board": "MOTHERBOARD", "mousepad": "MOUSEMAT", "mousemat": "MOUSEMAT", "pad": "MOUSEMAT",
           "gpu": "GPU"}


def parse_color(text: str) -> RGBColor:
    named = {"red": "ff0000", "green": "00ff00", "blue": "0000ff", "white": "ffffff",
             "orange": "ff5000", "purple": "7800ff", "cyan": "00ffff", "magenta": "ff00ff",
             "yellow": "ffc800", "off": "000000", "black": "000000", "warm": "ff9040"}
    text = named.get(text.lower(), text).lstrip("#")
    if len(text) != 6:
        raise SystemExit(f"bad colour {text!r}: expect 6 hex digits or a name {sorted(named)}")
    return RGBColor(int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))


def clamp_mode(m):
    """Some controllers report a mode value outside its own declared range (MSI GPU Direct mode
    says brightness 12 with range 0-5); openrgb-python refuses to send that, so clamp first."""
    if m.brightness is not None and m.brightness_min is not None and m.brightness_max is not None:
        lo, hi = sorted((m.brightness_min, m.brightness_max))
        m.brightness = min(max(m.brightness, lo), hi)
    if m.speed is not None and m.speed_min is not None and m.speed_max is not None:
        lo, hi = sorted((m.speed_min, m.speed_max))
        m.speed = min(max(m.speed, lo), hi)
    return m


def set_mode(device, name: str):
    device.set_mode(clamp_mode(mode_by_name(device, name)))


def pick(client: OpenRGBClient, ref: str):
    """Resolve a device reference: 'all', numeric id, type alias, or name substring."""
    if ref.lower() == "all":
        return list(client.devices)
    if ref.isdigit():
        return [client.devices[int(ref)]]
    if ref.lower() in ALIASES:
        hits = [d for d in client.devices if d.type.name == ALIASES[ref.lower()]]
    else:
        hits = [d for d in client.devices if ref.lower() in d.name.lower()]
    if not hits:
        raise SystemExit(f"no device matches {ref!r}; run `rgb list`")
    return hits


def mode_by_name(device, name: str):
    for m in device.modes:
        if m.name.lower() == name.lower():
            return m
    raise SystemExit(f"{device.name}: no mode {name!r}; available: {[m.name for m in device.modes]}")


def load_labels() -> dict:
    import json
    from pathlib import Path
    try:
        return json.loads((Path(__file__).parent / "labels.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def cmd_list(client, _args):
    all_labels = load_labels()
    for d in client.devices:
        active = d.modes[d.active_mode].name if d.modes else "?"
        dev_labels = all_labels.get(d.name, {})
        print(f"[{d.id}] {d.name}  ({d.type.name})  mode={active}")
        if dev_labels.get("_note"):
            print(f"      note: {dev_labels['_note']}")
        for z in d.zones:
            col = d.colors[z.leds[0].id] if z.leds else None
            col_txt = f"#{col.red:02x}{col.green:02x}{col.blue:02x}" if col else "-"
            label = dev_labels.get(z.name, "")
            print(f"      zone {z.id}: {z.name}  leds={len(z.leds)}  first={col_txt}" + (f"  [{label}]" if label else ""))
        print(f"      modes: {', '.join(m.name for m in d.modes)}")


def cmd_set(client, args):
    color = parse_color(args.color)
    for d in pick(client, args.device):
        set_mode(d, "Direct")
        if args.zone is None:
            d.set_color(color)
        else:
            d.zones[args.zone].set_color(color)
        print(f"{d.name}: {args.color}")


def cmd_all(client, args):
    args.device, args.zone = "all", None
    cmd_set(client, args)


def cmd_mode(client, args):
    for d in pick(client, args.device):
        m = clamp_mode(mode_by_name(d, args.mode))
        kwargs = {}
        if args.speed is not None and m.speed is not None:
            kwargs["speed"] = m.speed_min + (m.speed_max - m.speed_min) * args.speed // 100
        if args.brightness is not None and m.brightness is not None:
            kwargs["brightness"] = m.brightness_min + (m.brightness_max - m.brightness_min) * args.brightness // 100
        if args.color and m.colors_max:
            m.colors = [parse_color(args.color)] * max(m.colors_min or 1, 1)
        for k, v in kwargs.items():
            setattr(m, k, v)
        d.set_mode(m)
        print(f"{d.name}: mode {m.name} {kwargs}")


def cmd_off(client, args):
    for d in pick(client, args.device):
        names = [m.name for m in d.modes]
        if "Off" in names:
            set_mode(d, "Off")
        else:
            set_mode(d, "Direct")
            d.set_color(RGBColor(0, 0, 0))
        print(f"{d.name}: off")


def cmd_resize(client, args):
    for d in pick(client, args.device):
        z = d.zones[args.zone]
        z.resize(args.count)
        print(f"{d.name} zone {z.id} ({z.name}) -> {args.count} LEDs")


def cmd_profile(client, args):
    if args.action == "list":
        print("\n".join(p.name for p in client.profiles) or "(no profiles)")
    elif args.action == "save":
        client.save_profile(args.name)
        print(f"saved profile {args.name}")
    elif args.action == "load":
        client.load_profile(args.name)
        print(f"loaded profile {args.name}")


def cmd_identify(client, _args):
    import identify  # noqa: F401  (runs the mapping test on import)


def main(argv=None):
    p = argparse.ArgumentParser(prog="rgb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=6742)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    s = sub.add_parser("set"); s.add_argument("device"); s.add_argument("color"); s.add_argument("--zone", type=int); s.set_defaults(fn=cmd_set)
    s = sub.add_parser("all"); s.add_argument("color"); s.set_defaults(fn=cmd_all)
    s = sub.add_parser("mode"); s.add_argument("device"); s.add_argument("mode"); s.add_argument("--color"); s.add_argument("--speed", type=int); s.add_argument("--brightness", type=int); s.set_defaults(fn=cmd_mode)
    s = sub.add_parser("off"); s.add_argument("device", nargs="?", default="all"); s.set_defaults(fn=cmd_off)
    s = sub.add_parser("resize"); s.add_argument("device"); s.add_argument("zone", type=int); s.add_argument("count", type=int); s.set_defaults(fn=cmd_resize)
    s = sub.add_parser("profile"); s.add_argument("action", choices=["save", "load", "list"]); s.add_argument("name", nargs="?"); s.set_defaults(fn=cmd_profile)
    sub.add_parser("identify").set_defaults(fn=cmd_identify)
    args = p.parse_args(argv)
    if args.cmd == "profile" and args.action != "list" and not args.name:
        p.error("profile save/load needs a name")
    try:
        client = OpenRGBClient(args.host, args.port, name="rgb-cli")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"cannot reach OpenRGB SDK server at {args.host}:{args.port} ({exc}); is the OpenRGB Server task running?")
    try:
        args.fn(client, args)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
