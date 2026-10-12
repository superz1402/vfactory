#!/usr/bin/env python3
"""Stage 4 v2: REAL FOOTAGE FIRST.

Per-scene visuals are cut from the footage pool (real video, downloaded via
yt-farm/ytagent). Static images are a LAST-RESORT fallback, never the default.

Pool: vfactory/footage_pool/*.mp4 + INDEX.json  (file -> {title, tags, era, res})
Scene plan fields used:
  footage_tags : list[str]  semantic tags describing what should be on screen
  duration     : filled later from voice timings (s6 needs exact lengths)

Algorithm:
  1. Score sources per scene by tag overlap (+era bonus). Require >0 unless
     the pool is starving, in which case fall back to any source with a
     fresh window.
  2. Non-overlapping cut windows per source (usage ledger), skipping intro
     (first 12s) and outro (last 8s) of each source.
  3. Cut main clip (normalized 1080p/30fps, silent) + 2 short cutaways from
     OTHER matching sources for edit rhythm.
  4. Only if no usable source at all: image search, then title card.
"""
import argparse, glob, json, os, random, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

POOL_DIR = os.path.join(os.path.dirname(__file__), "..", "footage_pool")
SKIP_HEAD = 12.0   # skip intros
SKIP_TAIL = 8.0    # skip outros
MIN_SRC_RES = 480  # accept >= 480p sources (prefer higher)
OUT_W, OUT_H, FPS = 1920, 1080, 30


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,duration",
                        "-show_entries", "format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        st = d["streams"][0]
        w, h = int(st["width"]), int(st["height"])
        dur = float(st.get("duration") or d["format"].get("duration") or 0)
        if dur <= 0:
            dur = float(d["format"].get("duration", 0))
        return w, h, dur
    except Exception:
        return 0, 0, 0.0


def load_pool():
    """INDEX.json + discovery of unindexed files (tags guessed empty -> low score)."""
    idx_path = os.path.join(POOL_DIR, "INDEX.json")
    index = json.load(open(idx_path)) if os.path.exists(idx_path) else {}
    pool = {}
    for f in sorted(glob.glob(os.path.join(POOL_DIR, "*.mp4"))):
        name = os.path.basename(f)
        w, h, dur = probe(f)
        if dur < 20:  # too short to cut from
            continue
        meta = index.get(name, {})
        pool[name] = {
            "path": f, "w": w, "h": h, "dur": dur,
            "title": meta.get("title", name),
            "tags": set(meta.get("tags", [])),
            "era": meta.get("era", ""),
            "res": min(w, h) if w and h else 0,
        }
    return pool


def score_source(src, tags, era=None):
    """Tag overlap scoring. Era match adds a bonus."""
    overlap = len(set(tags) & src["tags"])
    if overlap == 0:
        return 0.0
    score = float(overlap)
    if era and src.get("era") == era:
        score += 0.75
    if src["res"] >= 1080:
        score += 0.4
    elif src["res"] < MIN_SRC_RES:
        score -= 1.0
    return score


def next_window(src, ledger, need):
    """Allocate the next non-overlapping window in src. Deterministic w/ jitter."""
    used = ledger.setdefault(src["title"], [])
    span = src["dur"] - SKIP_HEAD - SKIP_TAIL - need
    if span <= 1.0:
        return None
    candidates = []
    for attempt in range(14):
        start = SKIP_HEAD + (random.random() * span)
        ok = all(abs(start - u) > need + 1.5 for u in used)
        if ok:
            candidates.append(start)
            break
    if not candidates:
        # ledger saturated: reuse with max spacing from used windows
        best = None
        for attempt in range(30):
            start = SKIP_HEAD + (random.random() * span)
            mind = min((abs(start - u) for u in used), default=999)
            if best is None or mind > best[1]:
                best = (start, mind)
        start = best[0] if best else SKIP_HEAD
    else:
        start = candidates[0]
    start = max(SKIP_HEAD, min(start, src["dur"] - SKIP_TAIL - need))
    used.append(start)
    return start


def cut(src_path, start, dur, out, ar="16:9"):
    """Cut + normalize: 1080p, 30fps, silent, faststart."""
    vf = (f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
          f"crop={OUT_W}:{OUT_H},fps={FPS}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
           "-i", src_path, "-vf", vf, "-an",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return r.returncode == 0 and os.path.exists(out)


def valid_image(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[0:2]
        return int(w) >= 400 and int(h) >= 300
    except Exception:
        return False


def fallback_card(run_dir, sc, text):
    out = os.path.join(run_dir, "04_media", f"scene_{sc['id']:02d}.jpg")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "color=c=0x101418:s=1920x1080:d=1",
                    "-vf", (f"drawtext=text='{text[:60]}':fontcolor=white@0.85:"
                            f"fontsize=64:x=(w-tw)/2:y=(h-th)/2"),
                    "-frames:v", "1", "-q:v", "3", out],
                   capture_output=True, timeout=60)
    return out if os.path.exists(out) else None


def _plan_scene(task):
    """Worker: cut main + cutaways for one scene. Returns (sid, main, cutaways)."""
    (media_dir, sc, need, pool, ledger, random_seed) = task
    sid = sc["id"]
    tags = set(sc.get("footage_tags") or [])
    era = sc.get("era")
    ranked = sorted(((score_source(s, tags, era), n, s)
                     for n, s in pool.items()), key=lambda x: -x[0])
    main = None
    cutaways = []
    for score, name, src in ranked:
        if score <= 0:
            break
        start = next_window(src, ledger, need)
        if start is None:
            continue
        out = os.path.join(media_dir, f"scene_{sid:02d}.mp4")
        if cut(src["path"], start, need, out):
            main = {"path": out, "kind": "video", "source": name,
                    "title": src["title"], "start": round(start, 2),
                    "need": round(need, 2), "score": score,
                    "tags": sorted(tags)}
            break
    ins_id = 0
    for score, name, src in ranked:
        if ins_id >= 2:
            break
        if main and name == main["source"]:
            continue
        if score <= 0 and ins_id == 0:
            continue
        start = next_window(src, ledger, 2.8)
        if start is None:
            continue
        out = os.path.join(media_dir, f"scene_{sid:02d}_ins{ins_id}.mp4")
        if cut(src["path"], start, 2.8, out):
            cutaways.append({"path": out, "source": name,
                             "start": round(start, 2)})
            ins_id += 1
    return (sid, main, cutaways)


def run(run_dir, region="us", ai_broll=False, scene_seconds=None):
    media_dir = os.path.join(run_dir, "04_media")
    os.makedirs(media_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {}
    tpath = os.path.join(run_dir, "03_timings.json")
    if os.path.exists(tpath):
        timings = {t["id"]: t["audio"] for t in
                   json.load(open(tpath))["timings"]}
    pool = load_pool()
    if not pool:
        raise RuntimeError("footage pool is empty — run farm pulls first")
    print(f"[s4] pool: {len(pool)} sources, "
          f"{sum(s['dur'] for s in pool.values())/60:.1f} min total")
    ledger = {}          # shared window ledger (thread-safe enough: GIL list ops)
    manifest = {}
    mpath = os.path.join(run_dir, "04_media.json")
    if os.path.exists(mpath):
        try:
            manifest = json.load(open(mpath))
        except Exception:
            manifest = {}
    tasks, notes = [], []
    for sc in plan["scenes"]:
        sid = sc["id"]
        main_out = os.path.join(media_dir, f"scene_{sid:02d}.mp4")
        side = main_out + ".json"
        if os.path.exists(side):
            try:
                entry = json.load(open(side))
                if entry.get("kind") == "video" and os.path.exists(entry.get("path", "")):
                    manifest[str(sid)] = entry
                    continue  # resume support (per-scene sidecar)
            except Exception:
                pass
        need = max(scene_seconds or 0, timings.get(sid, 0) + 2.5, 8.0)
        tasks.append((media_dir, sc, need, pool, ledger, sid))
    if tasks:
        with ThreadPoolExecutor(max_workers=4) as ex:
            for sid, main, cutaways in ex.map(_plan_scene, tasks):
                main_out = os.path.join(media_dir, f"scene_{sid:02d}.mp4")
                if main:
                    if cutaways:
                        main["cutaways"] = cutaways
                    manifest[str(sid)] = main
                    json.dump(main, open(main_out + ".json", "w"),
                              ensure_ascii=False, indent=1)  # crash-safe sidecar
                    notes.append(f"scene {sid}: VIDEO <- {main['source']} "
                                 f"@{main['start']:.0f}s (score {main['score']:.1f})")
    # LAST RESORT for any scene without footage: image search, then card
    for sc in plan["scenes"]:
        sid = sc["id"]
        if str(sid) in manifest:
            continue
        got = False
        for item in (zai.image_search(sc.get("visual_query", plan["topic"]),
                                      count=6, region=region) or [])[:6]:
            url = (item.get("original_url") or item.get("url") or
                   item.get("image") or item.get("oss_url") or "")
            if not url.startswith("http"):
                continue
            out = os.path.join(media_dir, f"scene_{sid:02d}.jpg")
            if zai.download(url, out, min_bytes=8000) and valid_image(out):
                manifest[str(sid)] = {"path": out, "kind": "image",
                                      "credit": url[:200]}
                notes.append(f"scene {sid}: IMAGE fallback <- {url[:60]}")
                got = True
                break
        if not got:
            card = fallback_card(run_dir, sc, sc.get("on_screen", ""))
            if card:
                manifest[str(sid)] = {"path": card, "kind": "card"}
                notes.append(f"scene {sid}: CARD fallback")
    video_n = sum(1 for m in manifest.values() if m["kind"] == "video")
    json.dump(manifest, open(os.path.join(run_dir, "04_media.json"), "w"),
              ensure_ascii=False, indent=1)
    open(os.path.join(run_dir, "04_media.log"), "w").write("\n".join(notes))
    print(f"[s4] video scenes: {video_n}/{len(manifest)} "
          f"(images/cards: {len(manifest) - video_n})")
    for n in notes:
        print("   ", n)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic_json")
    ap.add_argument("--ai-broll", action="store_true")
    a = ap.parse_args()
    run_dir = os.path.dirname(a.topic_json)
    d = json.load(open(a.topic_json))
    run(run_dir, d.get("region", "us"), a.ai_broll)
    print("media done")
