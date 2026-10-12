#!/usr/bin/env python3
"""Stage 6 v2: render for REAL footage clips.

  A) per-scene: pre-cut video clip from s4 (fade in/out) or image fallback
     (Ken Burns). Captions only on title + act-opening scenes (no text spam).
  B) concat demuxer (robust for any film length) + global fades -> video.mp4
  C) narration timeline (adelay/amix) + ducked bed + loudnorm -> final.mp4
  D) HARD ASSERTIONS: voiceover present, per-scene audio non-silent,
     narration coverage >= 50% of runtime. Raises on failure — a render that
     ships without a real voice track is a defect, not a deliverable.
Aspect: 16:9 (1920x1080) or 9:16 (1080x1920) from topic json."""
import json, math, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
TAIL = 0.7          # silence tail after narration in each scene
MIN_SCENE = 4.0     # minimum scene duration
FADE = 0.35         # per-clip fade in/out
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def rms_db(path):
    """Mean RMS in dB via astats."""
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", path, "-af", "astats=measure_overall=RMS_level:measure_perchannel=none",
                        "-f", "null", "-"], capture_output=True, text=True)
    for line in (r.stderr or "").splitlines():
        if "RMS level dB" in line:
            try:
                return float(line.split(":")[-1].strip())
            except ValueError:
                pass
    return -120.0


def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    durs = {}
    for sc in json.load(open(os.path.join(run_dir, "02_script.json")))["scenes"]:
        durs[sc["id"]] = max(MIN_SCENE, timings.get(sc["id"], 4.0) + TAIL)
    return durs


def esc_textfile(run_dir, sc, text):
    p = os.path.join(run_dir, "04_media", f"scene_{sc['id']:02d}.txt")
    with open(p, "w") as fh:
        fh.write(text.replace("\n", " ").strip()[:80])
    return p


def _seg(src, ss, dur, out, W, H, fade=None):
    """Cut one segment (normalized). fade=('in'|'out'|None) with FADE secs."""
    vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps=30"]
    if fade == "in":
        vf.append(f"fade=t=in:st=0:d={FADE}")
    elif fade == "out":
        vf.append(f"fade=t=out:st={max(dur - FADE, 0):.2f}:d={FADE}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{ss:.2f}", "-t", f"{dur:.2f}",
           "-i", src, "-vf", ",".join(vf), "-an", "-c:v", "libx264",
           "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", out]
    subprocess.run(cmd, capture_output=True, timeout=900, check=True)
    return out


def _scene_with_cutaways(m, dur, out, W, H):
    """Long scenes: main <-> cutaway <-> main (hard cuts, documentary rhythm).
    Fades baked on the assembled scene clip ends."""
    seg_dir = os.path.dirname(out)
    parts, cur, used_ins = [], 0.0, 0
    ins = [c for c in m.get("cutaways", [])][:2]
    if dur > 14 and len(ins) >= 1:
        # plan: inserts REPLACE main footage — total stays exactly dur
        cuts = []
        ins_total = 2.5 * min(len(ins), 2)
        p1 = round(dur * 0.30, 2)
        remaining = dur - p1 - ins_total
        if len(ins) >= 2:
            p2 = round(remaining * 0.55, 2)
            tail = round(remaining - p2, 2)
            cuts = [("main", 0.0, p1), ("ins", 0, 2.5),
                    ("main", p1 + 0.1, p2), ("ins", 1, 2.5),
                    ("main", p1 + p2 + 0.2, tail)]
        else:
            p2 = round(remaining, 2)
            cuts = [("main", 0.0, p1), ("ins", 0, 2.5),
                    ("main", p1 + 0.1, p2)]
        n = 0
        for kind, ss, sd in cuts:
            if sd < 1.2:
                continue
            src = m["path"] if kind == "main" else ins[ss]["path"]
            s = ss if kind == "main" else 0.0
            p = os.path.join(seg_dir, f"{os.path.basename(out)}.seg{n}.mp4")
            _seg(src, s, sd, p, W, H)
            parts.append(p)
            cur += sd
            n += 1
    if not parts:  # single continuous clip
        _seg(m["path"], 0.0, dur, out + ".raw.mp4", W, H)
        parts = [out + ".raw.mp4"]
        cur = dur
    lst = out + ".segs.txt"
    with open(lst, "w") as fh:
        for p in parts:
            fh.write(f"file '{os.path.abspath(p)}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-vf",
                    (f"scale={W}:{H},format=yuv420p,fade=t=in:st=0:d={FADE},"
                     f"fade=t=out:st={max(cur - FADE, 0):.2f}:d={FADE}"),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                    "-r", "30", "-movflags", "+faststart", out],
                   capture_output=True, timeout=900, check=True)
    for p in parts:
        try:
            os.remove(p)
        except OSError:
            pass
    return cur


def pass_a(run_dir, durs, W, H, title):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    manifest = json.load(open(os.path.join(run_dir, "04_media.json")))
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    clips = []
    for sc in plan["scenes"]:
        sid = sc["id"]
        dur = durs[sid]
        out = os.path.join(clip_dir, f"clip_{sid:02d}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 50000:
            real = audio_len(out)  # assembled length may differ (cutaways)
            durs[sid] = round(real, 2)
            clips.append(out)
            continue  # resume support
        m = manifest[str(sid)]
        if m["kind"] == "video":
            dur = _scene_with_cutaways(m, dur, out, W, H)
            durs[sid] = dur
        else:
            frames = max(int(dur * 30), 2)
            zin = (sid % 2 == 1)
            if zin:
                z = f"zoompan=z='min(1.0+0.10*on/{frames},1.10)'"
            else:
                z = f"zoompan=z='max(1.10-0.10*on/{frames},1.0)'"
            z += (f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
                  f":d={frames}:s={W}x{H}:fps=30")
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", m["path"],
                   "-vf", (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                           f"crop={W}:{H}," + z +
                           f",fade=t=in:st=0:d={FADE},"
                           f"fade=t=out:st={max(dur - FADE, 0):.2f}:d={FADE}"),
                   "-frames:v", str(frames), "-c:v", "libx264",
                   "-preset", "veryfast", "-crf", "19",
                   "-pix_fmt", "yuv420p", out]
            subprocess.run(cmd, capture_output=True, timeout=900, check=True)
        # caption ONLY on title and act-opening scenes (documentary, no spam)
        cap_on = (sid == 1) or sc.get("act_open")
        if cap_on and sc.get("on_screen"):
            cap = esc_textfile(run_dir, sc,
                               title if sid == 1 else sc["on_screen"])
            size = 62 if sid == 1 else 44
            ypos = "h*0.82" if sid == 1 else "h*0.88"
            tmp = out + ".cap.mp4"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", out, "-vf",
                            f"drawtext=fontfile={FONT}:textfile={cap}:fontsize={size}"
                            f":fontcolor=white:borderw=2:bordercolor=black@0.7"
                            f":x=(w-tw)/2:y={ypos}",
                            "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "19", "-pix_fmt", "yuv420p", tmp],
                           capture_output=True, timeout=300, check=True)
            os.replace(tmp, out)
        clips.append(out)
    return clips


def pass_b(clips, total, W, H, run_dir):
    """Concat demuxer with stream copy (clips are uniform 1080p30 + fades baked).
    Re-encoding 20 min on 2 CPUs is neither fast nor quality-positive."""
    video = os.path.join(run_dir, "06_final", "video.mp4")
    lst = os.path.join(run_dir, "06_final", "concat.txt")
    with open(lst, "w") as fh:
        for c in clips:
            fh.write(f"file '{os.path.abspath(c)}'\n")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lst, "-c", "copy", "-movflags", "+faststart", video],
                   capture_output=True, timeout=600, check=True)
    return video


def pass_c(run_dir, starts, total, video):
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    starts = {int(k): v for k, v in starts.items()}  # json round-trip safety
    music = json.load(open(os.path.join(run_dir, "05_music.json")))["path"]
    final = os.path.join(run_dir, "final.mp4")
    inputs = ["-i", music]
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"atrim=0:{total:.2f},apad=whole_dur={total:.2f}[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        ms = int((starts[t["id"]] + 0.25) * 1000)
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:"
              f"normalize=0[nar]")
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
                   capture_output=True, timeout=1800, check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", mix_wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", final],
                   capture_output=True, timeout=600, check=True)
    return final


def assert_voice(run_dir, final, total, starts, durs):
    """HARD QA: the film MUST have a real voice track (Round-8 lesson)."""
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    # 1. narration files exist, non-silent, sane durations
    total_voice = 0.0
    for t in timings:
        wav = t["wav"]
        if not (os.path.exists(wav) and os.path.getsize(wav) > 10000):
            raise RuntimeError(f"voiceover missing for scene {t['id']}: {wav}")
        lvl = rms_db(wav)
        if lvl < -55:
            raise RuntimeError(f"scene {t['id']} narration is SILENT "
                               f"({lvl:.1f} dB) — refusing to ship")
        total_voice += audio_len(wav)
    # 2. coverage
    cov = total_voice / max(total, 1)
    if cov < 0.50:
        raise RuntimeError(f"narration coverage {cov:.0%} < 50% — not a "
                           f"narrated film, refusing to ship")
    # 3. final file has an audio stream and sane loudness
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                        final], capture_output=True, text=True)
    if "aac" not in r.stdout:
        raise RuntimeError("final.mp4 has NO audio stream")
    fl = rms_db(final)
    if fl < -42 or fl > -8:
        raise RuntimeError(f"final loudness out of range: {fl:.1f} dB")
    return {"coverage": round(cov, 2), "final_rms_db": round(fl, 1),
            "voice_sec": round(total_voice, 1)}


def run(run_dir):
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    W, H = dims(topic.get("aspect", "16:9"))
    durs = scene_durations(run_dir)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    clips = pass_a(run_dir, durs, W, H, plan.get("title", topic["topic"]))
    # pass_a may have adjusted durs (cutaway assembly) — recompute timeline
    starts, acc = {}, 0.0
    for sid in sorted(durs):
        starts[sid] = acc
        acc += durs[sid]
    total = round(acc, 2)
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    video = pass_b(clips, total, W, H, run_dir)
    final = pass_c(run_dir, starts, total, video)
    qa = assert_voice(run_dir, final, total, starts, durs)
    return {"final": final, "total": total, "scenes": len(durs), "qa": qa}


if __name__ == "__main__":
    info = run(sys.argv[1])
    print("render done:", info)
