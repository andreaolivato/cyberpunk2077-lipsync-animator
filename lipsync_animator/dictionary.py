"""The sound dictionary: an average face pose for every sound, measured from
the game's own lines, and the rules for the parts of the face that do not
follow the sounds. For the method and its accuracy, see docs/dictionary.md;
for the evidence behind each constant, see docs/face-tracks.md.

The tool ships one in data/dictionary.json, written by compact(): averaged
numbers per sound, no game files. `extract` and `build-dictionary` make a
new one from the player's own game."""
import glob
import json
import os

import numpy as np

from . import glb, sounds

FPS = 30
LEAD = 0.07         # the mouth runs this far ahead of each sound's middle
LEAD_JAW = 0.033    # and the jaw this far ahead of the loudness
REST_RAMP = 0.2     # seconds from the first and last sound to a resting mouth
RAMP = 0.6          # seconds of control curve kept either side of speech
MIN_MOVING = 20     # an animation moving fewer tracks is a placeholder
MAX_LENGTH_DIFF = 0.3
# Every vanilla clip starts and ends with the face at rest (mouth, fade and
# control tracks at 0). On a clip that does not, the game opens and closes
# the mouth once more after the last word. So everything that moves fades
# in and out over EDGE seconds at the clip's two ends.
EDGE = 0.1
JAW = 'jaw_mid_openLipsyncPoseOutput'

# Tracks the sounds drive. On lines a dictionary never saw, every track in
# these families follows the per-sound average at r 0.44 to 0.78; eyes,
# brows, blinks, head and the control tracks stay below 0.26, and face()
# makes them by rule instead.
SPEECH_PREFIXES = ('lips_', 'jaw_', 'cheek_', 'tongue_', 'neck_l_stretch', 'neck_r_stretch',
                   'neck_tighten', 'neck_l_platysma', 'neck_r_platysma',
                   'neck_l_sternocleidomastoid', 'neck_r_sternocleidomastoid',
                   'neck_throat_', 'nose_l_snear', 'nose_r_snear')
SPEECH_SUFFIXES = ('LipsyncPoseOutput', 'AnimOverrideWeight')
CONTROL = ['upperFace', 'lowerFace', 'lipSyncEnvelope', 'jaliJaw', 'jaliLips',
           'muzzleLips', 'muzzleEyes', 'muzzleBrows']
BLINKS = ['eye_l_blinkLipsyncPoseOutput', 'eye_r_blinkLipsyncPoseOutput']


def is_speech_track(name):
    return name.endswith(SPEECH_SUFFIXES) and name.startswith(SPEECH_PREFIXES)


# A sound's mouth depends on the sounds beside it: the "m" in "mom" looks
# different from the "m" in "him". So besides one average per sound, the
# dictionary keeps one per sound in context, keyed by the class of the
# sound before and of the sound after. On speakers the dictionary never
# saw, this beat the plain average on every mouth track tested (lip closing
# 0.83 to 0.85, corners 0.62 to 0.67), and whole-word curves did not beat it
# (docs/dictionary.md). A context with fewer than MIN_CONTEXT examples falls
# back to one side, then to the plain average.
MIN_CONTEXT = 10    # tried 10, 20 and 40: 10 was best on every track, by 0.001 to 0.005
NEAR = 0.3          # a sound further than this from its neighbour has none
CLASSES = {}
for _c, _ps in (('closed', 'M B P'), ('lowerlip', 'F V'),
                ('round', 'W UW OW UH OY SH CH JH ZH R'), ('open', 'AA AE AH AO AW AY'),
                ('vowel', 'EH ER EY IH IY')):
    for _p in _ps.split():
        CLASSES[_p] = _c


def sound_class(p):
    if p is None:
        return 'edge'
    return 'pause' if p == sounds.SILENCE else CLASSES.get(p, 'cons')


def contexts(phones):
    """(start, end, sound, class before, class after) for each sound."""
    out = []
    for i, (s, e, p) in enumerate(phones):
        prev = phones[i - 1][2] if i > 0 and phones[i - 1][0] >= s - NEAR else None
        nxt = phones[i + 1][2] if i + 1 < len(phones) and phones[i + 1][0] <= e + NEAR else None
        out.append((s, e, p, sound_class(prev), sound_class(nxt)))
    return out


def context_keys(p, before, after):
    """Lookup order: both sides, the left side, the right side."""
    return ['%s|%s|%s' % (p, before, after), '%s|%s|' % (p, before), '%s||%s' % (p, after)]


def pose(dic, p, before, after):
    table = dic.get('contexts', {})
    for k in context_keys(p, before, after):
        if k in table:
            return table[k]
    return dic['phones'][p]['mean'] if p in dic['phones'] else None


# ------------------------------------------------------------------ reading
def load_lines(roots, exclude=(), report=print):
    """Vanilla training lines from data folders, each holding glb/ (exported
    sets), aligned/ (TextGrids) and audio/ or corpus/ (one audio file per
    line, named by stringId in hex). Returns [(hex, animation, sounds,
    (db, level))].

    Left out: placeholder animations, a line recorded by more than one
    speaker (which take the mouth was made from is unknown), and a line
    whose audio and mouth lengths differ by more than MAX_LENGTH_DIFF."""
    out, dropped = [], {'placeholder': 0, 'two recordings': 0, 'length': 0}
    for root in roots:
        anims = {}
        for path in glob.glob(os.path.join(root, 'glb', '**', '*.glb'), recursive=True):
            for name, a in glb.animations(path).items():
                a['set'] = os.path.relpath(path, os.path.join(root, 'glb'))
                anims[name[2:].lower()] = a
        audio = {}
        for folder in ('audio', 'corpus'):
            for path in glob.glob(os.path.join(root, folder, '**', '*.*'), recursive=True):
                if path.lower().endswith(('.ogg', '.wav', '.flac')):
                    key = os.path.splitext(os.path.basename(path))[0].lower()
                    audio.setdefault(key, []).append(path)
        seen = set()
        for tg in glob.glob(os.path.join(root, 'aligned', '**', '*.TextGrid'), recursive=True):
            h = os.path.basename(tg)[:-len('.TextGrid')].lower()
            if h in seen or h not in anims or h not in audio or h in exclude:
                continue
            seen.add(h)
            anim = anims[h]
            if any(x in anim['set'].lower() for x in exclude):
                continue
            if len(audio[h]) > 1:
                dropped['two recordings'] += 1
                continue
            span = {}
            for k in anim['extras']['trackKeys']:
                lo, hi = span.get(k['trackIndex'], (k['value'], k['value']))
                span[k['trackIndex']] = (min(lo, k['value']), max(hi, k['value']))
            if sum(hi - lo > 1e-3 for lo, hi in span.values()) < MIN_MOVING:
                dropped['placeholder'] += 1
                continue
            db, level = sounds.loudness(audio[h][0])
            if abs(len(db) / FPS - max(k['time'] for k in anim['extras']['trackKeys'])) > MAX_LENGTH_DIFF:
                dropped['length'] += 1
                continue
            out.append((h, anim, sounds.from_textgrid(tg), (db, level)))
    if report:
        report('lines used %d, left out: %s' % (len(out), ', '.join(
            '%d %s' % (n, k) for k, n in dropped.items())))
    return out


def loud_at(db, level, t):
    return np.interp(t * FPS, np.arange(len(db)), db) - level


# ----------------------------------------------------------------- building
def build(track_names, data):
    """The dictionary, as a plain dict ready for JSON."""
    if not data:
        raise SystemExit('no usable lines found: run extract on the folder first')
    n_tracks = len(track_names)
    jaw = track_names.index(JAW)
    samples, durations, in_context = {}, {}, {}
    moving = np.zeros(n_tracks, bool)
    cached = []
    for _h, anim, phones, _loud in data:
        cv = glb.face_keys(anim, n_tracks)
        cached.append(cv)
        for i, (_ts, vs) in enumerate(cv):
            moving[i] |= len(vs) > 1 and np.ptp(vs) > 1e-4
        poses = glb.sample(cv, np.array([(s + e) / 2 for s, e, _ in phones]) - LEAD)
        for (s, e, p, before, after), row in zip(contexts(phones), poses):
            samples.setdefault(p, []).append(row)
            durations.setdefault(p, []).append(e - s)
            for k in context_keys(p, before, after):
                in_context.setdefault(k, []).append(row)
    tracks = np.nonzero(moving)[0]
    mean = {p: np.mean(rows, axis=0) for p, rows in samples.items()}
    context_mean = {k: np.mean(rows, axis=0)[tracks] for k, rows in in_context.items()
                    if len(rows) >= MIN_CONTEXT}

    # How much louder audio opens the jaw beyond each sound's average.
    resid, loud = [], []
    for cv, (_h, _anim, phones, (db, level)) in zip(cached, data):
        for s, e, p in phones:
            if p != sounds.SILENCE:
                m = (s + e) / 2 - LEAD
                resid.append(np.interp(m, *cv[jaw]) - mean[p][jaw])
                loud.append(loud_at(db, level, np.array([m + LEAD_JAW]))[0])
    slope, offset = np.polyfit(loud, resid, 1)

    return {
        'format': 1,
        'lead': LEAD, 'lead_jaw': LEAD_JAW, 'fps': FPS, 'lines': len(data),
        'all_track_names': list(track_names),
        'tracks': [int(t) for t in tracks],
        'track_names': [track_names[t] for t in tracks],
        'phones': {p: {'n': len(samples[p]),
                       'duration': round(float(np.median(durations[p])), 4),
                       'mean': [round(float(mean[p][t]), 5) for t in tracks]}
                   for p in sorted(samples)},
        'contexts': {k: [round(float(x), 5) for x in v] for k, v in sorted(context_mean.items())},
        'jaw': {'track': jaw, 'slope_per_db': float(slope), 'offset': float(offset),
                'r': float(np.corrcoef(loud, resid)[0, 1])},
        'rest': build_rest(track_names, data, cached),
    }


def build_rest(track_names, data, cached):
    offs = np.arange(-RAMP, RAMP + 1e-6, 1 / FPS)
    start = {c: [] for c in CONTROL}
    end = {c: [] for c in CONTROL}
    mid = {c: [] for c in CONTROL}
    blinks, gaps, firsts, consts = [], [], [], {}
    bl = [track_names.index(b) for b in BLINKS]
    for cv, (_h, anim, phones, _loud) in zip(cached, data):
        speech = [p for p in phones if p[2] != sounds.SILENCE]
        if not speech:
            continue
        first, last = speech[0][0], speech[-1][1]
        for c in CONTROL:
            ts, vs = cv[track_names.index(c)]
            start[c].append(np.interp(first + offs, ts, vs))
            end[c].append(np.interp(last + offs, ts, vs))
            mid[c].append(np.interp((first + last) / 2, ts, vs))
        n = int(max(k['time'] for k in anim['extras']['trackKeys']) * FPS) + 1
        t = np.arange(n) / FPS
        b = np.interp(t, *cv[bl[0]])
        peaks = [i for i in range(1, n - 1) if b[i] > 0.5 and b[i] >= b[i - 1] and b[i] > b[i + 1]]
        blinks += [[np.interp(t[i - 6:i + 7], *cv[j]) for j in bl]
                   for i in peaks if i >= 6 and i + 7 <= n]
        if peaks:
            firsts.append(t[peaks[0]])
        gaps += list(np.diff(peaks) / FPS)
        for k in anim['extras']['constTrackKeys']:
            counts = consts.setdefault(k['trackIndex'], {})
            v = round(k['value'], 5)
            counts[v] = counts.get(v, 0) + 1
    return {
        'ramp_offsets': [round(float(o), 4) for o in offs],
        'control': {c: {'start': [round(float(v), 5) for v in np.median(start[c], axis=0)],
                        'end': [round(float(v), 5) for v in np.median(end[c], axis=0)],
                        'mid': round(float(np.median(mid[c])), 5)} for c in CONTROL},
        'blink': {'shape': np.round(np.median(blinks, axis=0), 4).tolist(), 'peak_index': 6,
                  'first': round(float(np.median(firsts)), 3),
                  'gap_quartiles': [round(float(g), 3) for g in np.percentile(gaps, [25, 75])]},
        'constants': {str(i): max(c, key=c.get) for i, c in sorted(consts.items())},
    }


SHIPPED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'dictionary.json')


def compact(dic, digits=4):
    """Only what making a line needs, rounded: for each sound its typical
    length and one number per moving face track, the jaw's loudness term,
    and the rules for the rest of the face. No counts, no game files."""
    r = lambda v: round(float(v), digits)  # noqa: E731
    rest = dic['rest']
    return {
        'format': 1,
        'about': 'Average face pose per English sound (ARPAbet), one number per track in '
                 '"tracks", read %d ms before each sound\'s middle in Cyberpunk 2077\'s own '
                 'lines. Rebuild your own with: extract, then build-dictionary.'
                 % round(dic['lead'] * 1000),
        'fps': dic['fps'], 'lead': dic['lead'], 'lead_jaw': dic['lead_jaw'],
        'all_track_names': dic['all_track_names'],
        'tracks': dic['tracks'], 'track_names': dic['track_names'],
        'phones': {p: {'duration': r(v['duration']), 'mean': [r(x) for x in v['mean']]}
                   for p, v in dic['phones'].items()},
        'contexts': {k: [round(float(x), 3) for x in v] for k, v in dic.get('contexts', {}).items()},
        'jaw': {'track': dic['jaw']['track'], 'slope_per_db': r(dic['jaw']['slope_per_db']),
                'offset': r(dic['jaw']['offset'])},
        'rest': {'ramp_offsets': rest['ramp_offsets'],
                 'control': {c: {'start': [r(x) for x in v['start']],
                                 'end': [r(x) for x in v['end']], 'mid': r(v['mid'])}
                             for c, v in rest['control'].items()},
                 'blink': rest['blink'],
                 'constants': {k: r(v) for k, v in rest['constants'].items()}},
    }


def save(dic, path, compact_form=False):
    if compact_form:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(compact(dic), f, separators=(',', ':'))
    else:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(dic, f, indent=1)


def load(path=None):
    """A dictionary file, or the one shipped with the tool."""
    with open(path or SHIPPED, encoding='utf-8') as f:
        return json.load(f)


# ---------------------------------------------------------------- synthesis
def mouth(dic, phones, n_frames, db=None, level=None):
    """The dictionary's tracks per frame (n_frames x len(dic['tracks'])).

    One key per sound at its middle minus the lead, holding that sound's
    average pose, with straight lines between keys and a resting mouth
    REST_RAMP seconds before the first sound and after the last. The jaw is
    pushed by loudness while speaking. Unknown sounds are skipped."""
    tracks, lead = dic['tracks'], dic['lead']
    keys_t, keys_v = [], []
    for s, e, p, before, after in contexts(phones):
        v = pose(dic, p, before, after)
        if v is not None:
            keys_t.append((s + e) / 2 - lead)
            keys_v.append(v)
    t = np.arange(n_frames) / FPS
    if not keys_t:
        return np.zeros((n_frames, len(tracks)))
    speech = [(s, e) for s, e, p in phones if p != sounds.SILENCE and p in dic['phones']]
    if speech:
        keys_t = [min(keys_t[0], speech[0][0] - lead) - REST_RAMP] + keys_t + \
                 [max(keys_t[-1], speech[-1][1] - lead) + REST_RAMP]
        keys_v = [[0.0] * len(tracks)] + keys_v + [[0.0] * len(tracks)]
    keys_v = np.array(keys_v)
    out = np.stack([np.interp(t, keys_t, keys_v[:, j]) for j in range(len(tracks))], axis=1)
    if db is not None:
        j = tracks.index(dic['jaw']['track'])
        push = dic['jaw']['offset'] + dic['jaw']['slope_per_db'] * loud_at(db, level, t + dic['lead_jaw'])
        speaking = np.zeros(n_frames, bool)
        for s, e, p in phones:
            if p != sounds.SILENCE:
                speaking |= (t >= s - lead) & (t <= e - lead)
        out[:, j] = np.maximum(out[:, j] + np.where(speaking, push, 0.0), 0.0)
    return out * edges(n_frames)[:, None]


def edges(n_frames):
    """1 in the middle of a clip, falling to exactly 0 on its first and last
    frame over EDGE seconds."""
    t = np.arange(n_frames) / FPS
    end = (n_frames - 1) / FPS
    return np.clip(np.minimum(t, end - t) / EDGE, 0.0, 1.0)


def face(dic, phones, n_frames, db=None, level=None, seed=0, neutral=True,
         control=True, blinks=True):
    """All 414 tracks of a new line, as {track index: values per frame}.

    A lipsync animation is added on top of the face the character already
    has: every value is a change, and 0 changes nothing. (CDPR's lines store
    0 on tracks whose rig rest value is 1, and each mouth track's
    AnimOverrideWeight partner as its exact negative.) The speech tracks
    (mouth, jaw, lips, tongue, cheeks, throat) come from the dictionary.
    Every other track holds 0, which leaves the character's face as it is,
    or with neutral=False the value CDPR's lines most often give it, which
    puts the same small expression on everyone (a slight squint, for one).
    control adds the lipsync fade and the other control curves CDPR's lines
    carry; blinks adds blinks."""
    names, rest = dic['all_track_names'], dic['rest']
    t = np.arange(n_frames) / FPS
    if neutral:
        out = {i: np.zeros(n_frames) for i in range(len(names))}
    else:
        out = {int(i): np.full(n_frames, float(v)) for i, v in rest['constants'].items()}
        for i in range(len(names)):
            out.setdefault(i, np.zeros(n_frames))
    m = mouth(dic, phones, n_frames, db, level)
    for j, (ti, nm) in enumerate(zip(dic['tracks'], dic['track_names'])):
        if is_speech_track(nm):
            out[ti] = m[:, j]
        else:
            out[ti] = np.zeros(n_frames)

    speech = [p for p in phones if p[2] != sounds.SILENCE]
    if speech and control:
        first, last = speech[0][0], speech[-1][1]
        offs = np.array(rest['ramp_offsets'])
        split = (first + last) / 2
        for c in CONTROL:
            cc = rest['control'][c]
            a = np.interp(t - first, offs, cc['start'], left=cc['start'][0], right=cc['mid'])
            b = np.interp(t - last, offs, cc['end'], left=cc['mid'], right=cc['end'][-1])
            out[names.index(c)] = np.where(t < split, a, b) * edges(n_frames)

    if not blinks:
        return out
    bl = rest['blink']
    rng = np.random.default_rng(seed)
    shape = np.array(bl['shape'])
    peak = bl['first'] + rng.uniform(-0.3, 0.3)
    while peak < n_frames / FPS - 0.2 - EDGE:
        f = int(round(peak * FPS))
        for side, nm in enumerate(BLINKS):
            track = out[names.index(nm)]
            for k, v in enumerate(shape[side]):
                i = f - bl['peak_index'] + k
                if 0 <= i < n_frames:
                    track[i] = max(track[i], v)
        peak += rng.uniform(*bl['gap_quartiles'])
    return out
