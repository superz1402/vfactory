#!/usr/bin/env python3
"""Stage 4 (smart): entity-aware scene direction.

The doctrine (AGENT.md §Scene Doctrine):
  The screen must show WHAT the narrator is saying, WHEN they say it.
  - Word-level alignment: faster-whisper timestamps the narrated audio.
  - Anchor words: each scene declares visual spans with an anchor word
    (e.g. the shot for BLACKPINK must start when "BLACKPINK" is spoken).
  - Entity-accurate footage: every library clip carries entity tags from
    its authoritative source title (who/what is actually in it).
  - Matcher: picks a clip whose tags cover the span entity, with
    variety (no immediate repeats) and deterministic in-point selection.

Outputs: <run>/04_smart/timeline.json
"""
import json, os, subprocess, sys, hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

GAP = 0.35       # silence between scenes in narration_full.wav
LEAD = 0.30      # cut this many seconds BEFORE the anchor word is spoken
FPS = 30
W, H = 1920, 1080

SCENE_GAP_SAMPS = None  # computed


def sh(cmd, timeout=300):
    import os as _os
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            _os.killpg(_os.getpgid(p.pid), 15)
        except Exception:
            pass
        try:
            out, err = p.communicate(timeout=8)
        except Exception:
            out, err = "", ""
        return -9, out or "", err or ""


def ffprobe_dur(path):
    rc, out, _ = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=30)
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def concat_narration(run_dir):
    """Concat scene WAVs with GAP silence; return narration_full.wav + scene bounds."""
    timings = json.load(open(os.path.join(run_dir, "03_timings.json")))["timings"]
    out_dir = os.path.join(run_dir, "04_smart")
    os.makedirs(out_dir, exist_ok=True)
    full = os.path.join(out_dir, "narration_full.wav")
    bounds, acc = {}, 0.0
    inputs, fparts = [], []
    for i, t in enumerate(sorted(timings, key=lambda x: x["id"])):
        wav = t["wav"] if os.path.isabs(t["wav"]) else os.path.join("/home/z/my-project", t["wav"])
        inputs += ["-i", wav]
        bounds[t["id"]] = {"start": round(acc, 3), "dur": t["audio"]}
        acc += t["audio"] + GAP
        fparts.append(f"[{i}:a]aformat=channel_layouts=stereo,aresample=48000[a{i}]")
        fparts.append(f"anullsrc=channel_layout=stereo:sample_rate=48000,atrim=0:{GAP},asetpts=PTS-STARTPTS[g{i}]")
    n = len(timings)
    mix = "".join(f"[a{i}][g{i}]" for i in range(n))
    fparts.append(f"{mix}concat=n={2*n}:v=0:a=1[out]")
    cmd = (["ffmpeg", "-y", "-v", "error"] + inputs +
           ["-filter_complex", ";".join(fparts), "-map", "[out]", "-ar", "48000", full])
    rc, _, err = sh(cmd, timeout=180)
    if rc != 0 or not os.path.exists(full):
        raise RuntimeError(f"narration concat failed: {err[-300:]}")
    return full, bounds


def word_timestamps(wav, cache=None):
    """faster-whisper word timestamps on the narration track.

    Audio is decoded via ffmpeg to 16k mono float32 and passed as a numpy
    array (bypasses PyAV, whose API drift breaks decode_audio).
    Results are cached to <run>/04_smart/words.json (whisper is deterministic
    for identical audio; re-transcribing on every resume caused timeline
    drift against cached shot renders)."""
    if cache and os.path.exists(cache):
        return json.load(open(cache))
    import numpy as np
    from faster_whisper import WhisperModel
    import subprocess as _sp
    r = _sp.run(["ffmpeg", "-v", "error", "-i", str(wav),
                 "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                capture_output=True, timeout=120)
    if r.returncode != 0 or not r.stdout:
        raise RuntimeError(f"audio decode failed: {r.stderr[-200:]}")
    audio = np.frombuffer(r.stdout, dtype=np.float32)
    model = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)
    segments, info = model.transcribe(audio, word_timestamps=True, language="en",
                                      vad_filter=False, beam_size=3)
    words = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"w": (w.word or "").strip().lower(), "start": round(w.start, 3),
                          "end": round(w.end, 3)})
    return words


def norm(w):
    """Collapse variants: 'black pink'/'blackpink'/'blackpink's' -> 'blackpink'."""
    return "".join(ch for ch in w.lower() if ch.isalnum())


def find_anchor(words, lo, hi, anchor):
    """Find anchor in [lo,hi) against the CONCATENATED normalized token stream.

    Whisper splits names across tokens ('baby'+'monster', 'ah'+'yahn') and
    misspells names ('ahyahn'); joining the window then searching (exact
    first, fuzzy >=0.78 fallback) catches both. Returns the token whose
    start contains the match (the moment the word BEGINS being spoken)."""
    import difflib
    a = norm(anchor)
    if not a:
        return None
    toks = [(norm(w["w"]), w["start"]) for w in words if lo <= w["start"] < hi]
    joined = "".join(t[0] for t in toks)
    if not joined:
        return None
    idx = joined.find(a)
    if idx == -1 and len(a) >= 4:
        best = (-1.0, -1)
        for i in range(0, max(1, len(joined) - len(a) + 1)):
            chunk = joined[i:i + len(a)]
            r = difflib.SequenceMatcher(None, chunk, a).ratio()
            if r > best[0]:
                best = (r, i)
        if best[0] >= 0.78:
            idx = best[1]
    if idx == -1:
        return None
    pos = 0
    for t, st in toks:
        if pos <= idx < pos + max(len(t), 1):
            return {"w": t, "start": st, "end": st}
        pos += len(t)
    return None


def load_library():
    lib = json.load(open("/home/z/my-project/footage/library.json"))["clips"]
    return {c["clip_id"]: c for c in lib if os.path.exists(c.get("file", ""))}


def entities_cover(clip_entities, want):
    return want in clip_entities


def pick_in_point(clip, shot_dur, shot_idx, span_entity):
    """Deterministic, varied in-point. Prefer the middle 60% of the source
    (intros/outros of MVs tend to be static logos)."""
    d = clip["duration"] or 0.0
    if d <= shot_dur + 1.0:
        return 0.0
    usable_start = d * 0.15
    usable_len = d * 0.70
    max_start = max(0.0, d - shot_dur - 0.2)
    h = int(hashlib.md5(f"{clip['clip_id']}:{shot_idx}:{span_entity}".encode()).hexdigest(), 16)
    # try to land inside usable window, never past the end
    raw = usable_start + (h % 1000) / 1000.0 * usable_len
    return round(min(raw, max_start), 2)


def match_span(span, scene_id, shot_idx, library, used_recent, hints):
    """Choose the best clip for an entity span.
    1) span-level clip lock (authoritative: 'screen MUST be this footage')
    2) pinned entity hints, 3) any entity-covering clip. Variety respected
    unless a lock forces reuse."""
    lock = span.get("clip")
    if lock:
        c = library.get(lock)
        if c:
            return c
    want = span["entity"]
    pinned = hints.get(want, [])
    for cid in pinned:
        c = library.get(cid)
        if c and (cid not in used_recent or len(used_recent) >= len(library)):
            return c
    for cid, c in sorted(library.items()):
        if entities_cover(c["entities"], want) and (cid not in used_recent or len(used_recent) >= len(library)):
            return c
    # last resort: ignore recency
    for cid in pinned:
        if cid in library:
            return library[cid]
    for cid, c in sorted(library.items()):
        if entities_cover(c["entities"], want):
            return c
    return None


def build_timeline(run_dir, plan, words, bounds, library):
    shots, scene_map = [], []
    t_cursor = 0.0
    used_recent = []          # last used clip_ids (variety)
    total_narr = bounds[max(bounds)]["start"] + bounds[max(bounds)]["dur"]
    hints = plan.get("clip_hints", {})
    prev_clip = None
    for sc in plan["scenes"]:
        sid = sc["id"]
        sb = bounds[sid]
        s_start, s_dur = sb["start"], sb["dur"]
        scene_end = s_start + s_dur + GAP
        spans = sc.get("visual", [{"entity": sc.get("visual_entity", "ahyeon_solo"),
                                   "anchor": None}])
        scene_shots = []
        cut_times = [s_start]
        span_of_cut = []
        for sp in spans:
            if sp.get("anchor"):
                anchors = sp["anchor"] if isinstance(sp["anchor"], list) else [sp["anchor"]]
                wd = None
                for a in anchors:
                    wd = find_anchor(words, s_start - 0.5, scene_end, a)
                    if wd:
                        break
                if wd:
                    cut = max(s_start + 0.2, wd["start"] - LEAD)
                    if cut > cut_times[-1] + 0.8:      # avoid micro-shots
                        cut_times.append(round(cut, 3))
                        span_of_cut.append(sp)
        for i, ct in enumerate(cut_times):
            end = cut_times[i + 1] if i + 1 < len(cut_times) else scene_end
            sp = span_of_cut[i - 1] if i > 0 else spans[0]
            dur = round(end - ct, 3)
            if dur < 0.6:
                continue
            clip = match_span(sp, sid, i, library, used_recent, hints)
            if not clip:
                raise RuntimeError(f"scene {sid} span {i}: no clip for entity {sp['entity']}")
            if clip["clip_id"] in used_recent:
                used_recent.remove(clip["clip_id"])
            used_recent.append(clip["clip_id"])
            used_recent = used_recent[-3:]
            in_pt = sp.get("in_point")
            if in_pt is not None:
                in_pt = round(max(0.0, min(float(in_pt),
                                            (clip["duration"] or 0.0) - dur - 0.5)), 2)
                if in_pt < 0:
                    in_pt = 0.0
            else:
                in_pt = pick_in_point(clip, dur, len(shots), sp["entity"])
            # same clip back-to-back: never replay overlapping content —
            # continue where the previous shot stopped (documentary habit)
            if shots and shots[-1]["clip"] == clip["clip_id"]:
                prev_end = shots[-1]["in_point"] + shots[-1]["dur"]
                if in_pt < prev_end and (in_pt + dur) > shots[-1]["in_point"]:
                    max_start = max(0.0, (clip["duration"] or 0.0) - dur - 0.2)
                    in_pt = round(min(prev_end, max_start), 2)
            shots.append({"start": round(t_cursor, 3), "end": round(t_cursor + dur, 3),
                          "dur": dur, "narr_start": ct, "narr_end": end,
                          "scene": sid, "span_index": i, "entity": sp["entity"],
                          "clip": clip["clip_id"], "file": clip["file"],
                          "in_point": in_pt, "punch": ("in" if len(shots) % 2 == 0 else "out")})
            prev_clip = clip["clip_id"]
            t_cursor += dur
        scene_map.append({"scene": sid, "t_start": s_start, "shots": [s for s in shots if s["scene"] == sid]})
    # hold the last shot a beat past narration for a clean fade-out
    if shots:
        shots[-1]["end"] = round(shots[-1]["end"] + 1.2, 3)
        shots[-1]["dur"] = round(shots[-1]["end"] - shots[-1]["start"], 3)
        t_cursor = shots[-1]["end"]
    return {"fps": FPS, "w": W, "h": H, "gap": GAP, "lead": LEAD,
            "narration_total": round(total_narr + GAP, 2),
            "video_total": round(t_cursor, 2),
            "narration_wav": os.path.join(run_dir, "04_smart", "narration_full.wav"),
            "scene_bounds": bounds, "shots": shots}


def run(run_dir):
    plan = json.load(open(os.path.join(run_dir, "02_script.json")))
    full, bounds = concat_narration(run_dir)
    print(f"narration_full.wav: {ffprobe_dur(full):.2f}s")
    words = word_timestamps(full, cache=os.path.join(run_dir, "04_smart", "words.json"))
    print(f"whisper words: {len(words)}")
    json.dump(words, open(os.path.join(run_dir, "04_smart", "words.json"), "w"), indent=1)
    library = load_library()
    print(f"library clips: {len(library)} -> {list(library)}")
    tl = build_timeline(run_dir, plan, words, bounds, library)
    out = os.path.join(run_dir, "04_smart", "timeline.json")
    json.dump(tl, open(out, "w"), indent=1)
    print(f"timeline: {len(tl['shots'])} shots, video_total={tl['video_total']}s -> {out}")
    for s in tl["shots"]:
        print(f"  t{s['start']:7.2f}-{s['end']:7.2f} {s['entity']:22s} <- {s['clip']} @ {s['in_point']:.1f}s")
    return tl


if __name__ == "__main__":
    run(sys.argv[1])
