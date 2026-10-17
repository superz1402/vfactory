# AHYEON — Director's Cut v3.0 → vfactory Integration Brief

**Date:** 2026-10-17 (Asia/Calcutta) · **Author:** Super Z (main agent) · **Repo:** superz1402/vfactory
**Trigger:** User uploaded 8 files — Director's Cut v3.0 FINAL (×4 copies), DOCUMENTARY_ENGINE_SPEC.md, FULL_NARRATION_SCRIPT.csv, FULL_NARRATION_DIRECTORIAL_SCRIPT.md, ahyeon_v2_narration_script_brief.docx

---

## 1. What arrived and what it is

| File | What it is | Verdict |
|---|---|---|
| `AHYEON_DirectorsCut_v3.0_FINAL_FULL.md` (×4 identical) | The sibling system's master plan: 48 scenes · 9 acts · 30:00.0 · 155 shots + 12 place plates · 1,692-shot face-indexed library / 110 verified windows · Appendix A top-40 verified windows with in/out timecodes · Appendix B retrieval list · Appendix C 22-source registry · Appendix D real URLs+timestamps (airport crowds, core clips) · Appendix E repo deep-dive + v3.0 narration deltas | **AUTHORITATIVE build plan** |
| `DOCUMENTARY_ENGINE_SPEC.md` | "Carmack Protocol": 4-cadre agent architecture + 7 hardened laws (subject >80% solo, historical precision, no black slides, acoustic voice chain, multi-movement score + 3:1 ducking, two-pass EBU R128) | Adopt as **render/mix law set** for s4–s7 |
| `FULL_NARRATION_SCRIPT.csv` + `FULL_NARRATION_DIRECTORIAL_SCRIPT.md` | Older 68-beat variant, 31:14, cold open on Nov 27 debut; still carries "Little Jennie" framing and "Carmack Masterpiece" outro; references `D:/ahyeon_crowd/` local files | **Superseded** — use only as lower-third copy source; its airport beats are replaced by v3.0 s32 + Appendix D1 |
| `ahyeon_v2_narration_script_brief.docx` | v2.0 formatted brief (pre-v3.0) | Superseded by v3.0 FINAL |

**Programmatic checks run on v3.0:** 48 scene headers parsed; timecodes strictly monotonic; film ends at exactly 30:00.0. Internally consistent. Narration is word-timed and declared locked — vfactory must NOT rewrite it; s2_script is bypassed for this build (script stage = ingest, not generate).

---

## 2. Build decision

- **Build cut:** Director's Cut v3.0 FINAL. The v3.0 deltas at the end of the doc (s07/s23 Jennie removed, s32 airport proof added, s43–44 dome+flower-cart) plus Appendix D URLs are part of the locked narration.
- **vfactory pipeline role:** s1/s2 become *verification + ingest* of the DC plan; s3 voice per DC spec; **s4 = EDL builder that consumes the DC scene plan + the mirror files we harvest** (the doc's in/out timecodes are positions "inside the mirror file" — mirror files = our harvest pool, keyed by source); s5/s6 rebuilt per Engine Spec laws; s7 delivery unchanged.
- **Era-honesty flags (10 scenes):** the four `era-absence` scenes (s10/s12/s15/s17) and `era-anon` (s06) are historically correct by design — she is objectively not in DREAM/Batter Up/SITM and the narration says so. These stay. The four `wide-framing` scenes (s19/s21/s24/s28) get verified closeups from Appendix A + newly added fancams.

---

## 3. Cross-verification results

**Fact dates in v3.0 all match vfactory FACT_BANK:** Nov 15 2023 notice · Batter Up Nov 27 2023 / 22.59M-24h / 100M-18d · Dream May 14 2023 / 1M-subs-52d · BABYMONS7ER Apr 1 2024 / 460k pre-orders / Circle #3 · DRIP Nov 1 2024 / 820k wk1 / 1M domestic / Billboard 200 · KSPO Jan 25–26 2025 / 32 shows / 20 cities / ~300k · MAMA Nov 29 2025 / Golden 6.68M views · RLY 5 days #1 Viral 50 · Vogue HK Mar 2026 · KGMA Apr 2026 33,380 votes 85.8% · CHOOM May 4 2026 · SHIT Jun 2026 #1 global daily / 100M · Mediabase #35 Jul 2026 · 10B cumulative Sep 3 2026 · Kyocera Sep 22–23 2026 / 55k.

**Source registry vs our harvest pool (the actionable diff):**
- 10 of 23 Appendix-C keys already covered by our 45-item list (SHEESH/SITM/DRIP/FOREVER/HOT SAUCE/BATTER UP MVs, LE EP.1–8, SHEESH MPD/facecams, Dangerously, MAMA Golden, MOON fancam, RLY fancam, LIKE THAT fancam, Zach Sang).
- **14 true gaps identified → resolved with channel-verified IDs via yt-dlp flat-playlist search → 19 items added (list 45 → 64; P1 21 → 32):**

| DC key | Added ID | Source |
|---|---|---|
| `shit` (0.76×2 — highest MV) | `naoGk-Zjc1s` | BABYMONSTER official |
| `choom` | `x3eqqoZPV_E` | BABYMONSTER official |
| `moon` MV | `xXZwZ0DolJc` | BABYMONSTER official |
| `dream` (Act-2 backbone) | `ynOtYmpZxak` | BABYMONSTER official |
| `reallylikeyou` | `XShaIZs7J7M` | BABYMONSTER official |
| `leval_ahyeon` (282 shots) | `8i_wZQoqbwU` (Introducing AHYEON) | BABYMONSTER official |
| `choom_stage` (**0.77 — highest window in film**) | `UPkyursCTfE` + `c1jLt0EarG4` | MBCkpop |
| `choom_stage` alt | `4cGD1koF2bk` | SBS Inkigayo |
| `kspo` (302 shots) | `qoDZQ3-CtCY` (BEHIND in SEOUL) | BABYMONSTER official |
| `nextmovement` | `rYyUpQ_veL4` | YG ENTERTAINMENT |
| `interview` | `a5cHf4Ls3o4` (InStyle) + `6y0MD1WkMN0` (Cosmopolitan) | official shows |
| `batterup_stage` | `FinTVHCeYBo` (Stadium Ver) | BABYMONSTER official |
| `shit` alt / `choom` alt | `SsuCimm5BIU` / `wqSHogLRtJI` performance videos | BABYMONSTER official |
| Airport era (v3.0 s32–35) | `n5ZKXeXSVeg` (Newsen GMP 2026.9.2) + `5LWSNVhkDgY` (D1-A1 Incheon short) | news/shorts |
| `sheesh_stage` flag fix (D3-P2) | `ILOm4yRXvuw` FaceCam 4K | SBS |

- Appendix D2 (Taipei flower cart, Kyocera sing-along) rows are search-only in the doc (no IDs) — they are find-guides for a phone-run or future search pass, not yet harvest items.

---

## 4. Acquisition status (honest)

- **Server-side drip lane** (`cobalt_drip_harvest.py`): relay currently self-tunnels with a googlevideo-blocked egress → 0-byte tunnels this session. Upstream health rotates; bursts retry with decay. Previously harvested files (DRIP/TFT 30.7MB, vampire 14.6MB, MOON fancam 42.5MB) were lost in the sandbox rollback and need re-harvest.
- **Search lane:** `--flat-playlist` search works from the datacenter (IDs resolve; player extraction is bot-gated).
- **Phone lane (PRIMARY):** `one_run_harvest.sh` now embeds the **64-item DC-synced list** (heredoc synced in both copies, bash -n clean). User runs once on Termux → uploads to storage.to/filebin/gofile/uguu/litterbox chain → `links_manifest.json` → server `fetch_manifest.py` pulls + sha256-verifies into `ytdl-agent/downloads/harvest/`.
- After fetch: s4 EDL builder maps each DC shot's `source title + in/out` onto the mirror file, samples frames, and fails loudly where the mirror is missing or the window exceeds its duration (the one known case: `nextmovement` official trailer is 95s while DC windows go to 2:53 — the DC's mirror was an extended reupload; our s4 re-windows on the official cut).

---

## 5. Engine Spec → vfactory render-law mapping (s4–s7 rebuild contract)

| Law | Spec requirement | vfactory implementation |
|---|---|---|
| L1 >80% solo | >80% of assets subject-solo | Verified-window pool (110 windows + new fancam P1s); s4 QA gate counts solo-ratio, fails under threshold |
| L2 historical precision | Named entity on screen when narrated | DC already maps place plates (CC, provenance kept); YG building = declared gap (Policy E) — honest |
| L4 acoustic voice | HPF 80Hz · notch 3600Hz Q1.8 −3dB · shelf 8500Hz −2dB · headroom 0.82 | Wire into s6 mix chain ahead of ducking; regression: processed narration ≥ narration-intelligibility floor |
| L5 score | Multi-movement per act · sidechain 3:1, 15ms/250ms, −6..−8dB dip | s5 rewrite (already queued): 9 act-movements, restrained cinematic palette, CC0 samples + Salamander piano (matches DC credits, license-clean); music-only mix must FAIL QC |
| L6 no black slides | Lower-thirds/HUD over continuous b-roll | s6 card renderer overlays on blurred-loop footage (DC card scenes already specify backgrounds) |
| L7 loudness | Two-pass EBU R128 −14 LUFS, −1.0 dBTP | s6 loudnorm two-pass + s7 true-peak ceiling check |
| **Audio root cause (standing)** | — | s6 fingerprint-invalidations + post-mix narration-presence verification + 5 regression tests remain MANDATORY (spec's L7 alone would NOT catch a music-only mix) |

---

## 6. Ordered next actions

1. User runs `one_run_harvest.sh` on Termux (64-item DC-synced list) → paste.rs manifest back.
2. `fetch_manifest.py` pulls + verifies mirrors; drip bursts continue opportunistically for P1 gaps.
3. s4 EDL builder: DC scene plan + mirrors → auditable per-scene edit plan (frame-sampled verification, real in/out, solo-ratio gate, era-flag preservation).
4. s3 voice per DC (voice model choice stays Andrew; DC docx names Multilingual variant — decide at proof stage, change invalidates downstream).
5. s5 multi-movement score; s6 Law-4/6/7 mix chain + audio root-cause fixes + regressions.
6. 60–90s proof render → QC → full 30:00 → new versioned release (old releases preserved).
