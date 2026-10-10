# vfactory — topic → full video, one command

Send a topic. Get a finished video — research, script, narration, visuals,
score, render, delivery. Fully autonomous.

```
python3 vfactory.py "Ahyeon BABYMONSTER main vocalist journey" --style documentary
```

→ ~60-90s 1080p30 mp4, TTS narration, real sourced images with Ken Burns
motion, synthesized cinematic score (sidechain-ducked under VO, loudnorm
-14 LUFS), delivered to Telegram (direct ≤48 MB) or storage.to (bigger),
link pushed to the same chat.

## Pipeline

| Stage | What happens | Checkpoint |
|-------|--------------|------------|
| s1 research | 3-angle web search → deduped source brief | `01_research.json` |
| s2 script   | LLM documentary plan: hook/body/outro scenes, narration + on-screen text + visual queries. FACT discipline: only sourced facts, thin sources → safe general phrasing | `02_script.json` |
| s3 voice    | per-scene TTS (voice `tongtong`) + ffprobe timings | `03_voice/`, `03_timings.json` |
| s4 media    | image-search per scene → download + validate; ffmpeg title-card fallback so render never breaks; optional `--ai-broll` generates scene-1 b-roll | `04_media/`, `04_media.json` |
| s5 music    | synthesized bed (dark/bright mood) — zero licensing risk | `05_music/bed.wav` |
| s6 render   | A: per-scene Ken Burns (zoompan, alternating in/out) + captions · B: xfade concat + global fades · C: narration timeline (adelay/amix) + bed sidechain-duck 8:1 + loudnorm → `final.mp4` | `06_final/` |
| s7 deliver  | ≤48 MB → Telegram sendVideo · bigger → storage.to 3-step upload → link via Telegram | `delivery.json` |

Every stage checkpoints; a killed run resumes with `--run-dir <dir>`.
`--rebuild` ignores checkpoints.

## Telegram interface (send a topic from your phone)

```
python3 telegram_listener.py          # long-poll bot, allowlist = your chat id
```

Message text = topic. Prefixes: `9:16` vertical, `#hype` style,
`5 scenes` count. `/help`, `/status` supported. One build at a time, queued.

Token: `~/.tg_token` (chmod 600, never in git). Default chat: owner's.

## Options

```
--style documentary|cinematic|hype|explainer
--scenes 3..10          (default 7)
--aspect 16:9|9:16      (1080p / vertical 1080x1920)
--region us|kr|jp|cn    (image search locale)
--tts-speed 0.5..2.0
--ai-broll              AI-generate the hook shot (slow)
--no-deliver            render only
--run-dir DIR           resume
```

## storage.to

`lib/storageto.py` implements the official 3-step flow
(`/upload/init` → presigned PUT(s) → `/upload/confirm`), multipart for
>50 MB, persistent visitor token, owner_token captured per file.
Anonymous limits: 50 files/24h, 100 GB/24h, 25 GB/file, 3-day expiry.
Drop a bearer token into `storageto.upload(path, bearer=...)` for
premium (permanent) files.

## Provenance

- Built and verified end-to-end 2026-10-09: Ahyeon documentary run,
  53.2s 1920x1080@30, 19.9 MB → Telegram message_id 291 +
  https://storage.to/ZooVLflbO
- Stack: z-ai CLI (search/LLM/TTS/image-search/video-gen), ffmpeg 7.1,
  Python 3.12. No external services beyond those + Telegram/storage.to.

## Files

```
vfactory.py              orchestrator (CLI, checkpoints, logging)
telegram_listener.py     bot front-end (long-poll, queue, delivery)
lib/zai.py               z-ai CLI wrappers (group-kill timeout hardening)
lib/storageto.py         storage.to 3-step upload (single + multipart)
lib/telegram.py          sendVideo/sendMessage/getUpdates
stages/s1..s7            pipeline stages
runs/<slug>/             per-run artifacts + final.mp4 + delivery.json
```
