#!/usr/bin/env python3
"""srt.py — build subtitles.srt from 03_timings.json word timings.

Word timings exist exactly (edge) or approximately (zai, proportional).
Caption chunks: max ~8 words / 3.8s, snapped to word boundaries, shifted by
the unit's start offset on the global timeline.
"""
import json
import os
import sys


def _chunks(words, max_words=8, max_dur=3.8):
    out, cur = [], []
    for w in words:
        cur.append(w)
        span = w["t1"] - cur[0]["t0"]
        if len(cur) >= max_words or span >= max_dur or w["w"].endswith((".", "!", "?")):
            out.append({"t0": cur[0]["t0"], "t1": w["t1"],
                        "text": " ".join(x["w"] for x in cur)})
            cur = []
    if cur:
        out.append({"t0": cur[0]["t0"], "t1": cur[-1]["t1"],
                    "text": " ".join(x["w"] for x in cur)})
    return out


def _approx_chunks(narration, dur, offset):
    """Proportional fallback: 8-word chunks spread evenly over duration."""
    ws = narration.split()
    step = max(1, min(8, int(len(ws) * 3.8 / max(dur, 1))))
    out = []
    n_chunks = max(1, -(-len(ws) // step))
    cd = dur / n_chunks
    for i in range(n_chunks):
        text = " ".join(ws[i * step:(i + 1) * step]).strip()
        if text:
            out.append({"t0": offset + i * cd, "t1": offset + (i + 1) * cd - 0.08,
                        "text": text})
    return out


def build(run_dir):
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    units = plan.get("chapters") or plan.get("scenes")
    kind = timings.get("kind", "scenes")
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    # global start of each unit
    starts = {}
    if kind == "scenes":
        for sid, st in tl["starts"].items():
            starts[int(sid)] = st
    else:
        for ch in tl["chapters"]:
            starts[ch["id"]] = ch["start"]

    cues = []
    for t in timings["units"]:
        uid, off = t["id"], starts.get(t["id"], 0.0)
        udur = t["audio"]
        if t.get("words"):
            local = _chunks(t["words"])
            for c in local:
                cues.append((off + c["t0"], off + c["t1"], c["text"]))
        else:
            narr = next((u["narration"] for u in units if u["id"] == uid), "")
            cues.extend((c["t0"], c["t1"], c["text"])
                        for c in _approx_chunks(narr, udur, off))

    cues.sort(key=lambda c: c[0])

    def fmt(ts):
        h, rem = divmod(max(ts, 0), 3600)
        m, s = divmod(rem, 60)
        return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int((s % 1) * 1000):03d}"

    path = os.path.join(run_dir, "subtitles.srt")
    with open(path, "w", encoding="utf-8") as fh:
        for i, (a, b, txt) in enumerate(cues, 1):
            fh.write(f"{i}\n{fmt(a)} --> {fmt(min(b, a + 6.0))}\n{txt}\n\n")
    return path, len(cues)


if __name__ == "__main__":
    p, n = build(sys.argv[1])
    print(f"{p}: {n} cues")
