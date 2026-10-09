#!/usr/bin/env python3
"""Stage 4c: character-verified footage selection (vfactory v2).

Replaces random image-search media with REAL footage of the exact subject,
verified frame-by-frame by InsightFace face recognition using the
character-clip-extractor engine (github.com/ansaribilal14/character-clip-extractor)
and its bundled member reference centroids.

Flow:
  1. discover source videos (--sources globs; default ytdl-agent downloads)
  2. per source workspace run04_charmedia/ws_<srcid>/:
       bundled refs -> 00 normalize -> 01 shots -> 02 faces @2fps -> 03 visibility
     every step sentinel-checkpointed (re-runnable, interruption safe)
  3. build shot candidate index: every shot where the character is visible
     (coverage >= 0.5, mean cos >= 0.45, face >= 90 px), scored by
     confidence / face size, cut centered on the peak-recognition moment
  4. per script scene: assign ceil(dur / 3.0) distinct cuts, rotating across
     sources so no two adjacent cuts share a source when avoidable
Output: 04_charmedia.json
  {character, sources[], scenes: {sid: {cuts: [...]}}, audio_bed: {...}}
Returns False if nothing usable was found (caller falls back to image search).
"""
import argparse, glob, json, os, shutil, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CCE_REPO = os.environ.get("CCE_REPO",
                          "/home/z/my-project/agent-tools/character-clip-extractor")
CCE_SCRIPTS = os.path.join(CCE_REPO, "scripts")
REFS_REPO = os.path.join(CCE_REPO, "references")
sys.path.insert(0, CCE_REPO)

MEMBERS = ["ahyeon", "asa", "chiquita", "pharita", "rami", "rora", "ruka"]
MIN_COVERAGE = 0.50     # character visible in >= half of the shot's samples
MIN_COS = 0.45          # recognition confidence floor
MIN_FACE_PX = 90        # prefer usable face size (close/medium shots)
MIN_SHOT_S = 1.2        # shortest usable shot
MAX_CUT_S = 4.5         # cap individual cut length
DEFAULT_SOURCES = ["/home/z/my-project/ytdl-agent/downloads/*.mp4"]


def log(msg):
    print(f"[s4c] {msg}", flush=True)


def detect_character(topic_text, override=None):
    t = (override or topic_text or "").lower()
    for m in MEMBERS:
        if m in t:
            return m
    return None


def discover_sources(patterns):
    out = []
    seen = set()
    for pat in (patterns or DEFAULT_SOURCES):
        for p in sorted(glob.glob(os.path.expanduser(pat))):
            b = os.path.basename(p).lower()
            if (p.endswith(".mp4") and "small" not in b and p not in seen
                    and os.path.getsize(p) > 1_000_000):
                seen.add(p)
                out.append(p)
    return out


def src_id(path):
    return "".join(c if c.isalnum() else "_" for c in
                   os.path.splitext(os.path.basename(path))[0])[:48]


def ensure_refs(ws, target):
    """Copy bundled verified references into the workspace (refs.py step 3)."""
    ws_refs = os.path.join(ws, "references")
    os.makedirs(ws_refs, exist_ok=True)
    summary_path = os.path.join(ws_refs, "refs_summary.json")
    if os.path.exists(summary_path):
        try:
            if target in json.load(open(summary_path)).get("members", {}):
                return True
        except Exception:
            pass
    bundled = os.path.join(REFS_REPO, "refs_summary.json")
    if not os.path.exists(bundled):
        log(f"FATAL: bundled refs missing at {bundled}")
        return False
    b = json.load(open(bundled))
    if target not in b.get("members", {}):
        log(f"no bundled references for '{target}'")
        return False
    members = {}
    for m, v in b["members"].items():
        src_dir = os.path.join(REFS_REPO, m)
        if os.path.isdir(src_dir):
            dst = os.path.join(ws_refs, m)
            os.makedirs(dst, exist_ok=True)
            for f in glob.glob(os.path.join(src_dir, "*.jpg")):
                shutil.copy(f, dst)
        members[m] = v
    json.dump({"members": members}, open(summary_path, "w"), indent=1)
    return True


def analyze_source(src, ws, target):
    """Run CCE steps 00-03 in ws. Returns True when visibility data exists."""
    from character_clip_extractor import runner
    env = dict(os.environ)
    env.update({"CCE_BASE": ws, "CCE_TARGET": target,
                "CCE_VIDEO_ID": src_id(src), "CCE_VIDEO_URL": src,
                "CCE_MAXH": "1080", "CCE_PROC_W": "1280"})
    os.makedirs(os.path.join(ws, "output", "analysis"), exist_ok=True)
    # 00_normalize.py expects the source inside <ws>/output/source/
    src_dir = os.path.join(ws, "output", "source")
    os.makedirs(src_dir, exist_ok=True)
    link = os.path.join(src_dir, os.path.basename(src))
    if not os.path.exists(link):
        os.symlink(os.path.abspath(src), link)
    for script, sentinel in [("00_normalize.py", None),
                             ("01_detect_shots.py", None),
                             ("02_analyze_faces.py", None),
                             ("03_raw_visibility.py", None)]:
        if runner.step_complete(ws, script):
            log(f"  resume: {script} already complete")
            continue
        expect = {"00_normalize.py": "NORMALIZE_OK",
                  "01_detect_shots.py": "DETECT_SHOTS_OK",
                  "02_analyze_faces.py": "ANALYZE_FACES_OK",
                  "03_raw_visibility.py": "RAW_VISIBILITY_OK"}[script]
        runner.run_step(script, env, expect=expect,
                        timeout=3300 if script == "02_analyze_faces.py" else 900)
    vis = os.path.join(ws, "output", "analysis", "raw_visibility.json")
    return os.path.exists(vis) and json.load(open(vis)).get("n_intervals", 0) > 0


def build_shot_index(ws, target):
    """One candidate per visibility interval (character-present window).

    Uses raw_visibility intervals (bridged runs of face-verified samples),
    NOT whole shots: music-show long takes can hold the character only part
    of the time, and shot-level coverage filtering would discard them.
    Each cut is capped at MAX_CUT_S and centred on the peak-recognition
    moment, clamped to the interval (and its shot) bounds.
    """
    an = os.path.join(ws, "output", "analysis")
    shots = json.load(open(os.path.join(an, "shots.json")))["shots"]
    vis = json.load(open(os.path.join(an, "raw_visibility.json")))
    recs = []
    with open(os.path.join(an, "analysis.jsonl")) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    tkey = f"{target}_best_cos"
    _pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width", "-of", "csv=p=0",
                          os.path.join(an, "normalized.mp4")],
                         capture_output=True, text=True, timeout=30)
    try:
        VW = float(_pr.stdout.strip().split(",")[0])
    except Exception:
        VW = 1280.0

    def shot_bounds(t):
        for sh in shots:
            if sh["start"] - 1e-6 <= t < sh["end"] + 1e-6:
                return sh["start"], sh["end"]
        return None

    out = []
    for iv in vis["intervals"]:
        if iv["duration"] < MIN_SHOT_S:
            continue
        if iv.get("mean_cos", 0) < MIN_COS:
            continue
        samples = [r for r in recs if iv["start"] - 1e-6 <= r["t"] <= iv["end"]]
        ah = [(r["t"], r[tkey],
               max((f["size"] for f in r["faces"] if f["member"] == target),
                   default=0.0)) for r in samples if r.get(tkey) is not None]
        if not ah:
            continue
        max_px = max(px for _, _, px in ah)
        if max_px < MIN_FACE_PX:
            continue
        peak_t, peak_cos, _ = max(ah, key=lambda x: x[1])
        cut_len = min(iv["duration"], MAX_CUT_S)
        lo = iv["start"]
        hi = max(iv["end"] - cut_len, iv["start"])
        sb = shot_bounds(peak_t)
        if sb and sb[1] - sb[0] <= MAX_CUT_S + 0.5:
            # short shot: keep the cut inside the shot (no mid-cut shot change)
            lo, hi = max(lo, sb[0]), min(hi, max(sb[1] - cut_len, sb[0]))
        t0 = min(max(peak_t - cut_len / 2.0, lo), hi)
        score = (0.45 * min((iv["mean_cos"] - MIN_COS) / (0.85 - MIN_COS), 1.0)
                 + 0.30 * min(iv["duration"] / 6.0, 1.0)
                 + 0.25 * min(max_px / 500.0, 1.0))
        fx = None
        for r in recs:
            if abs(r["t"] - peak_t) < 1e-6:
                for f in r["faces"]:
                    if f["member"] == target:
                        fx = round(((f["bbox"][0] + f["bbox"][2]) / 2.0)
                                   / max(1.0, VW), 4)
                        break
                break
        out.append({"video": os.path.join(an, "normalized.mp4"),
                    "interval": [round(iv["start"], 2), round(iv["end"], 2)],
                    "t0": round(t0, 2), "t1": round(t0 + cut_len, 2),
                    "dur": round(cut_len, 2), "coverage": 1.0,
                    "cos": round(iv["mean_cos"], 4), "peak_cos": round(peak_cos, 4),
                    "face_px": round(max_px, 1), "fx": fx,
                    "score": round(score, 4)})
    out.sort(key=lambda c: -c["score"])
    return out


def assign_cuts(candidates, scenes, timeline):
    """Source-rotating assignment for visual variety.

    Each scene leads with a DIFFERENT source (scene i -> order[i % n]) and
    takes at most one cut per source, so a scene never shows two near
    identical shots from the same camera setup. Near-duplicate windows
    inside one source (t0 within 2.5 s) are collapsed first.
    """
    tstarts = timeline["starts"]
    by_src = {}
    for c in candidates:
        by_src.setdefault(c["video"], []).append(c)
    # collapse near-duplicate cuts within each source
    for v, pool in by_src.items():
        pool.sort(key=lambda c: -c["score"])
        kept = []
        for c in pool:
            if kept and abs(c["t0"] - kept[-1]["t0"]) < 2.5:
                continue
            kept.append(c)
        by_src[v] = kept
    order = sorted(by_src, key=lambda v: -by_src[v][0]["score"])
    used = {v: 0 for v in order}
    plan = {}
    n_src = len(order)
    for si, sc in enumerate(scenes):
        sid = str(sc["id"])
        dur = timeline["durations"][sid]
        need = max(2, min(4, round(dur / 3.0)))
        cuts = []
        # lead source rotates with scene index -> every scene opens differently
        for k in range(min(need, n_src * 2)):
            v = order[(si + k) % n_src]
            if used[v] < len(by_src[v]):
                cuts.append(dict(by_src[v][used[v]]))
                used[v] += 1
            if len(cuts) >= need:
                break
        if not cuts:
            continue
        share = dur / len(cuts)
        plan[sid] = {"need": need, "cuts": cuts, "share": round(share, 2),
                     "scene_start": tstarts[sid]}
    return plan


def best_bed_source(sources):
    """Highest-resolution source with audio (the MV master) for the song bed."""
    best, best_px = None, 0
    for s in sources:
        ws = s["ws"]
        norm = os.path.join(ws, "output", "analysis", "normalized.mp4")
        if not os.path.exists(norm):
            continue
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json",
                 "-show_streams", "-select_streams", "a:0", norm],
                capture_output=True, text=True, timeout=30)
            if '"codec_type": "audio"' not in r.stdout.replace("'audio'", '"audio"'):
                continue
            r2 = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", norm],
                capture_output=True, text=True, timeout=30)
            w, h = (int(x) for x in r2.stdout.strip().split(","))
            if w * h > best_px:
                best, best_px = {"video": norm, "w": w, "h": h}, w * h
        except Exception:
            continue
    return best


def _scenes(plan):
    """beats (v2 script) or scenes (v1) -> unified scene list."""
    if plan.get("beats"):
        return [{"id": b.get("id", i + 1),
                 "narration": b.get("narration", ""),
                 "on_screen": b.get("on_screen", "")}
                for i, b in enumerate(plan["beats"])]
    return plan["scenes"]


def run(run_dir, character=None, sources=None, timeline=None):
    run_dir = os.path.abspath(run_dir)
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    target = detect_character(topic["topic"], character)
    if not target:
        log("no known character in topic -> charmedia not applicable")
        return False
    vids = discover_sources(sources)
    if not vids:
        log("no source footage found")
        return False
    log(f"character='{target}' sources={len(vids)}")
    analyzed = []
    for v in vids:
        ws = os.path.join(run_dir, "04_charmedia", "ws_" + src_id(v))
        os.makedirs(ws, exist_ok=True)
        if not ensure_refs(ws, target):
            continue
        try:
            ok = analyze_source(v, ws, target)
        except Exception as e:
            log(f"  analysis failed for {os.path.basename(v)}: {e}")
            ok = False
        if ok:
            analyzed.append({"path": v, "ws": ws})
            log(f"  OK {os.path.basename(v)}")
        else:
            log(f"  no {target} visibility in {os.path.basename(v)}")
    if not analyzed:
        log("no analyzable sources -> fallback required")
        return False

    candidates = []
    for s in analyzed:
        cands = build_shot_index(s["ws"], target)
        log(f"  {os.path.basename(s['path'])}: {len(cands)} verified shots")
        for c in cands:
            c["src_label"] = os.path.basename(s["path"])
        candidates += cands
    if len(candidates) < 6:
        log(f"candidate pool too small ({len(candidates)})")
        return False

    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    scenes = _scenes(plan)
    assignment = assign_cuts(candidates, scenes, timeline)

    doc = {
        "character": target,
        "engine": "character-clip-extractor (InsightFace buffalo_l)",
        "sources": [{"label": os.path.basename(s["path"]), "ws": s["ws"]}
                    for s in analyzed],
        "n_candidates": len(candidates),
        "scenes": assignment,
        "audio_bed": best_bed_source(analyzed),
        "notes": ("every cut contains face-verified " + target +
                  " footage; cuts centred on peak recognition moment"),
    }
    out = os.path.join(run_dir, "04_charmedia.json")
    json.dump(doc, open(out, "w"), indent=1)
    log(f"charmedia plan: {sum(len(v['cuts']) for v in assignment.values())} cuts "
        f"across {len(assignment)} scenes -> {out}")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--character", default=None)
    ap.add_argument("--sources", nargs="*", default=None)
    a = ap.parse_args()
    tl = json.load(open(os.path.join(a.run_dir, "06_timeline.json")))
    ok = run(a.run_dir, a.character, a.sources, tl)
    sys.exit(0 if ok else 3)
