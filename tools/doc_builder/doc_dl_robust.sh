#!/bin/bash
# Robust per-file download: timeout-guarded ytagent with retries
set -u
export PATH="/home/z/my-project/venv-cce/bin:$PATH"
DL="/home/z/my-project/ytdl-agent/downloads"
for id in "$@"; do
  [ -f "$DL/$id.mp4" ] && [ -s "$DL/$id.mp4" ] && { echo "SKIP $id"; continue; }
  ok=0
  for try in 1 2; do
    echo "=== $id try$try $(date +%H:%M:%S) ==="
    timeout "${TMO:-150}" ytagent download "https://www.youtube.com/watch?v=$id" --out-dir "$DL" 2>&1 | grep -E "(SUCCESS|download ok|ERROR|FAIL)" | tail -2
    [ -f "$DL/$id.mp4" ] && [ -s "$DL/$id.mp4" ] && { ok=1; break; }
  done
  [ $ok -eq 0 ] && echo "FAIL $id"
done
echo "=== BATCH DONE $(date +%H:%M:%S) ==="
