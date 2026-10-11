#!/usr/bin/env python3
"""v2 smart build driver: entity-anchored documentary end-to-end.

  run_dir setup -> s3 voice -> library sync -> s4 smart director ->
  s5 score -> s6 smart render -> s7 deliver (Telegram @Submittermebot)

Usage: python3 scripts/build_v2_smart.py [--no-deliver] [--only stage]
"""
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path("/home/z/my-project")
VF = ROOT / "vfactory"
sys.path.insert(0, str(VF))

ENTITY_DIR = ROOT / "ytdl-agent" / "downloads" / "entity"
DL_DIR = ROOT / "ytdl-agent" / "downloads"

# entity-tagged library entries for NEW clips (source-title verified)
LIB_ADDITIONS = {
    "blackpink_group": ("downloads/entity/blackpink_group.mp4", "BLACKPINK - 'How You Like That' M/V (official)",
                        ["blackpink_group", "mv_quality"]),
    "visual_film": ("downloads/entity/visual_film.mp4", "[BABYMONS7ER] VISUAL FILM (return-era reveal)",
                    ["announcement", "babymonster_members", "ahyeon_solo"]),
    "introducing_ahyeon": ("downloads/entity/introducing_ahyeon.mp4", "BABYMONSTER - Introducing AHYEON (official)",
                           ["ahyeon_solo", "announcement"]),
    "batter_up_mv": ("downloads/entity/batter_up_mv.mp4", "BABYMONSTER - 'BATTER UP' M/V (debut as six)",
                     ["babymonster_members", "mv_quality"]),
    "sheesh_mv": ("downloads/entity/sheesh_mv.mp4", "BABYMONSTER - 'SHEESH' M/V (all seven debut)",
                  ["babymonster_members", "mv_quality"]),
    "ahyeon_drip_facecam": ("downloads/entity/ahyeon_drip_facecam.mp4", "AHYEON 'DRIP' FaceCam 4K @Inkigayo (SBS)",
                            ["ahyeon_solo", "stage_performance"]),
    "stuck_middle_mv": ("downloads/entity/stuck_middle_mv.mp4", "BABYMONSTER - 'Stuck In The Middle' M/V",
                        ["babymonster_members", "mv_quality"]),
    "drip_mv": ("downloads/video_Zp-Jhuhq0bQ.mp4", "BABYMONSTER - 'DRIP' M/V (official)",
                ["babymonster_members", "mv_quality", "ahyeon_solo"]),
}

CRITICAL = {"blackpink_group", "visual_film", "introducing_ahyeon", "batter_up_mv",
            "sheesh_mv", "ahyeon_drip_facecam", "drip_mv"}


def sh(cmd, timeout=600):
    import signal as sg
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(p.pid), sg.SIGTERM)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=8)
        except Exception:
            out, err = "", ""
        return -9, out or "", err or ""


def probe_dur(p):
    rc, out, _ = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(p)], timeout=30)
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def sync_library():
    lib_path = ROOT / "footage" / "library.json"
    lib = json.loads(lib_path.read_text()) if lib_path.exists() else {"clips": []}
    have = {c["clip_id"] for c in lib["clips"]}
    added, missing = [], []
    for cid, (rel, title, ents) in LIB_ADDITIONS.items():
        f = ROOT / "ytdl-agent" / rel
        if f.exists() and f.stat().st_size > 500_000:
            if cid in have:
                # refresh path/entities
                for c in lib["clips"]:
                    if c["clip_id"] == cid:
                        c.update({"file": str(f), "source_title": title, "entities": ents,
                                  "duration": c.get("duration") or probe_dur(f)})
            else:
                lib["clips"].append({"clip_id": cid, "file": str(f), "source_title": title,
                                     "entities": ents, "duration": probe_dur(f),
                                     "verified": "title"})
                added.append(cid)
        elif cid in CRITICAL:
            missing.append(cid)
    lib_path.write_text(json.dumps(lib, indent=1, ensure_ascii=False))
    print(f"library sync: +{added} critical_missing={missing}")
    return missing


def main():
    no_deliver = "--no-deliver" in sys.argv
    stamp = time.strftime("%m%d-%H%M")
    run_dir = (Path(sys.argv[sys.argv.index("--run-dir") + 1]) if "--run-dir" in sys.argv \
        else VF / "runs" / f"ahyeon-v2-smart-{stamp}").resolve()
    if not (run_dir / "02_script.json").exists():
        run_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(VF / "runs" / "v2_script.json", run_dir / "02_script.json")
        (run_dir / "00_topic.json").write_text(json.dumps(
            {"topic": "Ahyeon BABYMONSTER main vocalist journey", "style": "documentary",
             "aspect": "16:9", "tts_speed": 1.0}, indent=1))

    # s3 voice
    from stages import s3_voice
    s3_voice.run(str(run_dir))
    print("[s3] voice done")

    missing = sync_library()
    if missing:
        print(f"FATAL: critical footage missing: {missing}")
        return 2

    # s4 smart director
    from stages import s4_smart
    s4_smart.run(str(run_dir))
    print("[s4] smart timeline done")

    # s5 score
    from stages import s5_score
    s5_score.run(str(run_dir))
    print("[s5] score done")

    # s6 render
    from stages import s6_smart_render
    final = s6_smart_render.run(str(run_dir))
    print(f"[s6] final: {final}")

    if no_deliver:
        print("[s7] skipped (--no-deliver)")
        return 0

    # s7 deliver via @Submittermebot
    os.environ["TG_TOKEN_PATH"] = str(ROOT / ".tg_token_submitter")
    from lib import telegram as tg
    from lib import storageto
    size = os.path.getsize(final)
    caption = ("AHYEON — The Voice of BABYMONSTER | entity-matched documentary cut v2\n"
               "Scene doctrine: cuts land ON the words (BLACKPINK->BLACKPINK, "
               "debut->BATTER UP era, return->BABYMONS7ER visual film, seven->all members)")
    ok, resp = tg.send_video(str(final), caption=caption)
    delivery = {"final": str(final), "size": size, "channel": "telegram_direct",
                "bot": "@Submittermebot", "ok": ok, "resp": resp}
    if not ok:
        print("direct send failed:", resp.get("description"))
        up = storageto.upload(str(final))
        delivery["storage"] = up
        if up.get("url"):
            r2 = tg.send_message(f"AHYEON documentary v2 (full quality):\n{up['url']}")
            delivery["telegram_link_msg"] = r2
    (run_dir / "delivery.json").write_text(json.dumps(delivery, indent=1))
    print("[s7] delivery:", json.dumps(delivery, default=str)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
