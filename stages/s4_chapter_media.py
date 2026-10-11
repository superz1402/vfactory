#!/usr/bin/env python3
"""Stage 4: visuals per scene/chapter.

Scene mode:  one visual per scene (search -> validate -> fallback card).
Chapter mode: 8-12 SHOTS per chapter sourced from the chapter's
             entity-matched visual_queries (each query tried until 1-2 valid
             hits), distributed across the chapter audio duration at ~8-11s
             per shot so every narration beat gets a matching picture.

Manifest 04_media.json:
  scenes mode:   {"<scene_id>": {path, kind, ...}}
  chapters mode: {"chapters": {"<ch_id>": {"shots": [{path, kind, query,
                            caption, credit, dur}], "audio": seconds}}}
Local footage (topic "footage_dir" or "footage_glob") is matched by keyword
overlap with the query first — real clips outrank images.
"""
import glob
import hashlib
import json
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402

SHOT_SEC = 8.0        # average long-form shot length
SHOTS_PER_QUERY = 1   # valid hits to keep per query

# ----------------------------------------------------------- validation ----
def valid_image(path):
    """Real image codec + sane dimensions + real photographic content."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[0:2]
        if not (int(w) >= 400 and int(h) >= 300):
            return False
    except Exception:
        return False
    return looks_like_photo(path)


def looks_like_photo(path):
    """Reject HTML error pages saved as .jpg, blank/uniform fills."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
        magic_ok = (head.startswith(b"\xff\xd8") or                    # jpeg
                    head.startswith(b"\x89PNG") or                     # png
                    head[:4] == b"RIFF" or                             # webp
                    head[:6] in (b"GIF87a", b"GIF89a"))
        if not magic_ok:
            return False
        from PIL import Image
        import numpy as np
        im = Image.open(path).convert("L").resize((64, 64))
        a = np.asarray(im, dtype=np.float32)
        if a.std() < 12.0:          # flat / blank page
            return False
        # bot-block pages: dark bg + few bright text lines -> very low entropy
        hist = np.histogram(a, bins=32, range=(0, 255))[0].astype(np.float32)
        p = hist / hist.sum()
        ent = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
        return ent >= 2.2
    except Exception:
        return False


def sig(path):
    """(md5, 16x16 phash-ish) for duplicate rejection."""
    try:
        md5 = hashlib.md5(open(path, "rb").read()).hexdigest()
        from PIL import Image
        im = Image.open(path).convert("L").resize((16, 16))
        return md5, tuple(im.getdata())
    except Exception:
        return None, None


def dup(a, b):
    if a[0] and b[0] and a[0] == b[0]:
        return True
    if a[1] and b[1]:
        d = sum(x != y for x, y in zip(a[1], b[1]))
        return d < 8      # near-identical thumbnail
    return False


def video_ok(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height,duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        parts = r.stdout.strip().split(",")
        return int(parts[0]) >= 400 and int(parts[1]) >= 300
    except Exception:
        return False


def fallback_card(run_dir, uid, text):
    out = os.path.join(run_dir, "04_media", f"card_{uid:02d}.jpg")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "color=c=0x101418:s=1920x1080:d=1",
                    "-vf", (f"drawtext=text='{text[:60]}':fontcolor=white@0.85:"
                            "fontsize=64:x=(w-tw)/2:y=(h-th)/2"),
                    "-frames:v", "1", "-q:v", "3", out],
                   capture_output=True, timeout=60)
    return out if os.path.exists(out) else None


def _local_footage(topic):
    pats = []
    if topic.get("footage_dir"):
        pats.append(os.path.join(topic["footage_dir"], "**", "*"))
    for g in topic.get("footage_glob") or []:
        pats.append(g)
    files = []
    for p in pats:
        files += [f for f in glob.glob(p, recursive=True)
                  if f.lower().endswith((".mp4", ".mkv", ".webm", ".mov"))]
    return files


def _keyword_hit(query, path):
    q = set(query.lower().replace("_", " ").split())
    name = os.path.basename(path).lower().replace("_", " ").replace("-", " ")
    return len(q & set(name.split()))


WATERMARK_FARMS = ("alamy", "gettyimages", "shutterstock", "istockphoto",
                   "dreamstime", "123rf", "agefotostock", "stockphoto",
                   "adobe.stock", "depositphotos")


def _search_one(query, out_base, region, used_sigs):
    """Try to download one valid, non-duplicate visual for query."""
    for item in (zai.image_search(query, count=8, region=region) or [])[:8]:
        url = (item.get("original_url") or item.get("url") or
               item.get("image") or item.get("oss_url") or "")
        if not url.startswith("http"):
            continue
        if any(f in url.lower() for f in WATERMARK_FARMS):
            continue  # watermarked stock comps look terrible in a doc
        out = out_base + ".jpg"
        if zai.download(url, out, min_bytes=8000) and valid_image(out):
            s = sig(out)
            if any(dup(s, u) for u in used_sigs):
                os.remove(out)
                continue
            used_sigs.append(s)
            return {"path": out, "kind": "image", "query": query,
                    "credit": url[:200],
                    "caption": (item.get("caption") or "")[:160]}
    return None


def run_chapters(run_dir, region):
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    media_dir = os.path.join(run_dir, "04_media")
    os.makedirs(media_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["units"]}
    pool = _local_footage(topic)
    used_pool = set()
    used_sigs = []      # global (cross-chapter) duplicate rejection
    rng = random.Random(topic.get("topic", ""))
    manifest = {"chapters": {}}

    for ch in plan["chapters"]:
        cid = ch["id"]
        audio = timings.get(cid, 150.0)
        mpath = os.path.join(run_dir, f"04_media_ch_{cid:02d}.json")
        if os.path.exists(mpath):  # checkpoint
            data = json.load(open(mpath))
            for s in data["shots"]:
                used_sigs.append(sig(s["path"]))
            manifest["chapters"][cid] = data
            continue
        n_shots = max(6, min(24, int(round(audio / SHOT_SEC))))
        shots = []
        queries = [q for q in ch.get("visual_queries", []) if q][:12]
        qi = 0
        # 1) local footage matched by keywords
        for q in queries:
            if len(shots) >= n_shots:
                break
            cands = sorted(pool, key=lambda f: -_keyword_hit(q, f))
            for f in cands[:2]:
                if f in used_pool or not video_ok(f):
                    continue
                used_pool.add(f)
                shots.append({"path": f, "kind": "video", "query": q,
                              "credit": f"local:{os.path.basename(f)}",
                              "caption": ""})
                break
        # 2) image search per query (entity-matched)
        while len(shots) < n_shots and qi < len(queries):
            q = queries[qi]
            qi += 1
            ent = _search_one(q, os.path.join(media_dir, f"ch{cid:02d}_s{qi:02d}"),
                              region, used_sigs)
            if ent:
                shots.append(ent)
        # 3) fallback cards for any remaining gap
        while len(shots) < max(4, n_shots // 2):
            card = fallback_card(run_dir, cid * 100 + len(shots),
                                 ch.get("on_screen") or ch.get("title") or "")
            if not card:
                break
            shots.append({"path": card, "kind": "card", "query": "fallback",
                          "credit": "", "caption": ""})
            break
        if not shots or len(shots) < 2:
            raise RuntimeError(f"chapter {cid}: too few visuals "
                               f"({len(shots)}) for an xfade chain")
        # distribute durations: jitter ±1.2s around audio/n, first shot longer
        base = audio / len(shots)
        durs = [max(3.0, base + rng.uniform(-1.2, 1.2)) for _ in shots]
        durs[0] = max(durs[0], base + 1.0)
        drift = audio - sum(durs)
        durs[-1] = max(3.0, durs[-1] + drift)
        for s, d in zip(shots, durs):
            s["dur"] = round(d, 2)
        data = {"id": cid, "audio": round(audio, 2), "shots": shots}
        json.dump(data, open(mpath, "w"), ensure_ascii=False, indent=1)
        manifest["chapters"][cid] = data
        print(f"  chapter {cid}: {len(shots)} shots / {audio:.0f}s "
              f"({sum(1 for s in shots if s['kind'] == 'video')} video)",
              flush=True)
    json.dump(manifest, open(os.path.join(run_dir, "04_media.json"), "w"),
              ensure_ascii=False, indent=1)
    return manifest


def run_scenes(run_dir, region, ai_broll=False):
    media_dir = os.path.join(run_dir, "04_media")
    os.makedirs(media_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    manifest = {}
    for sc in plan["scenes"]:
        out = os.path.join(media_dir, f"scene_{sc['id']:02d}.jpg")
        if os.path.exists(out) and valid_image(out):
            manifest[str(sc["id"])] = {"path": out, "kind": "image"}
            continue
        got = False
        for item in (zai.image_search(sc["visual_query"], count=6, region=region) or [])[:6]:
            url = (item.get("original_url") or item.get("url") or
                   item.get("image") or item.get("oss_url") or "")
            if not url.startswith("http"):
                continue
            if zai.download(url, out, min_bytes=8000) and valid_image(out):
                manifest[str(sc["id"])] = {"path": out, "kind": "image",
                                           "credit": url[:200],
                                           "caption": (item.get("caption") or "")[:200]}
                got = True
                break
        if not got:
            card = fallback_card(run_dir, sc["id"], sc["on_screen"])
            if card:
                manifest[str(sc["id"])] = {"path": card, "kind": "card"}
                got = True
        if not got:
            raise RuntimeError(f"no visual for scene {sc['id']}")
    if ai_broll:
        clip = os.path.join(media_dir, "scene_01_ai.mp4")
        q = plan["scenes"][0]["visual_query"]
        if zai.gen_video_clip(f"Cinematic documentary b-roll: {q}", clip,
                              size="1920x1080", duration=5):
            manifest["1"] = {"path": clip, "kind": "video"}
    json.dump(manifest, open(os.path.join(run_dir, "04_media.json"), "w"),
              ensure_ascii=False, indent=1)
    return manifest


def run(run_dir, region="us", ai_broll=False):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    if plan.get("mode") == "chapters":
        return run_chapters(run_dir, region)
    return run_scenes(run_dir, region, ai_broll)


if __name__ == "__main__":
    ap = __import__("argparse").ArgumentParser()
    ap.add_argument("topic_json")
    ap.add_argument("--ai-broll", action="store_true")
    a = ap.parse_args()
    run_dir = os.path.dirname(a.topic_json)
    d = json.load(open(a.topic_json))
    run(run_dir, d.get("region", "us"), a.ai_broll)
    print("media done")
