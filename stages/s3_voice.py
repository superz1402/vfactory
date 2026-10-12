#!/usr/bin/env python3
"""Stage 3 v2: narration per scene.

Engine (in order):
  1. edge-tts  — natural neural voice, no rate limit (default; documentary voice)
  2. z-ai tts  — fallback (voice tongtong/jam), heavier rate limits

Outputs per-scene WAV (48k mono -> stereo-safe) + measured timings."""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

EDGE_VOICE = "en-US-AndrewNeural"     # documentary gravitas; alt: en-US-GuyNeural
EDGE_RATE = "-4%"                     # slightly slower = gravitas
ZAI_VOICE = "jam"                     # proven documentary fallback voice


def _run(cmd, timeout=300):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def tts_edge(text, wav, voice=EDGE_VOICE, rate=EDGE_RATE):
    mp3 = wav + ".src.mp3"
    r = _run(["edge-tts", "--voice", voice, f"--rate={rate}",
              "--text", text, "--write-media", mp3])
    if r.returncode != 0 or not (os.path.exists(mp3) and os.path.getsize(mp3) > 2000):
        return False
    c = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3,
                        "-ar", "48000", "-ac", "2", wav],
                       capture_output=True, timeout=120)
    os.path.exists(mp3) and os.remove(mp3)
    return c.returncode == 0 and os.path.getsize(wav) > 5000


def run(run_dir, speed=1.0):
    out_dir = os.path.join(run_dir, "03_voice")
    os.makedirs(out_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings, failures, engine_used = [], [], {}
    for sc in plan["scenes"]:
        wav = os.path.join(out_dir, f"scene_{sc['id']:02d}.wav")
        if not (os.path.exists(wav) and os.path.getsize(wav) > 10000):
            ok = tts_edge(sc["narration"], wav)
            if ok:
                engine_used[sc["id"]] = "edge"
            else:
                # z-ai fallback with retry/backoff (rate limits are real)
                for attempt in range(3):
                    ok = zai.tts(sc["narration"], wav, voice=ZAI_VOICE,
                                 speed=speed, fmt="wav")
                    if ok:
                        engine_used[sc["id"]] = "zai"
                        break
                    time.sleep(20 * (attempt + 1))
            if not ok:
                failures.append(sc["id"])
                continue
        timings.append({"id": sc["id"], "wav": os.path.abspath(wav),
                        "audio": round(audio_len(wav), 2)})
    if failures:
        raise RuntimeError(f"voiceover failed for scenes {failures}")
    if not engine_used:
        raise RuntimeError("no narration produced at all")
    json.dump({"voice": "mixed", "edge_voice": EDGE_VOICE,
               "engines": engine_used, "speed": speed, "timings": timings},
              open(os.path.join(run_dir, "03_timings.json"), "w"), indent=1)
    n_edge = sum(1 for v in engine_used.values() if v == "edge")
    print(f"[s3] voice: {n_edge}/{len(timings)} scenes via edge-tts")
    return timings


if __name__ == "__main__":
    run_dir = os.path.dirname(sys.argv[1]) if len(sys.argv) > 1 else "."
    d = json.load(open(os.path.join(run_dir, "00_topic.json")))
    run(run_dir, d.get("tts_speed", 1.0))
    print("voice done")
