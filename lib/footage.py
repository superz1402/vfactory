#!/usr/bin/env python3
"""footage.py — real-motion-footage acquisition for documentary v2.

Sources (all validated live 2026-10-09):
  1. local MV library   (DRIP MV 1080p, THE FIRST TAKE x2, AHYEON cover)
  2. Mixkit stock       (direct mp4, 720p, no key)
  3. Coverr stock       (direct mp4, no key)
  4. image-search stills (fallback layer, z-ai)
Segment index: local videos are scene-scanned once; segments cached in
CACHE/segments.json so the shot planner can pick real 2-6s moments.
"""
import json, os, re, subprocess, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache")
SEG_INDEX = os.path.join(CACHE, "segments.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")

# ---- local MV library (verified files) ----
LOCAL_LIBRARY = [
    {"id": "drip_mv", "path": "/home/z/my-project/ytdl-agent/downloads/video_Zp-Jhuhq0bQ.mp4",
     "label": "BABYMONSTER - DRIP M/V (official)", "tags": ["stage", "performance", "drip", "group", "glamour", "dance"]},
    {"id": "drip_firsttake", "path": "/home/z/my-project/ytdl-agent/downloads/O99aP4AvEF8.mp4",
     "label": "BABYMONSTER - DRIP / THE FIRST TAKE", "tags": ["vocal", "live", "closeup", "studio", "drip", "ahyeon"]},
    {"id": "sheesh_firsttake", "path": "/home/z/my-project/ytdl-agent/downloads/06mCrMgv0zY.mp4",
     "label": "BABYMONSTER - SHEESH / THE FIRST TAKE", "tags": ["vocal", "live", "closeup", "studio", "sheesh", "ahyeon"]},
    {"id": "ahyeon_dangerously", "path": "/home/z/my-project/ytdl-agent/downloads/xw7Y2gviWbA.mp4",
     "label": "AHYEON - Dangerously COVER", "tags": ["solo", "ahyeon", "vocal", "emotional", "closeup"]},
]


def ffprobe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


# ---------------- local library segment index ----------------
def scan_local(min_gap=0.25):
    """Scene-scan each local MV once; cache segments (cut-to-cut ranges)."""
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(SEG_INDEX):
        try:
            idx = json.load(open(SEG_INDEX))
            if idx.get("v") == 2:
                return idx
        except Exception:
            pass
    import tempfile
    idx = {"v": 2, "videos": {}}
    for item in LOCAL_LIBRARY:
        p = item["path"]
        if not os.path.exists(p):
            continue
        dur = ffprobe_dur(p)
        cuts_f = os.path.join(CACHE, f"cuts_{item['id']}.txt")
        if not os.path.exists(cuts_f) or os.path.getsize(cuts_f) < 10:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
                cuts_f = tf.name
            cmd = (f'ffmpeg -hide_banner -nostats -i "{p}" '
                   f'-vf "fps=6,scale=192:-2,select=\'gt(scene,0.25)\',showinfo" '
                   f'-an -f null /dev/null 2>{cuts_f}')
            subprocess.run(cmd, shell=True, timeout=900)
        pts = sorted(set(round(float(m.group(1)), 2)
                         for m in re.finditer(r"pts_time:([\d.]+)", open(cuts_f).read())))
        # build segments between cuts, keep 1.2s..9s
        bounds = [0.0] + pts + [dur]
        segs = []
        for a, b in zip(bounds, bounds[1:]):
            d = b - a
            if 1.2 <= d <= 9.0:
                segs.append({"in": round(a + 0.05, 2), "dur": round(d - 0.1, 2)})
            elif d > 9.0:
                # split long holds into ~4s windows
                t = a + 0.3
                while t + 2.0 <= b:
                    seg_d = min(4.0, b - t - 0.2)
                    if seg_d >= 1.6:
                        segs.append({"in": round(t, 2), "dur": round(seg_d, 2)})
                    t += 4.5
        idx["videos"][item["id"]] = {"label": item["label"], "tags": item["tags"],
                                     "path": p, "dur": round(dur, 1), "segments": segs}
    json.dump(idx, open(SEG_INDEX, "w"), indent=1)
    return idx


# ---------------- stock download ----------------
def _dl(url, path, min_bytes=300_000):
    try:
        r = subprocess.run(["curl", "-sL", "--max-time", "90", "-A", UA,
                            "-o", path, url], capture_output=True, timeout=100)
        if r.returncode == 0 and os.path.exists(path) and os.path.getsize(path) >= min_bytes:
            return True
    except Exception:
        pass
    if os.path.exists(path):
        os.remove(path)
    return False


def _mixkit_search(query, n=4):
    """Scrape mixkit category page for direct 720p mp4 urls."""
    cat = urllib.parse.quote(query.replace(" ", "-")[:40])
    out = []
    for url in (f"https://mixkit.co/free-stock-video/{cat}/",
                f"https://mixkit.co/free-stock-video/?q={urllib.parse.quote(query)}"):
        try:
            r = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", UA, url],
                               capture_output=True, timeout=30)
            vids = re.findall(r"https://assets\.mixkit\.co/videos/(\d+)/\1-720\.mp4",
                              r.stdout.decode("utf-8", "ignore"))
            for v in list(dict.fromkeys(vids))[:n]:
                out.append((f"https://assets.mixkit.co/videos/{v}/{v}-720.mp4",
                            f"mixkit_{v}"))
            if out:
                break
        except Exception:
            continue
    return out[:n]


def _coverr_search(query, n=4):
    q = urllib.parse.quote(query)
    out = []
    try:
        r = subprocess.run(["curl", "-sL", "--max-time", "25", "-A", UA,
                            f"https://coverr.co/s?q={q}"],
                           capture_output=True, timeout=30)
        html = r.stdout.decode("utf-8", "ignore")
        for m in list(dict.fromkeys(
                re.findall(r"https://cdn\.coverr\.co/videos/[^\"']+\.mp4", html)))[:n]:
            slug = m.split("/videos/")[-1].split("/")[0]
            out.append((m, f"coverr_{slug}"))
    except Exception:
        pass
    return out[:n]


def fetch_stock(query, n=3):
    """Download up to n stock clips for query into CACHE/stock/. Returns file paths."""
    stock_dir = os.path.join(CACHE, "stock")
    os.makedirs(stock_dir, exist_ok=True)
    got = []
    for url, name in _mixkit_search(query, n=n) + _coverr_search(query, n=n):
        dst = os.path.join(stock_dir, f"{name}.mp4")
        if os.path.exists(dst) and ffprobe_dur(dst) > 2:
            got.append(dst)
            continue
        if _dl(url, dst):
            d = ffprobe_dur(dst)
            w = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height", "-of", "csv", dst],
                               capture_output=True, text=True).stdout.strip()
            if d >= 2.0 and ("1920" in w or "1280" in w or "640" in w or "960" in w):
                got.append(dst)
    return got


STOCK_MANIFEST = os.path.join(CACHE, "stock_manifest.json")


def ensure_stock(queries):
    """Fetch stock for a list of queries; returns {query: [paths]}."""
    man = {}
    if os.path.exists(STOCK_MANIFEST):
        try:
            man = json.load(open(STOCK_MANIFEST))
        except Exception:
            man = {}
    changed = False
    for q in queries:
        if q not in man:
            man[q] = fetch_stock(q, n=3)
            changed = True
    if changed:
        json.dump(man, open(STOCK_MANIFEST, "w"), indent=1)
    return man


# ---------------- stills (fallback layer) ----------------
def fetch_still(query, dst, region="us"):
    from lib import zai
    res = zai.image_search(query, region=region)
    for r in res:
        for k in ("original_url", "url", "image", "oss_url"):
            u = r.get(k) if isinstance(r, dict) else None
            if u and zai.download(u, dst, min_bytes=40_000):
                return True
    return False


if __name__ == "__main__":
    import sys
    idx = scan_local()
    for vid, v in idx["videos"].items():
        print(f"{vid}: {len(v['segments'])} segments of {v['dur']}s total")
    if len(sys.argv) > 1:
        print("stock test:", ensure_stock(sys.argv[1:]))
