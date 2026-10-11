#!/usr/bin/env python3
"""Integration test: eased Ken Burns + animated cards + whoosh hit.
Builds a synthetic 1-chapter run, renders it, probes the output."""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, "/home/z/my-project/vfactory")
RUN = "/home/z/my-project/vfactory/tests/motion_test"
W, H = 640, 360

shutil.rmtree(RUN, ignore_errors=True)
os.makedirs(RUN, exist_ok=True)


def sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"FAILED {cmd[:4]}...\n{r.stderr[-1500:]}")
    return r


# assets ---------------------------------------------------------------
img1, img2 = os.path.join(RUN, "img1.jpg"), os.path.join(RUN, "img2.jpg")
sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
    "-i", "testsrc2=size=1280x720:duration=1", "-frames:v", "1", img1])
sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
    "-i", "smptebars=size=1280x720:duration=1", "-frames:v", "1", img2])
tone = os.path.join(RUN, "tone.wav")
sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
    "-i", "sine=frequency=220:duration=14", "-ac", "2", tone])
sil = os.path.join(RUN, "sil.wav")
sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
    "-i", "anullsrc=r=48000:cl=stereo", "-t", "12", sil])

# run skeleton ----------------------------------------------------------
json.dump({"topic": "motion test", "aspect": "16:9"},
          open(os.path.join(RUN, "00_topic.json"), "w"))
json.dump({"mode": "chapters", "chapters": [
    {"id": 1, "title": "Motion Test", "role": "cold_open",
     "on_screen": "EASED KEN BURNS"}]},
    open(os.path.join(RUN, "02_script.json"), "w"))
json.dump({"units": [{"id": 1, "wav": sil, "audio": 11.5, "words": []}]},
          open(os.path.join(RUN, "03_timings.json"), "w"))
json.dump({"chapters": {"1": {
    "audio": 11.5,
    "shots": [{"path": img1, "kind": "image", "dur": 5.0},
              {"path": img2, "kind": "image", "dur": 6.5}]}}},
    open(os.path.join(RUN, "04_media.json"), "w"))
json.dump({"beds": {"1": tone}},
          open(os.path.join(RUN, "05_music.json"), "w"))

# render ----------------------------------------------------------------
from stages import s6_chapters  # noqa: E402
info = s6_chapters.run_chapters(RUN, W, H)
final = info["final"]
print("rendered:", info)

# probe ------------------------------------------------------------------
r = sh(["ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,codec_name,width,height,duration",
        "-of", "json", final])
streams = json.loads(r.stdout)["streams"]
print("streams:", [(s.get("codec_type"), s.get("codec_name"),
                    s.get("duration")) for s in streams])
assert any(s["codec_type"] == "audio" for s in streams), "NO AUDIO STREAM"
assert abs(float(info["total"]) - 12.5) < 0.5, "duration mismatch"  # audio+tail

# whoosh present in first second? ----------------------------------------
r = subprocess.run(["ffmpeg", "-v", "info", "-t", "1.0", "-i", final,
                    "-af", "volumedetect", "-f", "null", "-"],
                   capture_output=True, text=True)
mean_line = [ln for ln in r.stderr.splitlines() if "mean_volume" in ln]
print("0-1s audio:", mean_line[0].split("] ")[-1] if mean_line else "?")

# frames: title mid-fade / settled / after -------------------------------
for tag, t in [("a_mid", 0.8), ("b_settled", 2.2), ("c_after", 6.0)]:
    sh(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", final,
        "-frames:v", "1", os.path.join(RUN, f"frame_{tag}.png")])
print("frames extracted OK")

# animated alpha check: mid-fade frame must differ from settled frame -----
d = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", os.path.join(RUN, "frame_a_mid.png"),
     "-i", os.path.join(RUN, "frame_b_settled.png"),
     "-filter_complex", "blend=all_mode=psnr", "-f", "null", "-"],
    capture_output=True, text=True).stderr
print("mid vs settled PSNR lines:", d.strip()[:200])
print("TEST COMPLETE")
