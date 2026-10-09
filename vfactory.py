#!/usr/bin/env python3
"""vfactory v2.1 — topic -> documentary-grade video -> Telegram/storage.to.

Two media paths, chosen automatically:
  charmedia (default when the topic names a bundled character, e.g. ahyeon):
    s4_charmedia face-verifies every cut with InsightFace +
    character-clip-extractor reference centroids — the fix for "random
    clips". Real song bed from the subject's own MV (s5). Documentary
    render: multi-shot hard cuts, one opening title, no caption spam.
  stock (fallback for topics without bundled references):
    s4_footage (MV library + Mixkit/Coverr) -> s6_render_stock (beats
    grammar, letterbox/grade, s6_audio real music).

Both paths end in s8_qa hard gates (cut cadence, LUFS, dead air,
integrity) — delivery is blocked on fail unless --force.
"""
import argparse, json, os, re, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from stages import (s1_research, s2_script, s3_voice, s4_charmedia,  # noqa: E402
                    s4_media, s4_footage, s5_music, s6_render,
                    s6_render_stock, s7_deliver, s8_qa)


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
    ap.add_argument("--scenes", type=int, default=None,
                    help="[legacy] number of scenes for the v1 script shape")
    ap.add_argument("--target-seconds", type=int, default=165)
    ap.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    ap.add_argument("--region", default="us")
    ap.add_argument("--tts-speed", type=float, default=1.0)
    ap.add_argument("--character", default=None,
                    help="force character slug (ahyeon/asa/ruka/...) for "
                         "face-verified footage selection")
    ap.add_argument("--sources", nargs="*", default=None,
                    help="source footage glob patterns for charmedia")
    ap.add_argument("--ai-broll", action="store_true")
    ap.add_argument("--no-deliver", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="deliver even if QA gates fail (never default)")
    ap.add_argument("--chat-id", default=None)
    ap.add_argument("--run-dir", default=None)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    run_dir = args.run_dir or os.path.join(BASE, "runs", slugify(args.topic))
    os.makedirs(run_dir, exist_ok=True)
    topic_json = os.path.join(run_dir, "00_topic.json")
    if not os.path.exists(topic_json) or args.rebuild:
        json.dump({"topic": args.topic, "style": args.style,
                   "scenes": args.scenes, "target_seconds": args.target_seconds,
                   "aspect": args.aspect, "region": args.region,
                   "tts_speed": args.tts_speed, "ai_broll": args.ai_broll,
                   "character": args.character, "sources": args.sources,
                   "chat_id": args.chat_id,
                   "created": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(topic_json, "w"), ensure_ascii=False, indent=1)
    topic = json.load(open(topic_json))

    log(run_dir, f"RUN START: {topic['topic']}")
    steps = [
        ("research", lambda: s1_research.run(run_dir, topic["topic"], topic.get("region", "us"))),
        ("script", lambda: s2_script.run(run_dir, topic["topic"], topic.get("style", "documentary"),
                                         topic.get("target_seconds", 165), topic.get("region", "us"))),
        ("voice", lambda: s3_voice.run(run_dir, topic.get("tts_speed", 1.0))),
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

    # timeline early: charmedia + music + render all need it
    tl_path = os.path.join(run_dir, "06_timeline.json")
    if not os.path.exists(tl_path) or args.rebuild:
        durs, starts, total = s6_render.scene_durations(run_dir)
        json.dump({"durations": durs, "starts": starts, "total": total},
                  open(tl_path, "w"), indent=1)
        log(run_dir, f"timeline computed ({total:.0f}s)")

    # media: face-verified charmedia first, stock fallback, image-search last
    mode = None
    if not os.path.exists(os.path.join(run_dir, ".done_charmedia")) or args.rebuild:
        t0 = time.time()
        tl = json.load(open(tl_path))
        ok = s4_charmedia.run(run_dir, topic.get("character"),
                              topic.get("sources"), tl)
        if ok:
            open(os.path.join(run_dir, ".done_charmedia"), "w").write("1")
            mode = "char"
            log(run_dir, f"stage charmedia done in {time.time()-t0:.0f}s "
                         "(face-verified cuts)")
        else:
            log(run_dir, "charmedia not applicable -> stock footage path")
    elif os.path.exists(os.path.join(run_dir, "04_charmedia.json")):
        mode = "char"
        log(run_dir, "skip charmedia (checkpoint)")

    if mode != "char":
        if not os.path.exists(os.path.join(run_dir, ".done_footage")) or args.rebuild:
            t0 = time.time()
            s4_footage.run(run_dir, region=topic.get("region", "us"))
            open(os.path.join(run_dir, ".done_footage"), "w").write("1")
            log(run_dir, f"stage footage done in {time.time()-t0:.0f}s")
        mode = "stock"

    if mode == "char":
        # real song bed + face-verified documentary render
        if not os.path.exists(os.path.join(run_dir, ".done_music")) or args.rebuild:
            t0 = time.time()
            tl = json.load(open(tl_path))
            s5_music.run(run_dir, tl["total"])
            open(os.path.join(run_dir, ".done_music"), "w").write("1")
            log(run_dir, f"stage music done in {time.time()-t0:.0f}s")
        if not os.path.exists(os.path.join(run_dir, "final.mp4")) or args.rebuild:
            t0 = time.time()
            info = s6_render.run(run_dir)
            log(run_dir, f"render done in {time.time()-t0:.0f}s "
                         f"({info['total']:.0f}s video)")
    else:
        if not os.path.exists(os.path.join(run_dir, "final.mp4")) or args.rebuild:
            t0 = time.time()
            info = s6_render_stock.run(run_dir)
            log(run_dir, f"render done in {time.time()-t0:.0f}s "
                         f"({info['total']:.0f}s video, {info['events']} events)")

    size_mb = os.path.getsize(os.path.join(run_dir, "final.mp4")) / 1048576
    log(run_dir, f"final.mp4 ready: {size_mb:.1f} MB")

    # QA gates (hard numbers; delivery blocked on fail)
    qa = s8_qa.run(run_dir)
    log(run_dir, f"QA: {qa['overall'].upper()} — "
                 f"{qa['cuts']['cuts_per_min']} cpm, ASL {qa['cuts']['asl_s']}s, "
                 f"{qa['audio']['lufs']} LUFS, "
                 f"{len([c for c in qa['checks'] if not c['ok']])} failed gates")
    if qa["overall"] == "fail" and not args.force:
        log(run_dir, "QA FAILED — delivery blocked. Inspect 07_qa.json / qa_frames/")
        return 2

    if not args.no_deliver:
        res = s7_deliver.run(run_dir, deliver=True, chat_id=args.chat_id)
        log(run_dir, f"delivery: {res.get('method')} ok={res.get('ok')} "
                     f"url={res.get('url')}")
    log(run_dir, "RUN COMPLETE")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
