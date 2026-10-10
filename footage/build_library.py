#!/usr/bin/env python3
"""Footage library builder — the s4 ingredient that killed 'random clips'.

Wraps character-clip-extractor (ansaribilal14/character-clip-extractor):
for every source video listed in footage/sources.json it runs (or reuses)
the analysis pipeline (normalize -> shots -> InsightFace @2fps -> raw
visibility -> audio -> scene grouping) inside /home/z/my-project/cce-ws/<ws>,
then emits footage/library.json — an index of Ahyeon-verified visibility
windows per source.

s4 consumes ONLY windows from this library. No image-search, no stock
photos, no unverified footage can enter the pipeline.

Usage:
  python3 footage/build_library.py            # build/refresh library.json
  python3 footage/build_library.py --list     # summarize the library
"""
import json, os, subprocess, sys, time

BASE = os.path.dirname(os.path.abspath(__file__))
VF = os.path.dirname(BASE)                     # vfactory root
CCE_REPO = "/home/z/my-project/research-repos/character-clip-extractor"
CCE_WS = "/home/z/my-project/cce-ws"
PY = "/home/z/my-project/venv-cce/bin/python"
SOURCES_JSON = os.path.join(BASE, "sources.json")
LIBRARY_JSON = os.path.join(BASE, "library.json")


def run_step(ws, script, timeout=590):
    env = dict(os.environ, CCE_BASE=os.path.join(CCE_WS, ws), CCE_TARGET="ahyeon")
    p = subprocess.run([PY, os.path.join(CCE_REPO, "scripts", script)],
                       capture_output=True, text=True, timeout=timeout, env=env)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out


def analyze_source(ws, force=False):
    """Run cce steps 00-05 for one workspace. Resumes via cce sentinels."""
    an = os.path.join(CCE_WS, ws, "output", "analysis")
    done = os.path.join(an, "grouped_scenes.json")
    if os.path.exists(done) and not force:
        return True, "cached"

    steps = [
        ("00_normalize.py", "normalized.mp4", 300),
        ("01_detect_shots.py", "shots.json", 300),
        ("02_analyze_faces.py", "analysis.jsonl", 590),   # frame-level resume
        ("03_raw_visibility.py", "raw_visibility.json", 120),
        ("04_audio_activity.py", "audio_activity.json", 120),
        ("05_group_scenes.py", "grouped_scenes.json", 120),
    ]
    for script, sentinel, tmo in steps:
        if os.path.exists(os.path.join(an, sentinel)):
            continue
        try:
            rc, out = run_step(ws, script, tmo)
        except subprocess.TimeoutExpired:
            return False, f"{script} timed out (resume by re-running)"
        if rc != 0 or not os.path.exists(os.path.join(an, sentinel)):
            tail = "\n".join((out or "").strip().splitlines()[-3:])
            return False, f"{script} failed: {tail}"
    return True, "analyzed"


def build(force=False):
    sources = json.load(open(SOURCES_JSON))
    library = {"character": "ahyeon", "built": time.strftime("%Y-%m-%d %H:%M:%S"),
               "sources": []}
    problems = []
    for src in sources["sources"]:
        ws = src["workspace"]
        print(f"[library] {src['video_id']} ({src.get('kind','?')}) workspace={ws}",
              flush=True)
        # source file must exist (copy on first run)
        an = os.path.join(CCE_WS, ws, "output", "analysis")
        norm = os.path.join(an, "normalized.mp4")
        srcfile = os.path.join(CCE_WS, ws, "output", "source")
        if not os.path.exists(norm):
            os.makedirs(srcfile, exist_ok=True)
            # find the source video listed
            local = src.get("local_file")
            if local and os.path.exists(local):
                dst = os.path.join(srcfile, os.path.basename(local))
                if not os.path.exists(dst):
                    os.link(local, dst) if os.path.exists(dst) is False else None
                    if not os.path.exists(dst):
                        os.link(local, dst)
        ok, msg = analyze_source(ws, force=force)
        if not ok:
            problems.append(f"{src['video_id']}: {msg}")
            print(f"[library]   SKIP ({msg})", flush=True)
            continue
        raw = json.load(open(os.path.join(an, "raw_visibility.json")))
        grouped = json.load(open(os.path.join(an, "grouped_scenes.json")))
        import subprocess as sp
        dur = float(sp.check_output(["ffprobe", "-v", "error", "-show_entries",
                                     "format=duration", "-of", "csv=p=0",
                                     norm]).decode().strip())
        library["sources"].append({
            "video_id": src["video_id"],
            "title": src["title"],
            "channel": src.get("channel", ""),
            "url": f"https://www.youtube.com/watch?v={src['video_id']}",
            "kind": src.get("kind", "group"),
            "workspace": ws,
            "normalized": norm,
            "duration": round(dur, 2),
            "raw_intervals": raw.get("intervals", raw if isinstance(raw, list) else []),
            "grouped_scenes": grouped.get("scenes", []),
        })
        n_vis = sum(iv.get("duration", 0) for iv in library["sources"][-1]["raw_intervals"])
        print(f"[library]   ok: {len(library['sources'][-1]['raw_intervals'])} windows, "
              f"{n_vis:.1f}s verified-visible ({msg})", flush=True)
    json.dump(library, open(LIBRARY_JSON, "w"), indent=1)
    print(f"[library] wrote {LIBRARY_JSON} "
          f"({len(library['sources'])} sources, {len(problems)} problems)")
    for p in problems:
        print("[library]   PROBLEM:", p)
    return library


def summarize():
    lib = json.load(open(LIBRARY_JSON))
    tot = 0
    for s in lib["sources"]:
        vis = sum(i.get("duration", 0) for i in s["raw_intervals"])
        tot += vis
        print(f"{s['video_id']} [{s['kind']:5}] {vis:6.1f}s visible | {s['title'][:60]}")
        for i in s["raw_intervals"]:
            if i.get("duration", 0) >= 2.0:
                print(f"    {i['start']:8.2f} - {i['end']:8.2f}  ({i['duration']:.2f}s, "
                      f"conf~{i.get('mean_cos', 0):.2f})")
    print(f"TOTAL verified-visible: {tot:.1f}s across {len(lib['sources'])} sources")


if __name__ == "__main__":
    if "--list" in sys.argv:
        summarize()
    else:
        build(force="--force" in sys.argv)
