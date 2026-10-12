#!/usr/bin/env python3
"""GitHub Releases publishing — standing rule (user directive, Round 10+):

    "Always upload the main video as a git release and share the link"

The main film is ALWAYS published as assets of a git release on the PUBLIC
repo (superz1402/vfactory), and the release link is ALWAYS shared with the
user. Telegram parts alone are never a complete delivery. Public release
assets serve HTTP 206 (range) so the landing page can stream them too.

Token resolution order: $GH_TOKEN -> ~/.gh_token -> /home/z/my-project/.gh_token.
Credentials never enter the repo (AGENT.md rule 8).
"""
import json
import os
import subprocess

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"
REPO = os.environ.get("RELEASE_REPO", "superz1402/vfactory")


def _token():
    env = os.environ.get("GH_TOKEN")
    if env:
        return env.strip()
    for cand in (os.path.expanduser("~/.gh_token"),
                 "/home/z/my-project/.gh_token"):
        if cand and os.path.isfile(cand):
            return open(cand).read().strip()
    raise RuntimeError("no GitHub token found (GH_TOKEN / ~/.gh_token)")


def _curl(args, timeout=1800):
    """curl with auth header; returns (stdout, returncode)."""
    cmd = ["curl", "-sS", "-H", "Authorization: token " + _token()] + args
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.stdout, p.returncode


def get_release(tag):
    out, _ = _curl([f"{API}/repos/{REPO}/releases/tags/{tag}"])
    try:
        rel = json.loads(out)
    except Exception:
        return None
    return rel if rel and rel.get("id") else None


def ensure_release(tag, title, body=""):
    """Fetch release by tag; create it when missing. Idempotent."""
    rel = get_release(tag)
    if rel:
        return rel
    payload = json.dumps({"tag_name": tag, "name": title, "body": body})
    out, _ = _curl(["-X", "POST", "-H", "Content-Type: application/json",
                    "-d", payload, f"{API}/repos/{REPO}/releases"])
    rel = json.loads(out)
    if not rel.get("id"):
        raise RuntimeError("release create failed: " + out[:300])
    return rel


def upload_asset(rel_id, path, name=None, timeout=3600):
    """Upload one file. If an asset with the same name exists:
    same size -> skip (idempotent); different size -> delete then re-upload.
    Returns (ok, asset_dict_or_error)."""
    name = name or os.path.basename(path)
    size = os.path.getsize(path)
    rel = get_release_by_id(rel_id)
    for a in (rel or {}).get("assets", []):
        if a["name"] == name:
            if a.get("size") == size and a.get("state") == "uploaded":
                return True, a
            _curl(["-X", "DELETE",
                   f"{API}/repos/{REPO}/releases/assets/{a['id']}"])
            break
    url = f"{UPLOAD}/repos/{REPO}/releases/{rel_id}/assets?name={name}"
    out, _ = _curl(["-X", "POST", "-H", "Content-Type: application/octet-stream",
                    "--data-binary", f"@{path}", "-w", "\n%{http_code}", url],
                   timeout=timeout)
    body, _, code = out.rpartition("\n")
    try:
        asset = json.loads(body)
    except Exception:
        asset = {}
    ok = code == "201" and asset.get("state") == "uploaded" \
        and asset.get("size") == size
    if not ok:
        return False, {"error": f"upload http={code} body={body[:200]}"}
    return True, asset


def get_release_by_id(rel_id):
    out, _ = _curl([f"{API}/repos/{REPO}/releases/{rel_id}"])
    try:
        rel = json.loads(out)
    except Exception:
        return None
    return rel if rel and rel.get("id") else None


def publish(tag, title, named_files, body=""):
    """ensure release + upload every (path, asset_name).
    Returns (html_url, {asset_name: download_url_or_None})."""
    rel = ensure_release(tag, title, body)
    urls = {}
    for path, name in named_files:
        ok, asset = upload_asset(rel["id"], path, name)
        urls[name] = asset.get("browser_download_url") if ok else None
        if not ok:
            urls[name + "__error"] = asset.get("error", "upload failed")
    return rel.get("html_url"), urls
