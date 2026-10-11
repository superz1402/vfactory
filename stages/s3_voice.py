#!/usr/bin/env python3
"""Stage 3: narration TTS per beat/scene/chapter -> WAVs + measured timings.

Voice selection via 00_topic.json "voice": preset name (doc_male_us...),
provider string (edge:en-GB-RyanNeural / zai:tongtong) or empty = default
(zai:tongtong — identical to v2.1 behavior).

Word-level timestamps stored per unit (exact for edge, approximated for zai)
and cached in a .words sidecar so resume keeps them. The long-form path uses
word timings for entity-aligned cuts (lib/align.py) and subtitles (lib/srt.py).
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import voice  # noqa: E402
from lib.voice import audio_len  # noqa: E402


def run(run_dir, speed=1.0):
    out_dir = os.path.join(run_dir, "03_voice")
    os.makedirs(out_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    vname = voice.resolve(topic.get("voice"))

    if plan.get("chapters"):
        units, kind = plan["chapters"], "chapter"
    elif plan.get("beats"):
        units, kind = plan["beats"], "beat"
    else:
        units, kind = plan.get("scenes", []), "scene"
    timings, failures = [], []
    for u in units:
        uid = u["id"]
        base = os.path.join(out_dir, f"{kind}_{uid:02d}")
        wav, side = base + ".wav", base + ".words.json"
        words = []
        if not (os.path.exists(wav) and os.path.getsize(wav) > 1000):
            r = voice.synth(u["narration"], wav, voice=vname, speed=speed)
            if not r or not os.path.exists(wav) or os.path.getsize(wav) < 1000:
                failures.append(uid)
                continue
            json.dump(r["words"], open(side, "w"), ensure_ascii=False)
            words = r["words"]
        elif os.path.exists(side):
            words = json.load(open(side))
        timings.append({"id": uid, "wav": wav, "audio": round(audio_len(wav), 2),
                        "words": words, "kind": kind})
    if failures:
        raise RuntimeError(f"TTS failed for {kind}s {failures}")
    out = {"voice": vname, "speed": speed, "kind": kind, "units": timings,
           "timings": timings}  # "timings" kept for v2.1 consumers
    json.dump(out, open(os.path.join(run_dir, "03_timings.json"), "w"),
              ensure_ascii=False, indent=1)
    return timings


if __name__ == "__main__":
    run_dir = os.path.dirname(sys.argv[1]) if len(sys.argv) > 1 else "."
    d = json.load(open(os.path.join(run_dir, "00_topic.json")))
    run(run_dir, d.get("tts_speed", 1.0))
    print("voice done")
