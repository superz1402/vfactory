#!/usr/bin/env python3
"""Stage 6 (v2): documentary render.

v1 (slideshow + caption spam) is replaced by real editing grammar:
  Pass A  per cut: trim character-verified footage from the normalized
          sources, cover-scale to target, documentary drift (a 2% slow
          pan on cuts >= 3.5 s), hard-cut audio-free CRF18 clips.
          9:16 runs crop around the subject's face (fx from face analysis).
  Pass B  concat cuts inside a scene with hard cuts, xfade (0.5 s) between
          scenes, global fade in/out, ONE clean opening title (the only
          text on screen — no per-scene captions).
  Pass C  narration timeline + sidechain-ducked real-song bed + loudnorm.
Aspect: 16:9 (1920x1080) or 9:16 (1080x1920)."""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
XF = 0.5          # crossfade between scenes
TAIL = 0.8        # silence tail after narration in each scene
MIN_SCENE = 3.5   # minimum scene duration
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DRIFT_W = 0.02    # drift amplitude as fraction of frame width


def _scenes(plan):
    """beats (v2 script) or scenes (v1) -> unified list with id/on_screen."""
    if plan.get("beats"):
        return [{"id": b.get("id", i + 1),
                 "narration": b.get("narration", ""),
                 "on_screen": b.get("on_screen", "")}
                for i, b in enumerate(plan["beats"])]
    return plan["scenes"]


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    durs = {}
    for sc in _scenes(plan):
        durs[sc["id"]] = max(MIN_SCENE, timings.get(str(sc["id"]),
                                  timings.get(sc["id"], 4.0)) + TAIL)
    starts = {}
    acc = 0.0
    for sid in sorted(durs, key=int):
        starts[sid] = acc
        acc += durs[sid] - XF
    total = starts[sorted(durs, key=int)[-1]] + durs[sorted(durs, key=int)[-1]]
    return durs, starts, round(total, 2)


def _cover_crop(W, H, src_w, src_h, fx=None, dur=None, drift=0.0):
    """Cover-scale then crop, with optional documentary drift.

    Returns a vf string. Drift pans slowly toward the face/centre: the crop
    window starts offset by `drift` of the slack and ends centred."""
    s = max(W / src_w, H / src_h)
    sw, sh = int(src_w * s + 0.5), int(src_h * s + 0.5)
    slack = sw - W
    if slack <= 8:
        cx = slack / 2.0
        x = f"(iw-ow)/2"
        vf = (f"scale={sw}:{sh},crop={W}:{H}:{x}:(ih-oh)/2")
        return vf
    if fx is not None:
        fx = min(max(fx, 0.0), 1.0)
        # face centre in scaled px -> crop x keeping face in frame
        fc_px = fx * sw
        base = min(max(fc_px - W / 2.0, 0.0), slack)
    else:
        base = slack / 2.0
    if drift > 0 and dur:
        # start at base - drift*slack/2, glide to base (documentary drift)
        d_px = drift * slack
        x0 = min(max(base - d_px, 0.0), slack)
        vf = (f"scale={sw}:{sh},crop={W}:{H}:"
              f"x='{x0:.1f}+({base - x0:.1f})*min(t/{dur:.2f},1)':y=(ih-oh)/2")
    else:
        vf = f"scale={sw}:{sh},crop={W}:{H}:{base:.1f}:(ih-oh)/2"
    return vf


def pass_a(run_dir, W, H):
    """Per-cut clips from character-verified footage."""
    cm = json.load(open(os.path.join(run_dir, "04_charmedia.json")))
    aspect = "9:16" if H > W else "16:9"
    cut_dir = os.path.join(run_dir, "06_final", "cuts")
    os.makedirs(cut_dir, exist_ok=True)
    scene_cuts = {}
    n = 0
    for sid in sorted(cm["scenes"], key=int):
        lst = []
        for c in cm["scenes"][sid]["cuts"]:
            n += 1
            out = os.path.join(cut_dir, f"cut_{n:02d}.mp4")
            scene_cuts.setdefault(sid, []).append(out)
            if os.path.exists(out) and os.path.getsize(out) > 50_000:
                continue
            dur = c["t1"] - c["t0"]
            vw = int(c.get("vw") or 0)
            if not vw:
                pr = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height", "-of", "csv=p=0",
                     c["video"]], capture_output=True, text=True, timeout=30)
                try:
                    vw, vh = (int(x) for x in pr.stdout.strip().split(","))
                except Exception:
                    vw, vh = 1280, 720
            else:
                pr2 = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=height", "-of", "csv=p=0",
                     c["video"]], capture_output=True, text=True, timeout=30)
                try:
                    vh = int(pr2.stdout.strip())
                except Exception:
                    vh = 720
            drift = DRIFT_W if dur >= 3.5 else 0.0
            fx = c.get("fx") if aspect == "9:16" else None
            vf = _cover_crop(W, H, vw, vh, fx=fx, dur=dur, drift=drift)
            cmd = ["ffmpeg", "-y", "-v", "error",
                   "-ss", f"{c['t0']:.3f}", "-to", f"{c['t1']:.3f}",
                   "-i", c["video"], "-vf", vf + ",fps=30",
                   "-an", "-c:v", "libx264", "-preset", "medium",
                   "-crf", "18", "-pix_fmt", "yuv420p", out]
            subprocess.run(cmd, capture_output=True, timeout=600, check=True)
        cm["scenes"][sid]["files"] = scene_cuts.get(sid, [])
    json.dump(cm, open(os.path.join(run_dir, "04_charmedia.json"), "w"), indent=1)
    return cm


def _probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def pass_b_scene(cm, sid, out, cap_dur=None):
    """Concat a scene's cuts with hard cuts, EXACTLY cap_dur long:
    longer concats get trimmed, shorter ones get a freeze-frame pad
    (tpad clone) — documentary-standard hold on the last shot."""
    files = cm["scenes"][sid]["files"]
    if not cap_dur:
        cap = []
        pad_vf = "setsar=1"
    else:
        cap = ["-t", f"{cap_dur:.3f}"]
        pad_vf = (f"setsar=1,tpad=stop_mode=clone:stop_duration={cap_dur + 1:.3f}")
    if len(files) == 1:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", files[0],
                        "-vf", pad_vf] + cap +
                        ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                         "-pix_fmt", "yuv420p", out],
                       capture_output=True, timeout=600, check=True)
        return
    inputs = []
    for f in files:
        inputs += ["-i", f]
    norm = "".join(f"[{i}:v]setsar=1[v{i}];" for i in range(len(files)))
    fc = norm + "".join(f"[v{i}]" for i in range(len(files))) \
        + f"concat=n={len(files)}:v=1:a=0[cat];[cat]{pad_vf}[vout]"
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex", fc, "-map", "[vout]"] + cap +
                   ["-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", out],
                   capture_output=True, timeout=900, check=True)


def pass_b(run_dir, cm, durs, starts, total, W, H, title):
    """Scene assembly + xfade + the single opening title."""
    final_dir = os.path.join(run_dir, "06_final")
    scene_files = []
    for sid in sorted(durs, key=int):
        skey = str(sid)
        if skey not in cm["scenes"] or not cm["scenes"][skey].get("files"):
            continue
        sf = os.path.join(final_dir, f"scene_{int(sid):02d}.mp4")
        if os.path.exists(sf) and os.path.getsize(sf) > 200_000 \
                and abs(_probe_dur(sf) - durs[sid]) < 0.35:
            scene_files.append(sf)
            continue
        pass_b_scene(cm, skey, sf, cap_dur=durs[sid])
        scene_files.append(sf)
    if not scene_files:
        raise RuntimeError("no scene files assembled")
    # xfade chain
    inputs = []
    for f in scene_files:
        inputs += ["-i", f]
    fc = []
    prev = "[0:v]"
    offsets = []
    acc = 0.0
    for i in range(1, len(scene_files)):
        acc += _probe_dur(scene_files[i - 1]) - XF
        offsets.append(acc)
        prev_lab = prev if i == 1 else f"[vx{i - 1}]"
        out_lab = "[vx%d]" % i if i < len(scene_files) - 1 else "[vxlast]"
        fc.append(f"{prev_lab}[{i}:v]xfade=transition=fade:duration={XF}"
                  f":offset={acc:.3f}{out_lab}")
        prev = out_lab
    last = prev if prev.startswith("[vx") else "[0:v]"
    fc.append(f"{last}fade=t=in:d=0.6,fade=t=out:st={max(total - 0.9, 0):.3f}"
              f":d=0.9,format=yuv420p[base]")
    # the ONLY text: one clean opening title, fade in/out
    size = int(W * 0.042)
    tp = os.path.join(final_dir, "title.txt")
    with open(tp, "w") as fh:
        fh.write((title or "").replace("\n", " ").strip()[:80])
    fc.append(f"[base]drawtext=fontfile={FONT}:textfile={tp}:fontsize={size}"
              f":fontcolor=white:borderw=2:bordercolor=black@0.55"
              f":x=(w-tw)/2:y=h*0.74:"
              f"alpha='if(lt(t,0.5),0,if(lt(t,1.1),(t-0.5)/0.6,"
              f"if(lt(t,3.6),1,if(lt(t,4.4),(4.4-t)/0.8,0))))'[vout]")
    script = os.path.join(final_dir, "passb.txt")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    video = os.path.join(final_dir, "video.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex_script", script, "-map", "[vout]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-r", "30", video],
                   capture_output=True, timeout=1200, check=True)
    return video


def pass_c(run_dir, starts, total, video):
    """Narration timeline + ducked real-song bed + loudnorm -> final.mp4."""
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    bed = json.load(open(os.path.join(run_dir, "05_music.json")))["path"]
    final = os.path.join(run_dir, "final.mp4")
    inputs = ["-i", bed]
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"atrim=0:{total:.2f},apad=whole_dur={total:.2f}[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        st = starts.get(t["id"], starts.get(str(t["id"]), 0.0))
        ms = int((st + 0.30) * 1000)
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:normalize=0[nar]")
    fc.append("[bed][nar]sidechaincompress=threshold=0.015:ratio=8:attack=40"
              ":release=700:makeup=1[ducked]")
    fc.append("[nar][ducked]amix=inputs=2:duration=longest:normalize=0[mix]")
    fc.append(f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11,atrim=0:{total:.2f},"
              f"afade=t=out:st={max(total - 1.0, 0):.2f}:d=1.0[aout]")
    script = os.path.join(run_dir, "06_final", "passc.txt")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    mix_wav = os.path.join(run_dir, "06_final", "mix.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex_script", script, "-map", "[aout]",
                    "-ar", "48000", mix_wav],
                   capture_output=True, timeout=900, check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", mix_wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", final],
                   capture_output=True, timeout=300, check=True)
    return final


def run(run_dir):
    run_dir = os.path.abspath(run_dir)
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    W, H = dims(topic.get("aspect", "16:9"))
    durs, starts, total = scene_durations(run_dir)
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    cm = pass_a(run_dir, W, H)
    video = pass_b(run_dir, cm, durs, starts, total, W, H,
                   plan.get("title", topic["topic"]))
    final = pass_c(run_dir, starts, total, video)
    return {"final": final, "total": total, "scenes": len(durs)}


if __name__ == "__main__":
    info = run(sys.argv[1])
    print("render done:", info)
