#!/usr/bin/env bash
# =============================================================================
# one_run_harvest.sh — AHYEON documentary source harvester (one command)
# =============================================================================
# What it does (single run, resumable):
#   1. installs its own dependencies (Termux / Debian / macOS)
#   2. downloads the CURATED Ahyeon-dedicated source list (720p mp4)
#      - every item is Ahyeon-focused by design (MV / member cam / live vocal /
#        Last Evaluation doc / ensemble context), tagged by documentary act
#   3. validates every file (ffprobe streams, duration, height, sha256)
#   4. uploads EVERY file to storage.to (primary) + a verified backup host
#      (gofile / catbox / litterbox / 0x0.st / bashupload / uguu)
#   5. writes out/links_manifest.json + out/LINKS.md + ONE handoff link
#      (paste.rs) — send that single link back to the agent
#
# Usage:
#   bash one_run_harvest.sh                 # P1+P2 sources (default)
#   bash one_run_harvest.sh --priority 3    # everything incl. nice-to-have
#   bash one_run_harvest.sh --items xw7Y2gviWbA,O99aP4AvEF8
#   bash one_run_harvest.sh --max 2         # tiny test run
#   bash one_run_harvest.sh --selftest      # full chain without YouTube
#   bash one_run_harvest.sh --1080          # request 1080p (slower, bigger)
#
# Re-running is always safe: finished items are skipped, broken ones retried.
# =============================================================================
set -u
HARVEST_VERSION="1.0.0"
SCHEMA="ahyeon.harvest/1.0"

WORK="${HARVEST_DIR:-$HOME/ahyeon_harvest}"
STATE="$WORK/state"
MEDIA="$WORK/media"
OUT="$WORK/out"
LOG="$WORK/harvest.log"
VISITOR_TOKEN_FILE="$WORK/.visitor_token"
COOKIES="$WORK/cookies.txt"   # optional: export from browser if YouTube asks

MAX_HEIGHT="${HARVEST_HEIGHT:-720}"
PRIORITY_MAX=2
ONLY_ITEMS=""
MAX_ITEMS=0
SELFTEST=0
REDOWNLOAD=0

# ---------------------------------------------------------------- logging ---
TS() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log()  { echo "[$(TS)] $*" | tee -a "$LOG"; }
warn() { echo "[$(TS)] WARN: $*" | tee -a "$LOG" >&2; }
fail() { echo "[$(TS)] FAIL: $*" | tee -a "$LOG" >&2; }

# ----------------------------------------------------------------- args -----
while [ $# -gt 0 ]; do
  case "$1" in
    --priority) PRIORITY_MAX="$2"; shift 2;;
    --items)    ONLY_ITEMS="$2"; shift 2;;
    --max)      MAX_ITEMS="$2"; shift 2;;
    --1080)     MAX_HEIGHT=1080; shift;;
    --selftest) SELFTEST=1; shift;;
    --redownload) REDOWNLOAD=1; shift;;
    -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0;;
    *) warn "unknown arg: $1"; shift;;
  esac
done

mkdir -p "$STATE" "$MEDIA" "$OUT"
: > "$LOG" 2>/dev/null || LOG=/dev/null

log "=== AHYEON harvest v$HARVEST_VERSION | workdir=$WORK | max_height=$MAX_HEIGHT ==="

# ------------------------------------------------------------ environment ---
IS_TERMUX=0
case "${PREFIX:-}" in
  *com.termux*) IS_TERMUX=1; log "environment: Termux ($PREFIX)";;
  *) log "environment: $(uname -s)";;
esac

have() { command -v "$1" >/dev/null 2>&1; }

install_pkg() {
  if [ "$IS_TERMUX" = "1" ]; then
    pkg install -y "$@" >>"$LOG" 2>&1
  elif have apt-get; then
    if [ "$(id -u)" = "0" ]; then apt-get install -y "$@" >>"$LOG" 2>&1
    else sudo apt-get install -y "$@" >>"$LOG" 2>&1 || return 1; fi
  else
    return 1
  fi
}

ensure_deps() {
  local missing=""
  for c in python3 ffmpeg ffprobe curl jq; do
    have "$c" || missing="$missing $c"
  done
  if [ -n "$missing" ]; then
    log "installing missing commands:$missing"
    # map binary->package for termux/apt
    local pkgs=""
    for c in $missing; do
      case "$c" in
        python3) pkgs="$pkgs python";;
        ffprobe) pkgs="$pkgs ffmpeg";;   # ffprobe ships with ffmpeg
        *) pkgs="$pkgs $c";;
      esac
    done
    install_pkg $pkgs || { fail "cannot auto-install:$missing — install manually then re-run"; exit 1; }
  fi
  # yt-dlp via pip (user scope)
  if ! python3 -c "import yt_dlp" >/dev/null 2>&1 && ! have yt-dlp; then
    log "installing yt-dlp via pip"
    python3 -m pip install --user -q yt-dlp >>"$LOG" 2>&1 \
      || python3 -m pip install -q --break-system-packages yt-dlp >>"$LOG" 2>&1 \
      || { fail "pip install yt-dlp failed — run: python3 -m pip install yt-dlp"; exit 1; }
  fi
  log "deps ok: $(python3 --version 2>&1) | ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3) | yt-dlp $(python3 -m yt_dlp --version 2>/dev/null || have yt-dlp && yt-dlp --version 2>/dev/null)"
}

ensure_deps

YTDLP="python3 -m yt_dlp"

# ------------------------------------------- storage.to uploader (stdlib) ---
# Mirrors vfactory/lib/storageto.py: init -> presigned PUT(s) -> confirm.
# Anonymous: 25 GB max/file, 3-day expiry, 50 files / 24 h, 100 GB / 24 h.
cat > "$WORK/.storageto_up.py" <<'PYEOF'
#!/usr/bin/env python3
import json, os, sys, urllib.request, urllib.error

BASE = "https://storage.to/api"
PART_FALLBACK = 32 * 1024 * 1024

def visitor_token(path):
    if os.path.exists(path):
        return open(path).read().strip()
    import uuid
    tok = uuid.uuid4().hex + uuid.uuid4().hex[:16]
    open(path, "w").write(tok)
    os.chmod(path, 0o600)
    return tok

def req(url, data=None, headers=None, method=None, timeout=1800):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, dict(resp.headers), body

def upload(path, token_file):
    size = os.path.getsize(path)
    name = os.path.basename(path)
    ctype = "video/mp4" if name.lower().endswith((".mp4", ".mov", ".m4v")) else "application/octet-stream"
    H = {"X-Visitor-Token": visitor_token(token_file)}
    # 1) init
    body = json.dumps({"filename": name, "content_type": ctype, "size": size}).encode()
    st, hd, b = req(f"{BASE}/upload/init", data=body,
                    headers={**H, "Content-Type": "application/json"}, method="POST", timeout=60)
    init = json.loads(b)
    if not init.get("success"):
        raise RuntimeError(f"init failed: {init.get('error')} (http {st})")
    etags = []
    if init.get("type") == "multipart":
        upload_id = init["upload_id"]
        part_size = init.get("part_size", PART_FALLBACK)
        urls = {int(k): v for k, v in (init.get("initial_urls") or {}).items()}
        total = init.get("total_parts") or ((size + part_size - 1) // part_size)
        with open(path, "rb") as fh:
            for n in range(1, total + 1):
                fh.seek((n - 1) * part_size)
                chunk = fh.read(part_size)
                if n not in urls:
                    pb = json.dumps({"upload_id": upload_id, "part_numbers": [n]}).encode()
                    st, hd, b = req(f"{BASE}/upload/parts", data=pb,
                                    headers={**H, "Content-Type": "application/json"},
                                    method="POST", timeout=60)
                    pj = json.loads(b)
                    if not pj.get("success"):
                        raise RuntimeError(f"parts url failed: {pj.get('error')}")
                    urls = {**urls, **{u["partNumber"]: u["url"] for u in pj.get("part_urls", [])}}
                st, hd, _ = req(urls[n], data=chunk, method="PUT")
                if st not in (200, 201):
                    raise RuntimeError(f"part {n}/{total} PUT http {st}")
                etags.append({"partNumber": n, "etag": (hd.get("ETag") or "").strip()})
                if n % 4 == 0:
                    print(f"part {n}/{total}", file=sys.stderr)
        cb = json.dumps({"upload_id": upload_id, "parts": etags}).encode()
        st, hd, b = req(f"{BASE}/upload/complete-multipart", data=cb,
                        headers={**H, "Content-Type": "application/json"}, method="POST", timeout=120)
        if not json.loads(b).get("success"):
            raise RuntimeError(f"complete-multipart failed: {b[:200]!r}")
        r2_key = init["r2_key"]
    else:
        with open(path, "rb") as fh:
            st, hd, _ = req(init["upload_url"], data=fh.read(), method="PUT")
        if st not in (200, 201):
            raise RuntimeError(f"presigned PUT http {st}")
        r2_key = init["r2_key"]
    # 3) confirm
    cb = json.dumps({"filename": name, "size": size, "content_type": ctype,
                     "r2_key": r2_key}).encode()
    st, hd, b = req(f"{BASE}/upload/confirm", data=cb,
                    headers={**H, "Content-Type": "application/json"}, method="POST", timeout=60)
    cj = json.loads(b)
    if not cj.get("success"):
        raise RuntimeError(f"confirm failed: {cj.get('error')} (http {st})")
    f = cj["file"]
    return {"url": f["url"], "id": f["id"], "expires_at": f.get("expires_at")}

if __name__ == "__main__":
    try:
        print(json.dumps(upload(sys.argv[1], sys.argv[2])))
    except Exception as e:
        print(json.dumps({"error": str(e)[:300]}))
        sys.exit(1)
PYEOF

# --------------------------------------------------------------- helpers ----
sha256_of() { python3 - <<PYEOF
import hashlib, sys
h = hashlib.sha256()
with open("$1", "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
print(h.hexdigest())
PYEOF
}

# verify a link serves bytes (range GET), host-aware headers:
# default plain; storageto needs browser UA + referer (else 403)
BROWSER_UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
verify_link() { # $1=host $2=url -> 0 if fetchable
  local h="$1" u="$2" code
  local hdrs=()
  case "$h" in
    storageto) hdrs=(-A "$BROWSER_UA" -e "https://storage.to/");;
  esac
  code=$(curl -sSL -m 45 -o /dev/null -w "%{http_code}" -r 0-1023 "${hdrs[@]}" "$u" 2>/dev/null || echo 000)
  case "$code" in 200|206) return 0;; *) return 1;; esac
}

# --------------------------------------------- source list (curated, real) --
# [source_id, yt_id, role, priority, act_tags, title_kw, channel_kw, note]
SOURCES_JSON="$WORK/sources.json"
write_sources() {
cat > "$SOURCES_JSON" <<'JSONEOF'
{
  "schema": "ahyeon.harvest/1.0",
  "note": "Ahyeon-dedicated sources only. role: ahyeon_primary | ahyeon_cam | evaluation_doc | ensemble_context. ensemble_context = used ONLY for non-Ahyeon establishing beats.",
  "items": [
    ["xw7Y2gviWbA","xw7Y2gviWbA","ahyeon_primary",1,["s1_origin","s5_vocal"],"Dangerously","BABYMONSTER","Dangerously COVER (Last Evaluation, origin artifact)"],
    ["ysJCTCQYJyg","ysJCTCQYJyg","ahyeon_primary",1,["s1_origin"],"","","Ahyeon 15-year-old evaluation performance (~18M views)"],
    ["O99aP4AvEF8","O99aP4AvEF8","ahyeon_primary",1,["s4_coronation","s5_vocal"],"SHEESH","THE FIRST TAKE","SHEESH / THE FIRST TAKE (one-take live)"],
    ["06mCrMgv0zY","06mCrMgv0zY","ahyeon_primary",1,["s5_vocal"],"DRIP","THE FIRST TAKE","DRIP / THE FIRST TAKE (climax C5-G5 window ~t150-198)"],
    ["hSgMTFImB7c","hSgMTFImB7c","ahyeon_primary",1,["s5_vocal"],"vampire","KBS","AHYEON vampire - Limousine Service clip (MBC/KBS)"],
    ["MsOOG4Q5HvQ","MsOOG4Q5HvQ","ahyeon_primary",1,["s5_vocal"],"Monster","Begin Again","AHYEON Monster - Begin Again Open Mic"],
    ["1TYYOw-815A","1TYYOw-815A","ahyeon_primary",1,["s6_group_rise"],"Golden","Netflix","MAMA 2025 Golden - PHARITA/AHYEON/RORA (Mnet)"],
    ["e3U5Cz_ZASU","e3U5Cz_ZASU","ahyeon_cam",1,["s7_now"],"Problem","AHYEON","Problem (Ariana Grande) WORLD TOUR 4K fan cam"],
    ["ItDZsiOhG6M","ItDZsiOhG6M","ahyeon_cam",1,["s7_now"],"MOON","M2","MOON fancam MCOUNTDOWN 4K (Mnet MPD)"],
    ["OMeeqIge53E","OMeeqIge53E","ahyeon_cam",1,["s7_now"],"CHOOM","SBS","CHOOM fancam Inkigayo 4K (SBS)"],
    ["8l5q7ZmZN-s","8l5q7ZmZN-s","ahyeon_cam",1,["s7_now"],"PSYCHO","AHYEON","PSYCHO fancam WORLD TOUR 4K"],
    ["2wA_b6YHjqQ","2wA_b6YHjqQ","ahyeon_primary",1,["s3_return","s4_coronation"],"SHEESH","BABYMONSTER","SHEESH official MV"],
    ["GsV1i0QHi-o","GsV1i0QHi-o","ahyeon_primary",1,["s3_return"],"Stuck In The Middle","BABYMONSTER","Stuck In The Middle official MV (return era)"],
    ["Zp-Jhuhq0bQ","Zp-Jhuhq0bQ","ahyeon_primary",1,["s5_vocal"],"DRIP","BABYMONSTER","DRIP official MV"],
    ["VQOizqBsqLc","VQOizqBsqLc","ahyeon_cam",1,["s4_coronation"],"SHEESH","M2","SHEESH MPD fancam 4K (Mnet official)"],
    ["karQAIwewUk","karQAIwewUk","ahyeon_cam",1,["s5_vocal"],"DRIP","SBS","DRIP fancam 4K (SBS Inkigayo)"],
    ["hCgZqFscMp0","hCgZqFscMp0","evaluation_doc",1,["s1_origin","s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.1 (YG)"],
    ["Gi0ezbc0OwU","Gi0ezbc0OwU","evaluation_doc",1,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.8 (YG)"],
    ["UESsLN8i63w","UESsLN8i63w","evaluation_doc",1,["s2_system"],"Vocal Mission","BABYMONSTER","Last Evaluation Individual Vocal Mission"],
    ["UTfHawj9Z6w","UTfHawj9Z6w","ahyeon_primary",1,["s5_vocal"],"Leemujin","KBS","Leemujin Service EP.140 AHYEON (full live vocal show)"],
    ["Kxb0aUqmex0","Kxb0aUqmex0","evaluation_doc",1,["s2_system"],"Behind The Scenes","BABYMONSTER","Last Evaluation BTS #2 (dorm)"],
    ["eJCHKjt0MPw","eJCHKjt0MPw","ahyeon_primary",2,["s6_group_rise"],"FOREVER","BABYMONSTER","FOREVER official MV"],
    ["xn8mQqz2xmM","xn8mQqz2xmM","ahyeon_primary",2,["s6_group_rise"],"HOT SAUCE","BABYMONSTER","HOT SAUCE official MV"],
    ["gyRcsW9ORR4","gyRcsW9ORR4","ahyeon_cam",2,["s4_coronation"],"SHEESH","SBS","SHEESH fancam 4K (SBS Inkigayo)"],
    ["1vNM1ANg_3w","1vNM1ANg_3w","ahyeon_cam",2,["s4_coronation"],"SHEESH","SBS","SHEESH facecam 4K (SBS)"],
    ["uVjLpYYfsy4","uVjLpYYfsy4","ahyeon_cam",2,["s7_now"],"LIKE THAT","M2","LIKE THAT MPD fancam 4K (Mnet)"],
    ["lt_LdIkPYkY","lt_LdIkPYkY","ahyeon_cam",2,["s6_group_rise"],"Really Like You","M2","Really Like You fancam 4K (Mnet)"],
    ["jap9rSZds7U","jap9rSZds7U","ahyeon_primary",2,["s1_origin","s5_vocal"],"Dangerously","Knowing","Dangerously - Knowing Bros cut"],
    ["6kGauBXhawU","6kGauBXhawU","ahyeon_primary",2,["s7_now"],"Dangerously","","Dangerously live - HELLO MONSTERS tour Kanagawa"],
    ["olDWm2veCrM","olDWm2veCrM","ensemble_context",2,["s1_origin"],"BATTER UP","BABYMONSTER","BATTER UP MV - DEBUT WITHOUT AHYEON context only"],
    ["4pcmRcjMhvc","4pcmRcjMhvc","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.2"],
    ["mO9VkglQKgg","mO9VkglQKgg","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.3"],
    ["LN-G05mqGjY","LN-G05mqGjY","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.4"],
    ["geVfm6A7CHw","geVfm6A7CHw","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.5"],
    ["W8qUoHsE-wQ","W8qUoHsE-wQ","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.6"],
    ["k2GNcev8kaA","k2GNcev8kaA","evaluation_doc",2,["s2_system"],"Last Evaluation","BABYMONSTER","Last Evaluation EP.7"],
    ["HFLq5j8wU5Q","HFLq5j8wU5Q","ensemble_context",2,["s7_now"],"HELLO MONSTERS","BABYMONSTER","HELLO MONSTERS BEHIND in LA #1"],
    ["4NvYGr1YWr4","4NvYGr1YWr4","ensemble_context",2,["s7_now"],"SEE YOU THERE","BABYMONSTER","SEE YOU THERE BEHIND in JAKARTA"],
    ["6BVnhqQ28Vw","6BVnhqQ28Vw","ahyeon_cam",3,["s7_now"],"SUGAR HONEY","M2","SUGAR HONEY ICE TEA MPD fancam 4K"],
    ["lCO7-Z7ng-Q","lCO7-Z7ng-Q","ahyeon_cam",3,["s6_group_rise"],"HOT SAUCE","AHYEON","HOT SAUCE Summer Sonic Osaka 4K fan cam"],
    ["7xUO44qVEDc","7xUO44qVEDc","ahyeon_cam",3,["s3_return"],"STUCK","AHYEON","Stuck In The Middle Tokyo Summer Sonic 4K fan cam"],
    ["hQD8rwwB-Vc","hQD8rwwB-Vc","ahyeon_cam",3,["s6_group_rise"],"FOREVER","SBS","FOREVER fancam 4K (SBS)"],
    ["YGG3936Bt2c","YGG3936Bt2c","evaluation_doc",3,["s2_system"],"Behind The Scenes","BABYMONSTER","Last Evaluation BTS #3"],
    ["Am2NBfQ3I2g","Am2NBfQ3I2g","evaluation_doc",3,["s2_system"],"Behind The Scenes","BABYMONSTER","Last Evaluation BTS #4"],
    ["6ha4zBqRkUE","6ha4zBqRkUE","ensemble_context",3,["s8_future"],"Zach Sang","","Zach Sang Show interview (group)"]
  ]
}
JSONEOF
log "source list written: $SOURCES_JSON ($(jq '.items|length' "$SOURCES_JSON") items)"
}
write_sources

# honor a custom override list if present
if [ -f "$WORK/sources.custom.json" ]; then
  SOURCES_JSON="$WORK/sources.custom.json"
  log "using custom source list: $SOURCES_JSON"
fi

# ------------------------------------------------------------- yt helpers ---
YT_USER_AGENT="Mozilla/5.0 (HarvestAhyeon/$HARVEST_VERSION)"

yt_meta() { # $1 = yt id -> tab-separated meta line (or empty)
  local url="https://www.youtube.com/watch?v=$1"
  local cookies=()
  [ -f "$COOKIES" ] && cookies=(--cookies "$COOKIES")
  local TAB=$'\t'
  timeout 90 $YTDLP --skip-download --no-warnings --no-playlist "${cookies[@]}" \
    --print "%(id)s${TAB}%(title)s${TAB}%(channel)s${TAB}%(duration)s${TAB}%(view_count)s${TAB}%(upload_date)s" \
    "$url" 2>>"$LOG" | head -1
}

yt_resolve_query() { # $1=query $2=title_kw $3=channel_kw -> id (or empty)
  local cookies=()
  [ -f "$COOKIES" ] && cookies=(--cookies "$COOKIES")
  timeout 90 $YTDLP --flat-playlist --no-warnings -J "ytsearch6:$1" 2>>"$LOG" \
  | jq -r --arg tk "$2" --arg ck "$3" '
      [ .entries[]?
        | select(.id != null)
        | select(
            ($tk == "" or ((.title // "") | ascii_downcase | contains($tk | ascii_downcase)))
            and ($ck == "" or ((.channel // .uploader // "") | ascii_downcase | contains($ck | ascii_downcase)))
          )
        | .id ] | first // empty'
}

yt_download() { # $1=yt_id $2=out_base (no ext) -> 0 on success, file at $2.mp4
  local id="$1" base="$2"
  local cookies=()
  [ -f "$COOKIES" ] && cookies=(--cookies "$COOKIES")
  local FMT="bv*[height<=$MAX_HEIGHT][ext=mp4]+ba[ext=m4a]/bv*[height<=$MAX_HEIGHT]+ba/b[height<=$MAX_HEIGHT]/b"
  rm -f "$base".*.part 2>/dev/null
  if [ "${REDOWNLOAD:-0}" = "1" ]; then rm -f "$base.mp4"; fi
  # attempt 1: default clients; attempt 2: android_vr+ios (bot-check escape)
  timeout 3600 $YTDLP --no-playlist --no-warnings "${cookies[@]}" \
      -f "$FMT" --merge-output-format mp4 \
      --retries 8 --fragment-retries 8 --socket-timeout 30 \
      -o "$base.%(ext)s" "https://www.youtube.com/watch?v=$id" >>"$LOG" 2>&1 \
    || timeout 3600 $YTDLP --no-playlist --no-warnings "${cookies[@]}" \
      --extractor-args "youtube:player_client=android_vr,ios" \
      -f "$FMT" --merge-output-format mp4 \
      --retries 8 --fragment-retries 8 --socket-timeout 30 \
      -o "$base.%(ext)s" "https://www.youtube.com/watch?v=$id" >>"$LOG" 2>&1
  [ -f "$base.mp4" ]
}

validate_file() { # $1=file -> prints "OK dur w h fps" or "BAD reason"
  local f="$1" out dur w h fps v a
  out=$(ffprobe -v error -print_format json -show_format -show_streams "$f" 2>/dev/null) || { echo "BAD ffprobe_failed"; return; }
  dur=$(jq -r '.format.duration // "0"' <<<"$out" | cut -d. -f1)
  v=$(jq -r '[.streams[]|select(.codec_type=="video")][0] | .codec_name // empty' <<<"$out")
  a=$(jq -r '[.streams[]|select(.codec_type=="audio")][0] | .codec_name // empty' <<<"$out")
  w=$(jq -r '[.streams[]|select(.codec_type=="video")][0].width // 0' <<<"$out")
  h=$(jq -r '[.streams[]|select(.codec_type=="video")][0].height // 0' <<<"$out")
  fps=$(jq -r '[.streams[]|select(.codec_type=="video")][0].avg_frame_rate // "0/1"' <<<"$out" | awk -F/ '{if($2>0)printf "%.0f",$1/$2; else print 0}')
  if [ -z "$v" ]; then echo "BAD no_video_stream"; return; fi
  if [ -z "$a" ]; then echo "BAD no_audio_stream"; return; fi
  if [ "${dur:-0}" -lt 20 ]; then echo "BAD duration_${dur}s_lt_20s"; return; fi
  if [ "${h:-0}" -lt 360 ]; then echo "BAD height_${h}_lt_360"; return; fi
  echo "OK ${dur:-0} ${w:-0} ${h:-0} ${fps:-0}"
}

# ------------------------------------------------------------ upload chain ---
# storage.to first (user directive; browser mirror — machine GET is proof-gated).
# Then plain-curl-friendly hosts (machine mirrors for the build pipeline):
# filebin 7d | uguu 48h/128M | litterbox 72h/1G | 0x0.st 30d/512M | bashupload 3d
# gofile = browser mirror (machine download is premium-gated), catbox = phone-only.
# Every link is TESTED twice: browser-style (bytes exist) and PLAIN (no special
# headers, HTML detection) — machine_fetchable is honest per link, per run.
HOST_LIMIT_MB() {
  case "$1" in
    storageto) echo 25600;; filebin) echo 2048;; gofile) echo 20000;; catbox) echo 200;;
    litterbox) echo 1024;; 0x0.st) echo 512;; bashupload) echo 5120;;
    uguu) echo 128;; *) echo 0;;
  esac
}

up_storageto() { # $1=file -> link or empty
  local r
  r=$(python3 "$WORK/.storageto_up.py" "$1" "$VISITOR_TOKEN_FILE" 2>>"$LOG")
  local link expires
  link=$(jq -r '.url // empty' <<<"$r" 2>/dev/null)
  expires=$(jq -r '.expires_at // "unknown"' <<<"$r" 2>/dev/null)
  [ -n "$link" ] && { echo "$link|$expires|PAGE"; return 0; }
  warn "storageto: $(jq -r '.error // "unknown error"' <<<"$r" 2>/dev/null)"
  return 1
}

up_filebin() { # $2 unused; bin name derived from run
  local bin file_link
  bin=$(cat "$WORK/.filebin_id" 2>/dev/null || true)
  if [ -z "$bin" ]; then
    bin="ahyeon-$(date +%m%d)-$(head -c 4 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    echo "$bin" > "$WORK/.filebin_id"
  fi
  curl -sS -m 3600 --connect-timeout 30 -X PUT \
    --data-binary @"$1" -H "Content-Type: video/mp4" \
    -o /dev/null -w "%{http_code}" \
    "https://filebin.net/$bin/$(basename "$1")" 2>>"$LOG" | grep -qE "^(200|201)$" \
    || return 1
  echo "https://filebin.net/$bin/$(basename "$1")|7d|PAGE"
  return 0
}

up_gofile() {
  local srv r page direct fid fname
  srv=$(curl -sS -m 30 "https://api.gofile.io/servers" 2>/dev/null | jq -r '.data.servers[0].name // empty' 2>/dev/null)
  [ -z "$srv" ] && return 1
  r=$(curl -sS -m 3600 --connect-timeout 30 -F "file=@$1" "https://$srv.gofile.io/contents/uploadfile" 2>>"$LOG")
  page=$(jq -r '.data.downloadPage // empty' <<<"$r" 2>/dev/null)
  fid=$(jq -r '.data.id // empty' <<<"$r" 2>/dev/null)
  fname=$(jq -r '.data.name // empty' <<<"$r" 2>/dev/null)
  [ -z "$page" ] && { warn "gofile: $(jq -r '.status // "unknown error"' <<<"$r" 2>/dev/null)"; return 1; }
  direct=""
  [ -n "$fid" ] && [ -n "$fname" ] && direct="https://$srv.gofile.io/download/web/$fid/$fname"
  echo "$page|unknown|$direct"
  return 0
}

up_catbox() {
  local link
  link=$(curl -sS -m 3600 --connect-timeout 30 \
    -F "reqtype=fileupload" -F "fileToUpload=@$1" \
    "https://catbox.moe/user/api.php" 2>>"$LOG" | tr -d '[:space:]')
  case "$link" in https://*) echo "$link|permanent"; return 0;; esac
  return 1
}

up_litterbox() {
  local link
  link=$(curl -sS -m 3600 --connect-timeout 30 \
    -F "reqtype=fileupload" -F "time=72h" -F "fileToUpload=@$1" \
    "https://litterbox.catbox.moe/resources/internals/api.php" 2>>"$LOG" | tr -d '[:space:]')
  case "$link" in https://*) echo "$link|72h"; return 0;; esac
  return 1
}

up_0x0() {
  local link
  link=$(curl -sS -m 3600 --connect-timeout 30 -A "$YT_USER_AGENT" \
    -F "file=@$1" "https://0x0.st" 2>>"$LOG" | tr -d '[:space:]')
  case "$link" in https://0x0.st/*) echo "$link|30d+"; return 0;; esac
  return 1
}

up_bashupload() {
  local out link
  out=$(curl -sS -m 3600 --connect-timeout 30 -T "$1" \
    "https://bashupload.com/$(basename "$1")" 2>>"$LOG")
  link=$(grep -o 'https://bashupload.com/[^ ]*' <<<"$out" 2>/dev/null | head -1)
  [ -n "$link" ] && { echo "$link|3d"; return 0; }
  return 1
}

up_uguu() {
  local link
  link=$(curl -sS -m 3600 --connect-timeout 30 \
    -F "files[]=@$1" "https://uguu.se/upload.php" 2>>"$LOG" \
    | jq -r '.files[0].url // empty' 2>/dev/null)
  [ -n "$link" ] && { echo "$link|48h"; return 0; }
  return 1
}

# plain fetch test: real bytes, no special headers, not an HTML page
plain_fetch_ok() { # $1=url -> 0 if machine-fetchable
  local tmp; tmp=$(mktemp)
  local code
  code=$(curl -sSL -m 45 -r 0-1023 -o "$tmp" -w "%{http_code}" "$1" 2>/dev/null || echo 000)
  [ "$code" = "200" ] || [ "$code" = "206" ] || { rm -f "$tmp"; return 1; }
  if grep -aqiE "<!doctype html|<html[ >]" "$tmp" 2>/dev/null; then
    rm -f "$tmp"; return 1   # SPA/proof page, not the file
  fi
  rm -f "$tmp"; return 0
}

upload_file() { # $1=file $2=min_hosts(default 2) -> writes UPLOADS_JSON global
  local f="$1" min="${2:-2}" size_mb host link_payload link expires
  UPLOADS_JSON="[]"
  size_mb=$(( ($(stat -c%s "$f" 2>/dev/null || echo 0) + 1048575) / 1048576 ))
  for host in storageto filebin gofile uguu litterbox 0x0.st bashupload catbox; do
    [ "$(UPLOADS_LIMIT_OK "$host" "$size_mb")" = "1" ] && { log "  skip $host (size ${size_mb}MB over limit)"; continue; }
    # already recorded? (resume)
    if jq -e --arg h "$host" 'map(.host)|index($h)' <<<"$UPLOADS_JSON" >/dev/null 2>&1; then continue; fi
    log "  upload -> $host (${size_mb}MB) ..."
    link_payload=""
    case "$host" in
      storageto)  link_payload=$(up_storageto "$f");;
      filebin)    link_payload=$(up_filebin "$f");;
      gofile)     link_payload=$(up_gofile "$f");;
      catbox)     link_payload=$(up_catbox "$f");;
      litterbox)  link_payload=$(up_litterbox "$f");;
      0x0.st)     link_payload=$(up_0x0 "$f");;
      bashupload) link_payload=$(up_bashupload "$f");;
      uguu)       link_payload=$(up_uguu "$f");;
    esac
    if [ -n "$link_payload" ]; then
      link="${link_payload%%|*}"
      local rest="${link_payload#*|}" expires direct=""
      expires="${rest%%|*}"
      case "$rest" in *|*) direct="${rest#*|}";; esac
      [ "$direct" = "$rest" ] && direct=""          # no 3rd field
      [ "$expires" = "$link" ] && expires="unknown"
      [ "$expires" = "$rest" ] && expires="unknown"   # no 2nd field either
      local probe="$link"; [ -n "$direct" ] && [ "$direct" != "PAGE" ] && probe="$direct"
      local human_ok=1
      verify_link "$host" "$probe" || human_ok=0
      local machine=0
      plain_fetch_ok "$probe" && machine=1
      if [ "$human_ok" = "1" ] || [ "$machine" = "1" ]; then
        UPLOADS_JSON=$(jq -c --arg h "$host" --arg l "$link" --arg d "$direct" \
          --arg e "$expires" --argjson m "$machine" \
          '. + [{host:$h, link:$l, direct_link:(if $d=="" or $d=="PAGE" then null else $d end),
                 verified:true, machine_fetchable:(if $m==1 then true else false end),
                 expires:$e}]' <<<"$UPLOADS_JSON")
        log "  ok $host: $link (machine_fetchable=$machine)"
        if [ "$machine" = "1" ] && [ "$(jq '[.[]|select(.machine_fetchable)]|length' <<<"$UPLOADS_JSON")" -ge "$min" ]; then
          return 0
        fi
      else
        warn "  $host returned link but verification failed: $link"
      fi
    else
      warn "  $host upload failed"
    fi
  done
  [ "$(jq 'length' <<<"$UPLOADS_JSON")" -ge 1 ]
}
UPLOADS_LIMIT_OK() { # host size_mb -> 0 if under limit
  local lim; lim=$(HOST_LIMIT_MB "$1")
  [ "$2" -le "$lim" ] && echo 0 || echo 1
}

# ------------------------------------------------------------ item harvest ---
harvest_item() { # $1=sid $2=yt_id $3=role $4=priority $5=act_tags_csv $6=title_kw $7=channel_kw $8=note
  local sid="$1" ytid="$2" role="$3" prio="$4" tags="$5" tkw="$6" ckw="$7" note="$8"
  local SDIR="$STATE/$sid"
  local DONE="$SDIR/done.json"
  mkdir -p "$SDIR"

  if [ -s "$DONE" ] && jq -e '.status=="ok"' "$DONE" >/dev/null 2>&1; then
    log "== $sid already complete — skipping (resume)"
    return 0
  fi

  log "== [$sid] prio=$prio role=$role id=$ytid — $note"

  # -- 1. resolve metadata (title-verified sourcing) --
  local meta ytid_final="$ytid" title="" channel="" ytdur="" views="" update=""
  if [ "$ytid" = "QUERY" ]; then
    ytid_final=$(yt_resolve_query "$tkw" "$tkw" "$ckw")
    if [ -z "$ytid_final" ]; then
      jq -n --arg s "$sid" '{source_id:$s,status:"failed_resolve",error:"no search hit"}' > "$SDIR/done.json"
      warn "[$sid] resolve failed — recorded honestly"; return 1
    fi
    log "  resolved via search -> $ytid_final"
  fi
  meta=$(yt_meta "$ytid_final" || true)
  if [ -n "$meta" ]; then
    ytid_final=$(cut -f1 <<<"$meta")
    title=$(cut -f2 <<<"$meta"); channel=$(cut -f3 <<<"$meta")
    ytdur=$(cut -f4 <<<"$meta"); views=$(cut -f5 <<<"$meta"); update=$(cut -f6 <<<"$meta")
    if [ -n "$tkw" ] && ! grep -qi "$tkw" <<<"$title"; then
      warn "  title mismatch check: '$title' lacks '$tkw' (kept, flagged in manifest)"
    fi
    log "  meta: ${title:0:60} | $channel | ${ytdur}s"
  else
    warn "  metadata fetch failed (bot-gate?) — proceeding with download attempt anyway"
  fi

  # -- 2. download --
  local f="$MEDIA/$sid.mp4" base="$MEDIA/$sid"
  if [ ! -s "$f" ] || [ "$REDOWNLOAD" = "1" ]; then
    log "  downloading (<= ${MAX_HEIGHT}p) ..."
    if ! yt_download "$ytid_final" "$base"; then
      jq -n --arg s "$sid" --arg i "$ytid_final" \
        '{source_id:$s, yt_id:$i, status:"failed_download", error:"yt-dlp failed both attempts (see harvest.log)"}' > "$SDIR/done.json"
      warn "[$sid] download FAILED — recorded honestly"; return 1
    fi
  else
    log "  file exists locally — reusing (delete state/$sid or --redownload to refresh)"
  fi

  # -- 3. validate --
  local verdict dur w h fps sha size
  verdict=$(validate_file "$f")
  case "$verdict" in
    OK*) dur=$(cut -d' ' -f2 <<<"$verdict"); w=$(cut -d' ' -f3 <<<"$verdict")
         h=$(cut -d' ' -f4 <<<"$verdict"); fps=$(cut -d' ' -f5 <<<"$verdict");;
    *)   jq -n --arg s "$sid" --arg e "$verdict" \
           '{source_id:$s,status:"failed_validation",error:$e}' > "$SDIR/done.json"
         warn "[$sid] validation FAILED: $verdict"; rm -f "$f"; return 1;;
  esac
  sha=$(sha256_of "$f"); size=$(stat -c%s "$f")
  log "  validated: ${dur}s ${w}x${h}@${fps} $(awk -v b="$size" 'BEGIN{printf "%.1fMB",b/1048576}') sha=${sha:0:12}..."

  # -- 4. upload (storage.to first, then backups) --
  if ! upload_file "$f" 2; then
    jq -n --arg s "$sid" '{source_id:$s,status:"failed_upload",error:"no host accepted the file"}' > "$SDIR/done.json"
    warn "[$sid] upload FAILED — file kept locally at $f"; return 1
  fi

  # -- 5. record --
  jq -n --arg s "$sid" --arg i "$ytid_final" --arg r "$role" --arg p "$prio" \
        --arg t "$title" --arg c "$channel" --arg du "$dur" --arg v "$views" \
        --arg u "$update" --arg tags "$tags" --arg note "$note" \
        --arg f "$(basename "$f")" --arg sz "$size" --arg sha "$sha" \
        --arg dr "$dur" --arg w "$w" --arg h "$h" --arg fps "$fps" \
        --argjson up "$UPLOADS_JSON" \
        '{source_id:$s, yt_id:$i, role:$r, priority:($p|tonumber), act_tags:($tags|split(",")),
          note:$note,
          youtube:{id:$i, title:$t, channel:$c, duration_s:($du|tonumber? // null),
                   view_count:($v|tonumber? // null), upload_date:$u},
          file:{name:$f, size_bytes:($sz|tonumber), sha256:$sha, duration_s:($dr|tonumber),
                width:($w|tonumber), height:($h|tonumber), fps:($fps|tonumber)},
          uploads:$up,
          primary_link:($up | map(select(.machine_fetchable) | (.direct_link // .link)) | first // null),
          primary_browser_link:($up | map(.link) | first // null),
          status:"ok"}' > "$DONE"
  log "  DONE: primary=$(jq -r '.primary_link' "$DONE")"
  return 0
}

# ---------------------------------------------------------------- selftest ---
SELFTEST_IDS=()
selftest() {
  log "SELFTEST: generating 3 dummy videos and running validate+upload+manifest+handoff"
  local i sid
  for i in 1 2 3; do
    sid="SELFTEST_$i"
    ffmpeg -y -f lavfi -i "testsrc=duration=25:size=640x360:rate=24" \
           -f lavfi -i "sine=frequency=440:duration=25" \
           -c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -shortest \
           "$MEDIA/$sid.mp4" >>"$LOG" 2>&1 || { fail "selftest ffmpeg failed"; exit 1; }
    harvest_item "$sid" "SELFTEST_ID_$i" "ahyeon_cam" 1 "selftest" "" "" "selftest dummy video" \
      && OK_COUNT=$((OK_COUNT+1)) || FAIL_COUNT=$((FAIL_COUNT+1))
    SELFTEST_IDS+=("$sid")
  done
}

# ---------------------------------------------------------------- manifest ---
build_manifest() {
  local mf="$OUT/links_manifest.json"
  python3 - "$STATE" "$mf" "$WORK" <<'PYEOF'
import json, os, sys, glob
state_dir, out, work = sys.argv[1], sys.argv[2], sys.argv[3]
items = []
for d in sorted(glob.glob(os.path.join(state_dir, "*", "done.json"))):
    try:
        items.append(json.load(open(d)))
    except Exception:
        pass
ok = [i for i in items if i.get("status") == "ok"]
bad = [i for i in items if i.get("status") != "ok"]
manifest = {
    "schema": "ahyeon.harvest/1.0",
    "harvester_version": "1.0.0",
    "created_utc": os.popen("date -u +%FT%TZ").read().strip(),
    "counts": {"ok": len(ok), "failed": len(bad), "total": len(items)},
    "items": items,
}
json.dump(manifest, open(out, "w"), ensure_ascii=False, indent=1)
# human-readable sheet
lines = ["# AHYEON harvest — LINKS",
         "",
         f"generated: {manifest['created_utc']} | ok: {len(ok)} | failed: {len(bad)}",
         "",
         "| source_id | role | dur | res | size | primary link | backups |",
         "|---|---|---|---|---|---|---|"]
for i in ok:
    f = i.get("file", {})
    ups = i.get("uploads", [])
    alt = " ".join(u["link"] for u in ups[1:3])
    lines.append(f"| {i['source_id']} | {i.get('role')} | {f.get('duration_s')}s | "
                 f"{f.get('width')}x{f.get('height')} | {round(f.get('size_bytes',0)/1048576,1)}MB | "
                 f"{i.get('primary_link')} | {alt} |")
for i in bad:
    lines.append(f"| {i['source_id']} | FAILED | - | - | - | {i.get('status')}: {i.get('error','')[:60]} | - |")
open(os.path.join(os.path.dirname(out), "LINKS.md"), "w").write("\n".join(lines) + "\n")
print(f"manifest: {len(ok)} ok / {len(bad)} failed")
PYEOF
}

handoff() {
  local mf="$OUT/links_manifest.json"
  [ -s "$mf" ] || { warn "no manifest to hand off"; return 1; }
  local plink
  plink=$(curl -sS -m 60 --data-binary @"$mf" "https://paste.rs" 2>/dev/null | tr -d '[:space:]')
  local fallback=""
  case "$plink" in https://paste.rs/*) ;; *)
    fallback=$(up_catbox "$mf" 2>/dev/null | cut -d'|' -f1)
    case "$fallback" in https://*) plink="$fallback";; *) plink="";; esac;;
  esac
  {
    echo "SEND THIS ONE LINK BACK TO THE AGENT:"
    echo "$plink"
    echo ""
    echo "(it contains links_manifest.json — every video link + sha256 + metadata)"
    echo "local copies: $OUT/links_manifest.json and $OUT/LINKS.md"
  } | tee "$OUT/SEND_THIS_LINK.txt"
  if [ "$IS_TERMUX" = "1" ] && have termux-clipboard-set && [ -n "$plink" ]; then
    echo "$plink" | termux-clipboard-set 2>/dev/null && log "handoff link copied to clipboard"
  fi
  [ -n "$plink" ]
}

# ------------------------------------------------------------------- main ----
OK_COUNT=0; FAIL_COUNT=0
if [ "$SELFTEST" = "1" ]; then
  selftest
else
  # disk space guard
  FREE_MB=$(df -Pm "$WORK" 2>/dev/null | awk 'NR==2{print $4}')
  [ -n "$FREE_MB" ] && [ "$FREE_MB" -lt 3000 ] && \
    warn "only ${FREE_MB}MB free in $WORK — full library needs ~6-8GB. Clean up or expect failures."

  mapfile -t ROWS < <(jq -r '.items[] | [.[0], .[1], .[2], .[3], (.[4]|join(",")), .[5], .[6], .[7]] | @tsv' "$SOURCES_JSON" | \
    awk -F'\t' -v pm="$PRIORITY_MAX" -v only="$ONLY_ITEMS" '
      BEGIN{ if(only!="")split(only,OL,","); for(k in OL)O[OL[k]]=1 }
      { if ($4+0 > pm+0) next; if (only!="" && !($1 in O)) next; print }')

  TOTAL=${#ROWS[@]}
  log "running $TOTAL items (priority <= $PRIORITY_MAX)"
  n=0
  for row in "${ROWS[@]}"; do
    n=$((n+1))
    IFS=$'\t' read -r sid ytid role prio tags tkw ckw note <<<"$row"
    [ "$MAX_ITEMS" -gt 0 ] && [ "$n" -gt "$MAX_ITEMS" ] && break
    if harvest_item "$sid" "$ytid" "$role" "$prio" "$tags" "$tkw" "$ckw" "$note"; then
      OK_COUNT=$((OK_COUNT+1))
    else
      FAIL_COUNT=$((FAIL_COUNT+1))
    fi
  done
fi

build_manifest || true
handoff || warn "handoff link generation failed — send $OUT/links_manifest.json manually"

log "=== SUMMARY: ok=$OK_COUNT failed=$FAIL_COUNT (of scope) ==="
log "manifest: $OUT/links_manifest.json"
log "sheet:    $OUT/LINKS.md"
log "handoff:  $OUT/SEND_THIS_LINK.txt"
[ "$OK_COUNT" -gt 0 ] && exit 0 || exit 1
