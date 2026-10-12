#!/usr/bin/env python3
"""z-ai CLI wrappers for the vfactory pipeline.
Every call: subprocess -> bracket-extracted JSON -> retries. No keys in logs.
"""
import json, os, re, signal, subprocess, tempfile, time

ZAI = "z-ai"
PROGRESS_RE = re.compile(r"^[^\[\{\s].*$", re.M)


def _run(cmd, timeout=180):
    """Popen with process-group kill on timeout — z-ai spawns node
    grandchildren that otherwise hold the pipes open forever."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=8)
        except Exception:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                pass
            out, err = "", ""
        return subprocess.CompletedProcess(cmd, -9, out or "", err or "")


def _extract_json(text):
    """z-ai CLI prints progress lines around the payload; bracket-slice it."""
    if not text:
        return None
    i = min([x for x in (text.find("["), text.find("{")) if x != -1], default=-1)
    if i == -1:
        return None
    j = max(text.rfind("]"), text.rfind("}"))
    if j <= i:
        return None
    blob = text[i:j + 1]
    for candidate in (blob,):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    # last resort: find outermost balanced JSON object/array
    return None


def search(query, num=8, retries=2, timeout=90):
    """web_search via z-ai function call. Returns list of results or []."""
    for attempt in range(retries + 1):
        try:
            r = _run([ZAI, "function", "-n", "web_search",
                      "-a", json.dumps({"query": query, "num": num})], timeout=timeout)
            data = _extract_json(r.stdout)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "result" in data:
                res = data["result"]
                if isinstance(res, list):
                    return res
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(2 * (attempt + 1))
    return []


def chat(prompt, system=None, thinking=False, retries=2, timeout=300):
    """Chat completion. Returns assistant text (content field) or None."""
    cmd = [ZAI, "chat", "-p", prompt]
    if system:
        cmd += ["-s", system]
    if thinking:
        cmd += ["-t"]
    for attempt in range(retries + 1):
        try:
            r = _run(cmd, timeout=timeout)
            out = (r.stdout or "").strip()
            if not out:
                raise RuntimeError("empty stdout")
            resp = _extract_json(out)
            if isinstance(resp, dict) and "choices" in resp:
                content = resp["choices"][0]["message"]["content"]
                if content and content.strip():
                    return content.strip()
            # fallback: CLI printed plain text
            cleaned = PROGRESS_RE.sub("", out).strip()
            if cleaned:
                return cleaned
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(3 * (attempt + 1))
    return None


def chat_json(prompt, system=None, retries=2, timeout=300):
    """Chat that must return JSON; extracts the outermost object/array."""
    txt = chat(prompt, system=system, retries=retries, timeout=timeout)
    if not txt:
        return None
    txt = re.sub(r"```(?:json)?", "", txt)
    return _extract_json(txt)


def tts(text, out_path, voice="tongtong", speed=1.0, fmt="wav", retries=2, timeout=240):
    """Text-to-speech -> audio file. Returns True on success."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    for attempt in range(retries + 1):
        try:
            r = _run([ZAI, "tts", "-i", text, "-o", out_path,
                      "-v", voice, "-s", str(speed), "-f", fmt], timeout=timeout)
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                return True
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(2 * (attempt + 1))
    return False


def image_search(query, count=8, region="us", ranked=True, retries=2, timeout=60):
    """Image search. Returns list of {url, caption?...} dicts."""
    cmd = [ZAI, "image-search", "-q", query, "-c", str(count), "--gl", region]
    if not ranked:
        cmd.append("--no-rank")
    for attempt in range(retries + 1):
        try:
            r = _run(cmd, timeout=timeout)
            data = _extract_json(r.stdout)
            if isinstance(data, dict):
                for key in ("results", "data", "items", "images"):
                    if isinstance(data.get(key), list):
                        return data[key]
                return [data]
            if isinstance(data, list):
                return data
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(2 * (attempt + 1))
    return []


def download(url, out_path, timeout=60, min_bytes=2000):
    """Download a URL to file with UA header. Returns True on plausible image."""
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) vfactory/1.0"}
        resp = requests.get(url, headers=headers, timeout=timeout, stream=True)
        if resp.status_code != 200:
            return False
        with open(out_path, "wb") as fh:
            for chunk in resp.iter_content(65536):
                fh.write(chunk)
        return os.path.getsize(out_path) >= min_bytes
    except Exception:
        return False


def gen_video_clip(prompt, out_path, size="1920x1080", duration=5, quality="speed",
                   image_url=None, retries=1, timeout=900):
    """AI b-roll generation (optional, slow). Returns True on success."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [ZAI, "video", "-p", prompt, "-s", size, "-d", str(duration), "-q", quality]
    if image_url:
        cmd += ["-i", image_url]
    for attempt in range(retries + 1):
        try:
            r = _run(cmd, timeout=timeout)
            url_m = re.search(r"https?://\S+", r.stdout)
            if url_m and download(url_m.group(0).rstrip('",.'), out_path, min_bytes=100000):
                return True
        except (subprocess.TimeoutExpired, Exception):
            pass
    return False
