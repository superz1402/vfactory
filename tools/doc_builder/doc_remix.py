#!/usr/bin/env python3
"""Regenerate the doc audio mix with verified lengths."""
import json, os, subprocess

RUN = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3"
F = os.path.join(RUN, "06_final")
BED = "/home/z/my-project/vfactory/footage/music/emotional-respect.mp3"
MIXD = chr(91) + "mixd" + chr(93)

timings = json.load(open(os.path.join(RUN, "03_timings.json")))["timings"]
tl = json.load(open(os.path.join(RUN, "06_timeline.json")))
starts, total = tl["starts"], tl["total"]
# actual video duration on disk
vdur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                             "format=duration", "-of", "csv=p=0",
                             os.path.join(F, "video_typed.mp4")],
                            capture_output=True, text=True).stdout.strip())
print("video:", vdur, "timeline total:", total)

inputs = ["-i", BED]
for t in timings:
    inputs += ["-i", t["audio"]]
fc = [f"[0:a]aformat=channel_layouts=stereo,aresample=48000,"
      f"atrim=7.0:{7.0 + vdur + 0.5:.2f},volume=0.13[bed]"]
mix_in = ""
for n, t in enumerate(timings, 1):
    ms = int((starts[t["id"]] + 0.35) * 1000)
    fc.append(f"[{n}:a]aformat=channel_layouts=stereo,aresample=48000,"
              f"loudnorm=I=-15:TP=-1.5:LRA=11,adelay={ms}|{ms}[s{n}]")
    mix_in += f"[s{n}]"
fc.append(f"{mix_in}amix=inputs={len(timings)}:duration=longest:"
          f"normalize=0[nar]")
fc.append(f"[bed][nar]amix=inputs=2:duration=longest:normalize=0{MIXD}")
fc.append(f"{MIXD}loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{vdur:.2f},"
          f"afade=t=out:st={max(vdur - 1.3, 0):.2f}:d=1.3[aout]")
script = os.path.join(F, "passc2.txt")
with open(script, "w") as fh:
    fh.write(";".join(fc))
mix_wav = os.path.join(F, "mix2.wav")
r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs +
                   ["-filter_complex_script", script, "-map", "[aout]",
                    "-ar", "48000", mix_wav], capture_output=True, text=True)
print("mix rc:", r.returncode, r.stderr[-400:] if r.returncode else "")
d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "csv=p=0", mix_wav], capture_output=True, text=True).stdout
print("mix2.wav duration:", d.strip())

final = os.path.join(RUN, "final.mp4")
r2 = subprocess.run(["ffmpeg", "-y", "-v", "error",
                     "-i", os.path.join(F, "video_typed.mp4"), "-i", mix_wav,
                     "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                     "-c:a", "aac", "-b:a", "192k", "-shortest",
                     "-movflags", "+faststart", final],
                    capture_output=True, text=True)
print("mux rc:", r2.returncode, r2.stderr[-300:] if r2.returncode else "")
d2 = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                     "format=duration,size", "-of", "csv=p=0", final],
                    capture_output=True, text=True).stdout
print("FINAL:", d2.strip())
