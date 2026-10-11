#!/usr/bin/env python3
"""Stage 6 (smart render): narration-aligned multi-shot documentary cut.

Doctrine: hard cuts ON the words (real documentaries cut on speech, not
slideshows), alternating punch-in/punch-out for shot variety, NO cheap
overlay text. Audio: narration + sidechain-ducked score, loudnorm -14 LUFS.

Pass A: per-shot trim -> scale/crop 1920x1080@30 -> alternating zoom motion
Pass B: concat all shots (hard cuts) + global fade in/out -> video track
Pass C: narration + ducked score -> final.mp4
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

FPS = 30
W, H = 1920, 1080


def sh(cmd, timeout=900):
    import os as _os
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(p.pid), 15)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        return -9, out or "", err or ""


def pass_a(tl, run_dir):
    """Per-shot clips with alternating punch motion."""
    clip_dir = os.path.join(run_dir, "06_final", "clips")
    os.makedirs(clip_dir, exist_ok=True)
    outs = []
    for i, shot in enumerate(tl["shots"]):
        dur = shot["dur"]
        frames = max(int(dur * FPS), 2)
        out = os.path.join(clip_dir, f"shot_{i:03d}.mp4")
        meta = os.path.join(clip_dir, f"shot_{i:03d}.json")
        sig = {"clip": shot["clip"], "in_point": shot["in_point"], "dur": dur}
        cached = (os.path.exists(out) and os.path.getsize(out) > 50_000
                  and os.path.exists(meta)
                  and abs(json.load(open(meta)).get("dur", -1) - dur) < 0.15
                  and json.load(open(meta)).get("clip") == sig["clip"]
                  and abs(json.load(open(meta)).get("in_point", -1) - sig["in_point"]) < 0.01)
        if cached:
            outs.append(out)
            print(f"  shot {i:03d} [cached]")
            continue
        zin = shot.get("punch", "in") == "in"
        # zoompan with d=1 = one output frame per input frame (moving footage,
        # NOT a freeze-frame). Zoom accumulates via the 'zoom' state variable.
        # NOTE: d=frames on video input expands EVERY input frame N times —
        # the classic zoompan freeze-frame trap; never use it for video.
        if zin:
            z = "zoompan=z='min(zoom+0.0006,1.10)':d=1"
        else:
            z = "zoompan=z='if(lte(on,1),1.10,max(zoom-0.0006,1.0))':d=1"
        z += f":x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':s={W}x{H}:fps={FPS}"
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},fps={FPS},{z}")
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-ss", f"{shot['in_point']:.3f}", "-i", shot["file"],
               # EXACT duration: concat plays every file whole, so any pad
               # here accumulates per-shot drift against the narration
               "-frames:v", str(frames),
               "-vf", vf, "-an",
               "-c:v", "libx264", "-preset", "medium", "-crf", "19",
               "-pix_fmt", "yuv420p", out]
        rc, _, err = sh(cmd, timeout=600)
        if rc != 0 or not os.path.exists(out):
            raise RuntimeError(f"shot {i} render failed: {err[-300:]}")
        json.dump(sig, open(meta, "w"))
        outs.append(out)
        print(f"  shot {i:03d} {shot['entity']:22s} {dur:5.2f}s <- {shot['clip']}")
    return outs


def pass_b(tl, clips, run_dir):
    """Concat hard cuts + global fades."""
    final_dir = os.path.join(run_dir, "06_final")
    video = os.path.join(final_dir, "video_track.mp4")
    total = tl["video_total"]
    want = sum(1 for _ in tl["shots"])
    have = 0
    if os.path.exists(video):
        rc, out, _ = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                         "-of", "default=noprint_wrappers=1:nokey=1", video], timeout=30)
        try:
            have = 1 if abs(float(out.strip()) - total) < 0.6 else 0
        except ValueError:
            have = 0
    if have:
        # content-aware cache: rebuild if ANY shot file is newer than the track
        newest_shot = max(os.path.getmtime(c) for c in clips)
        if os.path.getmtime(video) >= newest_shot:
            print(f"video track [cached] {video}")
            return video
        print("video track stale (shots changed) — rebuilding")
    lst = os.path.join(final_dir, "clips", "shots.txt")
    with open(lst, "w") as f:
        for c in clips:
            f.write(f"file '{c}'\n")
    fade_out = max(0.0, total - 1.2)
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst,
           "-vf", f"fade=t=in:st=0:d=0.6,fade=t=out:st={fade_out:.2f}:d=1.2,format=yuv420p",
           "-c:v", "libx264", "-preset", "fast", "-crf", "24",
           "-maxrate", "4.5M", "-bufsize", "9M",
           "-t", f"{total:.2f}", video]
    rc, _, err = sh(cmd, timeout=600)
    if rc != 0:
        raise RuntimeError(f"concat failed: {err[-300:]}")
    print(f"video track: {video} ({total:.2f}s)")
    return video


def pass_c(tl, video, run_dir):
    """Narration + ducked score -> final.mp4."""
    final_dir = os.path.join(run_dir, "06_final")
    final = os.path.join(final_dir, "final.mp4")
    score = os.path.join(run_dir, "05_music", "score.wav")
    narr = tl["narration_wav"]
    total = tl["video_total"]
    # narration starts at t=0; score under it; duck score when narration speaks
    fc = ("[0:a][1:a]sidechaincompress=threshold=0.02:ratio=6:attack=25:release=500:makeup=1[bed];"
          "[1:a][bed]amix=inputs=2:duration=first:normalize=0[mix];"
          "[mix]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]")
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-i", score, "-i", narr, "-i", video,
           "-filter_complex", fc,
           "-map", "[aout]", "-map", "2:v",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-t", f"{total:.2f}", "-shortest", final]
    rc, _, err = sh(cmd, timeout=600)
    if rc != 0:
        raise RuntimeError(f"mux failed: {err[-300:]}")
    print(f"final.mp4: {final}")
    return final


def run(run_dir):
    tl = json.load(open(os.path.join(run_dir, "04_smart", "timeline.json")))
    clips = pass_a(tl, run_dir)
    video = pass_b(tl, clips, run_dir)
    final = pass_c(tl, video, run_dir)
    rc, out, _ = sh(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration,size", "-of", "json", final], timeout=30)
    print(out)
    return final


if __name__ == "__main__":
    run(sys.argv[1])
