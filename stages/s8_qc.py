#!/usr/bin/env python3
"""Stage 8: QC gate — automated failure checks BEFORE delivery.
Ported from ai-video-factory's qc.py philosophy: a run that fails any check
must never be delivered. Checks:
  1. resolution matches target aspect
  2. duration drift vs plan (<= 1.5s)
  3. dark-frame check (sampled mean luma)
  4. no long digital silence (> 6s)
  5. integrated loudness within -16 +/- 2.5 LUFS
  6. narration audibility via ASR on two sampled chunks
  7. footage provenance: every shot ahyeon_verified with credit
  8. music provenance: real licensed track (never 'synthesized')
Output: qc_report.json; raises SystemExit on fail.
"""
import json, math, os, re, subprocess, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASR_TIMEOUT = 120


def _probe(path):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
         "-show_streams", path], timeout=60)
    return json.loads(out)


def _luma_samples(path, n=6):
    """Mean luma via PNG frame extraction + PIL (signalstats-in-loop proved
    unreliable: returned near-black YAVG for frames that measure 150+)."""
    means = []
    for i in range(n):
        try:
            dur = float(subprocess.check_output(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path], timeout=30).decode().strip())
        except Exception:
            dur = 0
        t = dur * (i + 0.5) / n
        tmp = tempfile.mktemp(suffix=".png", dir="/tmp")
        try:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}",
                            "-i", path, "-frames:v", "1", tmp],
                           timeout=60, check=True)
            from PIL import Image
            im = Image.open(tmp).convert("L")
            px = list(im.getdata())
            means.append(sum(px) / len(px) if px else 0)
        except Exception:
            means.append(0)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    return means


def _silence_max(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-af",
                        "silencedetect=noise=-45dB:d=6", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    silences = re.findall(r"silence_duration: ([0-9.]+)", r.stderr or "")
    return max([float(s) for s in silences] or [0.0])


def _loudness(path):
    r = subprocess.run(["ffmpeg", "-i", path, "-af", "loudnorm=print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True,
                       timeout=600)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr or "", re.S)
    if not m:
        return None
    try:
        return float(json.loads(m.group(0))["input_i"])
    except Exception:
        return None


def _asr_words(path, ss, t):
    """ASR a chunk; retries on 429 rate-limit (backoff 60s/120s)."""
    import time as _time
    tmp = tempfile.mktemp(suffix=".wav", dir="/tmp")
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(ss),
                        "-t", str(t), "-i", path, "-vn", "-ac", "1",
                        "-ar", "16000", tmp], timeout=120, check=True)
        for attempt in range(3):
            r = subprocess.run(["z-ai", "asr", "--file", tmp,
                                "-o", tmp + ".json"],
                               capture_output=True, text=True,
                               timeout=ASR_TIMEOUT)
            if os.path.exists(tmp + ".json"):
                txt = json.load(open(tmp + ".json")).get("text", "")
                return len(re.findall(r"[A-Za-z]{2,}", txt)), txt[:120]
            if "429" in (r.stderr or "") or "429" in (r.stdout or ""):
                _time.sleep(60 * (attempt + 1))
                continue
            break
        return 0, ""
    except Exception as e:
        return 0, f"asr-error: {e}"
    finally:
        for p in (tmp, tmp + ".json"):
            if os.path.exists(p):
                os.remove(p)


def evaluate(run_dir):
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    final = os.path.join(run_dir, "final.mp4")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    info = _probe(final)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    W, H = (v.get("width"), v.get("height")) if v else (0, 0)
    want = ("1080", "1920") if topic.get("aspect") == "9:16" else ("1920", "1080")
    add("resolution", str(W) == want[0] and str(H) == want[1],
        f"{W}x{H} (want {want[0]}x{want[1]})")
    dur = float(info["format"]["duration"])
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    drift = abs(dur - tl["total"])
    add("duration_drift", drift <= 1.5, f"{dur:.2f}s vs plan {tl['total']:.2f}s "
        f"(drift {drift:.2f}s)")

    lumas = _luma_samples(final)
    add("dark_frames", min(lumas) > 30 and sorted(lumas)[len(lumas) // 2] > 70,
        f"sampled mean luma {[round(x) for x in lumas]}")

    sil = _silence_max(final)
    add("no_long_silence", sil < 6.0, f"longest silence {sil:.1f}s (cap 6s)")

    lufs = _loudness(final)
    add("loudness", lufs is not None and -18.5 <= lufs <= -13.5,
        f"integrated {lufs} LUFS (target -16 +/- 2.5)")

    w1, t1 = _asr_words(final, 1.0, 9.0)
    w2, t2 = _asr_words(final, max(dur * 0.55, 10), 9.0)
    add("narration_audible", max(w1, w2) >= 6,
        f"ASR words chunk1={w1} chunk2={w2} | '{t1[:60]}' | '{t2[:60]}'")

    media = json.load(open(os.path.join(run_dir, "04_media.json")))["manifest"]
    shots = [s for m in media.values() for s in m["shots"]]
    bad = [s["source_video_id"] for s in shots
           if not s.get("ahyeon_verified") or not s.get("credit")]
    add("footage_provenance", not bad,
        f"{len(shots)} shots, all ahyeon_verified + credited"
        if not bad else f"unverified shots: {bad}")

    music = json.load(open(os.path.join(run_dir, "05_music.json")))
    src = (music.get("license", "") + " " + music.get("source_track", "")).lower()
    add("music_real", "synth" not in src and bool(music.get("license")),
        f"{music.get('title', '')[:50]} | {music.get('license', '')[:50]}")

    report = {"status": "pass" if all(c["passed"] for c in checks) else "fail",
              "checks": checks, "final": final,
              "generated": __import__("time").strftime("%Y-%m-%d %H:%M:%S")}
    json.dump(report, open(os.path.join(run_dir, "qc_report.json"), "w"), indent=1)
    for c in checks:
        print(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
    return report


def run(run_dir):
    print(f"[qc] evaluating {run_dir}")
    report = evaluate(run_dir)
    if report["status"] != "pass":
        raise SystemExit("QC FAILED — delivery blocked. See qc_report.json")
    print("[qc] ALL CHECKS PASS")
    return report


if __name__ == "__main__":
    run(sys.argv[1])
