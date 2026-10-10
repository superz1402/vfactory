#!/usr/bin/env python3
"""Stage 4 (v2): beat plan -> documentary shot list.

Grammar (from reference metrics, DESIGN_V2.md):
- 2-5 shots per beat, each 2.0-6.0s (ASL target ~4s, median 2.5-4s)
- pacing arc: hook beats get shorter shots (fast cpm), later beats longer
- source mix: mv-library segments + stock clips + minimal stills (<=40%)
- punch-ins for energy, stills get Ken Burns, chapter cards at chapter starts
"""
import json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import footage  # noqa: E402

TAIL = 0.45          # narration tail per beat (s)
STILL_MAX_FRAC = 0.40

MOOD_TAGS = {
    "dark": ["closeup", "glamour", "emotional", "solo", "city"],
    "tense": ["dance", "performance", "stage", "city"],
    "hopeful": ["vocal", "live", "crowd", "glamour"],
    "triumphant": ["stage", "performance", "crowd", "group"],
    "reflective": ["closeup", "vocal", "emotional", "solo"],
    "energetic": ["dance", "performance", "group", "stage"],
}


def _keywords(text):
    return set(re.findall(r"[a-z]{3,}", (text or "").lower()))


def score_segment(seg_video, beat, used_ids, rng):
    """Tag/keyword overlap score for a local-library segment."""
    vid_id = seg_video["id"]
    if vid_id in used_ids:
        # allow reuse of a *different* segment from same video, small penalty
        pass
    tags = set(seg_video["tags"])
    intent_words = _keywords(" ".join(beat.get("visual_intent", [])))
    mood_words = set(MOOD_TAGS.get(beat.get("mood", ""), []))
    score = len(tags & intent_words) * 2 + len(tags & mood_words)
    score -= used_ids.count(vid_id) * 0.5
    return score + rng.uniform(0, 1.0)


def pick_stock_query(beat):
    """Map a beat's visual intent to a stock search query."""
    text = " ".join(beat.get("visual_intent", [])).lower()
    table = [
        ("seoul", "seoul city night"),
        ("city", "city skyline night"),
        ("street", "city street night"),
        ("crowd", "concert crowd"),
        ("lightstick", "concert crowd lights"),
        ("concert", "concert stage lights"),
        ("stage", "concert stage lights"),
        ("studio", "recording studio microphone"),
        ("practice", "dance studio"),
        ("mirror", "dance studio"),
        ("magazine", "magazine cover"),
        ("billboard", "city billboard night"),
        ("airport", "airport crowd travel"),
        ("arena", "concert arena crowd"),
        ("global", "earth globe night lights"),
        ("world", "earth globe night lights"),
        ("backstage", "backstage corridor"),
        ("camera", "camera lens closeup"),
        ("phone", "smartphone social media"),
    ]
    for k, q in table:
        if k in text:
            return q
    return "concert stage lights" if "stage" in text else None


def run(run_dir, region="us", seed=7):
    import random
    rng = random.Random(seed)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    timings = {t["id"]: t["audio"] for t in json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]}
    beats = plan["beats"]

    idx = footage.scan_local()
    videos = [dict(v, id=vid) for vid, v in idx["videos"].items()]
    if not videos:
        raise RuntimeError("local MV library empty — cannot build documentary shots")

    # what stock do we need?
    stock_queries = []
    for b in beats:
        q = pick_stock_query(b)
        if q and q not in stock_queries:
            stock_queries.append(q)
    stock_man = footage.ensure_stock(stock_queries) if stock_queries else {}

    # ---- plan shots ----
    n_beats = len(beats)
    shot_list, used_segments = [], []
    rot, last_video_id = {}, None
    still_count = video_count = 0

    for bi, b in enumerate(beats):
        beat_dur = max(3.0, timings.get(b["id"], 6.0) + TAIL)
        # pacing arc: hook fast, body medium, outro slower (ref: ASL 4.4-4.6,
        # median 2.5-4.0, hook cpm ~20)
        if bi <= 1:
            tgt = rng.uniform(1.7, 2.6)
        elif bi >= n_beats - 2:
            tgt = rng.uniform(3.2, 4.6)
        else:
            tgt = rng.uniform(2.3, 3.6)
        n_shots = max(2, min(6, round(beat_dur / tgt)))
        shots = []
        remaining = beat_dur

        # stock availability for this beat
        sq = pick_stock_query(b)
        stock_pool = [p for p in stock_man.get(sq, []) if footage.ffprobe_dur(p) >= 2.0] if sq else []

        for si in range(n_shots):
            if si == n_shots - 1:
                dur = remaining
            else:
                frac = rng.uniform(0.30, 0.52)
                dur = max(1.5, min(remaining - 1.4 * (n_shots - si - 1), remaining * frac))
            dur = round(min(dur, 6.0), 2)
            if dur < 1.2:
                break
            remaining -= dur

            src_type = None
            # 1) local MV segment (primary) — weighted by score, rotated through
            #    the video timeline, and never the same video twice in a row
            if videos and (si < n_shots - 1 or not stock_pool):
                vids = sorted(videos, key=lambda v: score_segment(v, b, used_segments, rng),
                              reverse=True)
                for v in vids:
                    if last_video_id and v["id"] == last_video_id and len(vids) > 1:
                        continue  # enforce consecutive-shot variety
                    segs = [s for s in v["segments"] if s["dur"] >= dur - 0.4]
                    if not segs:
                        continue
                    rot_i = rot.get(v["id"], 0)
                    rot[v["id"]] = rot_i + 1
                    seg = segs[rot_i % len(segs)]
                    use_dur = min(dur, seg["dur"])
                    shots.append({
                        "type": "video", "src": v["path"], "src_id": v["label"],
                        "in": round(seg["in"] + rng.uniform(0, max(0.05, seg["dur"] - use_dur - 0.05)), 2),
                        "dur": round(use_dur, 2),
                        "treatment": "punch_in" if (bi <= 2 and rng.random() < 0.5) else "flat",
                        "source": "local_mv:" + v["label"],
                    })
                    used_segments.append(v["id"])
                    last_video_id = v["id"]
                    video_count += 1
                    src_type = "video"
                    break
            # 2) stock clip
            if src_type is None and stock_pool:
                sp = rng.choice(stock_pool)
                d = footage.ffprobe_dur(sp)
                use_dur = min(dur, d - 0.4)
                if use_dur >= 1.4:
                    shots.append({
                        "type": "video", "src": sp, "src_id": os.path.basename(sp),
                        "in": round(rng.uniform(0, max(0.1, d - use_dur - 0.1)), 2),
                        "dur": round(use_dur, 2),
                        "treatment": "flat",
                        "source": "stock:" + os.path.basename(sp),
                    })
                    video_count += 1
                    src_type = "video"
            # 3) still fallback
            if src_type is None:
                q = (b.get("visual_intent") or [b.get("on_screen") or b["narration"][:40]])[0]
                dst = os.path.join(run_dir, "stills", f"b{b['id']:02d}_s{si}.jpg")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if footage.fetch_still(q, dst, region=region):
                    shots.append({
                        "type": "still", "src": dst, "src_id": os.path.basename(dst),
                        "in": 0, "dur": dur, "treatment": "kenburns",
                        "source": "image-search:" + q,
                    })
                    still_count += 1
                else:
                    shots.append({
                        "type": "card", "src": "", "src_id": "",
                        "in": 0, "dur": dur, "treatment": "flat",
                        "text": b.get("on_screen") or b["chapter"].upper(),
                        "source": "generated card",
                    })
            if not shots:
                raise RuntimeError(f"beat {b['id']}: no shot could be produced")
        shot_list.append({"beat_id": b["id"], "chapter": b.get("chapter", "story"),
                          "dur": round(beat_dur, 2), "shots": shots})
        # elegant overlay text rides on the FIRST shot of the beat
        if shots and b.get("on_screen"):
            shots[0]["on_screen"] = b["on_screen"]

    # ---- chapter cards ----
    cards = {}
    for c in plan.get("chapters", []):
        if c.get("card_text"):
            cards[c["id"]] = c["card_text"]
    final_list = []
    for entry in shot_list:
        card = cards.get(entry["chapter"])
        if card:
            final_list.append({"beat_id": entry["beat_id"], "chapter": entry["chapter"],
                               "card": {"type": "card", "dur": 1.8, "text": card,
                                        "source": "chapter card"}})
            entry.pop("chapter")
        final_list.append(entry)

    total_shots = sum(len(e["shots"]) for e in shot_list) + len([e for e in final_list if "card" in e])
    still_frac = still_count / max(1, total_shots)
    manifest = {
        "beats": final_list, "stats": {
            "total_shots": total_shots, "video_shots": video_count,
            "stills": still_count, "still_frac": round(still_frac, 2)},
    }
    json.dump(manifest, open(os.path.join(run_dir, "04_shots.json"), "w"),
              ensure_ascii=False, indent=1)
    return manifest


if __name__ == "__main__":
    run_dir = sys.argv[1]
    m = run(run_dir)
    print(json.dumps(m["stats"], indent=1))
