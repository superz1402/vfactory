#!/usr/bin/env python3
"""Stage 6 (v2): documentary render engine.

Pipeline: per-shot clips (letterbox + grade + grain + minimal serif text)
-> hard-cut concat -> narration J-cut timeline + ducked real music
-> master loudnorm -12.5 LUFS -> final.mp4.

Grammar implemented (see research/DESIGN_V2.md):
- shots 2.0-6.5s, hard cuts (dissolve only to/from chapter cards)
- 2.39:1 letterbox inside 16:9
- muted saturation, dark gamma, film grain, vignette
- <=1 elegant serif overlay per beat (names/dates/records only)
- animated punch-in on video shots, Ken Burns on stills
- narration leads video by ~0.25s (J-cut), music ducks under voice
"""
import json, os, subprocess, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import music as music_lib  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1920, 1080
CW, CH = 1920, 804          # 2.39:1 content area
BAR = (H - CH) // 2         # 138
FPS = 30
SERIF = "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Regular.ttf"
SERIF_BLACK = "/usr/share/fonts/truetype/noto-serif-sc/NotoSerifSC-Black.ttf"


def _run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# ---------------- timeline ----------------
def build_timeline(run_dir):
    """Absolute start times for every visual event + narration anchors."""
    shots_man = json.load(open(os.path.join(run_dir, "04_shots.json")))
    timings = {t["id"]: t["audio"]
               for t in json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    events, t = [], 0.0
    beat_starts = {}
    for entry in shots_man["beats"]:
        bid = entry["beat_id"]
        if "card" in entry:
            c = dict(entry["card"]); c["start"] = round(t, 2); c["kind"] = "card"
            events.append(c); t += c["dur"]
        beat_starts.setdefault(bid, round(t, 2))
        for s in entry.get("shots", []):
            s = dict(s); s["start"] = round(t, 2); s["beat_id"] = bid
            s["kind"] = "shot"
            events.append(s); t += s["dur"]
    total = round(t, 2)
    json.dump({"events": events, "beat_starts": beat_starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    return events, beat_starts, total


# ---------------- per-shot clips ----------------
def _textfile(run_dir, name, text):
    p = os.path.join(run_dir, "texts", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w", encoding="utf-8").write(text)
    return p


def _grade_chain():
    return ("eq=saturation=0.92:gamma=0.97,"
            "vignette=PI/4.2,"
            "unsharp=5:5:0.35,"
            "noise=alls=4:allf=t+u")


def _letterbox_chain():
    return (f"scale={W}:{CH}:force_original_aspect_ratio=increase,"
            f"crop={W}:{CH},"
            f"pad={W}:{H}:0:{BAR}:black")


def render_shot_clip(run_dir, ev, out_path):
    """Render one normalized clip: 1080p30, letterbox+grade, CRF17."""
    kind = ev.get("kind", "shot")
    dur = ev["dur"]
    if kind == "card":
        tf = _textfile(run_dir, f"card_{ev['start']}.txt", ev.get("text", ""))
        vf = (f"drawtext=fontfile={SERIF}:textfile='{tf}':fontsize=72:"
              f"fontcolor=0xEDEDEF:x=(w-text_w)/2:y=(h-text_h)/2:"
              f"alpha='if(lt(t,0.35),t/0.35,if(gt(t,{dur-0.4}),max(0,({dur}-t)/0.4),1))',"
              f"noise=alls=4:allf=t+u,format=yuv420p")
        cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats",
               "-f", "lavfi", "-i", f"color=c=0x0a0a0c:s={W}x{H}:d={dur}:r={FPS}",
               "-vf", vf, "-t", str(dur), "-an",
               "-c:v", "libx264", "-preset", "fast", "-crf", "19",
               "-video_track_timescale", "15360", out_path]
        r = _run(cmd)
        if r.returncode != 0:
            print(f"  card render err: {r.stderr[-300:]}", flush=True)
        return r.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 10_000

    src = ev["src"]
    if not os.path.exists(src):
        return False
    treat = ev.get("treatment", "flat")

    if ev["type"] == "still":
        d = dur + 0.35
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,"
              f"crop={W*2}:{H*2},"
              f"zoompan=z='1.0+0.11*on/({int(dur*FPS)})':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d={int(d*FPS)}:s={W*2}x{H*2}:fps={FPS},"
              f"scale={W}:{CH},")
        vf += _letterbox_chain() + "," + _grade_chain() + ",format=yuv420p"
        cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats", "-loop", "1",
               "-t", str(d), "-i", src, "-vf", vf, "-t", str(dur), "-an",
               "-c:v", "libx264", "-preset", "fast", "-crf", "19",
               "-video_track_timescale", "15360", out_path]
        r = _run(cmd, timeout=300)
        return r.returncode == 0 and os.path.exists(out_path)

    # video source
    din = ev.get("in", 0)
    d = dur + 0.4
    if treat == "punch_in":
        # smooth push-in on real video: upscale, then zoompan (d=1 -> passthrough
        # per input frame) with zoom evolving over the shot, output = content area
        n_frames = max(2, int(dur * FPS))
        vf = (f"scale={2*W}:{2*CH}:force_original_aspect_ratio=increase,"
              f"crop={2*W}:{2*CH},"
              f"zoompan=z='1.0+0.12*on/{n_frames}':x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':d=1:s={W}x{CH}:fps={FPS},")
    else:
        vf = f"scale={W}:{CH}:force_original_aspect_ratio=increase,crop={W}:{CH},"
    vf += f"pad={W}:{H}:0:{BAR}:black," + _grade_chain()
    # text overlay on designated shots
    if ev.get("on_screen"):
        tf = _textfile(run_dir, f"os_{ev['start']}.txt", ev["on_screen"])
        vf += (f",drawtext=fontfile={SERIF}:textfile='{tf}':fontsize=46:"
               f"fontcolor=0xF2F2F4:shadowcolor=0x00000088:shadowx=2:shadowy=2:"
               f"x=(w-text_w)/2:y=h-{BAR+110}:"
               f"alpha='if(lt(t,0.5),0,if(lt(t,1.0),(t-0.5)/0.5,1))'")
    vf += ",format=yuv420p"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-nostats",
           "-ss", str(din), "-t", str(d), "-i", src,
           "-vf", vf, "-t", str(dur), "-an", "-r", str(FPS),
           "-c:v", "libx264", "-preset", "fast", "-crf", "19",
           "-video_track_timescale", "15360", out_path]
    r = _run(cmd, timeout=420)
    return r.returncode == 0 and os.path.exists(out_path)


def render_all_shots(run_dir, events):
    shots_dir = os.path.join(run_dir, "shots")
    os.makedirs(shots_dir, exist_ok=True)
    fails = []
    for i, ev in enumerate(events):
        out = os.path.join(shots_dir, f"shot_{i:03d}.mp4")
        ev["_clip"] = out
        if os.path.exists(out) and os.path.getsize(out) > 20_000:
            continue
        if os.path.exists(out):
            os.remove(out)  # stale zero-byte from an interrupted run
        ok = render_shot_clip(run_dir, ev, out)
        if not ok:
            fails.append((i, ev.get("src_id", ev.get("text", "?"))))
    if fails:
        raise RuntimeError(f"shot renders failed: {fails}")
    return shots_dir


# ---------------- concat ----------------
def concat_video(run_dir, events):
    shots_dir = os.path.join(run_dir, "shots")
    lst = os.path.join(run_dir, "concat.txt")
    with open(lst, "w") as fh:
        for i, ev in enumerate(events):
            fh.write(f"file '{os.path.join(shots_dir, f'shot_{i:03d}.mp4')}'\n")
    out = os.path.join(run_dir, "video_track.mp4")
    r = _run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-f", "concat",
              "-safe", "0", "-i", lst, "-c", "copy", out])
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("concat failed: " + r.stderr[-400:])
    return out


# ---------------- audio (moved to s6_audio.py) ----------------
from stages.s6_audio import build_audio  # noqa: E402


# ---------------- mux + master ----------------
def mux_final(run_dir, video_track, audio_mix):
    out = os.path.join(run_dir, "final.mp4")
    r = _run(["ffmpeg", "-y", "-hide_banner", "-nostats",
              "-i", video_track, "-i", audio_mix,
              "-map", "0:v", "-map", "1:a",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-shortest", "-movflags", "+faststart", out], timeout=300)
    if r.returncode != 0 or not os.path.exists(out):
        raise RuntimeError("mux failed: " + r.stderr[-400:])
    return out


def run(run_dir):
    events, beat_starts, total = build_timeline(run_dir)
    render_all_shots(run_dir, events)
    video_track = concat_video(run_dir, events)
    audio_mix = build_audio(run_dir, beat_starts, total)
    final = mux_final(run_dir, video_track, audio_mix)
    return {"total": total, "events": len(events), "final": final}


if __name__ == "__main__":
    info = run(sys.argv[1])
    print(json.dumps(info, indent=1))
