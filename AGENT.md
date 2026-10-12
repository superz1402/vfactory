# AGENT.md — vfactory operator manual (MUST READ before every run)

## The non-negotiables (learned from 10 rounds of user feedback)

1. **REAL FOOTAGE ONLY.** No image slideshows. Every scene is cut from real
   video footage (fan cams, MVs, live stages, interviews). Static images are a
   last-resort fallback and must be reported in `04_media.log` — if more than
   10% of scenes fall back to images, the run is a FAILURE. (Rounds 1, 3, 10)
2. **SUBJECT FIDELITY.** Footage must show the film's subject (e.g. AHYEON),
   matched by era and content to what the narration says. No random clips.
   The footage pool (`footage_pool/INDEX.json`) is the source of truth: every
   source carries tags + era; scenes carry `footage_tags` + `era`; s4 matches
   them. (Round 3, 6)
3. **SCENE-VOICE SEMANTIC MATCH.** What the narrator says must be what is on
   screen. "SHEESH debut" must show SHEESH-era footage, not evaluation tapes.
   Era tags enforce this mechanically. (Round 6)
4. **VOICEOVER IS MANDATORY AND VERIFIED.** The render stage HARD-ASSERTS:
   every scene has a non-silent narration WAV, total narration coverage >= 50%
   of runtime, final.mp4 has an audio stream with sane loudness. A render that
   fails these refuses to ship. (Round 8)
5. **FULL FILM, NOT A TEASER.** The deliverable is a complete documentary
   (target 15-30 min). A 53-second fragment is not a deliverable. (Rounds 7, 9)
6. **NO BANNED MATERIAL.** `footage_pool/INDEX.json` has a `_banned` section
   (e.g. DRIP MV footage — Round 4). Banned sources get no tags and can never
   be selected. No reusing banned audio or MV edits.
7. **PRODUCTION GRADE PACING.** Documentary structure: acts with act-open
   cards, cutaways for rhythm (long scenes interleave main + insert footage),
   sparse captions (title + act opens only — no text spam), loudnorm audio,
   per-scene fades. Narration script: FACT-disciplined, spoken sentences,
   no hype words. (Rounds 1, 2)
8. **CREDENTIALS NEVER ENTER THE REPO.** Tokens live in `~/.tg_token`,
   `~/.gh_token` (chmod 600, gitignored). The footage farm lives in GitHub
   Actions workflows, tokens passed as runtime secrets/inputs only. (Round 5)
9. **MAIN VIDEO ALWAYS AS A GIT RELEASE — LINK ALWAYS SHARED.** Every run's
   main film (+720p mirror + trailer when present) is uploaded by s7 as
   assets of the film's release tag (`film-<slug>`) on the PUBLIC repo
   (superz1402/vfactory) — automatically, every delivery, no exceptions.
   The release link is then ALWAYS sent to the user (Telegram/chat).
   Telegram parts or storage.to mirrors alone are NOT a complete delivery.
   Verbatim directive: "Always upload the main video as a git release and
   share the link". (Round 10+)

## The footage problem (datacenter IP vs YouTube) — solved architecture

- `ytagent` (user's tool) + `agent-video-downloader` (avd) installed; YouTube
  direct is blocked from this sandbox IP (13/13 methods) — do NOT retry direct.
- **yt-farm** (GitHub Actions workflow `yt-farm.yml` in superz1402/moltbook-agent):
  dispatches `workflow_dispatch` with `video_url` = watch URL **or**
  `ytsearchN:query`. Runs on GitHub runners (unblocked): WARP proxy + BGutil
  POT provider + deno JS runtime + 5-player-client fallback chain. Uploads the
  file as a release asset `vid-<id>`. Pull assets via the **API octet-stream
  route** (`Accept: application/octet-stream`) — plain `releases/download`
  404s for private repos.
- Search-to-ID resolution happens ON the runner (v2.2+): the listing is taken
  straight from search output — NEVER re-extract the resolved video from the
  search URL (bot-wall).
- After pull: identify by frames (Read tool on extracted jpgs), tag honestly
  in INDEX.json, verify subject before first use.

## Pipeline contract

```
s1 research      -> 01_research.json            (skipped when --script-file)
s2 script        -> 02_script.json              (scenes: narration, on_screen, footage_tags, era, act_open)
s3 voice         -> 03_voice/*.wav + timings    (edge-tts en-US-AndrewNeural -4%; z-ai jam fallback)
s4 media         -> 04_media/*.mp4 + manifest   (footage-first cuts + cutaways; images only as last resort)
s5 music         -> 05_music/bed.wav            (numpy: Am-F-C-G progression, plucks, pulse, swells)
s6 render        -> final.mp4                   (concat demuxer -c copy; per-scene fades; HARD voice QA)
s7 deliver       -> delivery.json               (TG <=48MB direct; storage.to single-PUT <50MB; GitHub Releases ALWAYS for main film + link shared)
```

- Checkpoints: `.done_<stage>` markers + per-scene sidecars (`04_media/*.json`)
  make every stage resumable. Never re-derive; resume.
- Timeline = measured clip durations (pass_a adjusts; recompute starts after).
- Delivery sizes: TG sendVideo hard limit 48 MB. storage.to anonymous
  multipart is BLOCKED ("Unauthorized" at complete) — only single-PUT <50MB
  works. Big files go to **GitHub Releases on a PUBLIC repo** (vfactory).
  The sandbox<->GitHub pipe is fast (~11 MB/s).

## Film library / publishing

- Landing page: `gh-pages` branch of superz1402/vfactory ->
  https://superz1402.github.io/vfactory/ (film cards, embedded trailer <video>,
  full-film download links to public release assets).
- Release assets on public repos serve HTTP 206 (range) — <video> streaming
  works. On private repos everything 404s anonymously.

## Motion/animation layer (from mortiflix-oss study) — planned, additive only

See `docs/MOTION_PLAN.md`. Rule: **optional s6.5 overlay stage, never a rewrite**
— the 7-stage pipeline above stays frozen in shape.

## Operator checklist (every run)

1. Read this file. 2. Check pool: `ls footage_pool/*.mp4 | wc -l` >= 15 sources.
3. Dispatch farm pulls for missing eras BEFORE s4. 4. Run stages with
checkpoints; resume on timeout (2-CPU box: parallelize s4, chunk s6 pass_a).
5. Verify QA pass + spot-check frames with the Read tool. 6. Deliver: trailer
+ parts + **git-release link (Rule 9, mandatory — s7 does it automatically,
verify `delivery.json.release.ok == true`)** + library link. 7. Update
worklog; push repo; verify remote.
