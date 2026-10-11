#!/usr/bin/env python3
"""Stage 6: render.

Scene mode (short): per-scene Ken Burns clips -> xfade chain -> global mix.
Chapter mode (long-form): per chapter = shots (4-move Ken Burns cycle) ->
xfade chain -> chapter mix (bed segment + VO, ducked, loudnorm -14) ->
chapter_NN.mp4 (uniform h264/aac) -> concat demuxer -> final.mp4.

Chapter-level checkpoints (.done_ch_<id>) let long renders resume.
"""
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))
XF = 0.6
XF_CH = 0.7
TAIL = 0.8
TAIL_CH = 1.0
MIN_SCENE = 3.5
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def esc_textfile(run_dir, name, text):
    p = os.path.join(run_dir, "06_final", "captions", name + ".txt")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as fh:
        fh.write(text.replace("\n", " ").strip()[:70])
    return p


# ----------------------------------------------------------- scene mode ----
def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["units"]}
    durs = {}
    for sc in json.load(open(os.path.join(run_dir, "02_script.json")))["scenes"]:
        durs[sc["id"]] = max(MIN_SCENE, timings.get(sc["id"], 4.0) + TAIL)
    starts, acc = {}, 0.0
    for sid in sorted(durs):
        starts[sid] = acc
        acc += durs[sid] - XF
    total = starts[max(durs)] + durs[max(durs)]
    return durs, starts, round(total, 2)


def pass_a(run_dir, durs, W, H, title):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    manifest = json.load(open(os.path.join(run_dir, "04_media.json")))
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    clips = []
    for n, sc in enumerate(plan["scenes"], 1):
        sid = sc["id"]
        dur, frames = durs[sid], max(int(durs[sid] * 30), 2)
        out = os.path.join(clip_dir, f"clip_{sid:02d}.mp4")
        src = manifest[str(sid)]["path"]
        kind = manifest[str(sid)].get("kind", "image")
        zin = (n % 2 == 1)
        if kind == "video":
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},fps=30")
            cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                   "-i", src, "-t", f"{dur:.2f}", "-vf", vf, "-an",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                   "-pix_fmt", "yuv420p", out]
        else:
            z = (f"zoompan=z='min(1.0+0.12*on/{frames},1.12)'" if zin else
                 f"zoompan=z='max(1.12-0.12*on/{frames},1.0)'")
            z += (f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
                  f":d={frames}:s={W}x{H}:fps=30")
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H}," + z)
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", vf,
                   "-frames:v", str(frames), "-c:v", "libx264", "-preset",
                   "medium", "-crf", "19", "-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
        cap = esc_textfile(run_dir, f"scene_{sid:02d}",
                           title if n == 1 else sc["on_screen"])
        size = 66 if n == 1 else 46
        ypos = "(h-th)/2-120" if n == 1 else "h-170"
        tmp = out + ".cap.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out, "-vf",
                        f"drawtext=fontfile={FONT}:textfile={cap}:fontsize={size}"
                        f":fontcolor=white:borderw=2:bordercolor=black@0.6"
                        f":box=1:boxcolor=black@0.35:boxborderw=16"
                        f":x=(w-tw)/2:y={ypos}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-pix_fmt", "yuv420p", tmp],
                       capture_output=True, timeout=300, check=True)
        os.replace(tmp, out)
        clips.append(out)
    return clips


def pass_b(clips, durs, starts, total, W, H, run_dir):
    video = os.path.join(run_dir, "06_final", "video.mp4")
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    fc, prev = [], "[0:v]"
    for i in range(1, len(clips)):
        trans = "fadeblack" if i == 1 else "fade"
        fc.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={XF}"
                  f":offset={starts[i + 1]:.3f}[vx{i}]")
        prev = f"[vx{i}]"
    fc.append(f"{prev}fade=t=in:d=0.6,fade=t=out:st={max(total - 0.9, 0):.3f}"
              f":d=0.9,format=yuv420p[vout]")
    script = os.path.join(run_dir, "06_final", "passb.txt")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex_script", script, "-map", "[vout]",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                    "-pix_fmt", "yuv420p", "-r", "30", video],
                   capture_output=True, timeout=1200, check=True)
    return video


def pass_c(run_dir, starts, total, video):
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["units"]
    bed = json.load(open(os.path.join(run_dir, "05_music.json")))["path"]
    final = os.path.join(run_dir, "final.mp4")
    inputs = ["-i", bed]
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"atrim=0:{total:.2f},apad=whole_dur={total:.2f}[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        ms = int((starts[t["id"]] + 0.30) * 1000)
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:"
              f"normalize=0[nar]")
    # ASPLIT LAW: [nar] feeds sidechaincompress AND the final amix — without an
    # explicit asplit the narration frames go to the sidechain branch only and
    # the mix ends up bed-only (silent voiceover, ASR-verified bug).
    fc.append("[nar]asplit=2[nar1][nar2]")
    fc.append("[bed][nar1]sidechaincompress=threshold=0.015:ratio=8:attack=40"
              ":release=700:makeup=1[ducked]")
    fc.append("[nar2][ducked]amix=inputs=2:duration=longest:normalize=0[mix]")
    fc.append(f"[mix]loudnorm=I=-13.5:TP=-1.2:LRA=11,atrim=0:{total:.2f},"
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


# --------------------------------------------------------- chapter mode ----
MOVES = ("in", "out", "pan_r", "pan_l")


def kb_filter(move, frames, W, H):
    """4-move Ken Burns cycle; pan moves drift horizontally at fixed zoom."""
    if move == "in":
        z = f"zoompan=z='min(1.0+0.10*on/{frames},1.10)':x='(iw-iw/zoom)/2'" \
            f":y='(ih-ih/zoom)/2'"
    elif move == "out":
        z = f"zoompan=z='max(1.10-0.10*on/{frames},1.0)':x='(iw-iw/zoom)/2'" \
            f":y='(ih-ih/zoom)/2'"
    elif move == "pan_r":
        z = f"zoompan=z='1.08':x='(iw-iw/zoom)*on/{frames}':y='(ih-ih/zoom)/2'"
    else:
        z = f"zoompan=z='1.08':x='(iw-iw/zoom)*(1-on/{frames})':y='(ih-ih/zoom)/2'"
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H}," + z + f":d={frames}:s={W}x{H}:fps=30")


def render_shot(src, kind, dur, move, W, H, out, in_point=0.0):
    frames = max(int(dur * 30), 2)
    if kind == "video":
        # exact frame count (doctrine: -t pads drift; -frames:v is exact);
        # -ss before -i trims from the clip's advancing in_point
        ss = ["-ss", f"{max(in_point, 0.0):.2f}"] if in_point else []
        cmd = ["ffmpeg", "-y", "-v", "error"] + ss + \
              ["-stream_loop", "-1", "-i", src,
               "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                      f"crop={W}:{H},fps=30",
               "-frames:v", str(frames), "-an",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", out]
    elif kind == "card":
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", src,
               "-t", f"{dur:.2f}", "-vf",
               f"zoompan=z='min(1.0+0.06*on/{frames},1.06)'"
               f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d={frames}:s={W}x{H}:fps=30",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", out]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
               "-vf", kb_filter(move, frames, W, H), "-frames:v", str(frames),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
               "-pix_fmt", "yuv420p", out]
    subprocess.run(cmd, capture_output=True, timeout=900, check=True)
    return out


def chapter_video(run_dir, ch, shots, W, H, out_mp4, caption=None, big=False):
    """Shots -> title card -> HARD-CUT concat (doctrine: cuts land on words,
    no xfade soup) -> global chapter fades (silent video track)."""
    work = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(work, exist_ok=True)
    clip_paths = []
    for i, s in enumerate(shots, 1):
        cp = os.path.join(work, f"ch{ch['id']:02d}_s{i:02d}.mp4")
        if not (os.path.exists(cp) and os.path.getsize(cp) > 10000):
            move = MOVES[(ch["id"] + i) % 4]
            render_shot(s["path"], s.get("kind", "image"), s["dur"], move, W, H,
                        cp, in_point=s.get("in_point", 0.0))
        clip_paths.append(cp)
    # title card on the opening shot — doctrine allows <=3 cards per video
    if caption:
        tf = esc_textfile(run_dir, f"ch{ch['id']:02d}_title", caption)
        cap_done = clip_paths[0] + ".capdone"
        if not os.path.exists(cap_done):
            size = 72 if big else 52
            ypos = "(h-th)/2-140" if big else "h-190"
            tmp = clip_paths[0] + ".cap.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", clip_paths[0],
                            "-vf",
                            f"drawtext=fontfile={FONT}:textfile={tf}:fontsize={size}"
                            f":fontcolor=white:borderw=2:bordercolor=black@0.65"
                            f":box=1:boxcolor=black@0.38:boxborderw=18"
                            f":x=(w-tw)/2:y={ypos}"
                            f":enable='between(t,0.4,{min(4.6, shots[0]['dur'])})'",
                            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                            "-pix_fmt", "yuv420p", tmp],
                           capture_output=True, timeout=600, check=True)
            os.replace(tmp, clip_paths[0])
            open(cap_done, "w").write("1")
    # hard-cut concat: identical encodes -> demuxer -c copy is exact and fast
    vdur = sum(s["dur"] for s in shots)
    lst = os.path.join(work, f"concat_ch{ch['id']:02d}.txt")
    with open(lst, "w") as fh:
        for c in clip_paths:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    tmp = out_mp4 + ".v.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-vf",
                    f"fade=t=in:d=0.5,fade=t=out:st={max(vdur - 0.7, 0):.3f}:d=0.7"
                    f",format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-r", "30", tmp],
                   capture_output=True, timeout=2400, check=True)
    os.replace(tmp, out_mp4)
    return out_mp4


def chapter_mux(run_dir, ch, video_dur, W, H, out_mp4):
    """Chapter audio: bed segment + VO (ducked) + loudnorm -> final chapter."""
    music = json.load(open(os.path.join(run_dir, "05_music.json")))
    bed = music["beds"][str(ch["id"])]
    t = {u["id"]: u for u in
         json.load(open(os.path.join(run_dir, "03_timings.json")))["units"]}
    vo = t[ch["id"]]["wav"]
    vdur = video_dur
    fc = (
        f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"atrim=0:{vdur:.2f},apad=whole_dur={vdur:.2f}[bed];"
        f"[1:a]aformat=channel_layouts=stereo,aresample=48000,"
        f"adelay=600|600[nar];"
        f"[nar]asplit=2[nar1][nar2];"  # ASPLIT LAW: see pass_c comment
        f"[bed][nar1]sidechaincompress=threshold=0.015:ratio=8:attack=40"
        f":release=700:makeup=1[ducked];"
        f"[nar2][ducked]amix=inputs=2:duration=longest:normalize=0[mix];"
        f"[mix]loudnorm=I=-13.5:TP=-1.2:LRA=11,atrim=0:{vdur:.2f},"
        f"afade=t=out:st={max(vdur - 1.2, 0):.2f}:d=1.2[aout]")
    script = os.path.join(run_dir, "06_final", f"chaudio_{ch['id']:02d}.txt")
    with open(script, "w") as fh:
        fh.write(fc)
    tmp = out_mp4 + ".a.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", bed, "-i", vo,
                    "-filter_complex_script", script, "-map", "[aout]",
                    "-ar", "48000", "-c:a", "aac", "-b:a", "192k", tmp],
                   capture_output=True, timeout=900, check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out_mp4, "-i", tmp,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a",
                    "copy", "-shortest", "-movflags", "+faststart",
                    out_mp4 + ".mux.mp4"],
                   capture_output=True, timeout=600, check=True)
    os.replace(out_mp4 + ".mux.mp4", out_mp4)
    os.remove(tmp)


def run_chapters(run_dir, W, H):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    media = json.load(open(os.path.join(run_dir, "04_media.json")))["chapters"]
    fin_dir = os.path.join(run_dir, "06_final")
    os.makedirs(fin_dir, exist_ok=True)

    chapters, timeline = [], []
    acc = 0.0
    tmap = {u["id"]: u for u in
            json.load(open(os.path.join(run_dir, "03_timings.json")))["units"]}
    for ch in plan["chapters"]:
        cid = str(ch["id"])
        shots = media[cid]["shots"]
        audio = media[cid]["audio"]
        # entity-aligned shot plan: cuts land when subjects are spoken.
        # hard-cut grammar -> no xfade loss (xf=0); durs sum to audio+tail
        from lib import align
        shots = align.plan(shots, tmap.get(ch["id"], {}).get("words"),
                           audio, tail=TAIL_CH, xf=0.0)
        vdur = sum(x["dur"] for x in shots)
        chapters.append({"ch": ch, "shots": shots, "vdur": vdur})
        timeline.append({"id": ch["id"], "start": round(acc, 2),
                         "audio": round(audio, 2), "video": round(vdur, 2)})
        acc += vdur

    for item in chapters:
        cid = item["ch"]["id"]
        marker = os.path.join(run_dir, f".done_ch_{cid:02d}")
        out_mp4 = os.path.join(fin_dir, f"chapter_{cid:02d}.mp4")
        if os.path.exists(marker) and os.path.exists(out_mp4):
            continue
        # <=3 title cards per video (doctrine): ch1 big, climax + outro
        role = item["ch"].get("role", "")
        want_card = (cid == 1) or role in ("climax", "outro", "turning_point")
        cap = (item["ch"].get("on_screen") or item["ch"].get("title")) \
            if want_card else None
        chapter_video(run_dir, item["ch"], item["shots"], W, H, out_mp4,
                      caption=cap, big=(cid == 1))
        chapter_mux(run_dir, item["ch"], item["vdur"], W, H, out_mp4)
        open(marker, "w").write("1")
        print(f"  chapter {cid} rendered ({item['vdur']:.1f}s)", flush=True)

    # concat (uniform encodes -> stream copy)
    final = os.path.join(run_dir, "final.mp4")
    lst = os.path.join(fin_dir, "concat.txt")
    with open(lst, "w") as fh:
        for item in chapters:
            fh.write(f"file 'chapter_{item['ch']['id']:02d}.mp4'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", "-movflags", "+faststart", final],
                   capture_output=True, timeout=900, check=True)
    total = sum(item["vdur"] for item in chapters)
    json.dump({"mode": "chapters", "chapters": timeline,
               "total": round(total, 2)},
              open(os.path.join(run_dir, "06_timeline.json"), "w"),
              indent=1)
    return {"final": final, "total": round(total, 2), "chapters": len(chapters)}


def run(run_dir):
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    W, H = dims(topic.get("aspect", "16:9"))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    if plan.get("mode") == "chapters":
        return run_chapters(run_dir, W, H)

    durs, starts, total = scene_durations(run_dir)
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    clips = pass_a(run_dir, durs, W, H, plan.get("title", topic["topic"]))
    video = pass_b(clips, durs, starts, total, W, H, run_dir)
    final = pass_c(run_dir, starts, total, video)
    return {"final": final, "total": total, "scenes": len(durs)}


if __name__ == "__main__":
    info = run(sys.argv[1])
    print("render done:", info)
