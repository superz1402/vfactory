#!/usr/bin/env python3
"""score.py — structured, real-instrument background scores for vfactory.

Ported engine: lemomo-ai/lemo-opuscar sampler (MIT) + CC0/CC-BY sample libs.
A score = chapter/section arc (intro -> body -> climax -> outro), each section
gets an intensity 0..1 that turns instrument layers on/off:

  0.00-0.25  cellos sustained root+fifth (always)
  0.25-0.50  + violin pad (chord tones, slow attack)
  0.50-0.75  + piano/harp arpeggio motif + violin counter-line
  0.75-1.00  + spiccato pulse, timpani swells, crash accents

Styles: documentary/cinematic (D minor, 72bpm), hype/explainer (C major, 100bpm).
Per-chapter beds are rendered with pre/post pads so notes cross boundaries,
stingers mark act starts, everything ends in a real fade.

Public API:
  plan_chapters(dur, roles) -> section plan
  render_section(events... ) via compose_score(sections, style, seed) -> wavs
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio"))
import soundfile as sf  # noqa: E402
import numpy as np  # noqa: E402

import sampler as S  # noqa: E402
from sfx import SR  # noqa: E402

PAD = 3.0  # seconds rendered before/after each section for note tails


# ---------------------------------------------------------------- theory ----
NOTE_OFFSET = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


def midi(p):
    """'D3'/'F#4'/'Bb2' -> midi number (C4=60)."""
    if isinstance(p, (int, float)):
        return int(p)
    name = p[0].upper()
    i = 1
    acc = 0
    while i < len(p) and p[i] in '#b':
        acc += 1 if p[i] == '#' else -1
        i += 1
    octv = int(p[i:])
    return 12 * (octv + 1) + NOTE_OFFSET[name] + acc


def nname(m):
    names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    return f"{names[m % 12]}{m // 12 - 1}"


def triad(root, mode='min'):
    """root midi -> chord tone midis (closed position)."""
    iv = (0, 3, 7) if mode == 'min' else (0, 4, 7)
    return [root + x for x in iv]


# ---------------------------------------------------------------- styles ----
STYLES = {
    'documentary': dict(
        bpm=72, root='D', mode='min',
        prog=[('i', 0), ('VI', 8), ('VII', 10), ('v', 7)],   # Dm Bb C Am
        bass_inst='contrabass', pad_inst='cellos', strings='violins',
        motif_a='piano', motif_b='harp', perc=('timpani', 'sus_cymbal'),
        gong=True),
    'cinematic': dict(
        bpm=80, root='A', mode='min',
        prog=[('i', 0), ('VI', 8), ('III', 3), ('VII', 10)],
        bass_inst='contrabass', pad_inst='cellos', strings='violins',
        motif_a='piano', motif_b='glockenspiel', perc=('timpani', 'crash'),
        gong=True),
    'hype': dict(
        bpm=100, root='C', mode='maj',
        prog=[('I', 0), ('V', 7), ('vi', 9), ('IV', 5)],
        bass_inst='jazz_bass', pad_inst='guitar_nylon', strings='violins',
        motif_a='marimba', motif_b='piano', perc=('conga', 'crash'),
        gong=False),
    'explainer': dict(
        bpm=96, root='C', mode='maj',
        prog=[('I', 0), ('vi', 9), ('IV', 5), ('V', 7)],
        bass_inst='jazz_bass', pad_inst='guitar_nylon', strings='violins',
        motif_a='piano', motif_b='vibraphone', perc=('shaker', 'crash'),
        gong=False),
}

ROMAN = {'i': 'min', 'I': 'maj', 'iv': 'min', 'IV': 'maj', 'v': 'min', 'V': 'maj',
         'VI': 'maj', 'III': 'maj', 'VII': 'maj', 'vi': 'min', 'ii': 'min'}


# ------------------------------------------------------------ composition ----
def _chord_tones(st, deg, octv=4):
    """Chord tones for degree index, voiced in octave `octv`."""
    root_off = st['prog'][deg][1]
    root = midi(f"{st['root']}{octv}") + root_off
    return triad(root, ROMAN[st['prog'][deg][0]])


def compose_section(st, t0, dur, intensity, rng, bar=None, first=False, last=False):
    """Events for one section (chapter) of `dur` seconds starting at local t=0."""
    bpm = st['bpm']
    bar_dur = 4 * 60.0 / bpm
    ev = []
    n_bars = max(1, int(round(dur / bar_dur)))
    key_shift = 0

    for b in range(n_bars):
        bt = b * bar_dur
        if bt >= dur:
            break
        deg = (b + (bar or 0)) % len(st['prog'])
        tones = _chord_tones(st, deg, octv=4)
        # slow key brightness drift on long arcs (avoid monotony)
        if b and b % 16 == 0:
            key_shift = 12 if key_shift == 0 else 0
        # --- bass root + fifth (always) ---
        bass_root = midi(f"{st['root']}2") + st['prog'][deg][1]
        ev.append(dict(t=bt, inst=st['bass_inst'], pitch=bass_root - 12,
                       dur=bar_dur * 0.95, vel=0.30 + 0.10 * intensity, pan=-0.15,
                       attack=0.4 if intensity < 0.5 else 0.1))
        # --- sustained pad: root+fifth+third, low register ---
        for k, tone in enumerate(tones):
            if tone < 48:
                tone += 12
            ev.append(dict(t=bt, inst=st['pad_inst'], pitch=tone,
                           dur=bar_dur * (1.0 if intensity < 0.6 else 0.96),
                           vel=0.26 + 0.16 * intensity - 0.03 * k,
                           pan=(-0.2 if k % 2 else 0.2), attack=1.0))
        # --- motif layer: broken-chord arpeggio (intensity >= 0.45) ---
        if intensity >= 0.45:
            inst = st['motif_a'] if (b % 4) < 3 else st['motif_b']
            step = bar_dur / 4
            pattern = [0, 2, 1, 2] if b % 2 == 0 else [2, 1, 0, 1]
            for j, pi in enumerate(pattern):
                tone = tones[pi % 3] + (12 if j == 3 and intensity > 0.8 else 0)
                ev.append(dict(t=bt + j * step + rng.uniform(0, 0.03),
                               inst=inst, pitch=tone + key_shift,
                               dur=step * 1.4, vel=0.34 + 0.14 * intensity,
                               pan=0.25 if j % 2 else -0.25))
        # --- counter line (intensity >= 0.65): sparse violin phrase ---
        if intensity >= 0.65 and b % 2 == 1:
            tone = tones[(b // 2) % 3] + 12
            ev.append(dict(t=bt + bar_dur * 0.5, inst=st['strings'],
                           pitch=tone, dur=bar_dur * 0.9,
                           vel=0.30 + 0.10 * intensity, pan=0.3, attack=0.25))
        # --- pulse (intensity >= 0.8): spiccato eighths on beats 2/4 ---
        if intensity >= 0.80 and b >= 2:
            for beat in (1, 3):
                ev.append(dict(t=bt + beat * bar_dur / 4, inst='cellos_spic',
                               pitch=midi(f"{st['root']}3") + st['prog'][deg][1],
                               dur=0.3, vel=0.30, pan=0.0))
        # --- timpani swell into strong bars (intensity >= 0.7) ---
        if intensity >= 0.70 and b % 8 == 0 and b > 0:
            ev.append(dict(t=bt, inst=st['perc'][0], pitch=midi(f"{st['root']}2"),
                           dur=1.6, vel=0.55 + 0.15 * intensity, pan=0.0))
        if intensity >= 0.85 and b % 8 == 4:
            ev.append(dict(t=bt, inst=st['perc'][1], dur=1.0, vel=0.35, pan=0.1))
    # --- stinger at section start (act marker) ---
    if first and st['gong']:
        ev.append(dict(t=0, inst='gong', dur=3.0, vel=0.5, pan=0.0))
    elif first:
        ev.append(dict(t=0, inst=st['perc'][0], pitch=midi(f"{st['root']}2"),
                       dur=2.0, vel=0.6, pan=0.0))
        ev.append(dict(t=0.05, inst=st['perc'][1], dur=1.5, vel=0.3, pan=0.1))
    # final resolve: long tonic + bells
    if last:
        rt = n_bars * bar_dur - bar_dur
        root = midi(f"{st['root']}3")
        for tone in triad(root, st['mode']):
            ev.append(dict(t=max(rt, 0), inst=st['pad_inst'], pitch=tone,
                           dur=bar_dur * 2, vel=0.30, pan=0.0, attack=0.8))
        ev.append(dict(t=max(rt, 0), inst='tubular_bells', pitch=root + 24,
                       dur=3.0, vel=0.3, pan=0.2))
    return ev


def _fade(buf, fin=1.2, fout=2.0):
    n = len(buf)
    fi, fo = int(fin * SR), int(fout * SR)
    if fi * 2 < n:
        buf[:fi] *= np.linspace(0, 1, fi)[:, None]
    if fo * 2 < n:
        buf[n - fo:] *= np.linspace(1, 0, fo)[:, None]
    return buf


def normalize_rms(buf, target_db=-19.0):
    rms = float(np.sqrt(np.mean(buf ** 2)))
    if rms > 0:
        buf *= (10 ** (target_db / 20.0)) / rms
    peak = np.abs(buf).max()
    if peak > 0.92:
        buf *= 0.92 / peak
    return buf


def render_chapter(events, dur, out_path, fade_in=1.2, fade_out=2.0):
    buf = S.render(events, dur=dur)
    buf = S.room(buf, size=0.5, mix=0.16)
    buf = _fade(buf, fade_in, fade_out)
    buf = normalize_rms(buf)
    sf.write(out_path, buf, SR)
    return out_path


def compose_score(sections, style='documentary', out_dir='.', seed=7):
    """sections: [{id, dur, intensity, stinger}] in order -> per-section beds.

    Returns dict {beds: {id: path}, credits: str, style: style}.
    Each bed covers [start-PAD, dur+2*PAD] window of that section.
    """
    os.makedirs(out_dir, exist_ok=True)
    st = dict(STYLES[style])
    rng = np.random.default_rng(seed)
    beds, credits_insts = {}, set()
    for i, sec in enumerate(sections):
        dur = sec['dur'] + 2 * PAD
        events = compose_section(
            st, sec.get('start', 0), dur, sec['intensity'], rng,
            bar=i * 3 % 4, first=sec.get('stinger', False), last=(i == len(sections) - 1))
        for e in events:
            credits_insts.add(e['inst'])
        path = os.path.join(out_dir, f"bed_{sec['id']}.wav")
        fi = 0.4 if sec.get('stinger', False) else 1.2
        render_chapter(events, dur, path, fade_in=fi, fade_out=2.2)
        beds[sec['id']] = path
    credits = S.credits(sorted(credits_insts))
    return {'beds': beds, 'credits': credits, 'style': style}


# ------------------------------------------------------- plan from script ----
def arc_intensity(role, i, n, rng=None):
    """Narrative intensity curve per section role."""
    base = {
        'cold_open': 0.55, 'hook': 0.60,
        'context': 0.40, 'body': 0.50, 'rise': 0.65,
        'climax': 0.90, 'turning_point': 0.80,
        'resolution': 0.45, 'outro': 0.35, 'credits': 0.30,
    }
    v = base.get(role, 0.5)
    # gentle wobble so consecutive body sections don't feel looped
    wobble = ((i * 37) % 7) * 0.02 - 0.06
    return max(0.15, min(1.0, v + wobble))


def sections_from_chapters(chapters, style='documentary'):
    """chapters: [{id, audio_dur, role}] -> section plan for compose_score."""
    secs = []
    for i, ch in enumerate(chapters):
        secs.append({
            'id': ch['id'],
            'dur': float(ch['audio_dur']),
            'intensity': arc_intensity(ch.get('role', 'body'), i, len(chapters)),
            'stinger': i > 0,  # cold open flows in; every real act gets a marker
        })
    return secs


if __name__ == '__main__':
    # smoke: 3 sections, documentary
    secs = [
        {'id': 1, 'dur': 20, 'intensity': 0.55, 'stinger': False},
        {'id': 2, 'dur': 25, 'intensity': 0.75, 'stinger': True},
        {'id': 3, 'dur': 15, 'intensity': 0.35, 'stinger': True},
    ]
    out = compose_score(secs, 'documentary', '/tmp/scoretest')
    for k, v in out['beds'].items():
        print(k, os.path.getsize(v) // 1024, 'KB')
    print(out['credits'])
