#!/usr/bin/env python3
"""vfactory-bot — Telegram listener. Send a topic as a message, get the video back.
  python3 telegram_listener.py [--allow CHAT_ID]
Commands: /start /help, /status. Any other text = video topic.
One job at a time (queue), progress updates, delivery via s7 (direct or storage.to).
"""
import argparse, json, os, subprocess, sys, threading, time

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from lib import telegram  # noqa: E402
from stages import s7_deliver  # noqa: E402

OFFSET_FILE = os.path.join(BASE, ".tg_offset")
ALLOW = {"1263089875"}
HELP = ("🎬 <b>vfactory</b> — send me any topic and I build a full video:\n\n"
        "• research (multi-angle web search)\n"
        "• documentary script\n"
        "• TTS narration\n"
        "• real images/footage + captions\n"
        "• cinematic score (sidechain-ducked, -14 LUFS)\n"
        "• render 1080p → delivered right here\n\n"
        "Options in message prefix: <code>9:16</code> vertical, "
        "<code>#hype</code> style, <code>5 scenes</code> count.\n"
        "Example: <code>9:16 #hype 5 scenes rise of home robots</code>")


def parse_topic(text):
    """Message -> (topic, overrides dict)."""
    opts = {"aspect": "16:9", "style": "documentary", "scenes": 7}
    words = text.split()
    keep = []
    for w in words:
        lw = w.lower()
        if lw in ("9:16", "16:9"):
            opts["aspect"] = lw
        elif lw.startswith("#"):
            st = lw[1:]
            if st in ("hype", "documentary", "cinematic", "explainer"):
                opts["style"] = st
        elif lw.isdigit() and 3 <= int(lw) <= 10:
            opts["scenes"] = int(lw)
        elif lw == "scenes":
            continue
        else:
            keep.append(w)
    return " ".join(keep).strip(), opts


def consumer(queue, running):
    while True:
        if not queue:
            time.sleep(2)
            continue
        job = queue[0]
        try:
            telegram.send_message("⚙️ Building… I'll report when stages finish.",
                                  chat_id=job["chat_id"], silent=True)
            args = ["python3", os.path.join(BASE, "vfactory.py"), job["topic"],
                    "--style", job["opts"]["style"],
                    "--scenes", str(job["opts"]["scenes"]),
                    "--aspect", job["opts"]["aspect"],
                    "--run-dir", job["run_dir"], "--no-deliver"]
            proc = subprocess.run(args, capture_output=True, text=True,
                                  timeout=3600, cwd=BASE)
            if proc.returncode != 0:
                err = (proc.stderr or "unknown error").strip().splitlines()[-3:]
                telegram.send_message(f"❌ Build failed:\n<code>{' / '.join(err)[-500:]}</code>",
                                      chat_id=job["chat_id"])
            else:
                final = os.path.join(job["run_dir"], "final.mp4")
                if os.path.exists(final):
                    res = s7_deliver.run(job["run_dir"], deliver=True,
                                         chat_id=job["chat_id"])
                    telegram.send_message(f"✅ Delivered via {res.get('method')}",
                                          chat_id=job["chat_id"], silent=True)
                else:
                    telegram.send_message("⚠️ finished but no final.mp4",
                                          chat_id=job["chat_id"])
        except Exception as e:
            try:
                telegram.send_message(f"❌ vfactory error: {str(e)[:300]}",
                                      chat_id=job["chat_id"])
            except Exception:
                pass
        finally:
            queue.pop(0)
            if not queue:
                running["id"] = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow", default=None, help="comma-separated chat ids")
    args = ap.parse_args()
    if args.allow:
        global ALLOW
        ALLOW = {x.strip() for x in args.allow.split(",") if x.strip()}
    offset = 0
    if os.path.exists(OFFSET_FILE):
        offset = int(open(OFFSET_FILE).read().strip() or 0)
    telegram.send_message("🟢 vfactory-bot online — send a topic.", silent=True)
    running = {"id": None}
    queue = []
    threading.Thread(target=consumer, args=(queue, running), daemon=True).start()
    while True:
        try:
            data = telegram.get_updates(offset=offset, timeout=50)
            if not data.get("ok"):
                time.sleep(3)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                with open(OFFSET_FILE, "w") as fh:
                    fh.write(str(offset))
                msg = upd.get("message") or {}
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = (msg.get("text") or "").strip()
                if not text or (ALLOW and chat_id not in ALLOW):
                    continue
                if text.startswith("/start") or text.startswith("/help"):
                    telegram.send_message(HELP, chat_id=chat_id)
                    continue
                if text.startswith("/status"):
                    telegram.send_message(f"queue: {len(queue)} pending",
                                          chat_id=chat_id, silent=True)
                    continue
                topic, opts = parse_topic(text)
                if not topic:
                    continue
                if queue:
                    telegram.send_message("⏳ queued — one build runs at a time.",
                                          chat_id=chat_id, silent=True)
                slug = str(abs(hash(topic)) % 10 ** 8) + "-" + time.strftime("%m%d%H%M%S")
                job = {"topic": topic, "opts": opts, "chat_id": chat_id,
                       "run_dir": os.path.join(BASE, "runs", "tg-" + slug)}
                os.makedirs(job["run_dir"], exist_ok=True)
                running["id"] = slug
                queue.append(job)
        except KeyboardInterrupt:
            break
        except Exception:
            time.sleep(5)


if __name__ == "__main__":
    main()
