#!/usr/bin/env python3
"""Stage 5 v2: REAL royalty-free music bed. Synthesized sine drones are gone.

Resolution order (per ai-video-factory's music_bed design):
  1. curated local library  footage/music/<mood>-*.mp3|wav|m4a|ogg
  2. MUSIC_BED_PATH env     explicit operator override
  3. Openverse API (CC0/PDM) searched + cached under footage/music/cache/
Never synthesizes. If nothing resolves -> hard failure (a silent/wrong mix
must never ship).

The chosen track is pre-normalized to -23 LUFS (deterministic bed level) and
written as bed.wav; 05_music.json carries license + provenance.
"""
import glob, json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUSIC_DIR = os.path.join(BASE, "footage", "music")
CACHE = os.path.join(MUSIC_DIR, "cache")
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus")

MOOD_QUERIES = {
    "documentary": ["emotional uplifting soundtrack instrumental",
                    "inspiring cinematic piano instrumental",
                    "hopeful ambient soundtrack"],
    "cinematic": ["emotional cinematic soundtrack instrumental",
                  "epic ambient soundtrack"],
    "hype": ["uplifting electronic upbeat instrumental",
             "energetic pop instrumental"],
    "explainer": ["light upbeat instrumental", "clean minimal groove"],
}
BLACKLIST = ("whisper", "cave", "horror", "scream", "siren", "glitch",
             "noise", "drone", "creepy", "scary", "drops")


def probe_dur(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path], timeout=30)
        return float(out.decode().strip())
    except Exception:
        return 0.0


def loudnorm_to(path, out_wav, target_i="-23"):
    fc = (f"loudnorm=I={target_i}:TP=-2.0:LRA=11,"
          f"aformat=sample_rates=48000:channel_layouts=stereo")
    p = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path,
                        "-af", fc, "-ar", "48000", out_wav],
                       capture_output=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError(f"bed normalize failed: {p.stderr.decode()[-300:]}")


def from_curated(mood):
    pats = [os.path.join(MUSIC_DIR, f"{mood}-*{e}") for e in AUDIO_EXT]
    pats += [os.path.join(MUSIC_DIR, f"*{e}") for e in AUDIO_EXT]
    for pat in pats:
        for f in sorted(glob.glob(pat)):
            if probe_dur(f) >= 30:
                return f, {"license": "curated local library (royalty-free)",
                           "title": os.path.basename(f)}
    return None, None


def from_openverse(mood, min_dur):
    import urllib.parse, urllib.request
    queries = MOOD_QUERIES.get(mood, MOOD_QUERIES["documentary"])
    os.makedirs(CACHE, exist_ok=True)
    for q in queries:
        url = ("https://api.openverse.org/v1/audio/?q=" +
               urllib.parse.quote(q) +
               f"&license=cc0,pdm&page_size=12&length=medium")
        req = urllib.request.Request(url, headers={"User-Agent": "vfactory/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.load(r)
        except Exception as e:
            print(f"[s5] openverse query failed: {e}")
            continue
        results = data.get("results", [])
        # rank: instrumental-ish title, long enough, not blacklisted
        def score(r):
            t = (r.get("title") or "").lower()
            d = (r.get("duration") or 0) / 1000.0
            if d < min_dur:
                return -1
            if any(b in t for b in BLACKLIST):
                return -1
            s = min(d / 300.0, 1.0)
            if "instrumental" in t or "soundtrack" in t:
                s += 0.5
            return s
        results = [r for r in results if score(r) > 0]
        results.sort(key=score, reverse=True)
        for r in results[:3]:
            audio_url = r.get("url") or (r.get("alt_files") or [{}])[0].get("url")
            if not audio_url:
                continue
            title = (r.get("title") or "track").strip().replace(" ", "-")[:40]
            dst = os.path.join(CACHE, f"{title}.mp3")
            if not (os.path.exists(dst) and probe_dur(dst) > 10):
                try:
                    req = urllib.request.Request(audio_url,
                                                 headers={"User-Agent": "vfactory/2.0"})
                    with urllib.request.urlopen(req, timeout=90) as resp, \
                         open(dst, "wb") as fh:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            fh.write(chunk)
                except Exception as e:
                    print(f"[s5] download failed ({title}): {e}")
                    continue
            if probe_dur(dst) >= min(min_dur, 45):
                creator = r.get("creator") or "unknown"
                return dst, {
                    "license": "CC0 / Public Domain (Openverse)",
                    "title": r.get("title") or title,
                    "creator": creator,
                    "url": r.get("foreign_landing_url") or audio_url,
                }
    return None, None


def run(run_dir, total_dur, mood=None, required=False):
    out_dir = os.path.join(run_dir, "05_music")
    os.makedirs(out_dir, exist_ok=True)
    bed = os.path.join(out_dir, "bed.wav")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    mood = mood or topic.get("music_mood") or (
        "documentary" if topic.get("style", "documentary") in
        ("documentary", "cinematic", "dark") else "hype")

    track, meta = from_curated(mood)
    if not track:
        track, meta = from_openverse(mood, max(total_dur, 45))
    env_bed = os.environ.get("MUSIC_BED_PATH")
    if not track and env_bed and os.path.exists(env_bed):
        track, meta = env_bed, {"license": "operator override (MUSIC_BED_PATH)",
                                "title": os.path.basename(env_bed)}
    if not track:
        raise RuntimeError(
            "s5: no royalty-free music track resolved (curated library empty "
            "AND network search failed). Refusing to synthesize or ship silent.")

    loudnorm_to(track, bed)
    bdur = probe_dur(bed)
    json.dump({"mood": mood, "path": bed, "duration": round(bdur, 2),
               "source_track": track, **meta},
              open(os.path.join(run_dir, "05_music.json"), "w"), indent=1)
    print(f"[s5] bed: {os.path.basename(track)} ({bdur:.0f}s) "
          f"license={meta.get('license')}")
    return bed


if __name__ == "__main__":
    run(sys.argv[1], float(sys.argv[2]))
