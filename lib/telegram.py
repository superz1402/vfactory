#!/usr/bin/env python3
"""Telegram delivery module. Token lives in /home/z/my-project/.tg_token (chmod 600).
sendVideo direct if <= TG_DIRECT_LIMIT, else caller uploads to storage.to and
uses send_message with the link."""
import os
import requests

TOKEN_PATH = "/home/z/my-project/.tg_token"
DEFAULT_CHAT = "1263089875"
TG_DIRECT_LIMIT = 48 * 1024 * 1024  # 50 MB bot API cap, 2 MB safety margin


def token():
    with open(TOKEN_PATH) as fh:
        return fh.read().strip()


def _api(method, **kw):
    url = f"https://api.telegram.org/bot{token()}/{method}"
    timeout = kw.pop("timeout", 180)
    return requests.post(url, timeout=timeout, **kw)


def send_message(text, chat_id=DEFAULT_CHAT, parse_mode="HTML", silent=False):
    r = _api("sendMessage", data={"chat_id": chat_id, "text": text,
                                  "parse_mode": parse_mode,
                                  "disable_notification": silent})
    return r.json()


def send_video(path, caption="", chat_id=DEFAULT_CHAT, silent=False, timeout=1800):
    """Multipart upload of a local video. Returns (ok, response_json)."""
    p = os.path.abspath(path)
    size = os.path.getsize(p)
    if size > TG_DIRECT_LIMIT:
        return False, {"ok": False, "description": f"file {size}B > {TG_DIRECT_LIMIT}B limit"}
    with open(p, "rb") as fh:
        r = _api("sendVideo", timeout=timeout,
                 data={"chat_id": chat_id, "caption": caption[:1024],
                       "disable_notification": silent,
                       "supports_streaming": "true"},
                 files={"video": (os.path.basename(p), fh, "video/mp4")})
    return r.json().get("ok", False), r.json()


def get_updates(offset=None, timeout=50):
    params = {"timeout": timeout}
    if offset:
        params["offset"] = offset
    r = requests.get(f"https://api.telegram.org/bot{token()}/getUpdates",
                     params=params, timeout=timeout + 20)
    return r.json()


if __name__ == "__main__":
    import sys
    print(send_message("vfactory self-test ok"))
