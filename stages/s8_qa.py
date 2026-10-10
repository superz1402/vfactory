#!/usr/bin/env python3
"""Stage 8: QA gates — hard numbers against reference benchmarks.

Gates (from measured BPM Stories / KOOKIELIT metrics, DESIGN_V2.md):
  cut cadence : >=7 cuts/min overall, ASL <= 6.5s
  source mix  : >=55% of shots are real video (stills <=45%)
  audio       : integrated LUFS in [-14.0, -10.0], true peak <= -0.6 dB
  dead air    : zero silences > 1.3s
  integrity   : final.mp4 decodes clean, duration within ±3s of timeline
  duration    : >= 60s
Overall: pass | fail (any gate) | conditional (documented soft misses).
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _ffprobe_dur(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", p], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def cut_metrics(final, dur):
    out_f = os.path.join(os.path.dirname(final), "qa_cuts.txt")
    cmd = (f'ffmpeg -hide_banner -nostats -i "{final}" '
           f'-vf "fps=4,scale=256:-2,select=\'gt(scene,0.30)\',showinfo" '
           f'-an -f null /dev/null 2>{out_f}')
    subprocess.run(cmd, shell=True, timeout=1200)
    pts = sorted(set(float(m.group(1)) for m in
                     re.finditer(r"pts_time:([\d.]+)", open(out_f).read())))
    lens, prev = [], 0.0
    for p in pts + [dur]:
        lens.append(p - prev)
        prev = p
    lens = [l for l in lens if l > 0.15]
    return {"n_cuts": len(pts),
            "cuts_per_min": round(len(pts) / max(0.1, dur / 60), 1),
            "asl_s": round(sum(lens) / len(lens), 2) if lens else dur}


def audio_metrics(final):
    ebu = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", final,
                          "-af", "ebur128=peak=true", "-f", "null", "/dev/null"],
                         capture_output=True, text=True, timeout=900)
    # ebur128 prints a live table where the first rows are ~-70 LUFS;
    # the authoritative value is the LAST occurrence (Summary block)
    I_vals = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", ebu.stderr)
    P_vals = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", ebu.stderr)
    sil = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", final,
                          "-af", "silencedetect=noise=-35dB:d=1.3", "-f", "null", "/dev/null"],
                         capture_output=True, text=True, timeout=900)
    n_sil = len(re.findall(r"silence_duration", sil.stderr))
    return {"lufs": float(I_vals[-1]) if I_vals else None,
            "true_peak": float(P_vals[-1]) if P_vals else None,
            "silences_gt_1_3s": n_sil}


def decode_clean(final):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", final, "-f", "null", "/dev/null"],
                       capture_output=True, text=True, timeout=900)
    return r.returncode == 0 and "Error" not in (r.stderr or "")


def _source_stats(run_dir):
    """Source mix from either pipeline: stock (04_shots.json) or charmedia
    (04_charmedia.json — every cut is face-verified real video, no stills)."""
    sp = os.path.join(run_dir, "04_shots.json")
    cp = os.path.join(run_dir, "04_charmedia.json")
    if os.path.exists(sp):
        return json.load(open(sp))["stats"]
    if os.path.exists(cp):
        cm = json.load(open(cp))
        n = sum(len(v.get("cuts", [])) for v in cm.get("scenes", {}).values())
        return {"video_shots": n, "stills": 0, "still_frac": 0.0,
                "note": f"charmedia: {n} face-verified video cuts (0 stills)"}
    return {"video_shots": 0, "stills": 0, "still_frac": 1.0,
            "note": "unknown source mix"}


def run(run_dir):
    final = os.path.join(run_dir, "final.mp4")
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    dur = _ffprobe_dur(final)

    checks = []

    def gate(name, ok, evidence, severity="hard"):
        checks.append({"name": name, "ok": bool(ok), "evidence": evidence,
                       "severity": severity})

    gate("duration>=60s", dur >= 60, f"{dur:.1f}s")
    gate("duration_matches_timeline", abs(dur - tl["total"]) <= 3.0,
         f"final {dur:.1f}s vs timeline {tl['total']:.1f}s")
    gate("decode_clean", decode_clean(final), "ffmpeg error scan")

    cm = cut_metrics(final, dur)
    gate("cuts_per_min>=7", cm["cuts_per_min"] >= 7,
         f"{cm['cuts_per_min']} cpm (refs: 13.1-13.5)")
    gate("asl<=6.5s", cm["asl_s"] <= 6.5, f"ASL {cm['asl_s']}s (refs: 4.4-4.6s)")

    stats = _source_stats(run_dir)
    gate("video_shots>=55pct", stats["still_frac"] <= 0.45,
         f"{stats['video_shots']} video / {stats['stills']} stills "
         f"({round(100-stats['still_frac']*100)}% video)")

    am = audio_metrics(final)
    gate("lufs_in_range", am["lufs"] is not None and -14.0 <= am["lufs"] <= -10.0,
         f"{am['lufs']} LUFS (refs: -10.6, spec -12.5)")
    gate("true_peak<=-0.6", am["true_peak"] is not None and am["true_peak"] <= -0.6,
         f"{am['true_peak']} dBFS (ref: +0.4)")
    gate("no_dead_air", am["silences_gt_1_3s"] == 0,
         f"{am['silences_gt_1_3s']} silences >1.3s (refs: 0)")

    hard_fails = [c for c in checks if not c["ok"] and c["severity"] == "hard"]
    overall = "pass" if not hard_fails else "fail"
    # frame samples for eyeball review
    fdir = os.path.join(run_dir, "qa_frames")
    os.makedirs(fdir, exist_ok=True)
    for i, ts in enumerate([dur*0.04, dur*0.25, dur*0.5, dur*0.72, dur*0.93]):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-ss", str(ts),
                        "-i", final, "-frames:v", "1", "-q:v", "3",
                        os.path.join(fdir, f"qa{i}.jpg")], capture_output=True)
    report = {"overall": overall, "duration": round(dur, 1), "cuts": cm,
              "audio": am, "source_mix": stats, "checks": checks,
              "frames": fdir}
    json.dump(report, open(os.path.join(run_dir, "07_qa.json"), "w"), indent=1)
    return report


if __name__ == "__main__":
    rep = run(sys.argv[1])
    print(json.dumps({k: v for k, v in rep.items() if k != "frames"}, indent=1))
    sys.exit(0 if rep["overall"] == "pass" else 2)
