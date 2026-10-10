#!/usr/bin/env python3
"""Probe all footage + build contact sheets for visual shot selection."""
import json, os, subprocess, sys

DL = "/home/z/my-project/ytdl-agent/downloads"
SHEETS = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3/sheets"
os.makedirs(SHEETS, exist_ok=True)

SOURCES = {
    # short stages / fancams
    "ysJCTCQYJyg": ("AHYEON YG eval live #2 (viral 18M)", 4),
    "MsOOG4Q5HvQ": ("Ahyeon - Monster Begin Again Open Mic", 5),
    "1TYYOw-815A": ("MAMA 2025 Golden (PHARITA/AHYEON/RORA)", 5),
    "hSgMTFImB7c": ("Ahyeon - vampire Limousine Service", 5),
    "e3U5Cz_ZASU": ("4K Problem World Tour CHOOM", 4),
    "ItDZsiOhG6M": ("4K MOON fancam MCOUNTDOWN", 4),
    "OMeeqIge53E": ("4K CHOOM fancam Inkigayo", 4),
    "6BVnhqQ28Vw": ("4K SUGAR HONEY ICE TEA fancam", 4),
    "8l5q7ZmZN-s": ("4K PSYCHO fancam tour Seoul", 4),
    # documentary
    "UESsLN8i63w": ("Last Evaluation Individual Vocal Mission", 12),
    "hCgZqFscMp0": ("Last Evaluation EP.1", 15),
    "Gi0ezbc0OwU": ("Last Evaluation EP.8 debut announcement", 20),
    "6ha4zBqRkUE": ("Full interview (Last Evaluation/DRIP talk)", 20),
    "Kxb0aUqmex0": ("Last Evaluation BTS #2", 6),
    "YGG3936Bt2c": ("Last Evaluation BTS #3", 6),
    "Am2NBfQ3I2g": ("Last Evaluation BTS #4", 6),
}

meta = {}
for vid, (label, every) in SOURCES.items():
    p = f"{DL}/{vid}.mp4"
    if not os.path.exists(p):
        print("MISSING", vid); continue
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,r_frame_rate",
                        "-show_entries", "format=duration,size",
                        "-of", "json", p], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    dur = float((j.get("format") or {}).get("duration") or 0)
    st = (j.get("streams") or [{}])[0]
    w, h = st.get("width"), st.get("height")
    meta[vid] = {"label": label, "duration": round(dur, 2), "w": w, "h": h,
                 "size_mb": round(os.path.getsize(p) / 1e6, 1), "path": p}
    # contact sheet: fps=1/every, scaled tiles, grid 6 wide
    n = int(dur // every) + 1
    cols = 6
    rows = (n + cols - 1) // cols
    tw, th = 320, 180
    out = f"{SHEETS}/{vid}.jpg"
    vf = (f"fps=1/{every},scale={tw}:{th},"
          f"drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6,"
          f"tile={cols}x{rows}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p, "-vf", vf,
                    "-frames:v", "1", "-q:v", "3", out], capture_output=True)
    print(f"{vid} {w}x{h} {dur:.0f}s {meta[vid]['size_mb']}MB -> sheet {n} frames")

json.dump(meta, open(f"{SHEETS}/meta.json", "w"), indent=1)
print("META WRITTEN", len(meta))
