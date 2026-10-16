#!/usr/bin/env python3
"""Fetch the one_run_harvest.sh links_manifest.json back into the vfactory
media library — with sha256 verification on every file.

Usage:
  python3 fetch_manifest.py <manifest-path-or-URL> [--out-dir DIR]
                            [--priority-max N] [--only id1,id2]

- Downloads every ok item's primary_link (gofile direct / storageto with
  browser UA+Referer / any host) into <out-dir>/<source_id>.mp4
- Verifies sha256 against the manifest; a mismatch is a hard failure
- Validates streams with ffprobe (video+audio, duration>20s, height>=360)
- Writes fetch_report.json next to the output dir
- Exit 0 only if every in-scope item fetched + verified
"""
import argparse, hashlib, json, os, subprocess, sys, urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def headers_for(link):
    if "storage.to/" in link:
        # storage.to serves the file page to plain GETs; browser UA + referer
        # is needed for any chance of direct content
        return {"User-Agent": UA, "Referer": "https://storage.to/",
                "Accept": "*/*"}
    # filebin/uguu/0x0.st/bashupload/litterbox serve RAW BYTES to plain curl
    # (no UA) and HTML to browser-like agents — so send nothing browser-like
    return {"Accept": "*/*"}


def download(url, dest):
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers=headers_for(url))
    with urllib.request.urlopen(req, timeout=1800) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    os.replace(tmp, dest)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ffprobe_ok(path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout)
        v = any(s.get("codec_type") == "video" for s in d.get("streams", []))
        a = any(s.get("codec_type") == "audio" for s in d.get("streams", []))
        dur = float(d.get("format", {}).get("duration") or 0)
        h = max((s.get("height") or 0) for s in d.get("streams", []))
        return v and a and dur > 20 and h >= 360
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--out-dir", default="/home/z/my-project/ytdl-agent/downloads/harvest")
    ap.add_argument("--priority-max", type=int, default=3)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    if args.manifest.startswith("http"):
        req = urllib.request.Request(args.manifest, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
        manifest = json.loads(raw)
    else:
        manifest = json.load(open(args.manifest))

    os.makedirs(args.out_dir, exist_ok=True)
    only = set(x.strip() for x in args.only.split(",") if x.strip())

    items = [i for i in manifest.get("items", [])
             if i.get("priority", 99) <= args.priority_max
             and (not only or i.get("source_id") in only)]
    report, failed = [], 0
    for it in items:
        sid = it.get("source_id", "?")
        rec = {"source_id": sid, "status": it.get("status")}
        if it.get("status") != "ok":
            rec["error"] = it.get("error", "not ok in manifest")
            failed += 1
            report.append(rec)
            continue
        link = it.get("primary_link") or ""
        if not link:
            up = it.get("uploads") or []
            link = ((up[0].get("direct_link") or up[0]["link"]) if up else "")
        if not link:
            rec["error"] = "no usable link"; failed += 1; report.append(rec); continue
        dest = os.path.join(args.out_dir, f"{sid}.mp4")
        try:
            already = os.path.exists(dest) and sha256_of(dest) == it["file"]["sha256"]
            if not already:
                ups = it.get("uploads") or []
                candidates = [u.get("direct_link") or u["link"] for u in ups
                              if u.get("machine_fetchable")]
                candidates += [it["primary_link"]] if it.get("primary_link") else []
                err = "no candidate link"
                for u in candidates:
                    try:
                        download(u, dest)
                        if sha256_of(dest) == it["file"]["sha256"]:
                            err = None
                            break
                        err = "sha256 mismatch"
                    except Exception as e:  # try next mirror
                        err = f"{u[:60]}: {str(e)[:120]}"
                if err:
                    if os.path.exists(dest):
                        os.remove(dest)
                    raise RuntimeError(err)
            if sha256_of(dest) != it["file"]["sha256"]:
                raise RuntimeError("sha256 MISMATCH — file corrupt or wrong")
            if not ffprobe_ok(dest):
                raise RuntimeError("ffprobe validation failed")
            rec.update(status="ok", path=dest, bytes=os.path.getsize(dest))
        except Exception as e:
            rec["status"] = "failed"
            rec["error"] = str(e)[:200]
            failed += 1
        report.append(rec)

    out = {"fetched": sum(1 for r in report if r["status"] == "ok"),
           "failed": failed, "total": len(report), "items": report}
    rp = os.path.join(args.out_dir, "fetch_report.json")
    json.dump(out, open(rp, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: out[k] for k in ("fetched", "failed", "total")}))
    for r in report:
        print(("OK  " if r["status"] == "ok" else "FAIL") + f" {r['source_id']}"
              + ("" if r["status"] == "ok" else f"  {r.get('error','')}"))
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
