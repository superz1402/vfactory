# AHYEON harvest — one-run Termux script

**One command. Downloads the curated Ahyeon-dedicated source library, validates
every file, uploads everything to storage.to + machine mirrors, and gives you
ONE link to send back.**

## Run it on Termux (Android)

```bash
pkg update -y && pkg upgrade -y
pkg install -y python ffmpeg jq curl
termux-setup-storage          # only if you want the library on shared storage
# drop one_run_harvest.sh anywhere, then:
bash one_run_harvest.sh
```

That's the whole job. It installs yt-dlp itself, then:

1. resolves + downloads **45 Ahyeon-dedicated sources** (720p mp4, ~6-8 GB):
   - the origin artifacts (Dangerously cover, 15-y-o eval, Last Evaluation EP.1-8 + BTS)
   - THE FIRST TAKE vocals (SHEESH, DRIP), Leemujin Service, vampire, Monster, MAMA Golden
   - official MVs (SHEESH, Stuck In The Middle, DRIP, FOREVER, HOT SAUCE; BATTER UP only as
     "debut without Ahyeon" context)
   - official 4K member cams (Mnet MPD / SBS Inkigayo: SHEESH, DRIP, FOREVER, LIKE THAT,
     Really Like You, MOON, CHOOM, PSYCHO, SUGAR HONEY ICE TEA, Problem tour cam)
2. validates each file (ffprobe: real video+audio, duration, resolution, sha256)
3. uploads EVERY file to:
   - **storage.to** (your directive — permanent-ish browser mirror, 3 days anonymous)
   - **filebin.net / uguu / litterbox / 0x0.st / bashupload** — machine mirrors the
     build pipeline can pull from (each link is plain-fetch-tested, honestly flagged)
4. writes `~/ahyeon_harvest/out/links_manifest.json` (links + sha256 + metadata) and
   prints a **single paste.rs handoff link** (auto-copied to clipboard on Termux)

## What to send back

The script prints at the end:

```
SEND THIS ONE LINK BACK TO THE AGENT:
https://paste.rs/XXXX
```

Send that one link. It contains every video link + sha256 + metadata needed to
build. (Local copies: `~/ahyeon_harvest/out/links_manifest.json`, `out/LINKS.md`.)

## Useful variants

```bash
bash one_run_harvest.sh --priority 1      # only the 21 core sources (~3 GB)
bash one_run_harvest.sh --1080            # request 1080p (slower, ~12 GB)
bash one_run_harvest.sh --items xw7Y2gviWbA,UTfHawj9Z6w
bash one_run_harvest.sh --selftest        # full chain without YouTube (3 dummy files)
```

Re-running is always safe — finished items are skipped, failures retried.

## If YouTube asks "sign in to confirm you're not a bot"

On a home/mobile IP this is rare. If it happens: export cookies.txt from your
phone browser (any cookies.txt extension), save it as
`~/ahyeon_harvest/cookies.txt`, re-run. The script picks it up automatically.

## Honest notes

- **storage.to links are browser-only** (they gate direct fetches behind a
  proof challenge). They're your human mirror — the build pipeline pulls from
  the machine mirrors (filebin 7d / uguu 48h / litterbox 72h / 0x0.st 30d),
  each verified byte-for-byte with sha256 at fetch time.
- Files that fail download or validation are **reported as failed** in the
  manifest — nothing fake, nothing padded.
- On datacenter IPs (like the agent sandbox) catbox/litterbox/0x0.st are
  blocked and YouTube is bot-gated — that's exactly why this runs on your phone.

## Build-side counterpart

`fetch_manifest.py` (committed alongside in vfactory) takes the manifest URL,
pulls every machine-fetchable mirror, **verifies sha256**, ffprobe-validates,
and drops `~/ytdl-agent/downloads/harvest/<source_id>.mp4` — ready for the
Ahyeon-dedicated edit (character-locked clips per act).

## Server-side companion: cobalt_drip_harvest.py

Discovered 2026-10-16: the only no-JWT cobalt relay (api.cobalt.liubquanti.click)
rate-limits ~1 request per 90-100s per source IP, then RECOVERS. Behind it, tunnel
hosts rotate across community instances — some healthy, some googlevideo-blocked
(0-byte tunnels = upstream roulette, NOT a dead item).

So the server CAN harvest without any new IPs, slowly: 1 request per cooldown
window, full download + ffprobe validation, resumable state.

```bash
python3 tools/harvest/cobalt_drip_harvest.py --budget-sec 470 --max-priority 1
```

- Yield: ~1 video / 3-4 attempts (~30-40 min per item at 720p)
- State: ytdl-agent/downloads/harvest/drip_state.json (per-burst fail decay,
  flaky items requeued last, persistent api_error items die after 6)
- Files land next to state as <source_id>.mp4 — same pool fetch_manifest.py reads
- This lane accumulates P1 footage server-side; the Termux one-run script
  remains the primary mass lane for the full 45-item list
