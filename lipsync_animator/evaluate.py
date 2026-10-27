"""How close the tool's lipsync animations come to CDPR's, on lines the
dictionary never saw.

One whole set (one speaker in one scene) is left out at a time; the
dictionary is built from the rest; every line of the left-out set is rebuilt
from its own audio and compared frame by frame with CDPR's animation for it.
Three versions are compared: the aligner's timing, the no-aligner timing,
and a borrowed animation (another line's of about the same length, played from
its start), which is what mods with new audio use today. The score is the
correlation with CDPR's curve: 1 is the same shape, 0 is no relation."""
import glob
import os
import random

import numpy as np

from . import dictionary, fallback, glb, sounds

TRACKS = [('lips closing', 'lips_together_upLipsyncPoseOutput'),
          ('jaw', 'jaw_mid_openLipsyncPoseOutput'),
          ('lips rounding', 'lips_l_purseLipsyncPoseOutput'),
          ('lower lip in', 'lips_suck_dnLipsyncPoseOutput'),
          ('lips forward', 'lips_l_funnelLipsyncPoseOutput'),
          ('corners', 'lips_l_corner_stretchLipsyncPoseOutput')]
KINDS = ('aligner', 'no aligner', 'borrowed')


def run(track_names, roots, n_sets=10, seed=1, pron=None, log=print):
    data = dictionary.load_lines(roots, report=log)
    texts = {}
    for root in roots:
        for folder in ('audio', 'corpus'):
            for p in glob.glob(os.path.join(root, folder, '**', '*.lab'), recursive=True):
                texts[os.path.splitext(os.path.basename(p))[0].lower()] = open(p, encoding='utf-8').read()
    by_set = {}
    for row in data:
        by_set.setdefault(row[1]['set'], []).append(row)
    pool = sorted(s for s, rows in by_set.items() if len(rows) >= 5)
    held = random.Random(seed).sample(pool, min(n_sets, len(pool)))
    pron = pron or fallback.default_pronunciations()
    real = {k: [] for k in KINDS}
    made = {k: [] for k in KINDS}
    for name in held:
        train = [r for r in data if r[1]['set'] != name]
        dic = dictionary.build(track_names, train)
        cols = [dic['track_names'].index(t) for _l, t in TRACKS]
        ti = [dic['tracks'][c] for c in cols]
        lengths = [(r[3][0].shape[0], r) for r in train]
        for h, anim, phones, (db, level) in by_set[name]:
            n = db.shape[0]
            t = np.arange(n) / sounds.FPS
            truth = glb.sample(glb.face_keys(anim), t)[:, ti]
            fb = fallback.time_sounds(dic, texts.get(h, ''), db, pron)
            other = min(lengths, key=lambda x: abs(x[0] - n))[1][1]
            versions = (dictionary.mouth(dic, phones, n, db, level)[:, cols],
                        dictionary.mouth(dic, fb, n, db, level)[:, cols],
                        glb.sample(glb.face_keys(other), t)[:, ti])
            for k, v in zip(KINDS, versions):
                real[k].append(truth)
                made[k].append(v)
        log('  left out %s (%d lines)' % (name, len(by_set[name])))
    result = {}
    for j, (label, _t) in enumerate(TRACKS):
        result[label] = {}
        for k in KINDS:
            a = np.concatenate(real[k])[:, j]
            b = np.concatenate(made[k])[:, j]
            result[label][k] = float(np.corrcoef(a, b)[0, 1]) if np.std(b) > 0 else float('nan')
    return result


def report(result, out=print):
    out('%-16s' % '' + ''.join('%12s' % k for k in KINDS))
    for label, row in result.items():
        out('%-16s' % label + ''.join('%12.2f' % row[k] for k in KINDS))
