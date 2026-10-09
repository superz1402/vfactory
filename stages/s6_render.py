#!/usr/bin/env python3
"""Stage 6 v2: DOCUMENTARY EDITOR (shot-based, production pass).

When 04_footage.json has a real pool:
  A) per scene: render shots with camera motion (punch-in/pull-out/pan/drift
     on REAL footage), concat, prepend 0.2s white flash-cut head, exact scene
     duration (timeline-preserving: scene target = dur - XF, last = dur)
  B) stream-copy concat all scenes -> base.mp4
  C) kinetic captions + title, film grade (eq/colorbalance/vignette/grain),
     audio: narration timeline + sidechain-ducked bed + whoosh SFX on flash
     cuts + title thump, loudnorm -14 LUFS -> final.mp4

Fallback: v1 image path (Ken Burns over stills) when no footage pool.
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
XF = 0.6
FLASH = 0.2
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
ENC = ["-c:v", "libx264", "-preset", "fast", "-crf", "19",
       "-pix_fmt", "yuv420p", "-r", "30"]


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    durs = {}
    for sc in json.load(open(os.path.join(run_dir, "02_script.json")))["scenes"]:
        durs[sc["id"]] = max(3.5, timings.get(sc["id"], 4.0) + 0.8)
    starts, acc = {}, 0.0
    for sid in sorted(durs):
        starts[sid] = acc
        acc += durs[sid] - XF
    total = starts[max(durs)] + durs[max(durs)]
    return durs, starts, round(total, 2)


def sh(args, timeout=900):
    p = subprocess.run(args, capture_output=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("cmd failed: " + " ".join(args[:8]) +
                           "\n" + p.stderr.decode()[-500:])


def motion_filter(motion, dur, W, H, crop_x):
    """Camera motion via time-evaluated scale/crop (input pre-normalized)."""
    cx = f"(iw-ow)*{crop_x}"
    if motion == "punch-in":
        return (f"scale=w='trunc(iw*(1+0.10*t/{dur:.2f})/2)*2':h=-2:eval=frame,"
                f"crop={W}:{H}:{cx}:(ih-oh)/2")
    if motion == "pull-out":
        return (f"scale=w='trunc(iw*(1.10-0.10*t/{dur:.2f})/2)*2':h=-2:eval=frame,"
                f"crop={W}:{H}:{cx}:(ih-oh)/2")
    if motion == "pan-l":
        return (f"scale=w='trunc(iw*1.12/2)*2':h='trunc(ih*1.12/2)*2',"
                f"crop={W}:{H}:x='(iw-ow)*t/{dur:.2f}':y=(ih-oh)/2")
    if motion == "pan-r":
        return (f"scale=w='trunc(iw*1.12/2)*2':h='trunc(ih*1.12/2)*2',"
                f"crop={W}:{H}:x='(iw-ow)*(1-t/{dur:.2f})':y=(ih-oh)/2")
    return (f"scale=w='trunc(iw*1.08/2)*2':h='trunc(ih*1.08/2)*2',"
            f"crop={W}:{H}:x='(iw-ow)*min({crop_x}+0.06*t/{dur:.2f}\\,0.9)':y=(ih-oh)/2")


def render_shot(src, start, dur, motion, crop_x, W, H, out):
    norm = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H},")
    sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
        "-i", src, "-vf", norm + motion_filter(motion, dur, W, H, crop_x) +
        f",fps=30,setsar=1,format=yuv420p",
        "-an"] + ENC + ["-t", f"{dur:.2f}", out])


def flash_segment(W, H, out):
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
        "-i", f"color=c=white:s={W}x{H}:d={FLASH}:r=30",
        "-vf", "fade=t=out:st=0.05:d=0.15,setsar=1,format=yuv420p"] +
       ENC + [out])


def concat_copy(clips, out, run_dir):
    lst = os.path.join(run_dir, "06_final", "concat.txt")
    with open(lst, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", lst, "-c", "copy", out])


def build_scene_footage(scene, target, W, H, run_dir, clip_dir):
    """Scene = flash head + shots trimmed to exactly `target`."""
    shots = scene["shots"]
    footage_total = target - FLASH
    scale = footage_total / sum(s["dur"] for s in shots)
    segs = []
    for n, s in enumerate(shots):
        sdur = s["dur"] * scale
        seg = os.path.join(clip_dir, f"s{scene['scene_id']:02d}_{n}.mp4")
        render_shot(s["src"], s["start"], sdur, s["motion"], s["crop_x"], W, H, seg)
        segs.append(seg)
    body = os.path.join(clip_dir, f"scene_{scene['scene_id']:02d}_body.mp4")
    concat_copy(segs, body, run_dir)
    # trim body to footage_total exactly (concat rounding safety)
    trimmed = os.path.join(clip_dir, f"scene_{scene['scene_id']:02d}_trim.mp4")
    sh(["ffmpeg", "-y", "-v", "error", "-i", body, "-t", f"{footage_total:.3f}",
        "-c", "copy", trimmed])
    flash = os.path.join(clip_dir, f"flash_{scene['scene_id']:02d}.mp4")
    flash_segment(W, H, flash)
    out = os.path.join(clip_dir, f"scene_{scene['scene_id']:02d}.mp4")
    concat_copy([flash, trimmed], out, run_dir)
    return out


def build_scene_image(sc, dur, W, H, run_dir, clip_dir):
    """v1 fallback: Ken Burns over still image."""
    manifest = json.load(open(os.path.join(run_dir, "04_media.json")))
    src = manifest[str(sc["id"])]["path"]
    frames = max(int(dur * 30), 2)
    out = os.path.join(clip_dir, f"scene_{sc['id']:02d}.mp4")
    z = (f"zoompan=z='min(1.0+0.12*on/{frames},1.12)'" if sc["id"] % 2 == 1
         else f"zoompan=z='max(1.12-0.12*on/{frames},1.0)'")
    z += f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s={W}x{H}:fps=30"
    sh(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf",
        f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},{z}"
        f",setsar=1,format=yuv420p", "-frames:v", str(frames)] + ENC + [out])
    return out


def pass_a(run_dir, durs, starts, W, H):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    fp = os.path.join(run_dir, "04_footage.json")
    footage = json.load(open(fp)) if os.path.exists(fp) else {"pool": [], "scenes": []}
    use_footage = bool(footage.get("pool"))
    fmap = {s["scene_id"]: s["shots"] for s in footage.get("scenes", [])}
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    scenes = []
    for sc in plan["scenes"]:
        sid = sc["id"]
        target = durs[sid] - (XF if sid != max(durs) else 0.0)
        if use_footage and sid in fmap:
            scene = {"scene_id": sid, "shots": fmap[sid]}
            out = build_scene_footage(scene, target, W, H, run_dir, clip_dir)
        else:
            out = build_scene_image(sc, target, W, H, run_dir, clip_dir)
        scenes.append(out)
        print(f"  scene {sid} -> {os.path.basename(out)}")
    return scenes


def pass_b(scenes, run_dir):
    base = os.path.join(run_dir, "06_final", "base.mp4")
    concat_copy(scenes, base, run_dir)
    return base


def esc_textfile(run_dir, sid, text):
    p = os.path.join(run_dir, "04_media", f"cap_{sid:02d}.txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text.replace("\n", " ").strip()[:70])
    return p


def pass_c(run_dir, starts, durs, total, base, title):
    final = os.path.join(run_dir, "final.mp4")
    W, H = dims(json.load(open(os.path.join(run_dir, "00_topic.json")))["aspect"])
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    bed = json.load(open(os.path.join(run_dir, "05_music.json")))["path"]

    # ---- video overlays + grade ----
    fc_v, draw = [], []
    t0 = json.load(open(os.path.join(run_dir, "00_topic.json")))
    chain = [f"[0:v]fps=30,setsar=1"]
    # title (0-3.2s, big, fade out)
    tf = esc_textfile(run_dir, 0, title)
    chain.append(
        f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={H // 16}"
        f":fontcolor=white:borderw=3:bordercolor=black@0.7"
        f":x=(w-tw)/2:y=(h-th)/2"
        f":alpha='if(lt(t,0.3),t/0.3,if(lt(t,2.6),1,max(0,(3.2-t)/0.6)))'")
    # kinetic captions per scene (skip scene 1 = title)
    for sc in plan["scenes"]:
        if sc["id"] == 1:
            continue
        st, en = starts[sc["id"]], starts[sc["id"]] + durs[sc["id"]] - XF
        cf = esc_textfile(run_dir, sc["id"], sc["on_screen"])
        chain.append(
            f"drawtext=fontfile={FONT}:textfile={cf}:fontsize={H // 22}"
            f":fontcolor=white:borderw=2:bordercolor=black@0.6"
            f":box=1:boxcolor=black@0.30:boxborderw=14"
            f":x=(w-tw)/2:y='h-{int(H * 0.16)}+(th+20)*(1-min(t-{st:.2f}\\,1)/0.35)'"
            f":alpha='clip((t-{st:.2f})/0.35\\,0\\,1)*clip(({en - 0.3:.2f}-t)/0.3\\,0\\,1)'"
            f":enable='between(t,{st + 0.1:.2f},{en:.2f})'")
    # grade + grain + fade
    chain.append("eq=contrast=1.05:saturation=1.08:brightness=-0.01,"
                 "colorbalance=rs=-0.03:bs=0.04,"
                 "vignette=PI/5,noise=alls=5:allf=t+u,"
                 f"fade=t=in:d=0.4,fade=t=out:st={max(total - 0.9, 0):.2f}:d=0.9")
    fc_v.append(",".join(chain) + "[vout]")

    # ---- audio: narration + bed + SFX ----
    inputs = ["-i", bed]  # audio-only invocation: no video input
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc_a = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
            f"atrim=0:{total:.2f},apad=whole_dur={total:.2f}[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        ms = int((starts[t["id"]] + 0.30) * 1000)
        fc_a.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                    f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc_a.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:normalize=0[nar]")
    boundaries = [starts[sid] for sid in sorted(durs) if sid > 1]
    sfx_in = []
    for k, st in enumerate(boundaries):
        inputs += ["-f", "lavfi", "-i",
                   f"anoisesrc=color=pink:d=0.5:amplitude=0.5:seed={42 + k}"]
        idx = len(timings) + 1 + k
        ms = int(st * 1000)
        fc_a.append(f"[{idx}:a]highpass=f=400,lowpass=f=3200,"
                    f"afade=t=in:d=0.12,afade=t=out:st=0.18:d=0.32,"
                    f"volume=0.5,adelay={ms}|{ms}[w{k}]")
        sfx_in.append(f"[w{k}]")
    # title thump
    inputs += ["-f", "lavfi", "-i", "sine=frequency=58:duration=0.7"]
    th = len(timings) + 1 + len(boundaries)
    fc_a.append(f"[{th}:a]afade=t=out:st=0.05:d=0.6,volume=0.6,"
                f"adelay=150|150[thump]")
    if sfx_in:
        fc_a.append("".join(sfx_in) + f"[thump]amix=inputs={len(sfx_in) + 1}"
                    ":duration=longest:normalize=0[sfx]")
    else:
        fc_a.append("[thump]anull[sfx]")
    # proven mix: bed ducked 8:1 under narration (Session-28 recipe) + SFX layer
    fc_a.append("[bed][nar]sidechaincompress=threshold=0.015:ratio=8:attack=40"
                ":release=700:makeup=1[ducked]")
    fc_a.append("[nar][ducked][sfx]amix=inputs=3:duration=longest:normalize=0"
                ":weights=1 1 0.5[mix]")
    fc_a.append(f"[mix]loudnorm=I=-14:TP=-1.5:LRA=11,"
                f"atrim=0:{total:.2f},afade=t=out:st={max(total - 1.0, 0):.2f}"
                ":d=1.0[aout]")

    # C1: AUDIO-ONLY pass (no video input in this invocation — ffmpeg's
    # input binding mis-resolves link labels when a video-only input is
    # first; audio graph alone binds cleanly, proven by bisect)
    script_a = os.path.join(run_dir, "06_final", "passc_audio.txt")
    with open(script_a, "w") as fh:
        fh.write(";".join(fc_a))
    mix_wav = os.path.join(run_dir, "06_final", "mix.wav")
    sh(["ffmpeg", "-y", "-v", "error"] + inputs +
       ["-filter_complex_script", script_a, "-map", "[aout]",
        "-ar", "48000", "-t", f"{total:.2f}", mix_wav])
    # C2: VIDEO pass: overlays + grade on base, then mux with mix.wav
    script_v = os.path.join(run_dir, "06_final", "passc_video.txt")
    with open(script_v, "w") as fh:
        fh.write(";".join(fc_v))
    graded = os.path.join(run_dir, "06_final", "graded.mp4")
    sh(["ffmpeg", "-y", "-v", "error", "-i", base,
        "-filter_complex_script", script_v, "-map", "[vout]",
        "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "medium",
        "-crf", "19", "-pix_fmt", "yuv420p", graded])
    sh(["ffmpeg", "-y", "-v", "error", "-i", graded, "-i", mix_wav,
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "192k", "-shortest", "-movflags", "+faststart", final])
    return final


def run(run_dir):
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    W, H = dims(topic.get("aspect", "16:9"))
    durs, starts, total = scene_durations(run_dir)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    scenes = pass_a(run_dir, durs, starts, W, H)
    base = pass_b(scenes, run_dir)
    final = pass_c(run_dir, starts, durs, total, base,
                   plan.get("title", topic["topic"]))
    return {"final": final, "total": total, "mode": "documentary-edit"}


if __name__ == "__main__":
    print(run(sys.argv[1]))
