#!/usr/bin/env python3
"""Stage 4: visuals per scene.
Order of preference per scene:
  1. local footage file supplied via --footage (glob patterns) or run-dir map
  2. image-search (z-ai) -> download best candidate -> validated
  3. fallback: generated title-card PNG (ffmpeg) so render never breaks
Also supports --ai-broll flag to generate scene-1 b-roll with z-ai video.
"""
import argparse, glob, json, os, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import zai  # noqa: E402


def valid_image(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        w, h = r.stdout.strip().split(",")[0:2]
        return int(w) >= 400 and int(h) >= 300
    except Exception:
        return False


def fallback_card(run_dir, sc, text):
    out = os.path.join(run_dir, "04_media", f"scene_{sc['id']:02d}.jpg")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi",
                    "-i", "color=c=0x101418:s=1920x1080:d=1",
                    "-vf", f"drawtext=text='{sc['on_screen'][:60]}':fontcolor=white@0.85:fontsize=64:x=(w-tw)/2:y=(h-th)/2",
                    "-frames:v", "1", "-q:v", "3", out],
                   capture_output=True, timeout=60)
    return out if os.path.exists(out) else None


def run(run_dir, region="us", ai_broll=False):
    media_dir = os.path.join(run_dir, "04_media")
    os.makedirs(media_dir, exist_ok=True)
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    manifest = {}
    for sc in plan["scenes"]:
        out = os.path.join(media_dir, f"scene_{sc['id']:02d}.jpg")
        if os.path.exists(out) and valid_image(out):
            manifest[str(sc["id"])] = {"path": out, "kind": "image"}
            continue
        got = False
        # try image search (top 6, first valid)
        for item in (zai.image_search(sc["visual_query"], count=6, region=region) or [])[:6]:
            url = (item.get("original_url") or item.get("url") or
                   item.get("image") or item.get("oss_url") or "")
            if not url.startswith("http"):
                continue
            if zai.download(url, out, min_bytes=8000) and valid_image(out):
                manifest[str(sc["id"])] = {"path": out, "kind": "image",
                                           "credit": url[:200],
                                           "caption": (item.get("caption") or "")[:200]}
                got = True
                break
        if not got:
            card = fallback_card(run_dir, sc, sc["on_screen"])
            if card:
                manifest[str(sc["id"])] = {"path": card, "kind": "card"}
                got = True
        if not got:
            raise RuntimeError(f"no visual for scene {sc['id']}")
    # optional AI b-roll for the hook (replaces image with generated clip)
    if ai_broll:
        clip = os.path.join(media_dir, "scene_01_ai.mp4")
        q = plan["scenes"][0]["visual_query"]
        if zai.gen_video_clip(f"Cinematic documentary b-roll: {q}", clip,
                              size="1920x1080", duration=5):
            manifest["1"] = {"path": clip, "kind": "video"}
    json.dump(manifest, open(os.path.join(run_dir, "04_media.json"), "w"),
              ensure_ascii=False, indent=1)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("topic_json")
    ap.add_argument("--ai-broll", action="store_true")
    a = ap.parse_args()
    run_dir = os.path.dirname(a.topic_json)
    d = json.load(open(a.topic_json))
    run(run_dir, d.get("region", "us"), a.ai_broll)
    print("media done")
