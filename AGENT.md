# AGENT.md — MUST-FOLLOW OPERATING SYSTEM FOR ANY AGENT

This repository is a **topic → full-video documentary factory** (vfactory).
Any agent (human or AI) operating on this repo MUST follow this document.
It encodes 5 rounds of user quality rejections and the fixes that satisfied them.
Read it fully before changing anything. `README.md` is the quick tour; this file is the law.

---

## 1. Mission

Send a topic → get a finished, fact-disciplined documentary video delivered to Telegram.
Pipeline: `s1 research → s2 script → s3 voice → s4 smart scenes → s5 score → s6 render → s7 deliver`,
checkpointed per stage (`.done_*` / stage outputs are the checkpoints).

## 2. Non-negotiable quality doctrine (learned from 5 rejections)

1. **Real footage only.** Never compile slideshows of still images. Never reuse the same
   clip batch across builds ("rotating the same videos" was rejected outright).
2. **Entity-accurate footage.** The screen shows WHAT the narrator says WHEN they say it.
   See §3 Scene Doctrine. Random/unrelated shots = rejection.
3. **Subject-pure capture.** If the documentary is about a person (e.g. Ahyeon), do not show
   other random people/screens when that person is the subject. Other entities appear only
   when NAMED (saying "BLACKPINK" → show BLACKPINK; "all members" → all members).
4. **Never rip the source audio as the soundtrack.** If the narration is over MV footage,
   the music bed must be SYNTHESIZED (zero-licensing), sidechain-ducked under the voice,
   loudness-normalized (`loudnorm I=-14:TP=-1.5:LRA=11`). No weird SFX, no gimmick noises.
5. **No cheap overlays.** No `drawtext` captions floating on screen. Documentary look =
   footage + voice + score. Fades in/out only.
6. **Do not self-certify quality.** "done/good" requires evidence: extract frames at known
   narration timestamps and LOOK at them (vision check) before claiming completion.
7. **No excuses, no stalling.** If a source is blocked, build a workaround (§4). IP/availability
   excuses are not acceptable to the owner; the owner has explicitly authorized ytagent
   workarounds for footage retrieval.

## 3. Scene Doctrine (the smart director — `stages/s4_smart.py`)

The core improvement that made v2 acceptable. Every scene in `02_script.json` declares:

```json
"visual": [
  {"entity": "blackpink_group", "anchor": "BLACKPINK", "clip": "blackpink_group",
   "in_point": 27.8, "note": "screen must show BLACKPINK the moment the word is spoken"}
]
```

- **anchor** — the narration word that TRIGGERS the cut. `s4` runs faster-whisper
  (`small.en`, word timestamps) over the concatenated narration track, finds the anchor
  (normalized substring; fuzzy ≥0.78 fallback; pronunciation variant lists like
  `["Ahyeon","ahyahn"]` are allowed because TTS may pronounce names phonetically), and cuts
  `LEAD=0.3s` BEFORE the word is spoken. Cut times come from REAL audio, never from estimates.
- **entity** — from a fixed vocabulary (`ahyeon_solo, babymonster_members, blackpink_group,
  announcement, stage_performance, mv_quality`). Every library clip in `footage/library.json`
  carries entity tags derived from its AUTHORITATIVE source title (official MV title beats
  vision guessing).
- **clip** (optional lock) — when the documentary intent is explicit ("as six" must be the
  BATTER UP era), lock the exact clip. Locks bypass variety logic.
- **in_point** (optional) — pin exact source second (e.g. TFT Ahyeon vocal showcase ≈ t118).
- Matcher rules: pinned hints → entity-covering clips → variety (no repeats within last 3).
  Same clip back-to-back must CONTINUE (in_point advances past the previous window), never replay.
- Whisper words are CACHED to `04_smart/words.json`. Never re-transcribe identical audio —
  re-running whisper on resume caused timeline drift against cached renders.

## 4. Footage acquisition doctrine

- Prefer **official sources** (YG official MVs, broadcaster facecams, THE FIRST TAKE).
  Verify identity via `ytsearch` titles + `oembed` BEFORE downloading; record
  `video_id`, `source_title`, `entities`, `duration` in `footage/library.json`.
- Download ladder (tooling in `agent-tools/ytagent`, state in `ytdl-agent/state/truth.json`):
  local ytagent → **yt-farm GitHub Actions workflow** (`superz1402/moltbook-agent`,
  `.github/workflows/yt-farm.yml`, artifact `video_<id>` + release `vid-<id>`)
  — the farm is the reliable path from datacenter IPs. `scripts/farm_fetch.py dispatch|poll`.
- When narration mentions a specific entity, get footage FOR THAT ENTITY first
  (e.g. return-era → `[BABYMONS7ER] VISUAL FILM`; debut-as-six → BATTER UP MV).

## 5. Render doctrine (`stages/s6_smart_render.py`)

- Hard cuts ON the words. No xfade soup; global fade in/out only.
- Ken Burns motion: `zoompan` MUST use `d=1` with incremental zoom (`zoom+0.0006`).
  **The `d=frames` form expands EVERY input frame N times = freeze-frame + huge renders.**
- Shot files must be EXACT timeline duration (`-frames:v`). Any pad accumulates per-shot
  drift against the narration (0.4s × 15 shots = 6s desync).
- Pass B re-encodes concat at `crf 24, maxrate 4.5M` to fit Telegram's 48MB bot limit.
- Caches are content-aware: pass A validates a sidecar `shot_i.json` (clip + in_point + dur),
  pass B rebuilds if any shot file is newer than the track. Never trust duration-only caches.

## 6. Delivery protocol (`stages/s7`, `lib/telegram.py`, `lib/storageto.py`)

- ≤48MB → Telegram `sendVideo` (bot token in dotfile, chmod 600). 504 Gateway Timeout on
  upload is TRANSIENT — retry up to 3× before falling back.
- >48MB or repeated failure → `storage.to` 3-step upload → send the link as a message.
- Always write `delivery.json` (message_id, storage url, size, retries) — delivery is not
  "done" until a real message_id exists.
- The owner's chat_id is `1263089875`. Bots cannot initiate chats never started by the user.

## 7. Evidence & closure protocol

- Every stage writes its artifact + a json manifest. `runs/<slug>/` is the audit trail.
- Before delivering: extract frames at known anchor timestamps from `final.mp4` and
  visually verify the entity mapping (this caught a 6-second desync that probes missed).
- After delivery: secret scan (`git grep` for token patterns), commit, push, **verify the
  remote hash** — "updated locally" is not done.
- Never commit tokens. Credentials live in `$HOME` dotfiles (`chmod 600`):
  `.gh_token`, `.tg_token*`, `.nvapi_token`.

## 8. Known traps (each one cost a build)

| Trap | Symptom | Rule |
|------|---------|------|
| z-ai node grandchildren hold pipes | permanent hang | Popen + `start_new_session` + killpg SIGTERM→SIGKILL (`lib/zai.py:_run`) |
| sandbox reaps detached background procs | silent death | run stages foreground, checkpoint per stage |
| whisper re-run on resume | timeline drift vs cached shots | cache `words.json` |
| `-t dur+0.4` render pad | cumulative narration desync | `-frames:v` exact |
| `zoompan d=frames` on video | freeze-frames, 4× file size, slow | `d=1` incremental zoom |
| duration-only cache in concat | stale visuals after shot change | mtime + sidecar validation |
| `anullsrc=channel_layouts=` | ffmpeg "Option not found" | `channel_layout` (singular) for anullsrc |
| PyAV 15 removed `metadata_errors` | faster-whisper crash | decode via ffmpeg → numpy float32 |
| Telegram sendVideo 504 | looks like failure | retry ×3, it's transient |
| concat demuxer relative paths | doubled paths, open fail | absolute paths everywhere |

## 9. Repository map

```
vfactory.py            orchestrator (stage runner, checkpoints, flags)
stages/s1_research.py  web research → sourced facts
stages/s2_script.py    LLM scene plan (fact-disciplined narration)
stages/s3_voice.py     per-scene TTS (voice: tongtong) + measured timings
stages/s4_smart.py     SMART DIRECTOR: whisper word-align + entity matcher → timeline.json
stages/s5_score.py     synthesized cinematic score (exact duration, A-minor bed)
stages/s6_smart_render.py  per-shot renders → concat → narration+ducked score mux
stages/s7_deliver.py   telegram / storage.to + delivery.json
stages/s8_qa.py, s8_qc.py  QC gates from the character-verified lineage (keep using them)
tools/doc_builder/     hand-verified documentary build path (v3) — robust download,
                       TTS, 3-pass audio, probe sheets, upload ladder
lib/zai.py             z-ai CLI wrappers (chat, tts, image_search, download, gen_video_clip)
lib/telegram.py        bot delivery (token path overridable via TG_TOKEN_PATH)
lib/storageto.py       storage.to uploader (3-step, multipart, visitor token)
footage/library.json   entity-tagged clip library (title-verified)
scripts/               build drivers, farm fetch, footage search, proofs
runs/                  every build with full artifacts (audit trail)
```

---

## 10. Long-form doctrine (v3, `--minutes N`) — 29-minute class documentaries

Modules: `stages/s2_chapters.py` -> `s3_voice` -> `s4_chapter_media.py` ->
`s5_chapter_score.py` -> `s6_chapters.py` -> `s8_qa` (longform profile) -> `s7`.

1. **Chapters, not one giant render.** N minutes -> ~N/2.6 chapters of
   ~2.6 min (~400 words each). s2 enforces length with a continuation loop
   (append, don't rewrite). Each chapter checkpoints independently
   (`.done_ch_<id>` + `chapter_NN.mp4`) — a crashed 29-min render resumes
   at the broken chapter, never from zero.
2. **Entity alignment is word-exact.** Edge voices give REAL word timestamps
   (no whisper needed). `lib/align.py` anchors each shot's cut to the first
   spoken occurrence of its query's keywords (LEAD 0.35s), fills unanchored
   shots into gaps, and guarantees durations sum to audio+tail EXACTLY.
   "Say BLACKPINK -> cut to BLACKPINK as the word lands."
3. **Hard cuts on words; xfades are not used inside chapters** (§5 doctrine).
   Chapter videos join by concat demuxer `-c copy` (uniform encodes are a
   hard requirement for the final concat too). Chapter edges get fades.
4. **Title cards: at most 3 per video** (ch1 big title + climax/turning_point
   + outro). No per-shot captions.
5. **Music = original composition, never source audio.** `lib/score.py`
   composes a real-instrument score (lemo-opuscar sampler, MIT; CC0/CC-BY
   sample libraries in `lib/audio/instruments/`, NOT in git — fetch before
   running longform) per chapter with a narrative intensity arc, act
   stingers and an outro resolve. CC-BY attribution is auto-written to
   `music_credits.txt` — never delete it. Fallback chain: sampler ->
   legacy synth (only if libraries are missing).
6. **Voices.** `--voice doc_male_us` (or any `edge:*`/`zai:*`). Provider
   failure falls back to zai automatically. ffprobe every output.
7. **QA profile longform** (s8_qa): cut cadence >=4 cpm, ASL <=12s (soft),
   LUFS in [-14,-10] (chapter loudnorm targets I=-13.5 so fades land the
   final inside the gate), dead-air + integrity gates unchanged.
8. **Delivery for big files**: 720p Telegram transcode ladder (s7) then
   storage.to multipart; `subtitles.srt` (from word timings) + credits ship
   with every run.
9. **zoompan rules**: `d=frames` is correct ONLY for stills (one input frame
   expanded); for VIDEO sources use fps-normalized scale/crop without
   zoompan, and trim with `-frames:v` — never `-t` (cumulative desync).

## 11. Repository map (v3 additions)

```
stages/s2_chapters.py       long-form chapter generator (continuation loop)
stages/s4_chapter_media.py  entity-matched per-chapter sourcing (validated,
                            perceptual dedup, watermark-farm skip)
stages/s5_chapter_score.py  per-chapter real-instrument scores + credits
stages/s6_chapters.py       per-chapter render: 4-move Ken Burns (stills),
                            hard-cut concat, per-chapter loudnorm mix
lib/voice.py                edge-tts (word timestamps) + zai providers
lib/score.py                score composer on the sampler engine
lib/audio/                  sampler/pluck/sfx (ported from lemo-opuscar, MIT)
                            + instruments/ sample libraries (not in git)
lib/align.py                narration->shot word-time alignment
lib/srt.py                  subtitles from word timings
```
