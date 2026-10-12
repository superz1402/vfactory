# Motion / Animation Layer — from mortiflix-oss study (additive, pipeline-safe)

Source studied: github.com/GTKottman/mortiflix-oss (cloned at agent-tools/mortiflix-oss).

## What mortiflix actually is

A gate-based motion-design studio harness around Claude: brief -> script ->
style frames -> animatic -> build -> final, with human approval gates between
stages. Its motion capability is **Remotion** (React renders video per-frame),
driven by craft skills (`motion-design/SKILL.md`, `remotion-motion/SKILL.md`).

## What we borrow (and how, without touching the frozen 7-stage pipeline)

| mortiflix concept | vfactory integration |
|---|---|
| Remotion motion comps (kinetic type, lower-thirds, shape transitions, end cards) | **NEW OPTIONAL s6.5 "motion overlays"** — renders transparent-overlay clips (WebM alpha / ProRes4444) that s6 composites over scene clips. Enabled by `--motion` flag; default off. Pipeline shape unchanged. |
| `src/timing.ts` — all motion timing from narration word timings / beat grid | s6.5 reads `03_timings.json` + `06_timeline.json` — zero magic numbers, cut-accurate lower-thirds on narration keywords. |
| `motion-design` craft rules (ease-out entrances, 2-4 frame stagger, read-time = words/3+1, hold beats, safe areas) | Adopted as craft constants in the s6.5 skill doc + QC checks. |
| Animatic (720p timing preview before final) | s6 already renders fast clips; add `--animatic` cheap preview mode (720p, crf 30) for long films before final pass. |
| `final-pass/qc.mjs` (post-render check sheet) | Extend s6's hard QA: also emit a contact sheet (1 frame/sec grid PNG) for human spot-check. |
| TASTE.md (learned taste rules carried across projects) | Add `films/TASTE.md` — accumulated user-approved rules (already live in AGENT.md non-negotiables). |
| Render queue (`mfx render`, one heavy job) | Our 2-CPU box: keep chunked/checkpointed ffmpeg; Remotion renders run on GitHub runners (film-factory pattern) when adopted. |

## Why not a rewrite

User constraint (Round 9): "all without messing up our original pipeline."
Remotion replaces the RENDERER, not just adds overlays — adopting it as the
main render path would couple us to Node+Chrome (~750MB) and change output
characteristics. As an overlay layer it adds motion design value (animated
titles, transitions, data cards) while footage selection, pacing, voice mix
and delivery stay exactly as proven in v1.

## Implementation order (when green-lit)

1. `stages/s65_motion.py` skeleton: reads timeline + script act_open/on_screen
   fields; emits overlay WebM-alpha per act-open + end card (Remotion template
   vendored in `motion/`).
2. Runner-side render workflow (film-factory pattern): Remotion render job on
   GitHub runner, artifacts pulled back (sandbox cannot host Chrome).
3. s6 gains `overlay=` compositing (ffmpeg overlay filter per scene — cheap,
   no re-encode of base footage needed if overlays are pre-scaled).
4. QC: overlay legibility check (contrast at overlay regions), then existing
   voice QA unchanged.
