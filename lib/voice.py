#!/usr/bin/env python3
"""voice.py — narration providers for vfactory.

Providers:
  zai:<voice>    z-ai TTS (default voice: tongtong). WAV out. CJK-strong.
                 Long text is chunked per ~2 sentences; word timings are
                 approximated from chunk durations.
  edge:<voice>   Microsoft neural voices via edge-tts (online). MP3 -> WAV 48k.
                 Real word-level timestamps from WordBoundary events.

Voice presets (documentary casting):
  edge:en-US-ChristopherNeural   deep American male (classic doc)
  edge:en-US-EricNeural          warm American male
  edge:en-GB-RyanNeural          British male (BBC feel)
  edge:en-US-AriaNeural          American female
  edge:ko-KR-InJoonNeural        Korean male
  edge:zh-CN-YunjianNeural       Chinese male (deep)
  zai:tongtong                   Chinese female (default)

All synth() calls return dict: {path, duration, words: [{w,t0,t1}], provider,
approx: bool}. On provider failure, falls back to zai:tongtong.
"""
import asyncio
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import zai  # noqa: E402

DEFAULT = "zai:tongtong"
FALLBACK = "zai:tongtong"
ZAI_CHUNK_WORDS = 45  # z-ai TTS chunk size (words) for long texts


def audio_len(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _split_chunks(text, max_words=ZAI_CHUNK_WORDS):
    sents = re.split(r'(?<=[.!?。！？])\s+', text.strip())
    chunks, cur, n = [], [], 0
    for s in sents:
        w = len(s.split())
        if cur and n + w > max_words:
            chunks.append(" ".join(cur))
            cur, n = [], 0
        cur.append(s)
        n += w
    if cur:
        chunks.append(" ".join(cur))
    return chunks or [text.strip()]


# ------------------------------------------------------------------ z-ai ----
def _zai_synth(text, out_wav, voice, speed):
    """z-ai TTS; chunk long text and concat. Word timings approximated."""
    tmp_dir = out_wav + ".parts"
    os.makedirs(tmp_dir, exist_ok=True)
    chunks = _split_chunks(text)
    words = []
    t_cursor = 0.0
    ok = True
    for i, ch in enumerate(chunks):
        part = os.path.join(tmp_dir, f"p{i:02d}.wav")
        if not (os.path.exists(part) and os.path.getsize(part) > 1000):
            if not zai.tts(ch, part, voice=voice, speed=speed, fmt="wav"):
                ok = False
                break
        d = audio_len(part)
        # proportional word allocation inside chunk
        wlist = ch.split()
        if wlist and d > 0:
            per = d / len(wlist)
            for j, w in enumerate(wlist):
                words.append({"w": w, "t0": round(t_cursor + j * per, 3),
                              "t1": round(t_cursor + (j + 1) * per, 3)})
        t_cursor += d
    if not ok:
        return None
    if len(chunks) == 1:
        os.replace(os.path.join(tmp_dir, "p00.wav"), out_wav)
    else:
        lst = os.path.join(tmp_dir, "list.txt")
        with open(lst, "w") as fh:
            for i in range(len(chunks)):
                fh.write(f"file 'p{i:02d}.wav'\n")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", lst, "-c", "copy", out_wav],
                       capture_output=True, timeout=120, check=True)
    dur = audio_len(out_wav)
    return {"path": out_wav, "duration": round(dur, 3), "words": words,
            "provider": f"zai:{voice}", "approx": True}


# ---------------------------------------------------------------- edge ----
def _edge_synth(text, out_wav, voice, speed):
    import edge_tts  # lazy import

    async def _run():
        rate = f"{int(round((speed - 1.0) * 100)):+d}%"
        c = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
        mp3 = out_wav + ".src.mp3"
        words, audio = [], b""
        async for chunk in c.stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
            elif chunk["type"] == "WordBoundary":
                words.append({"w": chunk["text"],
                              "t0": round(chunk["offset"] / 1e7, 3),
                              "t1": round((chunk["offset"] + chunk["duration"]) / 1e7, 3)})
        with open(mp3, "wb") as f:
            f.write(audio)
        return words, mp3

    words, mp3 = asyncio.run(_run())
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp3,
                    "-ar", "48000", "-ac", "2", out_wav],
                   capture_output=True, timeout=300, check=True)
    os.remove(mp3)
    dur = audio_len(out_wav)
    return {"path": out_wav, "duration": round(dur, 3), "words": words,
            "provider": f"edge:{voice}", "approx": False}


# ----------------------------------------------------------------- api ----
def synth(text, out_wav, voice=None, speed=1.0, retries=2):
    """Synthesize narration -> wav + word timings. Falls back on failure."""
    text = " ".join(text.split())
    voice = voice or DEFAULT
    provider, _, vname = voice.partition(":")
    vname = vname or DEFAULT.split(":", 1)[1]
    last_err = None
    for attempt in range(retries + 1):
        try:
            if provider == "edge":
                return _edge_synth(text, out_wav, vname, speed)
            return _zai_synth(text, out_wav, vname, speed)
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"voice: provider {voice} failed ({last_err}); falling back to {FALLBACK}")
    return _zai_synth(text, out_wav, FALLBACK.split(":", 1)[1], speed)


PRESETS = {
    "doc_male_us": "edge:en-US-ChristopherNeural",
    "doc_male_uk": "edge:en-GB-RyanNeural",
    "doc_female_us": "edge:en-US-AriaNeural",
    "warm_male_us": "edge:en-US-EricNeural",
    "kr_male": "edge:ko-KR-InJoonNeural",
    "cn_male": "edge:zh-CN-YunjianNeural",
    "cn_female": "zai:tongtong",
}


def resolve(name):
    """Preset name, provider string, or None -> default."""
    if not name:
        return DEFAULT
    return PRESETS.get(name, name)


if __name__ == "__main__":
    out = "/tmp/voice_test.wav"
    for v in ("edge:en-US-ChristopherNeural", "zai:tongtong"):
        r = synth("Ahyeon's return redefined BABYMONSTER's sound. Seven years of training became seven minutes of pure vocal dominance.",
                  out, voice=v, speed=1.0)
        print(v, "->", r["provider"], f"{r['duration']}s", "words:", len(r["words"]),
              "approx:", r["approx"])
