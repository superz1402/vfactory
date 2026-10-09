#!/usr/bin/env python3
"""Stage 6: render. Three passes:
  A) per-scene clip: Ken Burns (zoompan) + caption (drawtext w/ textfile)
  B) xfade concat + global fades -> video track
  C) narration timeline (adelay/amix) + sidechain-ducked bed + loudnorm -> final.mp4
Aspect: 16:9 (1920x1080) or 9:16 (1080x1920) from topic json."""
import json, math, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
XF = 0.6          # crossfade seconds
TAIL = 0.8        # silence tail after narration in each scene
MIN_SCENE = 3.5   # minimum scene duration
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    durs = {}
    for sc in json.load(open(os.path.join(run_dir, "02_script.json")))["scenes"]:
        durs[sc["id"]] = max(MIN_SCENE, timings.get(sc["id"], 4.0) + TAIL)
    starts = {}
    acc = 0.0
    for sid in sorted(durs):
        starts[sid] = acc
        acc += durs[sid] - XF
    total = starts[max(durs)] + durs[max(durs)]
    return durs, starts, round(total, 2)


def esc_textfile(run_dir, sc, text):
    p = os.path.join(run_dir, "04_media", f"scene_{sc['id']:02d}.txt")
    with open(p, "w") as fh:
        fh.write(text.replace("\n", " ").strip()[:70])
    return p


def pass_a(run_dir, durs, W, H, title):
    """Per-scene clip with Ken Burns + caption."""
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    manifest = json.load(open(os.path.join(run_dir, "04_media.json")))
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    clips = []
    for n, sc in enumerate(plan["scenes"], 1):
        sid = sc["id"]
        dur = durs[sid]
        frames = max(int(dur * 30), 2)
        out = os.path.join(clip_dir, f"clip_{sid:02d}.mp4")
        src = manifest[str(sid)]["path"]
        kind = manifest[str(sid)].get("kind", "image")
        zin = (n % 2 == 1)
        if kind == "video":
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H},fps=30")
            cmd = ["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1",
                   "-i", src, "-t", f"{dur:.2f}",
                   "-vf", vf, "-an", "-c:v", "libx264", "-preset", "medium",
                   "-crf", "19", "-pix_fmt", "yuv420p", out]
        else:
            if zin:
                z = f"zoompan=z='min(1.0+0.12*on/{frames},1.12)'"
            else:
                z = f"zoompan=z='max(1.12-0.12*on/{frames},1.0)'"
            z += (f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
                  f":d={frames}:s={W}x{H}:fps=30")
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H}," + z)
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", src,
                   "-vf", vf, "-frames:v", str(frames),
                   "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                   "-pix_fmt", "yuv420p", out]
        subprocess.run(cmd, capture_output=True, timeout=600, check=True)
        # caption pass (drawtext from textfile => no escaping pain)
        cap = esc_textfile(run_dir, sc, title if n == 1 else sc["on_screen"])
        size = 66 if n == 1 else 46
        ypos = "(h-th)/2-120" if n == 1 else "h-170"
        tmp = out + ".cap.mp4"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out, "-vf",
                        f"drawtext=fontfile={FONT}:textfile={cap}:fontsize={size}"
                        f":fontcolor=white:borderw=2:bordercolor=black@0.6"
                        f":box=1:boxcolor=black@0.35:boxborderw=16"
                        f":x=(w-tw)/2:y={pos_y(ypos, H)}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
                        "-pix_fmt", "yuv420p", tmp],
                       capture_output=True, timeout=300, check=True)
        os.replace(tmp, out)
        clips.append(out)
    return clips


def pos_y(expr, H):
    return expr  # already resolution-independent


def pass_b(clips, durs, starts, total, W, H, run_dir):
    """xfade concat + global fade."""
    video = os.path.join(run_dir, "06_final", "video.mp4")
    inputs = []
    for c in clips:
        inputs += ["-i", c]
    fc = []
    prev = "[0:v]"
    for i in range(1, len(clips)):
        outlbl = f"[vx{i}]"
        trans = "fadeblack" if i == 1 else "fade"
        fc.append(f"{prev}[{i}:v]xfade=transition={trans}:duration={XF}"
                  f":offset={starts[i + 1]:.3f}{outlbl}")
        prev = outlbl
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
    """Narration timeline + ducked bed + loudnorm -> final.mp4."""
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
        ms = int((starts[t["id"]] + 0.30) * 1000)
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
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    W, H = dims(topic.get("aspect", "16:9"))
    durs, starts, total = scene_durations(run_dir)
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    clips = pass_a(run_dir, durs, W, H, plan.get("title", topic["topic"]))
    video = pass_b(clips, durs, starts, total, W, H, run_dir)
    final = pass_c(run_dir, starts, total, video)
    return {"final": final, "total": total, "scenes": len(durs)}


if __name__ == "__main__":
    info = run(sys.argv[1])
    print("render done:", info)
