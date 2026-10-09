#!/usr/bin/env python3
"""vfactory v2 — topic -> documentary-grade video -> Telegram/storage.to.

Usage:
  python3 vfactory.py "TOPIC" [--style documentary] [--target-seconds 165]
      [--aspect 16:9] [--region us] [--tts-speed 1.0] [--no-deliver]
      [--run-dir DIR] [--rebuild] [--force]

v2 grammar (research/DESIGN_V2.md): beats -> shots (2-6s, real footage,
hard cuts, letterbox+grade+grain, minimal serif text, real music, J-cuts,
-12.5 LUFS master). Every run ends with QA gates; delivery blocked on fail
unless --force.
"""
import argparse, json, os, re, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from stages import s1_research, s2_script, s3_voice, s4_footage, s6_render, s7_deliver, s8_qa  # noqa: E402


def slugify(text, maxlen=48):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:maxlen].rstrip("-") or "video") + "-" + time.strftime("%m%d-%H%M%S")


def log(run_dir, msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(run_dir, "run.log"), "a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser(description="topic -> documentary video")
    ap.add_argument("topic")
    ap.add_argument("--style", default="documentary")
    ap.add_argument("--target-seconds", type=int, default=165)
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--region", default="us")
    ap.add_argument("--tts-speed", type=float, default=1.0)
    ap.add_argument("--no-deliver", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="deliver even if QA gates fail (never default)")
    ap.add_argument("--chat-id", default=None)
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    slug = re.sub(r"[^a-z0-9]+", "-", args.topic.lower()).strip("-")[:48].rstrip("-") or "video"
    run_dir = args.run_dir or os.path.join(BASE, "runs", f"{slug}-{time.strftime('%m%d-%H%M%S')}")
    os.makedirs(run_dir, exist_ok=True)
    topic_json = os.path.join(run_dir, "00_topic.json")
    if not os.path.exists(topic_json) or args.rebuild:
        json.dump({"topic": args.topic, "style": args.style,
                   "target_seconds": args.target_seconds, "aspect": args.aspect,
                   "region": args.region, "tts_speed": args.tts_speed,
                   "chat_id": args.chat_id,
                   "created": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(topic_json, "w"), ensure_ascii=False, indent=1)
    topic = json.load(open(topic_json))

    log(run_dir, f"RUN START (v2 documentary): {topic['topic']}")
    steps = [
        ("research", lambda: s1_research.run(run_dir, topic["topic"], topic.get("region", "us"))),
        ("script", lambda: s2_script.run(run_dir, topic["topic"], topic.get("style", "documentary"),
                                         topic.get("target_seconds", 165), topic.get("region", "us"))),
        ("voice", lambda: s3_voice.run(run_dir, topic.get("tts_speed", 1.0))),
        ("footage", lambda: s4_footage.run(run_dir, region=topic.get("region", "us"))),
    ]
    for name, fn in steps:
        marker = os.path.join(run_dir, f".done_{name}")
        if os.path.exists(marker) and not args.rebuild:
            log(run_dir, f"skip {name} (checkpoint)")
            continue
        t0 = time.time()
        log(run_dir, f"stage {name} ...")
        fn()
        open(marker, "w").write("1")
        log(run_dir, f"stage {name} done in {time.time()-t0:.0f}s")

    if not os.path.exists(os.path.join(run_dir, "final.mp4")) or args.rebuild:
        t0 = time.time()
        info = s6_render.run(run_dir)
        log(run_dir, f"render done in {time.time()-t0:.0f}s ({info['total']:.0f}s video, "
                     f"{info['events']} events)")
    else:
        log(run_dir, "skip render (final.mp4 exists)")

    size_mb = os.path.getsize(os.path.join(run_dir, "final.mp4")) / 1048576
    log(run_dir, f"final.mp4 ready: {size_mb:.1f} MB")

    # QA gates
    qa = s8_qa.run(run_dir)
    log(run_dir, f"QA: {qa['overall'].upper()} — "
                 f"{qa['cuts']['cuts_per_min']} cpm, ASL {qa['cuts']['asl_s']}s, "
                 f"{qa['audio']['lufs']} LUFS, {len([c for c in qa['checks'] if not c['ok']])} failed gates")
    if qa["overall"] == "fail" and not args.force:
        log(run_dir, "QA FAILED — delivery blocked. Inspect 07_qa.json / qa_frames/ "
                     "and rerun with --run-dir to resume after fixes.")
        return 2

    if not args.no_deliver:
        res = s7_deliver.run(run_dir, deliver=True, chat_id=args.chat_id)
        log(run_dir, f"delivery: {res.get('method')} ok={res.get('ok')} "
                     f"msg={res.get('message_id')}")
    log(run_dir, "RUN COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
