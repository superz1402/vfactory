#!/usr/bin/env python3
"""Dispatch yt-farm (GitHub Actions) to download entity footage, then fetch results.

Usage:
  python3 scripts/farm_fetch.py dispatch   # dispatch all missing slots
  python3 scripts/farm_fetch.py poll       # poll runs, download finished artifacts
  python3 scripts/farm_fetch.py status     # show run states
"""
import json, os, subprocess, sys, time, zipfile, io
from pathlib import Path

ROOT = Path("/home/z/my-project")
ENTITY = ROOT / "ytdl-agent" / "downloads" / "entity"
ENTITY.mkdir(parents=True, exist_ok=True)
TOKEN = (ROOT / ".gh_token").read_text().strip()
REPO = "superz1402/moltbook-agent"
API = f"https://api.github.com/repos/{REPO}"

# video_id -> slot name  (verified via ytsearch titles + oEmbed)
WANTED = {
    "ioNng23DkIM": "blackpink_group",      # BLACKPINK - 'How You Like That' M/V
    "1myrYL8ybzM": "visual_film",          # [BABYMONS7ER] VISUAL FILM (return-era reveal)
    "8i_wZQoqbwU": "introducing_ahyeon",   # BABYMONSTER - Introducing AHYEON
    "olDWm2veCrM": "batter_up_mv",         # BABYMONSTER - 'BATTER UP' M/V (debut as six)
    "2wA_b6YHjqQ": "sheesh_mv",            # BABYMONSTER - 'SHEESH' M/V (debut as seven)
    "jPS1dDnyxTQ": "ahyeon_drip_facecam",  # AHYEON 'DRIP' FaceCam 4K @Inkigayo
    "GsV1i0QHi-o": "stuck_middle_mv",      # BABYMONSTER - 'Stuck In The Middle' M/V
}


def sh(cmd, timeout=120):
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
            out, err = "", ""
        return -9, out or "", err or ""


def gh(path, method="GET", body=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"Authorization: token {TOKEN}",
           "-H", "Accept: application/vnd.github+json"]
    if body:
        cmd += ["-d", json.dumps(body)]
    cmd.append(f"{API}{path}")
    rc, out, _ = sh(cmd, timeout=60)
    try:
        return json.loads(out)
    except Exception:
        return {"_raw": out[:300], "_rc": rc}


def slot_file(slot):
    return ENTITY / f"{slot}.mp4"


def missing_slots():
    return {vid: slot for vid, slot in WANTED.items()
            if not (slot_file(slot).exists() and slot_file(slot).stat().st_size > 500_000)}


def dispatch():
    todo = missing_slots()
    print(f"to dispatch: {list(todo.values())}")
    for vid, slot in todo.items():
        r = gh("/actions/workflows/yt-farm.yml/dispatches", "POST",
               {"ref": "main", "inputs": {"video_url": f"https://www.youtube.com/watch?v={vid}",
                                           "video_id": vid}})
        print(f"  dispatched {slot} ({vid}) -> {r if r.get('_raw') else 'OK'}")
        time.sleep(3)


def list_runs(minutes=90):
    runs = gh(f"/actions/runs?event=workflow_dispatch&per_page=30")
    out = []
    for r in runs.get("workflow_runs", []):
        if r["name"].strip().lower() != "yt download farm":
            continue
        out.append({"id": r["id"], "status": r["status"], "conclusion": r["conclusion"],
                    "created": r["created_at"], "vid": None})
    return out


def poll():
    done_ids = {}
    runs = list_runs()
    print(f"{len(runs)} farm runs found")
    for run in runs:
        if run["status"] != "completed":
            continue
        arts = gh(f"/actions/runs/{run['id']}/artifacts?per_page=10")
        for a in arts.get("artifacts", []):
            if a["name"].startswith("video_"):
                vid = a["name"][6:]
                if vid in WANTED:
                    done_ids[vid] = (run["id"], a)
    print(f"completed artifacts: {[WANTED[v] for v in done_ids]}")
    for vid, (run_id, art) in done_ids.items():
        slot = WANTED[vid]
        dest = slot_file(slot)
        if dest.exists() and dest.stat().st_size > 500_000:
            continue
        print(f"fetching {slot} ({vid}) ...")
        rc, out, err = sh(["curl", "-sL", "-H", f"Authorization: token {TOKEN}",
                           "-o", str(ENTITY / f"art_{vid}.zip"),
                           f"{API}/actions/artifacts/{art['id']}/zip"], timeout=280)
        zpath = ENTITY / f"art_{vid}.zip"
        try:
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    if name.endswith(".mp4"):
                        data = z.read(name)
                        dest.write_bytes(data)
                        print(f"  saved {dest} ({len(data)/1e6:.1f}MB)")
                        break
        except Exception as e:
            print(f"  zip fail: {e}")
        if zpath.exists():
            zpath.unlink()
    # release fallback for anything still missing
    for vid, slot in missing_slots().items():
        rc, out, err = sh(["curl", "-sL", "-H", f"Authorization: token {TOKEN}",
                           "-o", str(ENTITY / f"rel_{vid}.bin"),
                           f"https://api.github.com/repos/{REPO}/releases/tags/vid-{vid}"], timeout=60)
        try:
            rel = json.loads((ENTITY / f"rel_{vid}.bin").read_text())
            for asset in rel.get("assets", []):
                sh(["curl", "-sL", "-H", f"Authorization: token {TOKEN}",
                    "-o", str(ENTITY / f"rel_{vid}.mp4"),
                    asset["browser_download_url"].replace("https://api.github.com/repos",
                        "https://github.com").replace("/releases", "/releases/download")],
                   timeout=280)
                # direct download url form:
                sh(["curl", "-sL", "-H", f"Authorization: token {TOKEN}",
                    "-H", "Accept: application/octet-stream",
                    "-o", str(ENTITY / f"rel_{vid}.mp4"),
                    f"{API}/releases/assets/{asset['id']}"], timeout=280)
                f = ENTITY / f"rel_{vid}.mp4"
                if f.exists() and f.stat().st_size > 500_000:
                    f.rename(slot_file(slot))
                    print(f"  release-fallback saved {slot}")
                break
        except Exception:
            pass
        f = ENTITY / f"rel_{vid}.bin"
        if f.exists():
            f.unlink()
    rem = missing_slots()
    print(f"STILL MISSING: {list(rem.values()) if rem else 'none'}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "dispatch":
        dispatch()
    elif cmd == "poll":
        poll()
    else:
        for vid, slot in WANTED.items():
            f = slot_file(slot)
            print(f"{slot:22s} {'OK ' + str(f.stat().st_size//1000000) + 'MB' if f.exists() else 'missing'} ({vid})")
