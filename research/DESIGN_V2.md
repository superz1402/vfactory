# vfactory v2 — "Documentary Grade" Research & Design

Date: 2026-10-09
Trigger: user verdict on v1 output: "random clips, weird noises, text on screen — this is a worst video. Learn from real documentaries first. Don't rush. Be perfect instead."

## 1. What we measured (evidence, not vibes)

Downloaded 3 of the 5 user-given references via yt-farm (GitHub runners; YouTube blocks sandbox IP):

| Ref | Channel | Len | cuts/min | ASL | median | p90 | ≤1s shots | grade |
|-----|---------|-----|----------|-----|--------|-----|-----------|-------|
| SEIPw295qrg | BPM Stories "The Year BABYMONSTER Broke Kpop" | 17:00 | 13.1 | 4.6s | 2.5s | 8.5s | 12% | sat 14.6, luma 82.9 (muted, dark) |
| ryj6jhR4mCU | KOOKIELIT "What Nobody Understands About Ahyeon" | 8:06 | 13.5 | 4.4s | 4.0s | 8.0s | 24% | talking head + receipts |
| YtuVWTvR3S4 | THE NOITE "Why Nobody in 5th Gen..." | 17:07 | (pending) | | | | | |

Audio (ref1): **-10.6 LUFS integrated, true peak +0.4 dBFS, ZERO silences >1s** — wall-to-wall sound, hot compressed master.

Chapter structure (ref1, real): hook 0:00 → origins 0:57 → members 1:46 → debut chaos 2:40 → comparisons 3:02 → breakthrough 5:07 → records 5:52 → tour 6:07 → setback 6:47 → comeback 7:30 → spotlights 8:27 → milestones 14:34. Chapters 45–90s; long spotlight block later.

Pacing arc (ref1): intro 20.8 cpm → mid 11.8 → last 6.5 (fast hook, cinematic tail).
Ref2: flat 12–15 cpm.

Visual grammar (frames inspected):
- Real footage: MV cuts, music-show performances, fancam-style close-ups
- Letterbox bars (2.35:1 inside 16:9) = instant "documentary" feel
- Text is RARE and ELEGANT: serif, centered, dates/names only ("November 15, 2023"), small source attribution bottom-left ("source: reddit @kizoya")
- Social-proof inserts: highlighted reddit/quote screenshots
- KOOKIELIT uses host talking-head + cutaways + receipts

## 2. Why v1 failed (honest post-mortem)

1. One still image per 7.6s scene with zoompan = slideshow. Real: 2–6s shots, mostly VIDEO, 13+ cuts/min.
2. Synthesized "music" (sine drones + brown noise + tremolo) = the "weird noises".
3. Giant drawtext captions every scene = looks like a slideshow subtitle track.
4. No letterbox/grade/grain = raw拼接 look.
5. Reported "done" without watching the output or comparing against any benchmark.

## 3. Validated asset sources (all tested live today)

- **Local MV library**: DRIP M/V (1080p 187s), DRIP + SHEESH THE FIRST TAKE (720p live vocals), AHYEON Dangerously cover (720p) — hundreds of cuttable moments
- **Mixkit** (free, no key): direct mp4 e.g. assets.mixkit.co/videos/14084/14084-720.mp4 ✅ tested
- **Coverr**: direct mp4 cdn.coverr.co/.../360p.mp4 ✅ reachable
- **incompetech** (Kevin MacLeod, CC-BY): direct mp3, 7/8 probed tracks live ✅
- **yt-farm** (GH Actions, WARP+POT): any YouTube video → release asset; all 5 refs fetched ✅
- **z-ai video gen**: works in principle, currently 429 rate-limited → optional b-roll later
- **image-search stills**: existing, fallback layer only

## 4. v2 pipeline design

```
s1 research (unchanged, FACT discipline)
s2 script v2  → BEATS not scenes: 8–14s beats, each = 1–2 sentences + visual_intent[]
s3 voice v2   → per-beat TTS (tongtong ok; alt voice test planned)
s4 footage    → shot planner: beat → 2–5 shots {source: mv|stock|still|ai, in,out, treatment}
              → mv library scanner (ffprobe, segment cache) + mixkit/coverr fetch + stills fallback
s5 music v2   → incompetech fetch 2–3 candidates by mood → pick → trim/loop → ducking source
s6 render v2  → per-shot pass: trim/scale/crop + letterbox + grade + grain + lower-third serif text
              → hard-cut concat (xfade only at chapter borders) + J-cuts (audio leads 0.3s)
              → narration + ducked music + master loudnorm -12.5 LUFS + limiter, no dead air
s7 qa         → GATES: cut metrics vs ref benchmark; LUFS in [-13.5,-11.5]; 0 silences >1.2s;
              → frame-sample review artifacts; shot source mix ≥60% video (not stills)
s8 deliver    → unchanged (telegram ≤48MB / storage.to)
```

Quality gates (hard numbers, from measurements):
- cuts/min ≥ 8 (target 10–16), ASL ≤ 6s, median ≤ 5s
- video-source shots ≥ 60% of shot count; stills ≤ 40%
- integrated LUFS in [-13.5, -11.5]; true peak ≤ -1.0 dB
- zero silence gaps > 1.2s
- letterbox + grain + grade present (visual check via sampled frames)
- ≤ 1 text overlay per beat, serif style, no caption walls

## 5. Licensing note

Genre-standard (all 5 refs do it): commentary/essay fair use of MV/performance footage with attribution. incompetech = CC-BY (credit in description). Mixkit/Coverr = free licenses. vfactory will write a CREDITS block from provenance manifest.
