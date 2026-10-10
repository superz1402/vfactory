#!/usr/bin/env python3
"""Stage 3: narration TTS per scene -> WAVs + measured timings (ffprobe)."""
import json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

VOICE = "tongtong"


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def run(run_dir, speed=1.0):
    out_dir = os.path.join(run_dir, "03_voice")
    os.makedirs(out_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings, failures = [], []
    for b in plan["beats"]:
        wav = os.path.join(out_dir, f"beat_{b['id']:02d}.wav")
        if not (os.path.exists(wav) and os.path.getsize(wav) > 1000):
            ok = zai.tts(b["narration"], wav, voice=VOICE, speed=speed, fmt="wav")
            if not ok:
                failures.append(b["id"])
                continue
        timings.append({"id": b["id"], "wav": wav, "audio": round(audio_len(wav), 2)})
    if failures:
        raise RuntimeError(f"TTS failed for beats {failures}")
    json.dump({"voice": VOICE, "speed": speed, "timings": timings},
              open(os.path.join(run_dir, "03_timings.json"), "w"), indent=1)
    return timings


if __name__ == "__main__":
    run_dir = os.path.dirname(sys.argv[1]) if len(sys.argv) > 1 else "."
    d = json.load(open(os.path.join(run_dir, "00_topic.json")))
    run(run_dir, d.get("tts_speed", 1.0))
    print("voice done")
