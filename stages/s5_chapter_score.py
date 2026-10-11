#!/usr/bin/env python3
"""Stage 5: background music — real-instrument structured scores (v2).

Engine: lib/score.py on top of the lemomo-ai/lemo-opuscar sampler (MIT) with
CC0/CC-BY sample libraries (VSCO2CE, VCSL, Salamander). Documentary arcs get
intro/body/climax dynamics, act stingers and an outro resolve — no more static
drone loops. Falls back to the legacy sine bed only if samples are missing.

Outputs 05_music.json:
  scene mode:  {engine, style, path, duration, credits}
  chapter mode:{engine, style, beds: {chapter_id: path}, credits}
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import score  # noqa: E402


def legacy_synth(run_dir, total_dur, mood):
    """Old sine-drone bed (fallback when sample libraries are absent)."""
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    dur = int(total_dur + 2)
    freqs = [(55, 0.55, 0.15, 0.35), (110, 0.30, 0.11, 0.45),
             (164.81, 0.12, 0.10, 0.50), (220.5, 0.10, 0.10, 0.60)]
    if mood != "dark":
        freqs = [(65.41, 0.50, 0.15, 0.35), (130.81, 0.28, 0.11, 0.45),
                 (196.00, 0.14, 0.10, 0.50), (261.63, 0.12, 0.10, 0.60)]
    inputs, chains, names = [], [], ["drone", "sub", "fifth", "pad"]
    for idx, (f, vol, tf, td) in enumerate(freqs):
        inputs += ["-f", "lavfi", "-i", f"sine=frequency={f}:duration={dur}"]
        chains.append(f"[{idx}]volume={vol},tremolo=f={tf}:d={td}[{names[idx]}]")
    inputs += ["-f", "lavfi", "-i", f"anoisesrc=color=brown:duration={dur}:amplitude=0.05"]
    chains.append(f"[{len(freqs)}]lowpass=f=400,volume=0.15[air]")
    mix_in = "".join(f"[{n}]" for n in names) + "[air]"
    fc = (";".join(chains) + ";" + mix_in +
          "amix=inputs=5:duration=longest:normalize=0,"
          "lowpass=f=900,aecho=0.7:0.6:311|433:0.25|0.18,"
          f"apulsator=hz=0.08:width=0.6,afade=t=in:d=4,"
          f"afade=t=out:st={max(dur - 6, 1)}:d=6,"
          "aformat=channel_layouts=stereo[bed]")
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                          ["-filter_complex", fc, "-map", "[bed]", "-ar", "48000", bed],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"bed synth failed: {proc.stderr.decode()[-400:]}")
    return bed


def samples_available():
    idx = os.path.join(os.path.dirname(__file__), "..", "lib", "audio",
                       "instruments", "index.json")
    return os.path.exists(idx)


def run(run_dir, total_dur, mood=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    style = topic.get("style", "documentary")
    music_style = style if style in score.STYLES else \
        ("documentary" if style in ("documentary", "cinematic", "dark") else "hype")

    script_path = os.path.join(run_dir, "02_script.json")
    chapters = []
    if os.path.exists(script_path):
        chapters = json.load(open(script_path)).get("chapters") or []

    timings_path = os.path.join(run_dir, "03_timings.json")
    if chapters and os.path.exists(timings_path):
        # ---- chapter mode: one bed per chapter ----
        audio = {t["id"]: t["audio"] for t in
                 json.load(open(timings_path))["timings"]}
        secs = []
        for i, ch in enumerate(chapters):
            a = audio.get(ch["id"], 60.0)
            secs.append({"id": ch["id"], "dur": a + 1.2,
                         "intensity": score.arc_intensity(
                             ch.get("role", "body"), i, len(chapters)),
                         "stinger": i > 0})
        res = score.compose_score(secs, music_style, out_dir,
                                  seed=abs(hash(topic["topic"])) % 10000)
        json.dump({"engine": "sampler-v2", "style": music_style,
                   "beds": res["beds"], "credits": res["credits"],
                   "duration": sum(s["dur"] for s in secs)},
                  open(os.path.join(run_dir, "05_music.json"), "w"),
                  ensure_ascii=False, indent=1)
        return res["beds"]

    # ---- scene mode: single continuous bed ----
    if samples_available():
        secs = [{"id": 1, "dur": float(total_dur) + 1.0,
                 "intensity": 0.58, "stinger": False}]
        res = score.compose_score(secs, music_style, out_dir,
                                  seed=abs(hash(topic["topic"])) % 10000)
        bed = res["beds"]["1"]
        json.dump({"engine": "sampler-v2", "style": music_style,
                   "path": bed, "duration": total_dur,
                   "credits": res["credits"]},
                  open(os.path.join(run_dir, "05_music.json"), "w"),
                  ensure_ascii=False, indent=1)
        return bed

    mood = mood or ("dark" if style in ("documentary", "cinematic", "dark") else "bright")
    bed = legacy_synth(run_dir, total_dur, mood)
    json.dump({"engine": "legacy-synth", "style": mood, "path": bed,
               "duration": total_dur, "credits": ""},
              open(os.path.join(run_dir, "05_music.json"), "w"),
              ensure_ascii=False, indent=1)
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
