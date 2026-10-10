#!/bin/bash
# Batch download via ytagent (cobalt/POT chain). Usage: bash doc_ytagent_dl.sh <phase>
# phase a = short Ahyeon stages/fancams | phase b = documentary episodes
set -u
export PATH="/home/z/my-project/venv-cce/bin:$PATH"
DL="/home/z/my-project/ytdl-agent/downloads"

if [ "${1:-a}" = "a" ]; then
  IDS=(MsOOG4Q5HvQ 1TYYOw-815A hSgMTFImB7c e3U5Cz_ZASU ItDZsiOhG6M OMeeqIge53E 6BVnhqQ28Vw 8l5q7ZmZN-s)
else
  IDS=(UESsLN8i63w hCgZqFscMp0 Gi0ezbc0OwU 6ha4zBqRkUE Kxb0aUqmex0 YGG3936Bt2c Am2NBfQ3I2g 4pcmRcjMhvc mO9VkglQKgg)
fi

for id in "${IDS[@]}"; do
  if [ -f "$DL/$id.mp4" ] && [ -s "$DL/$id.mp4" ]; then echo "SKIP $id"; continue; fi
  echo "=== $id $(date +%H:%M:%S) ==="
  ytagent download "https://www.youtube.com/watch?v=$id" --out-dir "$DL" 2>&1 | tail -2
done
echo "=== DONE $(date +%H:%M:%S) ==="
ls -la "$DL" | grep -E "\.mp4" | tail -20
