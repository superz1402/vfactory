#!/usr/bin/env python3
"""Narration TTS for the Ahyeon documentary (edge-tts, en-US-ChristopherNeural)."""
import asyncio, json, os, subprocess, sys

RUN = "/home/z/my-project/vfactory/runs/ahyeon-doc-v3"
SEGDIR = os.path.join(RUN, "tts")
os.makedirs(SEGDIR, exist_ok=True)

import edge_tts

SEGS = [
    ("s1", "In 2018, an eleven year old girl walked into YG Entertainment — the company behind 2NE1 and BLACKPINK. Her name, was Jung Ahyeon."),
    ("s2", "Five years in the company's practice rooms. Then, in 2023, YG did what no major label had done before. It put its next girl group on trial — in public. Seven trainees. Seven solo missions. And a debut that could disappear, overnight."),
    ("s3", "Ahyeon's audition was a song called Dangerously. The internet did the rest — nearly eighty million views, a stamp of approval from Charlie Puth, and a place in BABYMONSTER."),
    ("s4", "But when BABYMONSTER finally debuted in November 2023... she wasn't on the stage. Health issues forced her out of the lineup, and the group walked its first months as six."),
    ("s5", "In January 2024, YG announced her return. By April — SHEESH — the seven were finally complete. And Ahyeon came back with proof: vampire, live with a band, nothing to hide behind."),
    ("s6", "Then the stages grew. Monster, under an open sky. Golden, on an award show main stage. Each performance answering the question the hiatus had left open."),
    ("s7", "By 2026, the numbers were historic. Ten billion YouTube views. Four hundred million for their debut single. And a second world tour, underway."),
    ("s8", "And in Seoul, on home turf, the cameras found her where she always belonged. Center stage. Sold out. Nothing left to prove."),
    ("s9", "The girl who walked in at eleven, had become the voice they built the group around. This is Jung Ahyeon. And this... is only the beginning."),
]

VOICE = "en-US-ChristopherNeural"
RATE = "-6%"

async def synth():
    out = []
    for sid, text in SEGS:
        mp3 = os.path.join(SEGDIR, f"{sid}.mp3")
        wav = os.path.join(SEGDIR, f"{sid}.wav")
        if not os.path.exists(mp3):
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(mp3)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3,
                        "-ar", "48000", "-ac", "2", wav], check=True)
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                  "format=duration", "-of", "csv=p=0", wav],
                                 capture_output=True, text=True).stdout.strip())
        out.append({"id": sid, "text": text, "audio": wav, "dur": round(d, 3)})
        print(f"{sid}: {d:.2f}s  ({len(text.split())} words)")
    json.dump({"voice": VOICE, "rate": RATE, "timings": out},
              open(os.path.join(RUN, "03_timings.json"), "w"), indent=1)
    total = sum(t["dur"] for t in out)
    print(f"TOTAL narration: {total:.1f}s")

asyncio.run(synth())
