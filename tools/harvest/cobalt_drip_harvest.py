#!/usr/bin/env python3
"""Cobalt slow-drip harvester — server-side supplementary lane, NO new IPs needed.

Discovery (2026-10-16 live tests): the only no-auth cobalt relay
(api.cobalt.liubquanti.click) rate-limits per source IP at ~1 request / 90s.
It recovers after cooldown and tunnels REAL video/mp4 bytes from googlevideo.

So: drip 1 request per cooldown window, download fully, validate, checkpoint.
Runs bounded (--budget-sec) so it can be driven in foreground bursts.

State: ytdl-agent/downloads/harvest/drip_state.json
Files: ytdl-agent/downloads/harvest/<source_id>.mp4
"""
import argparse, json, os, shutil, subprocess, sys, time
import requests, urllib3
urllib3.disable_warnings()

BASE = "/home/z/my-project/ytdl-agent/downloads/harvest"
SOURCES = f"{BASE}/sources.json"
STATE = f"{BASE}/drip_state.json"
RELAY = "https://api.cobalt.liubquanti.click"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) rv:130.0 Gecko/20100101 Firefox/130.0"
MIN_BYTES = 2 * 1024 * 1024          # <2MB = garbage
GAP_OK = 100                         # cooldown after any completed cycle
GAP_RETRY = 180                      # after a timeout/soft fail

def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"done": {}, "fails": {}, "updated": None}

def valid_file(path):
    if not os.path.exists(path) or os.path.getsize(path) < MIN_BYTES:
        return False
    try:
        p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name,width,height",
                            "-show_entries", "format=duration",
                            "-of", "json", path], capture_output=True, text=True, timeout=30)
        d = json.loads(p.stdout)
        v = d["streams"][0]
        dur = float(d["format"]["duration"])
        return v["codec_name"] in ("h264", "avc1", "vp9", "vp8", "av1") and dur > 10
    except Exception:
        return False

def relay_attempt(session, video_id, out_path, max_bytes):
    """One API call + full tunnel download. Returns (status, bytes)."""
    try:
        r = session.post(RELAY + "/", json={
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "videoQuality": "720", "youtubeVideoCodec": "h264",
            "youtubeVideoContainer": "mp4", "downloadMode": "auto"},
            headers={"Accept": "application/json"}, timeout=30)
    except requests.exceptions.ReadTimeout:
        return ("api_timeout", 0)
    except Exception as e:
        return (f"api_conn:{type(e).__name__}", 0)
    try:
        body = r.json()
    except Exception:
        return (f"api_http_{r.status_code}_nonjson", 0)
    st = body.get("status")
    if body.get("status") == "error":
        code = body.get("error", {}).get("code", "unknown")
        return (f"api_error:{code}", 0)
    tunnels = body.get("tunnel") or ([{"url": body["url"]}] if body.get("url") else [])
    if not tunnels:
        return (f"unexpected_status:{st}", 0)
    turl = tunnels[0]["url"] if isinstance(tunnels[0], dict) else tunnels[0]
    tmp = out_path + ".part"
    got = 0
    try:
        with session.get(turl, stream=True, timeout=90, verify=False) as resp:
            if resp.status_code != 200:
                return (f"tunnel_http_{resp.status_code}", 0)
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk); got += len(chunk)
                    if max_bytes and got >= max_bytes: break
        if got == 0:
            # signed URL sometimes needs one immediate re-GET (does not hit API rate limit)
            with session.get(turl, stream=True, timeout=90, verify=False) as resp:
                if resp.status_code == 200:
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(1 << 20):
                            f.write(chunk); got += len(chunk)
                            if max_bytes and got >= max_bytes: break
    except Exception as e:
        if got < MIN_BYTES:
            if os.path.exists(tmp): os.remove(tmp)
            return (f"stream_died:{type(e).__name__}", got)
        # partial but substantial: keep tmp, let validation decide
    if got < MIN_BYTES:
        if os.path.exists(tmp): os.remove(tmp)
        return ("too_small", got)
    shutil.move(tmp, out_path)
    return ("ok", got)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-sec", type=int, default=520)
    ap.add_argument("--max-priority", type=int, default=1)
    ap.add_argument("--max-bytes", type=int, default=700 * 1024 * 1024)
    ap.add_argument("--max-fails", type=int, default=6)
    a = ap.parse_args()

    items = [i for i in json.load(open(SOURCES))["items"] if i[3] <= a.max_priority]
    items.sort(key=lambda i: i[3])
    st = load_state()
    # decay soft-fail counters each burst: upstream roulette is transient,
    # only persistent item-specific errors (api_error: video unavailable etc.)
    # should accumulate to max_fails
    st["fails"] = {k: max(0, v - 1) for k, v in st["fails"].items()}
    # roulette-starvation fix: items with prior fails go LAST within their tier
    # so every burst reaches fresh items before revisiting flaky ones
    items.sort(key=lambda i: (i[3], 1 if i[0] in st["fails"] else 0))
    session = requests.Session(); session.headers["User-Agent"] = UA
    t_end = time.time() + a.budget_sec
    harvested, skipped = [], []

    for item in items:
        sid, vid, role, prio, acts, song, chan, title = (item + [""] * 8)[:8]
        if sid in st["done"] and valid_file(f"{BASE}/{sid}.mp4"):
            continue
        if st["fails"].get(sid, 0) >= a.max_fails:
            skipped.append((sid, "max_fails")); continue
        if time.time() >= t_end:
            break
        print(f"[{time.strftime('%H:%M:%S')}] drip -> {sid} P{prio} {title[:50]}", flush=True)
        status, got = relay_attempt(session, vid, f"{BASE}/{sid}.mp4", a.max_bytes)
        if status == "ok" and valid_file(f"{BASE}/{sid}.mp4"):
            mb = os.path.getsize(f"{BASE}/{sid}.mp4") / 1e6
            st["done"][sid] = {"bytes": int(mb * 1e6), "title": title, "prio": prio, "ts": time.time()}
            st["fails"].pop(sid, None)
            harvested.append((sid, round(mb, 1)))
            print(f"  OK {mb:.1f}MB", flush=True)
            gap = GAP_OK
        else:
            st["fails"][sid] = st["fails"].get(sid, 0) + 1
            print(f"  FAIL {status} ({got} bytes) fail#{st['fails'][sid]}", flush=True)
            gap = GAP_RETRY if "timeout" in status or "died" in status else GAP_OK
        st["updated"] = time.time()
        json.dump(st, open(STATE, "w"), indent=1)
        # sleep remaining budget or cooldown, whichever first
        remain = t_end - time.time()
        time.sleep(min(gap, max(0, remain)))

    total_valid = sum(1 for sid in st["done"] if valid_file(f"{BASE}/{sid}.mp4"))
    print(f"== burst end: +{len(harvested)} this burst | {total_valid} valid total "
          f"(P1 pool: {sum(1 for i in items)}) ==")
    for sid, mb in harvested: print(f"   + {sid} {mb}MB")

if __name__ == "__main__":
    main()
