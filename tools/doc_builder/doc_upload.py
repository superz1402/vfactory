#!/usr/bin/env python3
"""Upload final doc to storage.to and print the public URL."""
import sys, json
sys.path.insert(0, "/home/z/my-project/vfactory")
from lib.storageto import upload

PATH = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3/final.mp4"
r = upload(PATH)
print(json.dumps(r, indent=1))
