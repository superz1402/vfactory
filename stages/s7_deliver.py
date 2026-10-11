#!/usr/bin/env python3
"""Stage 7: delivery. <=48 MB -> Telegram sendVideo direct; bigger ->
storage.to upload (3-step API) -> send link via Telegram. Always writes
delivery.json with method, url and message ids."""
import json, os, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib import storageto, telegram  # noqa: E402
from lib import srt as srt_mod  # noqa: E402


def _tg_transcode(final, run_dir, max_mb=46):
    """Re-encode to 720p CRF23 (faststart) small enough for Telegram sendVideo."""
    out = os.path.join(run_dir, "tg_720p.mp4")
    if os.path.exists(out) and os.path.getsize(out) <= max_mb * 1048576:
        return out
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", final,
                        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
                        "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", out],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0 or not os.path.exists(out):
        return None
    if os.path.getsize(out) > max_mb * 1048576:
        # one quality step down
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", final,
                            "-vf", "scale=1152:648",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "25",
                            "-c:a", "aac", "-b:a", "128k",
                            "-movflags", "+faststart", out],
                           capture_output=True, text=True, timeout=1800)
        if r.returncode != 0 or os.path.getsize(out) > max_mb * 1048576:
            return None
    return out


def run(run_dir, deliver=True, chat_id=None):
    final = os.path.join(run_dir, "final.mp4")
    topic = json.load(open(os.path.join(run_dir, "00_topic.json")))
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    tl = json.load(open(os.path.join(run_dir, "06_timeline.json")))
    shots = {"stats": {"total_shots": 0}}
    if os.path.exists(os.path.join(run_dir, "04_shots.json")):
        shots = json.load(open(os.path.join(run_dir, "04_shots.json")))
    qa = {}
    qa_path = os.path.join(run_dir, "07_qa.json")
    if os.path.exists(qa_path):
        qa = json.load(open(qa_path))
    size = os.path.getsize(final)
    mb = size / 1024 / 1024
    title = plan.get("title", topic["topic"])
    n_beats = len(plan.get("beats", []))
    n_chapters = len(plan.get("chapters", []))
    structure = (f"{n_chapters} chapters" if n_chapters else f"{n_beats} beats")
    # side deliverables: subtitles + music credits (any mode)
    srt_path, n_cues, credits_line = None, 0, ""
    try:
        srt_path, n_cues = srt_mod.build(run_dir)
    except Exception:
        srt_path = None
    music_json = os.path.join(run_dir, "05_music.json")
    if os.path.exists(music_json):
        mu = json.load(open(music_json))
        cr = mu.get("credits", "")
        if isinstance(cr, (list, tuple)):
            cr = "\n".join(str(x) for x in cr)
        if cr:
            with open(os.path.join(run_dir, "music_credits.txt"), "w") as fh:
                fh.write(cr + "\n")
            credits_line = f"\n\n♪ {cr.splitlines()[0]}"
    else:
        cr_path = os.path.join(run_dir, "06_music_credit.json")
        if os.path.exists(cr_path):
            cr = json.load(open(cr_path))
            if cr.get("license"):
                credits_line = f"\n\n♪ Music: {cr['license']}"
    qa_line = ""
    if qa.get("overall"):
        qa_line = f" • QA {qa['overall'].upper()}"
    caption = (f"<b>{title}</b>\n{topic['topic']}\n"
               f"{tl['total']:.0f}s • {structure} • "
               f"{shots['stats'].get('total_shots', 0)} shots"
               f"{qa_line} • {mb:.1f} MB\n"
               f"built by vfactory" + credits_line)
    chat_id = chat_id or topic.get("chat_id") or telegram.DEFAULT_CHAT
    result = {"file": final, "size_mb": round(mb, 1), "chat_id": chat_id,
              "structure": structure}
    if srt_path:
        result["subtitles"] = srt_path
        result["subtitles_cues"] = n_cues

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
        tg = _tg_transcode(final, run_dir)
        sent_direct = False
        if tg:
            ok, resp = telegram.send_video(tg, caption=caption, chat_id=chat_id)
            if ok:
                sent_direct = True
                result.update({"method": "telegram_720p", "ok": True, "file": tg,
                               "size_mb": round(os.path.getsize(tg) / 1048576, 1),
                               "message_id": resp.get("result", {}).get("message_id")})
        if not sent_direct:
            up = storageto.upload(final)
            result.update({"method": "storageto", "ok": True, **{k: up[k] for k in
                           ("url", "id", "expires_at")}})
            msg = (f"<b>{title}</b> — {tl['total']:.0f}s, {structure}, {mb:.1f} MB{qa_line}\n"
                   f"⬇️ <a href=\"{up['url']}\">{up['url']}</a>\n"
                   f"(storage.to • link valid until {up['expires_at'] or 'expiry'})" + credits_line)
            sent = telegram.send_message(msg, chat_id=chat_id)
            result["message_id"] = sent.get("result", {}).get("message_id")
    json.dump(result, open(os.path.join(run_dir, "delivery.json"), "w"),
              ensure_ascii=False, indent=1)
    return result


if __name__ == "__main__":
    print(json.dumps(run(os.path.dirname(sys.argv[1])), indent=2))
