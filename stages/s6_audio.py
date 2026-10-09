#!/usr/bin/env python3
"""Documentary audio builder (v2) — narration J-cuts + ducked real music.

Split out of s6_render for clarity. All filtergraph labels chosen so no
label starts with the letter that ANSI-striped transports eat.
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import music as music_lib  # noqa: E402


def _run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def build_audio(run_dir, beat_starts, total):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    vo_dir = os.path.join(run_dir, "03_voice")

    tracks, delays = [], []
    for t in timings:
        bid = t["id"]
        start = max(0.4, beat_starts.get(bid, 0.0) - 0.25)  # J-cut lead
        ms = int(start * 1000)
        tracks.append(os.path.join(vo_dir, f"beat_{bid:02d}.wav"))
        delays.append(f"adelay={ms}|{ms}")

    mus = music_lib.pick_for_beats(plan["beats"], total)
    music_path = mus["path"] if mus else None

    lines = []
    n = len(tracks)
    for i, (p, d) in enumerate(zip(tracks, delays)):
        lines.append(f"[{i}:a]aformat=sample_rates=48000:channel_layouts=stereo,{d}[v{i}]")
    nar_mix = "".join(f"[v{i}]" for i in range(n))
    lines.append(f"{nar_mix}amix=inputs={n}:normalize=0:dropout_transition=0[nar]")
    lines.append("[nar]acompressor=threshold=0.06:ratio=2.5:attack=8:release=120,"
                 "volume=1.9[narv]")

    inputs = []
    for p in tracks:
        inputs += ["-i", p]

    if music_path:
        inputs += ["-i", music_path]
        lines.append(f"[{n}:a]aformat=sample_rates=48000:channel_layouts=stereo,"
                     f"aloop=loop=-1:size=2000000000,atrim=0:{total+1:.2f},"
                     f"volume=0.85[trackraw]")
        lines.append("[narv]asplit=2[narA][narK]")
        lines.append("[trackraw][narK]sidechaincompress=threshold=0.015:ratio=7:"
                     "attack=45:release=650:makeup=1[trackduck]")
        lines.append(f"[narA][trackduck]amix=inputs=2:normalize=0:dropout_transition=0,"
                     f"afade=t=in:st=0:d=0.8,afade=t=out:st={max(0, total-1.2):.2f}:d=1.2,"
                     f"loudnorm=I=-12.5:TP=-1.2:LRA=9,"
                     f"aformat=sample_rates=48000:channel_layouts=stereo[finalmix]")
        map_label = "[finalmix]"
    else:
        lines.append(f"[narv]afade=t=in:st=0:d=0.6,"
                     f"afade=t=out:st={max(0, total-1.0):.2f}:d=1.0,"
                     f"loudnorm=I=-13:TP=-1.2:LRA=9,"
                     f"aformat=sample_rates=48000:channel_layouts=stereo[finalmix]")
        map_label = "[finalmix]"

    script = os.path.join(run_dir, "audio_fc.txt")
    open(script, "w").write(";\n".join(lines) + "\n")
    out = os.path.join(run_dir, "audio_mix.wav")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats"] + inputs + [
        "-filter_complex_script", script, "-map", map_label,
        "-t", f"{total:.2f}", "-c:a", "pcm_s16le", out]
    r = _run(cmd, timeout=900)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("audio mix failed: " + r.stderr[-500:])
    json.dump({"music": mus["name"] if mus else "",
               "license": mus["license"] if mus else None},
              open(os.path.join(run_dir, "06_music_credit.json"), "w"), indent=1)
    return out
