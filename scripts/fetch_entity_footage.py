#!/usr/bin/env python3
"""Entity-targeted footage acquisition for the smart scene director.

Pipeline: web_search per slot -> pick official/authoritative source ->
ytagent download (cobalt_community ladder) -> title-based entity tags ->
footage/library.json

Entity taxonomy (fixed vocabulary, used by the matcher):
  ahyeon_solo        - Ahyeon alone / clearly the only subject
  babymonster_members- BABYMONSTER group (2+ members visible)
  blackpink_group    - BLACKPINK (the senior group)
  yg_brand           - YG logos / building / branding
  announcement       - official reveal/announcement/news context
  stage_performance  - live/stage performance footage
  mv_quality         - official MV footage (cinematic, crisp)

Usage: python3 scripts/fetch_entity_footage.py [--only slot1,slot2]
"""
import json, os, subprocess, sys, time, re
from pathlib import Path

ROOT = Path("/home/z/my-project")
DL = ROOT / "ytdl-agent" / "downloads" / "entity"
LIB = ROOT / "footage"
LIB.mkdir(exist_ok=True)
DL.mkdir(parents=True, exist_ok=True)

# --- slot definitions: (slot_id, search_queries, entities, prefer_words) ---
SLOTS = [
    ("blackpink_group",
     ["BLACKPINK How You Like That official MV youtube", "BLACKPINK Pink Venom official MV youtube"],
     ["blackpink_group", "mv_quality"], ["mv", "official"]),
    ("reveal_ahyeon",
     ["BABYMONSTER AHYEON visual reveal official", "BABYMONSTER AHYEON reveal video YG"],
     ["ahyeon_solo", "announcement"], ["reveal", "official"]),
    ("return_announcement",
     ["YG announces AHYEON return BABYMONSTER news", "AHYEON return BABYMONSTER 7th member news video"],
     ["announcement", "ahyeon_solo"], ["return", "announce"]),
    ("debut_six",
     ["BABYMONSTER BATTER UP official MV youtube", "BABYMONSTER BATTER UP debut MV"],
     ["babymonster_members", "mv_quality"], ["mv", "official"]),
    ("debut_seven",
     ["BABYMONSTER SHEESH official MV youtube", "BABYMONSTER BABYMONS7ER SHEESH MV"],
     ["babymonster_members", "mv_quality"], ["mv", "official"]),
    ("ahyeon_focus",
     ["BABYMONSTER DRIP AHYEON focus cam official", "BABYMONSTER DRIP AHYEON fancam stage"],
     ["ahyeon_solo", "stage_performance"], ["focus", "ahyeon"]),
    ("members_stage",
     ["BABYMONSTER SHEESH THE FIRST TAKE", "BABYMONSTER Stuck In The Middle official MV"],
     ["babymonster_members", "stage_performance"], ["first take", "official"]),
]

YT_PAT = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})")


def sh(cmd, timeout=120):
    """Subprocess with grandchild-safe kill semantics."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), 15)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=8)
        except Exception:
            try:
                os.killpg(os.getpgid(p.pid), 9)
            except Exception:
                pass
            out, err = "", ""
        return -9, out or "", err or ""


def web_search(query, num=8):
    rc, out, _ = sh(["z-ai", "function", "-n", "web_search",
                     "-a", json.dumps({"query": query, "num": num})], timeout=90)
    i, j = out.find("["), out.rfind("]")
    if i == -1 or j <= i:
        return []
    try:
        return json.loads(out[i:j + 1])
    except Exception:
        return []


def pick_candidates(query, prefer):
    res = web_search(query)
    scored = []
    for r in res:
        url = r.get("url") or r.get("link") or ""
        m = YT_PAT.search(url)
        if not m:
            continue
        title = (r.get("name") or r.get("title") or "").strip()
        score = sum(2 for w in prefer if w in title.lower())
        if any(b in title.lower() for b in ["reaction", "shorts", "eng sub", "lyrics only"]):
            score -= 2
        scored.append((score, title, m.group(1)))
    scored.sort(key=lambda x: -x[0])
    return scored[:3]


def ytagent_download(vid, out_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "agent-tools" / "ytagent" / "src"))
    out_dir = str(out_path.parent)
    final = out_path.parent / f"{vid}.mp4"
    if final.exists() and final.stat().st_size > 500_000:
        return 0, str(final)
    rc, out, err = sh([sys.executable, "-c",
                       "import sys; sys.path.insert(0,'{}'); from ytagent.cli import cli; cli()".format(
                           ROOT / "agent-tools" / "ytagent" / "src"),
                       "download", vid, "--out-dir", out_dir, "--format", "mp4"], timeout=280)
    # ytagent names output <vid>.mp4 inside out-dir
    if rc == 0:
        cand = final if final.exists() else out_path.parent / vid / f"{vid}.mp4"
        for c in out_path.parent.rglob(f"{vid}*.mp4"):
            cand = c
            break
        if cand.exists():
            if cand != final:
                cand.rename(final)
            return 0, str(final)
    return rc, (err[-300:] or out[-300:])


def probe_duration(path):
    rc, out, _ = sh(["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_format", str(path)], timeout=30)
    try:
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return 0.0


def main():
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))

    lib_path = LIB / "library.json"
    library = json.loads(lib_path.read_text()) if lib_path.exists() else {"clips": []}
    have = {c["clip_id"] for c in library["clips"]}

    for slot_id, queries, entities, prefer in SLOTS:
        if only and slot_id not in only:
            continue
        if slot_id in have:
            print(f"[skip] {slot_id} already in library")
            continue
        print(f"\n=== slot {slot_id} ===")
        got = None
        for q in queries:
            for score, title, vid in pick_candidates(q, prefer):
                print(f"  try: {vid} ({title[:60]}) score={score}")
                target = DL / f"{slot_id}.mp4"
                rc, info = ytagent_download(vid, target)
                if rc == 0 and Path(info).exists() and Path(info).stat().st_size > 500_000:
                    dur = probe_duration(info)
                    if dur >= 30:
                        got = {"clip_id": slot_id, "file": str(info), "video_id": vid,
                               "source_title": title, "entities": entities,
                               "duration": dur, "verified": "title"}
                        print(f"  OK: {info} dur={dur:.1f}s")
                        break
                print(f"  fail rc={rc} {info[:120]}")
            if got:
                break
        if got:
            library["clips"].append(got)
            lib_path.write_text(json.dumps(library, indent=1, ensure_ascii=False))
        else:
            print(f"  !! slot {slot_id} FAILED (no usable source)")
        time.sleep(2)

    # register existing local footage with known timing maps
    known = [
        {"clip_id": "dangerously_eval", "file": str(ROOT / "ytdl-agent/downloads/xw7Y2gviWbA.mp4"),
         "video_id": "xw7Y2gviWbA", "source_title": "AHYEON Dangerously (Last Evaluation solo)",
         "entities": ["ahyeon_solo", "stage_performance"], "duration": probe_duration(ROOT / "ytdl-agent/downloads/xw7Y2gviWbA.mp4"),
         "verified": "title+vision", "segment_hints": {"whole": "ahyeon solo studio performance"}},
        {"clip_id": "sheesh_tft", "file": str(ROOT / "ytdl-agent/downloads/O99aP4AvEF8.mp4"),
         "video_id": "O99aP4AvEF8", "source_title": "BABYMONSTER SHEESH - THE FIRST TAKE",
         "entities": ["babymonster_members", "stage_performance", "ahyeon_solo"],
         "duration": probe_duration(ROOT / "ytdl-agent/downloads/O99aP4AvEF8.mp4"),
         "verified": "title+vision+asr", "segment_hints": {"t120-160": "AHYEON vocal showcase"}},
        {"clip_id": "drip_tft", "file": str(ROOT / "ytdl-agent/downloads/06mCrMgv0zY.mp4"),
         "video_id": "06mCrMgv0zY", "source_title": "BABYMONSTER DRIP - THE FIRST TAKE",
         "entities": ["babymonster_members", "stage_performance", "ahyeon_solo"],
         "duration": probe_duration(ROOT / "ytdl-agent/downloads/06mCrMgv0zY.mp4"),
         "verified": "title+vision+asr", "segment_hints": {"t115-155": "AHYEON vocal line"}},
    ]
    have = {c["clip_id"] for c in library["clips"]}
    for k in known:
        if k["clip_id"] not in have and Path(k["file"]).exists():
            library["clips"].append(k)
            print(f"[+] registered local: {k['clip_id']}")
    lib_path.write_text(json.dumps(library, indent=1, ensure_ascii=False))
    print(f"\nLibrary: {len(library['clips'])} clips -> {lib_path}")


if __name__ == "__main__":
    main()
