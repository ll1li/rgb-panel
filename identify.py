"""Light every zone/LED in a distinct colour so the physical wiring can be mapped by eye."""
from openrgb import OpenRGBClient
from openrgb.utils import RGBColor

ARGB_TEST_LEDS = 30
PALETTE = {
    "red": RGBColor(255, 0, 0), "green": RGBColor(0, 255, 0), "blue": RGBColor(0, 0, 255),
    "yellow": RGBColor(255, 200, 0), "magenta": RGBColor(255, 0, 255), "cyan": RGBColor(0, 255, 255),
    "white": RGBColor(255, 255, 255), "orange": RGBColor(255, 80, 0), "purple": RGBColor(120, 0, 255),
}

c = OpenRGBClient(name="identify")
for d in c.devices:
    d.set_mode("Direct")
    if d.type.name == "MOTHERBOARD":
        names = ["red", "green", "blue", "yellow", "magenta"]
        for led, n in zip(d.zones[0].leds, names):
            led.set_color(PALETTE[n])
            print(f"mainboard zone LED {led.id} ({led.name}) -> {n}")
        for z, n in zip(d.zones[1:], ["cyan", "white"]):
            if len(z.leds) == 0:
                z.resize(ARGB_TEST_LEDS)
            z.set_color(PALETTE[n])
            print(f"{z.name} ({len(z.leds)} LEDs) -> {n}")
    elif d.type.name == "DRAM":
        d.set_color(PALETTE["orange"]); print(f"{d.name} -> orange")
    elif d.type.name == "MOUSEMAT":
        d.set_color(PALETTE["purple"]); print(f"{d.name} -> purple")
c.disconnect()
