#!/usr/bin/env python3
"""align.py — narration-to-shot alignment (round-6 requirement).

"If the narration says BLACKPINK the screen should show BLACKPINK."

Inputs: a chapter's shots (each carries its sourcing query) and the chapter's
word timings (exact for edge voices). Each shot's query yields entity keywords;
the first spoken occurrence of any keyword anchors that shot's cut to the
moment the subject is being talked about (with a small lead-in). Shots with no
spoken anchor become b-roll and fill the remaining gaps.

Output: same shots list, with `dur` recomputed so that
  sum(durs) - xfade*(n-1) == audio + tail
guaranteeing the chapter still muxes cleanly.
"""
import re

STOP = set("""a an the of in on at to for with from by and or is are was were be
been being it its this that these those as into about during after before over
under new old photo picture image closeup close-up group members member all
hd wallpaper official video mv stage performance concert montage clip scene
shot view people person""".split())

LEAD = 0.35     # cut slightly before the word is spoken
MIN_SHOT = 2.6  # never cut faster than this


def _tokens(words):
    out = []
    for w in words:
        tok = re.sub(r"[^a-z0-9']", "", w["w"].lower())
        if tok:
            out.append((tok, w["t0"]))
    return out


def _keywords(query):
    ks = [t for t in re.sub(r"[^a-z0-9' ]", " ", query.lower()).split()
          if t not in STOP and len(t) > 2]
    return ks or [w for w in re.sub(r"[^a-z0-9' ]", " ", query.lower()).split() if w]


def anchor_times(shots, words):
    """shot index -> spoken anchor time (or None)."""
    toks = _tokens(words)
    anchors = {}
    for i, s in enumerate(shots):
        t = None
        for kw in _keywords(s.get("query", "")):
            # longest keywords first so 'babymons7er' beats 'baby'
            for tok, tt in toks:
                if kw == tok or (len(kw) >= 5 and kw in tok):
                    t = tt
                    break
            if t is not None:
                break
        anchors[i] = t
    return anchors


def plan(shots, words, audio_dur, tail=1.0, xf=0.7):
    """Return new shot list with entity-aligned durations."""
    n = len(shots)
    if n < 2:
        out = [dict(s) for s in shots]
        out[0]["dur"] = round(audio_dur + tail, 2)
        return out
    anchors = anchor_times(shots, words or [])
    return _solve(shots, anchors, audio_dur, tail, xf)


def _solve(shots, anchors, audio_dur, tail, xf):
    n = len(shots)
    total = audio_dur + tail
    anchored = sorted([(t, i) for i, t in anchors.items() if t is not None])
    starts = [None] * n

    # 1) lay out anchored shots monotonically at anchor - LEAD
    prev = 0.0
    for t, i in anchored:
        st = max(prev, t - LEAD)
        starts[i] = st
        prev = st + MIN_SHOT
    # collision: later anchor cut pushed past audio end?
    if starts[anchored[-1][1]] + MIN_SHOT > total:
        # fall back to even layout
        anchored = []

    # 2) distribute unanchored shots in the gaps
    if not anchored:
        base = total / n
        for i in range(n):
            starts[i] = i * base
    else:
        bounds = [0.0] + [starts[i] for _, i in anchored if starts[i] is not None] + [total]
        gaps = [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1)]
        free = [i for i in range(n) if starts[i] is None]
        gi = 0
        for i in free:
            # next gap with usable width
            while gi < len(gaps) - 1 and gaps[gi][1] - gaps[gi][0] < MIN_SHOT:
                gi += 1
            a, b = gaps[gi]
            starts[i] = min(a + (b - a) / 2, max(a, b - MIN_SHOT))
            gaps[gi] = (starts[i] + MIN_SHOT, b)

    # 3) enforce monotonic + min duration, then durs
    starts = sorted(starts)
    for k in range(1, n):
        if starts[k] < starts[k - 1] + MIN_SHOT:
            starts[k] = starts[k - 1] + MIN_SHOT
    # if we overran the end, respace evenly
    if starts[-1] + MIN_SHOT > total:
        base = total / n
        starts = [i * base for i in range(n)]
    starts[-1] = min(starts[-1], total - MIN_SHOT)
    # clip lengths so the xfade chain outputs EXACTLY `total` seconds:
    #   first: alive until shot 2 is fully in   -> starts[1]
    #   middle: starts[k-1] .. starts[k] + xf   -> covers its own transition
    #   last: starts[n-1] .. end (+xf tail)
    durs = []
    for k in range(n):
        if k == 0:
            d = starts[1]
        elif k < n - 1:
            d = starts[k + 1] - starts[k] + xf
        else:
            d = total - starts[k] + xf
        durs.append(max(MIN_SHOT, d))
    out = []
    for s, d in zip(shots, durs):
        s2 = dict(s)
        s2["dur"] = round(d, 3)
        out.append(s2)
    return out
