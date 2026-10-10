# tools/doc_builder — hand-built mini-documentary pipeline (v3)

Builds one specific deliverable: "AHYEON — The Voice of BABYMONSTER"
(2:23, 1920x1080@30, narration + royalty-free bed, documentary grammar).
This is the human-supervised edit path: a human (or agent) visually verifies
every shot window from contact sheets BEFORE it enters the timeline.

## Pipeline (in execution order)

| script | what it does |
|--------|--------------|
| `doc_ytagent_dl.sh` / `doc_dl_robust.sh` | source footage via ytagent (13-method chain; cobalt_community worked when raw yt-dlp was bot-walled) |
| `doc_probe_sheets.py` | 1-frame-per-N-seconds contact sheets of every source (`fps=1/N`, NOT select-mod — that one bursts 30fps per bucket) |
| `doc_verify_sheets.py` | dense sheets for candidate cut windows |
| `doc_tts.py` | narration via edge-tts `en-US-ChristopherNeural` (rate -6%) -> wav + `03_timings.json` |
| `build_ahyeon_doc_v3.py` | cut list -> per-clip encode (fit / vpad / lpad) -> concat + act-break dip -> grade (eq+vignette) + fades + title + credits card -> audio pass |
| `doc_remix.py` | audio recovery path: narration amix (separate) -> bed amix (separate) -> final loudnorm (separate). Three passes; single mega-graph truncates at narration end |
| `doc_upload.py` / `doc_upload_ladder.sh` | storage.to 3-step upload (multipart OK; **delete `.visitor_token` first — stale identities get Unauthorized on complete-multipart**), then 0x0/litterbox/uguu fallbacks |

## Hard-won rules (do not relearn these)

1. **`fps=1/N`, never `select='not(mod(floor(t),N))'`** for contact sheets — the
   select form grabs ~30 frames per bucket and tiles only the first seconds.
2. **Do not put `[m...` label strings through tool transports** — `[m` gets
   stripped (SGR-escape eating). Build labels at runtime or avoid them; better,
   split audio into multiple passes so no mixed-label is needed at all.
3. **atrim start/end is absolute time**, not duration: `atrim=7.0:150.77`
   yields 143.77s. Using `total` as the end value silently truncates the bed
   to narration length.
4. **loudnorm output sample rate**: isolate loudnorm stages in their own pass
   with an explicit `aresample` after; mixing 192k loudnorm output with 48k
   bed in one amix is what caused the silent truncation above.
5. **sheet-derived timecodes are window-relative** — add the window start, or
   you will cut at t+180s and get an empty clip (s9_i3 incident).
6. Telegram: brand-new bot tokens can 404 on getMe for minutes
   (propagation). Retry before concluding the token is dead.
7. Every performance shot must be from an Ahyeon-focus source or a window
   visually verified to contain her; group shots only for
   establishing/context. Credits card is mandatory (fair-use posture).

## Run artifact

`runs/ahyeon-doc-v3/final.mp4` — 143.24s, 93.5MB 1080p; `ahyeon_doc_720p.mp4`
(39.5MB) for Telegram direct send. Delivered 2026-10-10 via
t.me/Submittermebot (message_id 213) + https://storage.to/zC4qMjhXe
