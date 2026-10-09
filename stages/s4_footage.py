#!/usr/bin/env python3
"""Stage 4v2: REAL footage sourcing — shot planner.
Builds a shot list from the local footage pool (yt-farm / ytdl-agent downloads
+ any dirs injected via config). Each narration scene becomes 2-5 shots with
varied motion treatments. Images/AI b-roll are fallback only.
Output: 04_footage.json = [{scene_id, shots: [{src, start, dur, motion, crop_x}]}]
"""
import glob, json, os, random, subprocess, sys

POOL_DIRS = [
    "/home/z/my-project/ytdl-agent/downloads",
    "/home/z/my-project/vfactory/footage",
]
MIN_SHOT = 1.8
MAX_SHOT = 3.4
MOTIONS = ["punch-in", "pull-out", "pan-l", "pan-r", "drift"]


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def discover_pool():
    pool = []
    for d in POOL_DIRS:
        for p in sorted(glob.glob(os.path.join(d, "*.mp4"))):
            dur = probe(p)
            if dur >= 10:
                pool.append({"path": p, "duration": dur,
                             "name": os.path.basename(p)})
    return pool


def plan(run_dir, seed=7):
    rng = random.Random(seed)
    pool = discover_pool()
    plan_data = {"pool": pool, "scenes": []}
    if not pool:
        return plan_data
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    durs = tl["durations"]
    # segment cursor per source so segments never repeat
    cursor = {p["path"]: rng.uniform(3.0, 8.0) for p in pool}
    for sid in sorted(int(k) for k in durs):
        need = durs[str(sid)]
        shots, acc = [], 0.0
        n_shots = max(2, min(5, round(need / 2.6)))
        base = need / n_shots
        pi = (sid - 1) % len(pool)  # rotate sources per scene
        for n in range(n_shots):
            dur = min(MAX_SHOT, max(MIN_SHOT, base * rng.uniform(0.85, 1.15)))
            if n == n_shots - 1:
                dur = need - acc  # exact fit
            src = pool[pi]["path"]
            start = cursor[src]
            if start + dur + 0.5 > pool[pi]["duration"]:
                start = cursor[src] = rng.uniform(3.0, 8.0)
            shots.append({"src": src, "start": round(start, 2),
                          "dur": round(dur, 2),
                          "motion": MOTIONS[(sid + n) % len(MOTIONS)],
                          "crop_x": rng.choice([0.5, 0.35, 0.65])})
            cursor[src] = start + dur + rng.uniform(2.0, 6.0)
            acc += dur
            pi = (pi + 1) % len(pool)  # alternate sources inside scene
        plan_data["scenes"].append({"scene_id": sid, "shots": shots})
    return plan_data


def run(run_dir, seed=7):
    data = plan(run_dir, seed)
    out = os.path.join(run_dir, "04_footage.json")
    json.dump(data, open(out, "w"), indent=1)
    n = sum(len(s["shots"]) for s in data["scenes"])
    return {"pool": len(data["pool"]), "shots": n, "mode": "footage" if data["pool"] else "none"}


if __name__ == "__main__":
    print(run(sys.argv[1]))
