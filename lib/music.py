#!/usr/bin/env python3
"""music.py — real royalty-free music for documentary v2.

Source: incompetech (Kevin MacLeod) direct mp3, CC-BY 4.0.
All tracks probed live 2026-10-09 (HTTP 206). Credited in delivery caption.
Mood -> candidate tracks; download once into cache/music/, validate with ffprobe.
"""
import json, os, subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, "cache", "music")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# mood -> ordered candidates (dark/tense -> hopeful/triumphant -> reflective)
TRACKS = {
    "dark":     ["Impact Prelude", "Crypto", "Anguish", "Long Note Two", "Deep Haze"],
    "tense":    ["Crypto", "Impact Prelude", "Long Note One", "Ossuary 5 - Rest"],
    "hopeful":  ["Rising Tide", "Frost Waltz", "Beauty Flow", "Meditation Impromptu 01"],
    "triumphant": ["Impact Prelude", "Rising Tide", "Beauty Flow", "Frost Waltz"],
    "reflective": ["Ossuary 5 - Rest", "Meditation Impromptu 01", "Deep Haze", "Rising Tide"],
    "energetic": ["Crypto", "Impact Prelude", "Beauty Flow"],
    "epic":     ["Impact Prelude", "Rising Tide", "Ossuary 5 - Rest"],
}


def _url(name):
    from urllib.parse import quote
    return ("https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
            + quote(name) + ".mp3")


def probe_available(name):
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-r", "0-99", "-w", "%{http_code}",
                        "-A", UA, _url(name)], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() in ("200", "206")


def get_track(name):
    """Download once, return local path or None."""
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, name.replace(" ", "_") + ".mp3")
    if os.path.exists(dst) and os.path.getsize(dst) > 500_000:
        return dst
    r = subprocess.run(["curl", "-sL", "--max-time", "120", "-A", UA,
                        "-o", dst, _url(name)], capture_output=True, timeout=130)
    if r.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 500_000:
        if os.path.exists(dst):
            os.remove(dst)
        return None
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", dst], capture_output=True, text=True)
    try:
        float(p.stdout.strip())
        return dst
    except ValueError:
        os.remove(dst)
        return None


def pick_for_beats(beats, total_dur):
    """Choose one track whose mood covers the majority of beat moods.

    Arc heuristic: hook moods weight highest (sets the tone).
    Returns {path, name, license} or None.
    """
    from collections import Counter
    moods = Counter()
    for i, b in enumerate(beats):
        w = 3 if i == 0 else (1.5 if i < 3 else 1.0)
        moods[b.get("mood", "dark")] += w
    top = [m for m, _ in moods.most_common()]
    for mood in top:
        for cand in TRACKS.get(mood, [])[:3]:
            if probe_available(cand):
                p = get_track(cand)
                if p:
                    return {"path": p, "name": cand,
                            "license": "Kevin MacLeod (incompetech.com), CC BY 4.0"}
    return None


if __name__ == "__main__":
    import sys
    beats = [{"mood": m} for m in sys.argv[1:]] or [{"mood": "dark"}]
    print(pick_for_beats(beats, 120))
