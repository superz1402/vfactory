#!/usr/bin/env python3
"""Dense verification sheets for planned cut windows."""
import os, subprocess

DL = "/home/z/my-project/ytdl-agent/downloads"
OUT = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3/verify"
os.makedirs(OUT, exist_ok=True)

# (video, start, end, step, label)
WINS = [
    ("UESsLN8i63w", 720, 882, 5, "dangerously_seg"),   # Ahyeon Dangerously 12:00-14:42
    ("hCgZqFscMp0", 250, 270, 3, "ep1_aerial2"),        # 4:10-4:30 night city
    ("hCgZqFscMp0", 955, 980, 3, "ep1_lineup"),         # 15:55-16:20 lineup wall
    ("hCgZqFscMp0", 375, 400, 3, "ep1_choice37"),       # 6:15-6:40 practice/studio
    ("Gi0ezbc0OwU", 1255, 1290, 4, "ep8_lineup"),       # 20:55-21:30 lineup blue
    ("MsOOG4Q5HvQ", 130, 160, 3, "monster_close"),      # 2:10-2:40 close vocal
    ("1TYYOw-815A", 88, 116, 3, "mama_y"),              # 1:28-1:56 solo+crowd
    ("e3U5Cz_ZASU", 118, 142, 3, "problem_tail"),       # 1:58-2:22 solo blue
    ("hSgMTFImB7c", 178, 200, 3, "vampire_end"),        # 2:58-3:20 ending
    ("OMeeqIge53E", 30, 60, 4, "choom_fancam"),
    ("8l5q7ZmZN-s", 20, 50, 4, "psycho_fancam"),
    ("ItDZsiOhG6M", 96, 120, 4, "moon_fancam"),
]

for vid, a, b, step, label in WINS:
    p = f"{DL}/{vid}.mp4"
    n = (b - a) // step + 1
    cols = 6
    rows = (n + cols - 1) // cols
    vf = (f"fps=1/{step},scale=320:180,"
          f"drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6,"
          f"tile={cols}x{rows}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(a), "-i", p,
                    "-t", str(b - a), "-vf", vf, "-frames:v", "1", "-q:v", "3",
                    f"{OUT}/{label}.jpg"], capture_output=True)
    print(label, "ok")
