#!/usr/bin/env python3
"""tools/trailer.py — cut a release trailer from a finished vfactory run.

usage:
  python3 tools/trailer.py <run_dir> [--dur 50] [--out trailer.mp4]
      [--voice edge:en-GB-RyanNeural]

Structure (mortiflix-inspired grammar, 2026-10-11):
  cold open (VO hook starts over chapter-1 visuals, after its title card)
  -> montage (one beat per chapter, spread 40-55% in to dodge chapter cards)
  -> climax burst (quick cuts from climax/turning_point chapters)
  -> TITLE CARD (animated alpha + whoosh/thump)
  -> two closing beats -> END CARD ("watch the full film").

Audio: chapter-1 bed trimmed/looped to length, VO hook re-synthesized from the
script's OWN narration (never stock audio), bed ducked under VO (ASPLIT LAW),
whoosh on the title card, loudnorm I=-14. Output: <run_dir>/trailer.mp4.
"""
import argparse
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DIP = 0.25  # micro dip-to-black between beats (trailer grammar)


def probe_size(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "json",
                        path], capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    return st["width"], st["height"]


def pick_beats(script, timeline, dur_target):
    """One beat per chapter + climax burst; drop middle beats if too long."""
    starts = {c["id"]: c["start"] for c in timeline["chapters"]}
    vdurs = {c["id"]: c["video"] for c in timeline["chapters"]}
    chs = script["chapters"]
    beats = []
    # cold open: after ch1's own title card (card window ends ~4.6s)
    beats.append({"id": 1, "at": starts.get(1, 0.0) + 5.2, "dur": 5.0})
    climax = [c for c in chs if c.get("role") in ("climax", "turning_point")]
    mids = [c for c in chs if c not in climax and c["id"] != chs[-1]["id"]
            and c["id"] != 1]
    est = 5.0 + 2.8 * len(mids) + 3.6 * len(climax) + 3.0 + 7.0
    while est > dur_target and len(mids) > 1:  # thin evenly
        mids.pop(len(mids) // 2)
        est = 5.0 + 2.8 * len(mids) + 3.6 * len(climax) + 3.0 + 7.0
    for c in mids:
        cid = c["id"]
        beats.append({"id": cid, "at": starts[cid] + vdurs[cid] * 0.45,
                      "dur": 2.8})
    for c in climax:  # burst: two fast cuts
        cid = c["id"]
        beats += [{"id": cid, "at": starts[cid] + vdurs[cid] * 0.30, "dur": 1.9},
                  {"id": cid, "at": starts[cid] + vdurs[cid] * 0.62, "dur": 1.7}]
    last = chs[-1]["id"]
    beats.append({"id": last, "at": starts[last] + vdurs[last] * 0.5,
                  "dur": 3.0})
    return beats


def render_slice(final, at, dur, W, H, out):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-t", f"{dur:.2f}",
         "-i", final, "-vf",
         f"scale={W}:{H},fade=t=in:d={DIP},"
         f"fade=t=out:st={max(dur - DIP, 0):.2f}:d={DIP},format=yuv420p",
         "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", out],
        capture_output=True, timeout=600, check=True)
    return out


def render_card(text, sub, dur, W, H, out):
    tf, sf = out + ".t.txt", out + ".s.txt"
    open(tf, "w").write(text[:40])
    open(sf, "w").write(sub[:48])
    fs = max(int(H * 0.085), 40)
    ss = max(int(H * 0.035), 20)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=black:s={W}x{H}:d={dur:.2f}:r=30", "-vf",
         f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={fs}"
         f":fontcolor=white:x=(w-tw)/2:y='(h-th)/2-24+16*clip(1-(t-0.4)/0.7,0,1)'"
         f":alpha='min(1,max(0,(t-0.4)/0.5))'"
         f",drawtext=fontfile={FONT}:textfile={sf}:fontsize={ss}"
         f":fontcolor=0xB9B9C9:x=(w-tw)/2:y='(h-th)/2+{int(fs*0.9)}'"
         f":alpha='min(1,max(0,(t-1.0)/0.6))'"
         f",format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", out],
        capture_output=True, timeout=300, check=True)
    os.remove(tf)
    os.remove(sf)
    return out


def vo_hook_text(script, max_words=24):
    """First sentence(s) of the cold open, capped — the film's own words."""
    raw = " ".join(script["chapters"][0]["narration"].split())
    sents, cur = [], ""
    for s in raw.split(". "):
        cand = (cur + " " + s).strip()
        if len(cand.split()) > max_words and cur:
            break
        cur = cand
    if not cur.endswith("."):
        cur += "."
    return cur


def build_audio(run_dir, T, card_start, out_wav, voice):
    from lib import voice as vlib
    from lib.audio import sfx as sfxlib
    import numpy as np
    import scipy.io.wavfile as wavfile
    music = json.load(open(os.path.join(run_dir, "05_music.json")))
    bed = music["beds"]["1"]
    sfx_dir = os.path.join(run_dir, "06_final", "sfx")
    os.makedirs(sfx_dir, exist_ok=True)

    def mk(path, buf):
        wavfile.write(path, sfxlib.SR,
                      (np.clip(buf, -1, 1) * 32767).astype(np.int16))
        return path

    whoosh = os.path.join(sfx_dir, "trailer_whoosh.wav")
    if not os.path.exists(whoosh):
        x = sfxlib.whoosh(0.9, 1.0)
        b = np.zeros((len(x), 2), dtype=np.float32)
        b[:, 0], b[:, 1] = x, x
        mk(whoosh, b)
    thump = os.path.join(sfx_dir, "trailer_thump.wav")
    if not os.path.exists(thump):
        x = sfxlib.thump(1.0, 62)
        b = np.zeros((len(x), 2), dtype=np.float32)
        b[:, 0], b[:, 1] = x, x
        mk(thump, b)

    hook = vo_hook_text(json.load(open(os.path.join(run_dir, "02_script.json"))))
    vo_wav = os.path.join(run_dir, "06_final", "trailer_vo.wav")
    meta = vlib.synth(hook, vo_wav, voice=voice)
    print(f"  VO hook ({len(hook.split())}w, {meta['duration']:.1f}s): {hook}")

    fc = (
        f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"aloop=loop=-1:size=2e9,atrim=0:{T:.2f},volume=0.9[bed];"
        f"[1:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"adelay=500|500,volume=1.15,apad=whole_dur={T:.2f}[nar];"  # pad: sidechaincompress stops at VO EOF otherwise
        f"[2:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"adelay={int(card_start * 1000)}|{int(card_start * 1000)},"
        f"volume=0.5[wh];"
        f"[3:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"adelay={int((card_start + 0.55) * 1000)}|"
        f"{int((card_start + 0.55) * 1000)},volume=0.45[th];"
        f"[nar]asplit=2[nar1][nar2];"
        f"[bed][nar1]sidechaincompress=threshold=0.02:ratio=9:attack=30"
        f":release=600[ducked];"
        f"[nar2][ducked][wh][th]amix=inputs=4:duration=longest:normalize=0[mix];"
        f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{T:.2f},"
        f"afade=t=out:st={max(T - 1.2, 0):.2f}:d=1.2[aout]")
    script = out_wav + ".txt"
    with open(script, "w") as fh:
        fh.write(fc)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", bed, "-i", vo_wav,
         "-i", whoosh, "-i", thump, "-filter_complex_script", script,
         "-map", "[aout]", "-ar", "48000", out_wav],
        capture_output=True, timeout=600, check=True)
    os.remove(script)
    return out_wav


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--dur", type=int, default=50)
    ap.add_argument("--out", default=None)
    ap.add_argument("--voice", default="edge:en-GB-RyanNeural")
    args = ap.parse_args()
    run_dir = args.run_dir
    final = os.path.join(run_dir, "final.mp4")
    assert os.path.exists(final), "run has no final.mp4"
    out = args.out or os.path.join(run_dir, "trailer.mp4")

    script = json.load(open(os.path.join(run_dir, "02_script.json")))
    timeline = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    W, H = probe_size(final)
    beats = pick_beats(script, timeline, args.dur)
    print(f"trailer plan: {len(beats)} beats, {W}x{H}")

    work = os.path.join(run_dir, "06_final", "trailer")
    os.makedirs(work, exist_ok=True)
    clips, T = [], 0.0
    for n, b in enumerate(beats):
        cp = os.path.join(work, f"beat_{n:02d}.mp4")
        if not (os.path.exists(cp) and os.path.getsize(cp) > 10000):
            render_slice(final, b["at"], b["dur"], W, H, cp)
        clips.append(cp)
        T += b["dur"]
    card_dur, end_dur = 3.6, 3.0
    title = script.get("title", "the film").upper()
    cp = os.path.join(work, "card_title.mp4")
    if not (os.path.exists(cp) and os.path.getsize(cp) > 10000):
        render_card(title, "A VFACTORY FILM", card_dur, W, H, cp)
    clips.append(cp)
    cp = os.path.join(work, "card_end.mp4")
    if not (os.path.exists(cp) and os.path.getsize(cp) > 10000):
        render_card("WATCH THE FULL FILM", "link in description",
                    end_dur, W, H, cp)
    clips.append(cp)
    T += card_dur + end_dur
    card_start = T - end_dur - card_dur  # title card position on timeline

    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    vout = out + ".v.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", lst, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", "30", vout],
        capture_output=True, timeout=1200, check=True)

    awav = os.path.join(run_dir, "06_final", "trailer_mix.wav")
    if not os.path.exists(awav):
        build_audio(run_dir, T, card_start, awav, args.voice)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", vout, "-i", awav,
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-shortest", "-movflags", "+faststart", out],
        capture_output=True, timeout=600, check=True)
    os.remove(vout)
    print(f"trailer done: {out} ({T:.1f}s, "
          f"{os.path.getsize(out) / 1048576:.1f} MB)", flush=True)
    sys.stdout.flush()
    os._exit(0)  # edge-tts asyncio can hang interpreter exit; files are flushed


if __name__ == "__main__":
    main()
