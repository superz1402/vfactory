#!/usr/bin/env python3
"""Stage 7: delivery.

STANDING RULE (user directive, Round 10+): "Always upload the main video as a
git release and share the link". So delivery is ALWAYS three parts:
  1. Telegram: <=48 MB sendVideo direct; bigger -> storage.to mirror link.
  2. GitHub Releases (MANDATORY, runs in every delivery): main film (+720p
     mirror + trailer when present) uploaded as assets of the film's release
     tag on the public repo. This is the canonical permanent link.
  3. The release link is ALWAYS sent to the user over Telegram.
Always writes delivery.json with method, urls, release info and message ids."""
import json, os, re, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import storageto, telegram, ghrelease  # noqa: E402


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40]


def publish_release(run_dir, title, topic, chat_id):
    """Rule 9: main video ALWAYS as a git release; link ALWAYS shared.
    Returns the release info dict for delivery.json."""
    slug = topic.get("slug") or _slug(title)
    tag = f"film-{slug}"
    named = [(os.path.join(run_dir, "final.mp4"), f"{slug}_full_1080p.mp4")]
    p720 = os.path.join(run_dir, "final_720p.mp4")
    if os.path.isfile(p720):
        named.append((p720, f"{slug}_full_720p.mp4"))
    tr = os.path.join(run_dir, "trailer.mp4")
    if os.path.isfile(tr):
        named.append((tr, f"{slug}_trailer.mp4"))
    named = [(p, n) for p, n in named if os.path.isfile(p)]
    info = {"tag": tag, "files": [n for _, n in named]}
    try:
        html, urls = ghrelease.publish(
            tag, title, named,
            body=(f"Auto-published by vfactory s7 — {title}\n\n"
                  f"Full film (1080p master) + 720p mirror + trailer."))
        info.update({"url": html, "assets": urls, "ok": True})
        lines = "\n".join(f"• {n}: {u}" for n, u in urls.items()
                          if u and not n.endswith("__error"))
        msg = (f"🎬 <b>{title}</b> — main video on GitHub Releases\n"
               f"⬇️ {html}\n{lines}")
        sent = telegram.send_message(msg, chat_id=chat_id)
        info["share_message_id"] = sent.get("result", {}).get("message_id")
    except Exception as e:  # never hide a broken delivery — record loudly
        info.update({"ok": False, "error": repr(e)[:300]})
    return info


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

    # STANDING RULE: the main video ALWAYS lands on a git release and the
    # link is ALWAYS shared — regardless of which Telegram path ran above.
    result["release"] = publish_release(run_dir, title, topic, chat_id)
    result["delivered"] = bool(result.get("release", {}).get("ok"))
    json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"),
              ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    print(json.dumps(run(os.path.dirname(sys.argv[1])), indent=2))
