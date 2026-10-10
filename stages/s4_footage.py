#!/usr/bin/env python3
"""Stage 4 v2: Ahyeon-specific footage assignment (replaces image-search s4).

Consumes footage/library.json — every window here is face-verified Ahyeon
footage produced by character-clip-extractor (InsightFace @2fps). For each
script scene this stage assigns 1-3 verified windows as shots, following the
OpenMontage documentary edit grammar:

  - hero slots (hook, outro) get the strongest solo windows
  - adjacent shots never share the same source AND scale
  - a window is cut at its best sub-interval (handles at both ends)
  - every shot carries provenance (source title/url) + ahyeon_verified

Output: 04_media.json
  {"<scene_id>": {"kind":"video", "scale": "close|wide", "credit": "...",
                  "shots": [{"path": <normalized.mp4>, "in": s, "out": s,
                             "dur": s, "source_video_id": ..., "scale": ...,
                             "ahyeon_verified": true, "window_conf": ...}]}}
"""
import json, os, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIBRARY = os.path.join(BASE, "footage", "library.json")
HANDLE = 0.15      # seconds of headroom kept inside each window edge
MIN_WINDOW = 2.2   # windows shorter than this can't hold a shot


def build_pool(library):
    pool = []
    for s in library["sources"]:
        for iv in s["raw_intervals"]:
            dur = iv.get("duration", 0)
            if dur >= MIN_WINDOW:
                pool.append({
                    "source": s,
                    "in": iv["start"] + HANDLE,
                    "max_dur": dur - 2 * HANDLE,
                    "conf": iv.get("mean_cos", iv.get("max_cos", 0.5)),
                    "kind": s.get("kind", "group"),
                    "scale": "close" if s.get("kind") == "solo" else "wide",
                })
    # strongest first: long + confident
    pool.sort(key=lambda p: (p["max_dur"] + p["conf"]), reverse=True)
    return pool


def assign(run_dir):
    script = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in
               json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    tail = 0.8
    library = json.load(open(LIBRARY))
    pool = build_pool(library)
    if not pool:
        raise RuntimeError("footage library has no usable Ahyeon windows — "
                           "run footage/build_library.py first")
    if len(pool) < 4:
        raise RuntimeError(f"footage library too thin ({len(pool)} windows) — "
                           f"add sources to footage/sources.json and rebuild")

    scene_durs = {}
    for sc in script["scenes"]:
        scene_durs[sc["id"]] = max(3.5, timings.get(sc["id"], 4.0) + tail)

    total = sum(scene_durs.values())
    used = set()          # window ids already assigned
    manifest = {}
    prev_scale, prev_src = None, None

    def take(prefer_kind=None, need=None, exclude_kinds=None):
        """Pick the best unused window for the constraint."""
        need = need or 3.0
        cands = [p for p in pool if id(p) not in used and p["max_dur"] >= min(need, 2.0)]
        if prefer_kind:
            pref = [p for p in cands if p["kind"] == prefer_kind]
            if pref:
                cands = pref
        if exclude_kinds:
            nk = [p for p in cands if p["kind"] not in exclude_kinds]
            if nk:
                cands = nk
        # diversity: avoid same source+scale as previous shot
        div = [p for p in cands
               if not (p["scale"] == prev_scale and p["source"]["video_id"] == prev_src)]
        cands = div or cands
        if not cands:
            # allow reuse of a used window with a different sub-cut
            cands = [p for p in pool if p["max_dur"] >= min(need, 2.0)]
            if prefer_kind:
                pref = [p for p in cands if p["kind"] == prefer_kind]
                cands = pref or cands
        if not cands:
            return None
        cands.sort(key=lambda p: (p["conf"] + p["max_dur"] / 10.0), reverse=True)
        pick = cands[0]
        used.add(id(pick))
        return pick

    order = [sc["id"] for sc in script["scenes"]]
    for pos, sid in enumerate(order):
        sc = next(s for s in script["scenes"] if s["id"] == sid)
        need_total = scene_durs[sid]
        n_shots = 1 if need_total <= 7.5 else (2 if need_total <= 13.5 else 3)
        is_hero = sid in (order[0], order[-1])
        shots = []
        remaining = need_total
        for k in range(n_shots):
            share = remaining / (n_shots - k)
            prefer = None
            if is_hero and k == 0:
                prefer = "solo"
            elif prev_scale == "close":
                prefer = "group"
            elif prev_scale == "wide":
                prefer = "solo"
            p = take(prefer_kind=prefer, need=share)
            if p is None:
                break
            dur = min(max(share, 2.2), p["max_dur"])
            # cut BEFORE the action ends: use the head of the window
            shot = {
                "path": p["source"]["normalized"],
                "in": round(p["in"], 3),
                "out": round(p["in"] + dur, 3),
                "dur": round(dur, 3),
                "source_video_id": p["source"]["video_id"],
                "source_title": p["source"]["title"],
                "credit": f"{p['source']['title']} ({p['source']['channel']}) " +
                          p["source"]["url"],
                "scale": p["scale"],
                "kind": p["kind"],
                "ahyeon_verified": True,
                "window_conf": round(p["conf"], 3),
            }
            shots.append(shot)
            prev_scale, prev_src = p["scale"], p["source"]["video_id"]
            remaining -= dur
            if remaining <= 2.0 and shots:
                break
        if not shots:
            raise RuntimeError(f"scene {sid}: no Ahyeon window could be assigned")
        scales = {s["scale"] for s in shots}
        manifest[str(sid)] = {
            "kind": "video",
            "scale": scales.pop() if len(scales) == 1 else "mixed",
            "credit": shots[0]["credit"],
            "source_title": shots[0]["source_title"],
            "ahyeon_verified": True,
            "shots": shots,
        }

    # audit: adjacent scenes must differ in source or scale
    swaps = []
    for a, b in zip(order, order[1:]):
        ma, mb = manifest[str(a)], manifest[str(b)]
        sa, sb = ma["shots"][0], mb["shots"][0]
        if sa["source_video_id"] == sb["source_video_id"] and sa["scale"] == sb["scale"]:
            swaps.append(f"scenes {a}->{b} share source+scale")
    json.dump({"manifest": manifest, "audit_warnings": swaps,
               "style": topic.get("style", "documentary"),
               "pool_size": len(pool), "windows_used": len(used)},
              open(os.path.join(run_dir, "04_media.json"), "w"), indent=1)
    return manifest


def run(run_dir, *a, **k):
    manifest = assign(run_dir)
    n = sum(len(m["shots"]) for m in manifest.values())
    print(f"[s4] assigned {n} Ahyeon-verified shots across "
          f"{len(manifest)} scenes")
    return manifest


if __name__ == "__main__":
    run(sys.argv[1])
