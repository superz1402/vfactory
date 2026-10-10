#!/usr/bin/env python3
"""Stage 6 v2: documentary render — the OpenMontage edit grammar applied.

Visual language (locked):
  - REAL footage only, cut at verified sub-windows (s4), source audio stripped
  - static center-crop framing; NO zoompan/Ken Burns (performance footage
    already moves), NO per-scene captions, NO wipes/pushes/glitch
  - hard cuts between shots and scenes (documentary default)
  - ONE act-break black dip (0.4s) at the midpoint
  - fade-in on the first shot, fade-to-black at the end
  - typography appears exactly twice: title card (scene 1, lower-third,
    alpha-faded) and end tag (closing line, centered, final seconds)

Audio:
  - narration on its own timeline (adelay per scene start)
  - bed pre-normalized -23 LUFS, ducked ~12 dB under narration
  - final mix loudnorm I=-16 TP=-1.5 LRA=11 (EBU R128 / YouTube)
"""
import json, math, os, subprocess, sys

sys.path.insert(0, os.path.dirname(__file__))
TAIL = 0.8
MIN_SCENE = 3.5
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def dims(aspect):
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def scene_durations(run_dir):
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    durs = {}
    for sc in json.load(open(os.path.join(run_dir, "02_script.json")))["scenes"]:
        durs[sc["id"]] = max(MIN_SCENE, timings.get(sc["id"], 4.0) + TAIL)
    return durs


def layout(durs, dip_after):
    """Scene starts including the 0.4s act-break dip."""
    starts, acc = {}, 0.0
    for sid in sorted(durs):
        starts[sid] = round(acc, 3)
        acc += durs[sid]
        if sid == dip_after:
            acc += 0.4
    return starts, round(acc, 3)


def enc_args(W, H):
    return ["-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                   f"crop={W}:{H},fps=30,format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17",
            "-an"]


def pass_a(run_dir, durs, W, H):
    """Cut every s4 shot from its source at the verified sub-window."""
    manifest = json.load(open(os.path.join(run_dir, "04_media.json")))["manifest"]
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    scene_files = {}
    for sid in sorted(int(k) for k in manifest):
        m = manifest[str(sid)]
        need = durs[sid]
        parts = []
        for k, shot in enumerate(m["shots"], 1):
            dur = shot["dur"] if k < len(m["shots"]) else \
                min(need - sum(p[1] for p in parts), shot["dur"])
            dur = max(min(dur, shot["dur"]), 1.0)
            out = os.path.join(clip_dir, f"s{sid:02d}_shot{k}.mp4")
            if not (os.path.exists(out) and os.path.getsize(out) > 10000):
                cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{shot['in']:.3f}",
                       "-i", shot["path"], "-t", f"{dur:.3f}"] + enc_args(W, H) + [out]
                subprocess.run(cmd, capture_output=True, timeout=600, check=True)
            parts.append((out, dur))
        # scene = concat of its shots (top-up last shot if under-filled)
        total = sum(d for _, d in parts)
        if total < need - 0.05:
            # extend final shot with a re-cut using longer window take
            last = m["shots"][-1]
            extra = need - total
            out2 = os.path.join(clip_dir, f"s{sid:02d}_fill.mp4")
            cmd = ["ffmpeg", "-y", "-v", "error",
                   "-ss", f"{last['out']:.3f}", "-i", last["path"],
                   "-t", f"{extra:.3f}"] + enc_args(W, H) + [out2]
            try:
                subprocess.run(cmd, capture_output=True, timeout=300, check=True)
                parts.append((out2, extra))
            except subprocess.CalledProcessError:
                pass
        scene_files[sid] = [p for p, _ in parts]
    return scene_files


def _concat(files, out, W, H, run_dir):
    lst = out + ".txt"
    with open(lst, "w") as fh:
        for f in files:
            fh.write(f"file '{os.path.abspath(f)}'\n")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", out],
                       capture_output=True, timeout=600)
    if r.returncode != 0:
        # fallback: re-encode concat (always works)
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
               "-i", lst] + enc_args(W, H) + [out]
        subprocess.run(cmd, capture_output=True, timeout=900, check=True)
    return out


def pass_b(run_dir, scene_files, durs, starts, total, W, H):
    """Assemble video: scenes + one act-break dip (concat only)."""
    final_dir = os.path.join(run_dir, "06_final")
    order = sorted(scene_files)
    dip_after = order[math.ceil(len(order) / 2) - 1]
    video = os.path.join(final_dir, "video.mp4")
    if os.path.exists(video) and os.path.getsize(video) > 100000:
        return video, dip_after
    black = os.path.join(final_dir, "dip.mp4")
    if not os.path.exists(black):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"color=black:s={W}x{H}:r=30:d=0.4"] + enc_args(W, H) +
                       [black], capture_output=True, timeout=120, check=True)
    seq = []
    for sid in order:
        seq += scene_files[sid]
        if sid == dip_after:
            seq.append(black)
    _concat(seq, video, W, H, run_dir)
    return video, dip_after


def typography(run_dir, video, total, W, H):
    """Fades + title card + end tag in ONE re-encode. Two text moments max."""
    final_dir = os.path.join(run_dir, "06_final")
    typed = os.path.join(final_dir, "video_typed.mp4")
    if os.path.exists(typed) and os.path.getsize(typed) > 100000:
        return typed
    script = json.load(open(os.path.join(run_dir, "02_script.json")))
    title = (script.get("title") or "").upper()
    outro = script["scenes"][-1].get("on_screen", "")
    end_line = outro.upper() if outro else ""
    fs_t = 62 if W == 1920 else 52
    fs_e = 46 if W == 1920 else 40
    x_t = int(W * 0.07)
    y_t = int(H * 0.72)
    filters = [f"fade=t=in:d=0.8,fade=t=out:st={max(total - 1.3, 0):.3f}:d=1.3"]
    if title:
        t_esc = title.replace("'", chr(92) + "'").replace(":", chr(92) + ":")
        filters.append(
            f"drawtext=fontfile={FONT}:text='{t_esc}'"
            f":fontsize={fs_t}:fontcolor=white:borderw=0"
            f":shadowx=2:shadowy=2:shadowcolor=black@0.7"
            f":x={x_t}:y={y_t}"
            f":alpha='if(lt(t,0.9),0,if(lt(t,1.5),(t-0.9)/0.6,"
            f"if(lt(t,4.2),1,if(lt(t,4.8),(4.8-t)/0.6,0))))'")
    if end_line:
        st = max(total - 4.6, 0)
        e_esc = end_line.replace("'", chr(92) + "'").replace(":", chr(92) + ":")
        filters.append(
            f"drawtext=fontfile={FONT}:text='{e_esc}'"
            f":fontsize={fs_e}:fontcolor=white:borderw=0"
            f":shadowx=2:shadowy=2:shadowcolor=black@0.7"
            f":x=(w-tw)/2:y=(h-th)/2"
            f":alpha='if(lt(t,{st + 0.6:.2f}),0,if(lt(t,{st + 1.4:.2f}),"
            f"(t-{st + 0.6:.2f})/0.8,if(lt(t,{st + 3.4:.2f}),1,"
            f"if(lt(t,{st + 4.2:.2f}),({st + 4.2:.2f}-t)/0.8,0))))'")
    vf = ",".join(filters) + ",format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-an", typed], capture_output=True, timeout=1500, check=True)
    return typed


def pass_c(run_dir, starts, total, video):
    """Narration timeline + fixed-level bed + R128 loudnorm -> final.mp4."""
    MIXD = chr(91) + "mixd" + chr(93)   # label built at runtime (transport-safe)
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    music = json.load(open(os.path.join(run_dir, "05_music.json")))
    bed = music["path"]
    final_dir = os.path.join(run_dir, "06_final")
    final = os.path.join(run_dir, "final.mp4")
    inputs = ["-i", bed]
    for t in timings:
        inputs += ["-i", t["wav"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"aloop=loop=-1:size=2e+09,atrim=0:{total + 1:.2f},"
          f"volume=0.13[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        sid = t["id"]
        st = starts[sid] if sid in starts else starts[str(sid)]
        ms = int((st + 0.30) * 1000)
        # narration normalized to a strong, speech-forward level
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"loudnorm=I=-15:TP=-1.5:LRA=11,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:"
              f"normalize=0[nar]")
    # bed sits ~18 dB under narration (static level; no sidechain pumping)
    fc.append(f"[bed][nar]amix=inputs=2:duration=longest:normalize=0{MIXD}")
    fc.append(f"{MIXD}loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{total:.2f},"
              f"afade=t=out:st={max(total - 1.0, 0):.2f}:d=1.0[aout]")
    script = os.path.join(final_dir, "passc.txt")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    mix_wav = os.path.join(final_dir, "mix.wav")
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
    durs = scene_durations(run_dir)
    starts, total = layout(durs, dip_after=None)  # placeholder, fixed in pass_b
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    scene_files = pass_a(run_dir, durs, W, H)
    video, dip_after = pass_b(run_dir, scene_files, durs, starts, total, W, H)
    starts, total = layout(durs, dip_after)
    json.dump({"durations": durs, "starts": starts, "total": total,
               "act_break_after_scene": dip_after},
              open(os.path.join(run_dir, "06_timeline.json"), "w"), indent=1)
    typed = typography(run_dir, video, total, W, H)
    final = pass_c(run_dir, starts, total, typed)
    return {"final": final, "total": total, "scenes": len(durs)}


if __name__ == "__main__":
    print("render done:", run(sys.argv[1]))
