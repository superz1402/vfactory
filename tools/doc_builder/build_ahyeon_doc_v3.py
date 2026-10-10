#!/usr/bin/env python3
"""AHYEON mini-documentary v3 — hand-built timeline from verified footage.

Sources (all real, credited):
  ep1   hCgZqFscMp0  BABYMONSTER 'Last Evaluation' EP.1 (YG Entertainment)
  ep8   Gi0ezbc0OwU  BABYMONSTER 'Last Evaluation' EP.8 (YG Entertainment)
  vmsn  UESsLN8i63w  Individual Vocal Mission graphic (YG Entertainment)
  dang  xw7Y2gviWbA  AHYEON 'Dangerously' COVER (YG Entertainment, 78M views)
  bwys  ysJCTCQYJyg  AHYEON 15-year-old eval performance (viral, 18M)
  vamp  hSgMTFImB7c  AHYEON 'vampire' Limousine Service (MBC)
  mons  MsOOG4Q5HvQ  AHYEON 'Monster' Begin Again Open Mic (KBS)
  mama  1TYYOw-815A  MAMA 2025 'Golden' BABYMONSTER (Mnet)
  prob  e3U5Cz_ZASU  'Problem' 2026 WORLD TOUR CHOOM (fan 4K cam)
  mfc   ItDZsiOhG6M  MOON fancam MCOUNTDOWN (Mnet, vertical)
  cfc   OMeeqIge53E  CHOOM fancam Inkigayo (SBS, vertical)
  pfc   8l5q7ZmZN-s  PSYCHO fancam WORLD TOUR (vertical)
  bts   Kxb0aUqmex0  Last Evaluation BTS #2 (dorm)
Grammar: hard cuts, one act-break dip after s4, fade in/out, title lower-third
in s1 only, credits card at end, no captions, no zoompan, narration forward.
"""
import json, os, subprocess, sys

RUN = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3"
DL = "/home/z/my-project/ytdl-agent/downloads"
F = os.path.join(RUN, "06_final")
os.makedirs(F, exist_ok=True)
W, H, FPS = 1920, 1080, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BED = "/home/z/my-project/vfactory/footage/music/emotional-respect.mp3"
MIXD = chr(91) + "mixd" + chr(93)

SRC = {
    "ep1":  f"{DL}/hCgZqFscMp0.mp4",
    "ep8":  f"{DL}/Gi0ezbc0OwU.mp4",
    "vmsn": f"{DL}/UESsLN8i63w.mp4",
    "dang": f"{DL}/xw7Y2gviWbA.mp4",
    "bwys": f"{DL}/ysJCTCQYJyg.mp4",
    "vamp": f"{DL}/hSgMTFImB7c.mp4",
    "mons": f"{DL}/MsOOG4Q5HvQ.mp4",
    "mama": f"{DL}/1TYYOw-815A.mp4",
    "prob": f"{DL}/e3U5Cz_ZASU.mp4",
    "mfc":  f"{DL}/ItDZsiOhG6M.mp4",
    "cfc":  f"{DL}/OMeeqIge53E.mp4",
    "pfc":  f"{DL}/8l5q7ZmZN-s.mp4",
    "bts":  f"{DL}/Kxb0aUqmex0.mp4",
}
CREDITS = "/home/z/my-project/repo-work/research/ahyeon/DOC_CREDITS.json"

# (scene, [(tag, src, in_sec, dur, mode)])  mode: fit | vpad | lpad
CUTS = [
    ("s1", [
        ("a1", "ep1", 1.0, 7.0, "fit"),
        ("a2", "ep1", 15.0, 2.6, "fit"),
        ("a3", "ep1", 262.0, 3.2, "fit"),
    ]),
    ("s2", [
        ("b1", "ep1", 375.0, 4.5, "fit"),
        ("b2", "ep1", 120.0, 3.5, "fit"),
        ("b3", "vmsn", 1.0, 2.5, "fit"),
        ("b4", "ep1", 60.0, 4.5, "fit"),
        ("b5", "ep1", 630.0, 4.5, "fit"),
        ("b6", "ep1", 973.0, 3.7, "fit"),
    ]),
    ("s3", [
        ("c1", "dang", 30.0, 8.5, "fit"),
        ("c2", "bwys", 4.0, 3.5, "fit"),
        ("c3", "bwys", 36.0, 2.45, "fit"),
    ]),
    ("s4", [
        ("d1", "ep8", 1267.0, 4.6, "fit"),
        ("d2", "ep8", 144.0, 4.0, "fit"),
        ("d3", "ep8", 1427.0, 3.0, "fit"),
        ("d4", "bts", 84.0, 3.0, "fit"),
    ]),
    ("s5", [
        ("e1", "vamp", 10.0, 6.5, "lpad"),
        ("e2", "vamp", 100.0, 4.5, "lpad"),
        ("e3", "vamp", 42.0, 3.2, "lpad"),
        ("e4", "vamp", 178.0, 3.0, "lpad"),
    ]),
    ("s6", [
        ("f1", "mons", 40.0, 4.5, "fit"),
        ("f2", "mama", 100.0, 4.5, "fit"),
        ("f3", "mama", 89.0, 2.5, "fit"),
        ("f4", "mons", 148.0, 3.5, "fit"),
    ]),
    ("s7", [
        ("g1", "prob", 121.0, 5.0, "fit"),
        ("g2", "prob", 130.0, 4.5, "fit"),
        ("g3", "prob", 24.0, 2.7, "fit"),
        ("g4", "mfc", 104.0, 2.7, "vpad"),
    ]),
    ("s8", [
        ("h1", "pfc", 30.0, 4.5, "vpad"),
        ("h2", "cfc", 34.0, 4.5, "vpad"),
        ("h3", "prob", 136.0, 4.5, "fit"),
    ]),
    ("s9", [
        ("i1", "mons", 154.0, 4.0, "fit"),
        ("i2", "ep8", 1287.0, 3.5, "fit"),
        ("i3", "vamp", 315.0, 4.5, "lpad"),
    ]),
]
SCENE_TAIL = {"s1": 1.2, "s2": 1.2, "s3": 1.3, "s4": 1.3, "s5": 1.2,
              "s6": 1.3, "s7": 1.3, "s8": 1.3, "s9": 1.2}
CREDITS_DUR = 5.5
DIP_AFTER = "s4"


def enc(mode):
    if mode == "fit":
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},fps={FPS}")
    elif mode == "vpad":
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},gblur=sigma=24[bg];[b]scale=-2:{H}[fg];"
              f"[bg][fg]overlay=(W-w)/2:0,fps={FPS}")
    else:  # lpad (2.35:1 -> cinematic pad)
        vf = (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H},gblur=sigma=24[bg];[b]scale={W}:-2[fg];"
              f"[bg][fg]overlay=0:(H-h)/2,fps={FPS}")
    return ["-vf", vf + ",format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-an"]


def pass_a():
    clip_dir = os.path.join(F, "clips")
    os.makedirs(clip_dir, exist_ok=True)
    files, durs = [], []
    for sid, shots in CUTS:
        for tag, src, tin, dur, mode in shots:
            out = os.path.join(clip_dir, f"{sid}_{tag}.mp4")
            if not (os.path.exists(out) and os.path.getsize(out) > 10000):
                cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{tin:.3f}",
                       "-i", SRC[src], "-t", f"{dur:.3f}"] + enc(mode) + [out]
                subprocess.run(cmd, capture_output=True, timeout=600, check=True)
            files.append(out)
            durs.append(round(dur, 3))
        if sid == DIP_AFTER:
            pass
    return files, durs


def scene_timeline():
    timings = json.load(open(os.path.join(RUN, "03_timings.json")))["timings"]
    tdur = {t["id"]: t["dur"] for t in timings}
    durs, starts, acc = {}, {}, 0.0
    for sid, shots in CUTS:
        shots_sum = sum(s[3] for s in shots)
        need = max(shots_sum, tdur[sid] + SCENE_TAIL[sid])
        durs[sid] = round(need, 3)
        starts[sid] = round(acc, 3)
        acc += need
        if sid == DIP_AFTER:
            acc += 0.4
    total = round(acc + CREDITS_DUR, 3)
    return durs, starts, total


def credits_clip():
    out = os.path.join(F, "credits.mp4")
    if os.path.exists(out) and os.path.getsize(out) > 10000:
        return out
    lines = [
        ("THE VOICE - JUNG AHYEON", 64, 250),
        ("A FAN DOCUMENTARY", 30, 380),
        ("FOOTAGE: YG ENTERTAINMENT / BABYMONSTER - LAST EVALUATION", 26, 560),
        ("BEGIN AGAIN OPEN MIC - MAMA - MBC - MNET - SBS - WORLD TOUR", 26, 610),
        ("MUSIC: ROYALTY-FREE", 26, 660),
    ]
    parts = []
    for text, fs, y in lines:
        esc = text.replace("'", chr(92) + "'").replace(":", chr(92) + ":")
        parts.append(f"drawtext=fontfile={FONT}:text='{esc}':fontsize={fs}"
                     f":fontcolor=white:x=(w-tw)/2:y={y}")
    vf = ",".join(parts) + ",format=yuv420p"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=black:s={W}x{H}:r={FPS}:d={CREDITS_DUR}",
                    "-vf", vf, "-c:v", "libx264", "-preset", "fast",
                    "-crf", "18", "-an", out], capture_output=True, check=True)
    return out


def pass_b(files, durs):
    dip = os.path.join(F, "dip.mp4")
    if not (os.path.exists(dip) and os.path.getsize(dip) > 1000):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"color=black:s={W}x{H}:r={FPS}:d=0.4",
                        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                        "-an", dip], capture_output=True, check=True)
    seq, k = [], 0
    for sid, shots in CUTS:
        for _ in shots:
            seq.append(files[k]); k += 1
        if sid == DIP_AFTER:
            seq.append(dip)
    seq.append(credits_clip())
    lst = os.path.join(F, "concat.txt")
    with open(lst, "w") as fh:
        for fpath in seq:
            fh.write(f"file '{os.path.abspath(fpath)}'\n")
    video = os.path.join(F, "video.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-c", "copy", video],
                       capture_output=True, timeout=600)
    if r.returncode != 0 or os.path.getsize(video) < 100000:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat",
                        "-safe", "0", "-i", lst, "-vf",
                        f"fps={FPS},format=yuv420p", "-c:v", "libx264",
                        "-preset", "fast", "-crf", "18", "-an", video],
                       capture_output=True, timeout=1200, check=True)
    return video


def typography(video, total):
    typed = os.path.join(F, "video_typed.mp4")
    if os.path.exists(typed) and os.path.getsize(typed) > 100000:
        return typed
    grade = ("eq=contrast=1.05:saturation=1.07,vignette=PI/5.5")
    title = "AHYEON"
    sub = "THE VOICE OF BABYMONSTER"
    esc_t = title.replace("'", chr(92) + "'")
    esc_s = sub.replace("'", chr(92) + "'")
    alpha = ("if(lt(t,1.6),0,if(lt(t,2.3),(t-1.6)/0.7,"
             "if(lt(t,5.6),1,if(lt(t,6.3),(6.3-t)/0.7,0))))")
    filters = [
        grade,
        f"fade=t=in:d=0.8,fade=t=out:st={total - 1.4:.3f}:d=1.4",
        f"drawtext=fontfile={FONT}:text='{esc_t}':fontsize=92:fontcolor=white"
        f":borderw=0:shadowx=2:shadowy=3:shadowcolor=black@0.75"
        f":x=120:y={int(H * 0.70)}:alpha='{alpha}'",
        f"drawtext=fontfile={FONT}:text='{esc_s}':fontsize=34:fontcolor=white"
        f":borderw=0:shadowx=1:shadowy=2:shadowcolor=black@0.75"
        f":x=124:y={int(H * 0.70) + 108}:alpha='{alpha}'",
        "format=yuv420p",
    ]
    vf = ",".join(filters)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", vf,
                    "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                    "-an", typed], capture_output=True, timeout=1500, check=True)
    return typed


def pass_c(starts, total, video):
    timings = json.load(open(os.path.join(RUN, "03_timings.json")))["timings"]
    inputs = ["-i", BED]
    for t in timings:
        inputs += ["-i", t["audio"]]
    fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
          f"atrim=7.0:{total + 2:.2f},volume=0.13[bed]"]
    mix_in = ""
    for n, t in enumerate(timings, 1):
        sid = t["id"]
        ms = int((starts[sid] + 0.35) * 1000)
        fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
                  f"loudnorm=I=-15:TP=-1.5:LRA=11,"
                  f"adelay={ms}|{ms}[s{n}]")
        mix_in += f"[s{n}]"
    fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:"
              f"normalize=0[nar]")
    fc.append(f"[bed][nar]amix=inputs=2:duration=longest:normalize=0{MIXD}")
    fc.append(f"{MIXD}loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{total:.2f},"
              f"afade=t=out:st={max(total - 1.2, 0):.2f}:d=1.2[aout]")
    script = os.path.join(F, "passc.txt")
    with open(script, "w") as fh:
        fh.write(";".join(fc))
    mix_wav = os.path.join(F, "mix.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex_script", script, "-map", "[aout]",
                    "-ar", "48000", mix_wav],
                   capture_output=True, timeout=900, check=True)
    final = os.path.join(RUN, "final.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-i", mix_wav,
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", final],
                   capture_output=True, timeout=600, check=True)
    return final


def main():
    files, durs = pass_a()
    print(f"pass_a: {len(files)} clips cut")
    durs, starts, total = scene_timeline()
    json.dump({"durations": durs, "starts": starts, "total": total},
              open(os.path.join(RUN, "06_timeline.json"), "w"), indent=1)
    print("timeline:", json.dumps({"total": total}))
    video = pass_b(files, durs)
    print("pass_b assembled:", video)
    typed = typography(video, total)
    print("typography done")
    final = pass_c(starts, total, typed)
    print("FINAL:", final)
    return final


if __name__ == "__main__":
    main()
