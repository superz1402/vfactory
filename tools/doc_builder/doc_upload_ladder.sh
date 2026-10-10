#!/bin/bash
# Upload ladder for the 93.5MB final doc
F="/home/z/my-project/vfactory/runs/ahyeon-doc-v3/final.mp4"
echo "== 1: storage.to fresh token =="
rm -f /home/z/my-project/vfactory/.visitor_token
cd /home/z/my-project && timeout 500 python3 scripts/doc_upload.py 2>&1 | tail -8 && exit 0
echo "== 2: 0x0.st =="
timeout 500 curl -s -F "file=@$F" https://0x0.st && exit 0
echo "== 3: litterbox 72h =="
timeout 500 curl -s -F "reqtype=fileupload" -F "time=72h" -F "fileToUpload=@$F" https://litterbox.catbox.moe/resources/internals/api.php && exit 0
echo "== 4: uguu =="
timeout 500 curl -s -F "files[]=@$F" https://uguu.se/upload | head -c 400 && exit 0
echo "== 5: tmpfiles =="
timeout 500 curl -s -F "file=@$F" https://tmpfiles.org/api/v1/upload | head -c 400
