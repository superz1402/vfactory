#!/usr/bin/env python3
"""storage.to uploader — implements the official 3-step REST flow.
Docs: init -> PUT bytes to presigned URL(s) -> confirm.
Files >50 MB are automatically multipart (part_size from server).
Anonymous: 50 files/24h, 100 GB/24h bandwidth, 25 GB max, 3-day expiry.
A bearer token can be dropped into config for premium (permanent) files.
"""
import json, os, uuid
import requests

BASE = "https://storage.to/api"
VISITOR_PATH = os.path.join(os.path.dirname(__file__), "..", ".visitor_token")
PART_SIZE_FALLBACK = 32 * 1024 * 1024  # 32 MiB


def _visitor_token():
    """Persistent anonymous identity (CLI convention). Generated once."""
    path = os.path.abspath(VISITOR_PATH)
    if os.path.exists(path):
        return open(path).read().strip()
    tok = uuid.uuid4().hex + uuid.uuid4().hex[:16]
    with open(path, "w") as fh:
        fh.write(tok)
    os.chmod(path, 0o600)
    return tok


def _headers(extra=None, bearer=None):
    h = {"X-Visitor-Token": _visitor_token()}
    if bearer:
        h["Authorization"] = f"Bearer {bearer}"
    if extra:
        h.update(extra)
    return h


def health():
    r = requests.get(f"{BASE}/health", timeout=15)
    return r.json().get("status") == "ok"


def bandwidth():
    r = requests.get(f"{BASE}/bandwidth/status", headers=_headers(), timeout=15)
    return r.json()


def upload(path, bearer=None, collection_id=None, progress=None):
    """Upload a local file. Returns dict {url, id, expires_at, size, storage:'storageto'}.
    Raises RuntimeError on failure."""
    p = os.path.abspath(path)
    size = os.path.getsize(p)
    filename = os.path.basename(p)
    ctype = "video/mp4" if filename.lower().endswith((".mp4", ".mov", ".m4v")) else "application/octet-stream"

    # 1) init
    r = requests.post(f"{BASE}/upload/init", headers=_headers(bearer=bearer), timeout=30,
                      json={"filename": filename, "content_type": ctype, "size": size})
    init = r.json()
    if not init.get("success"):
        raise RuntimeError(f"storage.to init failed: {init.get('error')} (http {r.status_code})")

    etags = []
    if init.get("type") == "multipart":
        upload_id = init["upload_id"]
        part_size = init.get("part_size", PART_SIZE_FALLBACK)
        urls = {int(k): v for k, v in (init.get("initial_urls") or {}).items()}
        total_parts = init.get("total_parts") or ((size + part_size - 1) // part_size)

        with open(p, "rb") as fh:
            for part_no in range(1, total_parts + 1):
                fh.seek((part_no - 1) * part_size)
                chunk = fh.read(part_size)
                if part_no not in urls:
                    pr = requests.post(f"{BASE}/upload/parts", timeout=30,
                                       headers=_headers(bearer=bearer),
                                       json={"upload_id": upload_id,
                                             "part_numbers": [part_no]})
                    pj = pr.json()
                    if not pj.get("success"):
                        raise RuntimeError(f"parts URL fetch failed: {pj.get('error')}")
                    urls = {**urls, **{u["partNumber"]: u["url"] for u in pj.get("part_urls", [])}}
                pr = requests.put(urls[part_no], data=chunk, timeout=600)
                if pr.status_code not in (200, 201):
                    raise RuntimeError(f"part {part_no}/{total_parts} PUT failed: {pr.status_code}")
                etag = pr.headers.get("ETag", "").strip()
                etags.append({"partNumber": part_no, "etag": etag})
                if progress:
                    progress(part_no, total_parts)

        cr = requests.post(f"{BASE}/upload/complete-multipart", timeout=30,
                           headers=_headers(bearer=bearer),
                           json={"upload_id": upload_id, "parts": etags})
        if not cr.json().get("success"):
            raise RuntimeError(f"complete-multipart failed: {cr.text[:200]}")
        r2_key = init["r2_key"]
    else:
        # single presigned PUT
        with open(p, "rb") as fh:
            pr = requests.put(init["upload_url"], data=fh, timeout=1800)
        if pr.status_code not in (200, 201):
            raise RuntimeError(f"presigned PUT failed: {pr.status_code}")
        r2_key = init["r2_key"]

    # 3) confirm -> shareable URL
    payload = {"filename": filename, "size": size, "content_type": ctype, "r2_key": r2_key}
    if collection_id:
        payload["collection_id"] = collection_id
    cr = requests.post(f"{BASE}/upload/confirm", headers=_headers(bearer=bearer), timeout=30,
                       json=payload)
    cj = cr.json()
    if not cj.get("success"):
        raise RuntimeError(f"confirm failed: {cj.get('error')} (http {cr.status_code})")
    f = cj["file"]
    return {"url": f["url"], "id": f["id"], "expires_at": f.get("expires_at"),
            "size": size, "filename": filename, "storage": "storageto",
            "owner_token": cj.get("owner_token")}


if __name__ == "__main__":
    import sys
    print("health:", health())
    if len(sys.argv) > 1:
        print(json.dumps(upload(sys.argv[1]), indent=2))
