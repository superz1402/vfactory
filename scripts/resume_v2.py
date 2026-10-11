#!/usr/bin/env python3
"""Resume v2 pipeline from existing timeline.json: s5 score + s6 render (B/C) + deliver."""
import os, sys, json
sys.path.insert(0, "/home/z/my-project/vfactory")
run_dir = os.path.abspath(sys.argv[1])
from stages import s4_smart, s5_score, s6_smart_render
import os as _os
if not _os.path.exists(_os.path.join(run_dir, "04_smart", "timeline.json")):
    s4_smart.run(run_dir)
    print("[s4] smart timeline done")
s5_score.run(run_dir)
print("[s5] score done")
final = s6_smart_render.run(run_dir)
print(f"[s6] final: {final}")

if "--no-deliver" in sys.argv:
    sys.exit(0)

os.environ["TG_TOKEN_PATH"] = "/home/z/my-project/.tg_token_submitter"
from lib import telegram as tg, storageto
size = os.path.getsize(final)
caption = ("AHYEON — The Voice of BABYMONSTER | v2 entity-matched documentary cut\n"
           "Cuts land ON the words: BLACKPINK->BLACKPINK, debut->BATTER UP era, "
           "return->BABYMONS7ER visual film, seven members->all members.")
ok, resp = tg.send_video(final, caption=caption)
delivery = {"final": final, "size": size, "channel": "telegram_direct",
            "bot": "@Submittermebot", "ok": ok, "resp": resp}
if not ok:
    print("direct send failed:", str(resp)[:200])
    up = storageto.upload(final)
    delivery["storage"] = up
    if up.get("url"):
        r2 = tg.send_message(f"AHYEON documentary v2 (full quality):\n{up['url']}")
        delivery["telegram_link_msg"] = r2
open(os.path.join(run_dir, "delivery.json"), "w").write(json.dumps(delivery, indent=1, default=str))
print("[s7]", json.dumps(delivery, default=str)[:300])
