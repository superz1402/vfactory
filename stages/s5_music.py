#!/usr/bin/env python3
"""Stage 5 v2: structured music bed — numpy synthesis, zero licensing risk.

Progression: Am - F - C - G (A-minor i-VI-III-VII), 8s per chord, looping.
Layers: warm pad (additive harmonics + slow attack), sub root, piano-ish pluck
arpeggio (decaying harmonics), air (filtered noise), soft pulse for momentum.
Dynamics: sparse intro (14s), arpeggio enters at 14s, swell every ~110s,
global fade-in/out. Mixed under VO in s6 via sidechain ducking."""
import json, os, subprocess, sys

import numpy as np

SR = 48000
CHORDS = {  # (root_hz, chord tones)
    "Am": (110.00, [110.00, 164.81, 220.00, 261.63]),
    "F":  (87.31,  [87.31, 130.81, 174.61, 220.00]),
    "C":  (65.41,  [130.81, 164.81, 196.00, 261.63]),
    "G":  (98.00,  [98.00, 146.83, 196.00, 246.94]),
}
PROG = ["Am", "F", "C", "G"]
CHORD_SEC = 8.0


def env_ad(n, attack, decay_tau):
    t = np.arange(n) / SR
    e = np.minimum(t / max(attack, 1e-3), 1.0) * np.exp(-np.maximum(t - attack, 0) / decay_tau)
    return e


def pad_note(freq, n, detune=0.15):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for h, amp in ((1, 1.0), (2, 0.38), (3, 0.18), (4, 0.09)):
        vib = 1 + 0.0015 * np.sin(2 * np.pi * 0.13 * t * h)
        out += amp * np.sin(2 * np.pi * freq * h * vib * t)
        out += amp * 0.6 * np.sin(2 * np.pi * freq * h * (1 + detune / 100) * t)
    return out / 3.2


def pluck(freq, n):
    t = np.arange(n) / SR
    body = (np.sin(2 * np.pi * freq * t) +
            0.5 * np.sin(2 * np.pi * freq * 2 * t) +
            0.22 * np.sin(2 * np.pi * freq * 3 * t))
    return body * env_ad(n, 0.004, 0.55)


def build(total):
    n_total = int(total * SR)
    mixL = np.zeros(n_total)
    mixR = np.zeros(n_total)

    # --- chord pad + sub (looped progression) ---
    chord_n = int(CHORD_SEC * SR)
    tpos = 0
    ci = 0
    while tpos < n_total:
        name = PROG[ci % len(PROG)]
        root, tones = CHORDS[name]
        n = min(chord_n + int(1.5 * SR), n_total - tpos)  # 1.5s overlap blend
        seg = np.zeros(n)
        for f in tones:
            seg += pad_note(f, n)
        seg /= len(tones)
        swell = np.ones(n)
        sw = int(0.9 * SR)
        swell[:sw] = np.linspace(0, 1, sw)          # soft attack per chord
        mixL[tpos:tpos + n] += seg * swell
        mixR[tpos:tpos + n] += seg * swell[::-1] * 0.9   # width via inverse env
        tpos += chord_n
        ci += 1
    pad_gain = 0.16
    mixL *= pad_gain
    mixR *= pad_gain

    # sub root (continuous, follows progression roots at low level)
    tpos = 0
    ci = 0
    while tpos < n_total:
        root = CHORDS[PROG[ci % len(PROG)]][0] / 2
        n = min(chord_n, n_total - tpos)
        t = np.arange(n) / SR
        sub = 0.5 * np.sin(2 * np.pi * root * t) * np.minimum(t / 0.6, 1)
        mixL[tpos:tpos + n] += sub * 0.20
        mixR[tpos:tpos + n] += sub * 0.20
        tpos += chord_n
        ci += 1

    # --- pluck arpeggio (enters at 14s) ---
    tpos = int(14 * SR)
    step = 0.0            # running 16th position
    eighth = CHORD_SEC / 8
    ci = 0
    rng = np.random.default_rng(2026)
    while tpos < n_total:
        name = PROG[int((tpos / SR) / CHORD_SEC) % len(PROG)]
        _, tones = CHORDS[name]
        pattern = [0, 2, 1, 3, 2, 3, 1, 2]
        for k in range(8):
            if tpos >= n_total:
                break
            f = tones[pattern[k]] * (2 if k % 3 == 0 else 1)
            n = int(eighth * SR * 2)
            e = min(1.0, (tpos / SR) / 60.0)           # plucks grow over first minute
            v = 0.11 * e * (0.8 + 0.4 * rng.random())
            pn = pluck(f, n) * v
            pan = 0.5 + 0.35 * np.sin(k * 1.3)
            end = min(tpos + n, n_total)
            mixL[tpos:end] += pn[:end - tpos] * (1 - pan)
            mixR[tpos:end] += pn[:end - tpos] * pan
            tpos += int(eighth * SR)
    # --- pulse (soft momentum, every 2 beats) ---
    tpos = int(30 * SR)
    while tpos < n_total:
        n = int(0.5 * SR)
        t = np.arange(n) / SR
        kick = np.sin(2 * np.pi * 52 * t) * np.exp(-t / 0.06) * 0.16
        end = min(tpos + n, n_total)
        mixL[tpos:end] += kick[:end - tpos]
        mixR[tpos:end] += kick[:end - tpos]
        tpos += int(2.0 * SR)

    # --- air ---
    air = rng.normal(0, 1, n_total)
    # cheap lowpass: cumulative smoothing
    k = 96
    air = np.convolve(air, np.ones(k) / k, mode="same")
    mixL += air * 0.05
    mixR += np.roll(air, 480) * 0.05

    # --- global dynamics: fade in, swells every ~110s, fade out ---
    t = np.arange(n_total) / SR
    dyn = np.ones(n_total)
    swell_period = 110.0
    dyn += 0.22 * np.sin(2 * np.pi * t / swell_period - np.pi / 2)
    fade_in = np.minimum(t / 5.0, 1.0)
    fade_out = np.clip((total - t) / 7.0, 0, 1)
    mixL *= dyn * fade_in * fade_out
    mixR *= dyn * fade_in * fade_out

    # normalize to -20 dBFS peak-ish (ducking + loudnorm handle the rest)
    peak = max(np.abs(mixL).max(), np.abs(mixR).max(), 1e-9)
    g = 0.1 / peak
    return np.stack([mixL * g, mixR * g], axis=1)


def run(run_dir, total_dur, mood=None):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    pcm = (np.clip(build(total_dur + 2), -1, 1) * 32767).astype(np.int16)
    import wave
    with wave.open(bed, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    json.dump({"mood": "aminor_progression", "path": bed,
               "duration": total_dur + 2},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    return bed


if __name__ == "__main__":
    run_dir = sys.argv[1]
    t = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    run(run_dir, t["total"])
    print("music done")
