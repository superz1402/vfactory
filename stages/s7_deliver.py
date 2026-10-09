#!/usr/bin/env python3
"""Stage 7: delivery. <=48 MB -> Telegram sendVideo direct; bigger ->
storage.to upload (3-step API) -> send link via Telegram. Always writes
delivery.json with method, url and message ids."""
import json, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import storageto, telegram  # noqa: E402


def run(run_dir, deliver=True, chat_id=None):
    final = os.path.join(run_dir, "final.mp4")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    size = os.path.getsize(final)
    mb = size / 1024 / 1024
    title = plan.get("title", topic["topic"])
    caption = (f"<b>{title}</b>\n{topic['topic']}\n"
               f"{tl['total']:.0f}s • {tl.get('scenes') or len(plan['scenes'])} scenes • {mb:.1f} MB\n"
               f"built by vfactory")
    chat_id = chat_id or topic.get("chat_id") or telegram.DEFAULT_CHAT
    result = {"file": final, "size_mb": round(mb, 1), "chat_id": chat_id}

    if not deliver:
        result["delivered"] = False
        json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"), indent=1)
        return result

    if size <= telegram.TG_DIRECT_LIMIT:
        ok, resp = telegram.send_video(final, caption=caption, chat_id=chat_id)
        result.update({"method": "telegram_direct", "ok": ok,
                       "message_id": resp.get("result", {}).get("message_id")})
        if not ok:
            result["error"] = resp.get("description", "sendVideo failed")
    else:
        up = storageto.upload(final)
        result.update({"method": "storageto", "ok": True, **{k: up[k] for k in
                       ("url", "id", "expires_at")}})
        msg = (f"<b>{title}</b> — {tl['total']:.0f}s, {mb:.1f} MB\n"
               f"⬇️ <a href=\"{up['url']}\">{up['url']}</a>\n"
               f"(storage.to • link valid until {up['expires_at'] or 'expiry'})")
        sent = telegram.send_message(msg, chat_id=chat_id)
        result["message_id"] = sent.get("result", {}).get("message_id")
    json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"),
              ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    print(json.dumps(run(os.path.dirname(sys.argv[1])), indent=2))
