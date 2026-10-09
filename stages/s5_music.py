#!/usr/bin/env python3
"""Stage 5 (v2): music bed — the artist's REAL song, not a synth.

v1 synthesized sine drones + brown noise: user verdict was "weird sorting
noises". Real documentaries cut to the subject's own music. When the run has
character-verified footage (04_charmedia.json), extract the strongest
sustained music section (usually the chorus) from the MV/scene audio using
an RMS-sustained-energy scan, trim to the narration timeline length, and
write bed.wav. s6 ducks it under narration.

Fallback: legacy synth bed only when no real source exists.
"""
import json, os, subprocess, sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))


def rms_windows(wav_path, win_s=1.0):
    """Per-second RMS of a decoded mono 8 kHz stream."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", wav_path, "-ac", "1", "-ar", "8000",
         "-f", "s16le", "-"], capture_output=True, timeout=300).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    w = int(8000 * win_s)
    n = len(x) // w
    if n == 0:
        return np.array([0.0])
    return np.sqrt((x[: n * w].reshape(n, w) ** 2).mean(axis=1))


def pick_song_segment(src, need_s):
    """Find the `need_s` window with the most sustained musical energy."""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", src],
        capture_output=True, text=True, timeout=60).stdout.strip() or 0)
    if dur < need_s + 4:
        return 0.0, min(dur, need_s)
    rms = rms_windows(src)
    n = len(rms)
    lo, hi = max(1, int(0.05 * n)), max(2, int(0.92 * n))
    need_w = int(np.ceil(need_s))
    med = float(np.median(rms[rms > 0])) if (rms > 0).any() else 1.0
    best_t, best_score = lo, -1.0
    for start in range(lo, min(hi, max(lo + 1, n - need_w))):
        seg = rms[start: start + need_w]
        if len(seg) < need_w:
            break
        energy = float(seg.mean())
        # sustained: penalize near-silent seconds inside the window
        dead = float((seg < 0.12 * med).sum())
        score = energy - 0.8 * (dead / need_w) * energy
        if score > best_score:
            best_score, best_t = score, start
    return float(best_t), min(need_s, dur - best_t - 0.5)


def extract_real_bed(src, need_s, out_wav):
    t0, take = pick_song_segment(src, need_s)
    if take < 8:
        return None
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{take:.2f}",
         "-i", src, "-af",
         f"afade=t=in:d=1.5,afade=t=out:st={max(take - 2.5, 0):.2f}:d=2.5,"
         "aformat=channel_layouts=stereo,aresample=48000",
         "-ar", "48000", "-ac", "2", out_wav],
        capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(out_wav) \
            or os.path.getsize(out_wav) < 100_000:
        return None
    return {"t0": round(t0, 2), "take": round(take, 2)}


def synth_fallback(total_dur, bed, mood):
    """v1 recipe kept only for topics with no real source (rare now)."""
    dur = int(total_dur + 2)
    if mood == "dark":
        layers = [
            ("sine=frequency=55:duration=%d", 0.55, 0.15, 0.35),
            ("sine=frequency=110:duration=%d", 0.30, 0.11, 0.45),
            ("sine=frequency=164.81:duration=%d", 0.12, 0.10, 0.50),
            ("sine=frequency=220.5:duration=%d", 0.10, 0.10, 0.60),
        ]
    else:
        layers = [
            ("sine=frequency=65.41:duration=%d", 0.50, 0.15, 0.35),
            ("sine=frequency=130.81:duration=%d", 0.28, 0.11, 0.45),
            ("sine=frequency=196.00:duration=%d", 0.14, 0.10, 0.50),
            ("sine=frequency=261.63:duration=%d", 0.12, 0.10, 0.60),
        ]
    inputs, chains = [], []
    names = ["drone", "sub", "fifth", "pad"]
    for idx, (s, vol, tf, td) in enumerate(layers):
        inputs += ["-f", "lavfi", "-i", s % dur]
        chains.append(f"[{idx}]volume={vol},tremolo=f={tf}:d={td}[{names[idx]}]")
    ni = len(layers)
    inputs += ["-f", "lavfi", "-i", f"anoisesrc=color=brown:duration={dur}:amplitude=0.05"]
    chains.append(f"[{ni}]lowpass=f=400,volume=0.15[air]")
    fc = (";".join(chains) + ";" + "".join(f"[{n}]" for n in names) + "[air]"
          + "amix=inputs=5:duration=longest:normalize=0,"
          f"lowpass=f=900,afade=t=in:d=4,afade=t=out:st={max(dur - 6, 1)}:d=6,"
          "aformat=channel_layouts=stereo[bed]")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex", fc, "-map", "[bed]", "-ar", "48000", bed],
                   capture_output=True, timeout=300, check=True)


def run(run_dir, total_dur, mood=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    mood = mood or ("dark" if topic.get("style", "documentary") in
                    ("documentary", "cinematic", "dark") else "bright")

    # real song from the subject's own footage
    cm_path = os.path.join(run_dir, "04_charmedia.json")
    bed_src = None
    if os.path.exists(cm_path):
        try:
            bed_src = json.load(open(cm_path)).get("audio_bed")
        except Exception:
            bed_src = None
    if bed_src and os.path.exists(bed_src.get("video", "")):
        need = min(total_dur + 2, 95.0)
        info = extract_real_bed(bed_src["video"], need, bed)
        if info:
            json.dump({"kind": "real_song", "path": bed,
                       "source": bed_src["video"],
                       "segment": info, "mood": mood},
                      open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
            print(f"[s5] real song bed: {os.path.basename(bed_src['video'])} "
                  f"@{info['t0']:.0f}s for {info['take']:.0f}s")
            return bed
        print("[s5] real-bed extraction failed -> synth fallback")
    synth_fallback(total_dur, bed, mood)
    json.dump({"kind": "synth", "path": bed, "mood": mood},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
