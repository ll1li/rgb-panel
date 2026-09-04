r"""Fetch the recordings the music presets play, with yt-dlp, into <project>\music\<name>.wav.

    uv run python fetch_music.py            # fetch every track in TRACKS that is missing
    uv run python fetch_music.py sweden     # one track
    uv run python fetch_music.py sweden "https://www.youtube.com/watch?v=..."   # a specific upload

Needs yt-dlp and ffmpeg on PATH (winget: yt-dlp.yt-dlp installs both) and a JavaScript runtime for
YouTube's download challenge (deno is picked up automatically when installed). YouTube bot-checks
VPN and datacenter exit IPs: if you get "Sign in to confirm you're not a bot", leave the VPN for a
minute or pass `-- --cookies-from-browser <browser>`. Sources are recorded in <name>.source.txt.
The recordings are not part of the repository; fetching them is your own responsibility.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

TRACKS = {
    # national day 2010 at Skansen: military band, speech, then the big choir at 65.4 s
    "sweden": "https://www.youtube.com/watch?v=om5WqGJ3Tsg",
    # 1944-1955 text; the orchestra comes in at 8.3 s after an announcer
    "soviet": "https://www.youtube.com/watch?v=tW6OMxbcTCk",
    # Team America OST; the first "America! F*** yeah!" is at 32.0 s
    "america": "https://www.youtube.com/watch?v=MhQ5678cJU8",
    # an 11 s "Sir, get down!" meme clip for the Police preset
    "police": "https://www.youtube.com/shorts/tEk5DYudbwU",
    # a 55 s scam-baiter rage clip ("do NOT redeem the cards") for the India preset; starts hot, no trim
    "india": "https://www.youtube.com/shorts/csy5RHcXT6Y",
    # a 39 s Bashar al-Assad song edit for the Syria (Assad) preset
    "syria": "https://www.youtube.com/watch?v=4K00naoeNDE",
    # "Hava Nagila" techno edit for the Israel preset; the drop worth hearing starts at 0:59
    "israel": "https://www.youtube.com/watch?v=q3P-ExI3iXM",
    # Tour de France "drinking raids" clip for the France preset; the good part starts at 0:46
    "france": "https://www.youtube.com/watch?v=7UhT6-GntcY",
}
# seconds cut from the start of each download (found with faster-whisper word timestamps and the
# loudness envelope); the untrimmed file is kept as <name>.orig.wav
TRIMS = {"sweden": 65.4, "soviet": 8.3, "america": 32.0, "israel": 59.0, "france": 46.0}
MUSIC = Path(__file__).parent / "music"
WINGET_LINKS = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"


def tool(name: str) -> str:
    found = shutil.which(name) or shutil.which(name, path=str(WINGET_LINKS))
    if not found:
        raise SystemExit(f"{name} not found; install with: winget install yt-dlp.yt-dlp")
    return found


def fetch(name: str, source: str, extra: list[str]) -> Path:
    MUSIC.mkdir(exist_ok=True)
    out = MUSIC / f"{name}.wav"
    tmp = MUSIC / f"{name}.tmp.%(ext)s"
    cmd = [tool("yt-dlp"), "--no-playlist", "-x", "--audio-format", "wav", "--audio-quality", "0",
           "--ffmpeg-location", str(Path(tool("ffmpeg")).parent), "--print-to-file",
           "%(title)s | %(uploader)s | %(duration)s s | %(webpage_url)s", str(MUSIC / f"{name}.source.txt"),
           "-o", str(tmp), *extra, source]
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)
    produced = next(MUSIC.glob(f"{name}.tmp.wav"))
    # 44.1 kHz 16-bit stereo so winsound and the envelope reader are happy
    orig = MUSIC / f"{name}.orig.wav"
    subprocess.run([tool("ffmpeg"), "-y", "-loglevel", "error", "-i", str(produced),
                    "-ar", "44100", "-ac", "2", "-sample_fmt", "s16", str(orig)], check=True)
    produced.unlink()
    start = TRIMS.get(name, 0.0)
    subprocess.run([tool("ffmpeg"), "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-i", str(orig),
                    "-af", "afade=t=in:st=0:d=0.05", str(out)], check=True)
    print(f"trimmed {start:.1f} s from the start")
    for stale in MUSIC.glob(f"{name}.wav.env.json"):
        stale.unlink()
    print("wrote", out, f"{out.stat().st_size/1e6:.1f} MB")
    return out


def default_extra() -> list[str]:
    """YouTube's download challenge needs a JavaScript runtime; use deno when it is around."""
    deno = shutil.which("deno") or shutil.which("deno", path=str(WINGET_LINKS))
    return ["--js-runtimes", f"deno:{deno}"] if deno else []


def main(argv: list[str]):
    # everything after a lone "--" goes to yt-dlp verbatim, e.g. -- --cookies-from-browser firefox
    extra = default_extra()
    if "--" in argv:
        i = argv.index("--")
        extra += argv[i + 1:]
        argv = argv[:i]
    args = argv
    if not args:
        for name, src in TRACKS.items():
            if (MUSIC / f"{name}.wav").exists():
                print("have", name)
            else:
                fetch(name, src, extra)
        return
    name = args[0]
    source = args[1] if len(args) > 1 else TRACKS.get(name)
    if not source:
        raise SystemExit(f"unknown track {name!r}; known: {list(TRACKS)}")
    fetch(name, source, extra)


if __name__ == "__main__":
    main(sys.argv[1:])
