from openrgb import OpenRGBClient
c = OpenRGBClient(name="enumerate")
print("server protocol:", c.protocol_version, "devices:", len(c.devices))
for d in c.devices:
    print(f"\n[{d.id}] {d.name}  type={d.type.name}  vendor={d.metadata.vendor!r}  desc={d.metadata.description!r}")
    print(f"     location={d.metadata.location!r} serial={d.metadata.serial!r} version={d.metadata.version!r}")
    print(f"     active mode: {d.active_mode} -> {d.modes[d.active_mode].name if d.modes else None}")
    print("     modes:", ", ".join(m.name for m in d.modes))
    for z in d.zones:
        print(f"     zone[{z.id}] {z.name!r} type={z.type.name} leds={len(z.leds)}")
    print(f"     leds total: {len(d.leds)}")
c.disconnect()
