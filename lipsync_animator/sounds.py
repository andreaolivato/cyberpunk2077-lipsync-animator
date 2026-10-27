"""A line's sounds with their times, and its loudness.

Sounds are ARPAbet phones without stress marks ("AA", "M", ...), the set the
English aligner model and the CMU Pronouncing Dictionary both use, plus
SILENCE for a pause between words inside a line."""
import re

import numpy as np

FPS = 30
SILENCE = 'sil'
MIN_GAP = 0.15      # seconds between words that count as a pause


def read_textgrid(path):
    """{'words': [(start, end, text)], 'phones': [(start, end, phone)]};
    empty intervals are left out."""
    tiers, cur = {}, None
    start = end = 0.0
    for line in open(path, encoding='utf-8').read().splitlines():
        line = line.strip()
        m = re.match(r'name = "(.*)"', line)
        if m:
            cur = tiers.setdefault(m.group(1), [])
            continue
        m = re.match(r'(xmin|xmax|text) = (.*)', line)
        if not m or cur is None:
            continue
        key, val = m.groups()
        if key == 'xmin':
            start = float(val)
        elif key == 'xmax':
            end = float(val)
        elif val.strip('"'):
            cur.append((start, end, val.strip('"')))
    return tiers


def from_textgrid(path):
    """Timed sounds from an aligner TextGrid, with pauses added."""
    tg = read_textgrid(path)
    out = [(s, e, p.rstrip('012')) for s, e, p in tg.get('phones', []) if p != 'spn']
    words = tg.get('words', [])
    for (_s0, e0, _w0), (s1, _e1, _w1) in zip(words, words[1:]):
        if s1 - e0 >= MIN_GAP:
            out.append((e0, s1, SILENCE))
    return sorted(out)


def frames(path):
    """How many animation frames a line needs: enough that the last one
    falls at or after the end of its audio. A frame count taken from the
    loudness frames alone ends the animation up to two frames early."""
    import math
    import soundfile
    info = soundfile.info(path)
    return int(math.ceil(info.frames / info.samplerate * FPS - 1e-6)) + 1


def loudness(path):
    """Per-frame loudness in dB, and the line's median speech level (the
    median of frames within 30 dB of the loudest)."""
    import soundfile
    audio, rate = soundfile.read(path, always_2d=True)
    audio = audio.mean(axis=1)
    hop = rate // FPS
    n = len(audio) // hop
    if n == 0:      # shorter than one frame: silence
        return np.full(1, -120.0), -120.0
    db = 20 * np.log10(np.sqrt((audio[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-6)
    return db, float(np.median(db[db > db.max() - 30]))
