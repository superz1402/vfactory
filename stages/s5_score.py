#!/usr/bin/env python3
"""Stage 5 (smart): synthesized cinematic score, exact timeline duration.

Zero-licensing synth bed (A minor): detuned drones + slow tremolo + filtered
air, gentle pulse. Narration is mixed on top in stage 6 (sidechain duck).
Output: <run>/05_music/score.wav
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def sh(cmd, timeout=300):
    import os as _os
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(p.pid), 15)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=8)
        except Exception:
            out, err = "", ""
        return -9, out or "", err or ""


def run(run_dir):
    tl = json.load(open(os.path.join(run_dir, "04_smart", "timeline.json")))
    dur = tl["video_total"]
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    score = os.path.join(out_dir, "score.wav")
    fade_out_start = max(0.0, dur - 5.0)
    fc = (
        "sine=frequency=55:duration={d},"
        "sine=frequency=110:duration={d},"
        "sine=frequency=164.81:duration={d},"
        "sine=frequency=220.5:duration={d},"
        "anoisesrc=color=brown:duration={d}:amplitude=0.05,"
        "sine=frequency=440:duration={d}"
    ).format(d=dur)
    graph = (
        "[0]volume=0.50,tremolo=f=0.15:d=0.35[drone];"
        "[1]volume=0.26,tremolo=f=0.11:d=0.45[sub];"
        "[2]volume=0.10,tremolo=f=0.10:d=0.50[fifth];"
        "[3]volume=0.09,tremolo=f=0.10:d=0.60[pad];"
        "[4]lowpass=f=400,volume=0.13[air];"
        "[5]volume=0.05,tremolo=f=0.5:d=0.8,highpass=f=2000,ebur128=metadata=0[sparkle];"
        "[drone][sub][fifth][pad][air]amix=inputs=5:duration=longest:normalize=0[base];"
        "[base][sparkle]amix=inputs=2:duration=first:normalize=0[mix];"
        "[mix]lowpass=f=1600,aecho=0.7:0.6:311|433:0.25|0.18,"
        "apulsator=hz=0.08:width=0.6,"
        "afade=t=in:d=3,afade=t=out:st={fo}:d=5,"
        "aformat=channel_layouts=stereo,aresample=48000[out]"
    ).format(fo=fade_out_start)
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", "sine=frequency=55:duration=%s" % dur,
           "-f", "lavfi", "-i", "sine=frequency=110:duration=%s" % dur,
           "-f", "lavfi", "-i", "sine=frequency=164.81:duration=%s" % dur,
           "-f", "lavfi", "-i", "sine=frequency=220.5:duration=%s" % dur,
           "-f", "lavfi", "-i", "anoisesrc=color=brown:duration=%s:amplitude=0.05" % dur,
           "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % dur,
           "-filter_complex", graph, "-map", "[out]", "-ar", "48000", score]
    rc, _, err = sh(cmd, timeout=240)
    if rc != 0:
        raise RuntimeError(f"score synth failed: {err[-300:]}")
    json.dump({"kind": "synth_cinematic_am", "duration": dur, "file": score},
              open(os.path.join(out_dir, "05_music.json"), "w"), indent=1)
    print(f"score: {score} ({dur:.2f}s)")
    return score


if __name__ == "__main__":
    run(sys.argv[1])
