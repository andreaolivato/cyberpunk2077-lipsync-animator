"""Time a line's sounds without an aligner, from its audio and text only.

1. Find speech and pauses in the audio. A pause lasts at least MIN_PAUSE
   seconds and is more than PAUSE_DB below the line's speech level.
2. Turn the text into sounds with a pronunciation file. A word it does not
   know is split into two known pieces if it can be ("japantown" is "japan"
   + "town"), and spelled out by letter rules if not.
3. Give every sound its typical length (the median from aligned vanilla
   lines, stored in the dictionary), share the words out over the stretches
   of speech so no word is split by a pause, and scale the sounds inside
   each stretch to fill it.

On lines the dictionary never saw, this gets the lip shapes at r 0.43 to
0.53 and the jaw at 0.67, against 0.67 to 0.85 and 0.78 with the aligner
(docs/dictionary.md).
"""
import os
import re
import unicodedata

import numpy as np

from . import aligner
from .sounds import FPS, SILENCE

MIN_PAUSE = 0.15
PAUSE_DB = 25

LETTERS = {
    'a': ['AE'], 'b': ['B'], 'c': ['K'], 'd': ['D'], 'e': ['EH'], 'f': ['F'], 'g': ['G'],
    'h': ['HH'], 'i': ['IH'], 'j': ['JH'], 'k': ['K'], 'l': ['L'], 'm': ['M'], 'n': ['N'],
    'o': ['AA'], 'p': ['P'], 'q': ['K'], 'r': ['R'], 's': ['S'], 't': ['T'], 'u': ['AH'],
    'v': ['V'], 'w': ['W'], 'x': ['K', 'S'], 'y': ['Y'], 'z': ['Z'],
}
DIGRAPHS = {'sh': ['SH'], 'ch': ['CH'], 'th': ['TH'], 'ph': ['F'], 'ng': ['NG'],
            'ee': ['IY'], 'oo': ['UW'], 'ou': ['AW'], 'ai': ['EY'], 'ay': ['EY'],
            'ck': ['K'], 'qu': ['K', 'W']}
PHONE = re.compile(r'^[A-Z]{1,2}[012]?$')


MFA_DICT = aligner.DICTIONARY


def load_pronunciations(path):
    """{word: [sounds]} from a pronunciation file: the CMU Pronouncing
    Dictionary's data file (BSD licence), or a Montreal Forced Aligner .dict
    (its numbers are skipped). The first pronunciation of each word wins."""
    out = {}
    for line in open(path, encoding='utf-8', errors='replace'):
        parts = line.split()
        if not parts or parts[0].startswith(';;;'):
            continue
        word = re.sub(r'\(\d+\)$', '', parts[0].lower())
        phones = [p.rstrip('012') for p in parts[1:] if PHONE.match(p)]
        if phones and word not in out:
            out[word] = phones
    return out


def spell(word):
    out, i = [], 0
    while i < len(word):
        if word[i:i + 2] in DIGRAPHS:
            out += DIGRAPHS[word[i:i + 2]]
            i += 2
        else:
            out += LETTERS.get(word[i], [])
            i += 1
    return out


def word_sounds(word, pron):
    w = word.lower().strip("'")
    if w in pron:
        return pron[w]
    if w.endswith("'s") and w[:-2] in pron:
        return pron[w[:-2]] + ['Z']
    for cut in range(len(w) - 2, 1, -1):
        if w[:cut] in pron and w[cut:] in pron:
            return pron[w[:cut]] + pron[w[cut:]]
    return spell(w)


def words_of(text):
    # Accented letters lose their accents ("señor" is looked up as "senor"):
    # the pronunciation lists are in plain letters.
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode()
    return [re.sub(r"[^A-Za-z']", '', m.group(0))
            for m in re.finditer(r"[A-Za-z0-9']+", text) if re.search('[A-Za-z]', m.group(0))]


def speech_runs(db):
    """(start, end) seconds of each stretch of speech in a per-frame dB curve."""
    level = np.median(db[db > db.max() - 30])
    loud = db > level - PAUSE_DB
    runs, start = [], None
    for i, v in enumerate(loud):
        if v and start is None:
            start = i
        if not v and start is not None:
            runs.append([start, i])
            start = None
    if start is not None:
        runs.append([start, len(loud)])
    merged = []
    for r in runs:
        if merged and (r[0] - merged[-1][1]) / FPS < MIN_PAUSE:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a / FPS, b / FPS) for a, b in merged if (b - a) / FPS >= 0.05]


def time_sounds(dic, text, db, pron):
    """[(start, end, sound)] in the aligner's shape, with SILENCE for pauses."""
    words = [s for s in (word_sounds(w, pron) for w in words_of(text)) if s]
    runs = speech_runs(db)
    if not words or not runs:
        return []
    dur = {p: v['duration'] for p, v in dic['phones'].items()}
    lengths = [sum(dur.get(p, 0.08) for p in snd) for snd in words]
    total, spoken = sum(lengths), sum(e - s for s, e in runs)
    bounds = np.cumsum([e - s for s, e in runs]) / spoken
    groups = [[] for _ in runs]
    acc = 0.0
    for snd, ln in zip(words, lengths):
        middle = (acc + ln / 2) / total
        groups[min(int(np.searchsorted(bounds, middle)), len(runs) - 1)].append((snd, ln))
        acc += ln
    out = []
    for (s, e), group in zip(runs, groups):
        if group:
            scale = (e - s) / sum(ln for _snd, ln in group)
            t = s
            for snd, _ln in group:
                for p in snd:
                    d = dur.get(p, 0.08) * scale
                    out.append((t, t + d, p))
                    t += d
    for (_s0, e0), (s1, _e1) in zip(runs, runs[1:]):
        if s1 - e0 >= MIN_PAUSE:
            out.append((e0, s1, SILENCE))
    return sorted(out)


SHIPPED_CMU = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'cmudict.dict')


def default_pronunciations():
    """The CMU Pronouncing Dictionary shipped with the tool (BSD licence,
    data/cmudict-LICENSE), with the aligner's English dictionary added for
    words CMU lacks if it was downloaded on this machine."""
    out = load_pronunciations(SHIPPED_CMU)
    if os.path.exists(MFA_DICT):
        for w, p in load_pronunciations(MFA_DICT).items():
            out.setdefault(w, p)
    return out
