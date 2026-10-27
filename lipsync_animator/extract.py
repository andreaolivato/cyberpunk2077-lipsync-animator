"""Pull training lines out of the player's own game for the sound dictionary.

Every vanilla line is a ready-made triple joined by one ID, its stringId:

- the lipsync animation: f_<stringId hex> in the speaker's lipsync set,
  base\\localization\\en-us\\lipsync\\<scene path>\\<actor>.anims
- the audio: base\\localization\\en-us\\vo\\<speaker>_<scene>_<f|m>_<hex>.wem
- the text: the subtitle entry with that stringId, in decimal, in
  lang_en_text.archive

extract() picks lipsync sets at random from the game's quests, exports each
set and the audio of its lines with WolvenKit, writes each line's subtitle
beside its audio, and runs the aligner, leaving a data folder that
`build-dictionary` reads:

    DATA/glb/<scene>__<actor>/<actor>.anims.glb
    DATA/audio/<hex>.ogg   DATA/audio/<hex>.lab
    DATA/aligned/...<hex>.TextGrid

Only plain `vo` audio is used: `vo_holocall`, `vo_helmet` and `vo_rewinded`
are the same take with a filter baked in. A line with bilingual markup
(part of it in another language) is skipped. Everything extracted is the
game's data and stays on the player's machine."""
import glob
import json
import os
import random
import re
import shutil
import tempfile

from . import aligner

WEM = re.compile(r'^(.*)_([fm])_([0-9a-f]{16})$')


def _archives(game):
    pairs = [(os.path.join(game, r'archive\pc\content\lang_en_voice.archive'),
              os.path.join(game, r'archive\pc\content\lang_en_text.archive'))]
    ep1 = (os.path.join(game, r'archive\pc\ep1\lang_en_voice.archive'),
           os.path.join(game, r'archive\pc\ep1\lang_en_text.archive'))
    if all(os.path.exists(p) for p in ep1):
        pairs.append(ep1)
    return pairs


def index(wk, data, log=print):
    """{'sets': [lipsync set depot paths], 'lines': {hex: {'text', 'audio'}}},
    cached in DATA/index.json. wk is a wolvenkit.WolvenKit."""
    path = os.path.join(data, 'index.json')
    if os.path.exists(path):
        return json.load(open(path, encoding='utf-8'))
    work = os.path.join(data, '_index')
    sets, wems, texts = [], {}, {}
    for n, (voice, text) in enumerate(_archives(wk.game)):
        log('listing %s' % voice)
        for line in wk.list(voice):
            parts = line.split('\\')
            if line.endswith('.anims') and '\\lipsync\\' in line:
                sets.append(line)
            elif line.endswith('.wem'):
                m = WEM.match(parts[-1][:-4])
                if m:
                    wems.setdefault(m.group(3), []).append({'dir': parts[-2], 'path': line})
        raw = os.path.join(work, 'raw%d' % n)
        log('reading the subtitles in %s (a few minutes)' % text)
        for f in wk.unbundle(raw, 'en-us.subtitles', under=text):
            try:
                entries = wk.read(f)['Data']['RootChunk']['root']['Data']['entries']
            except Exception:   # noqa: BLE001, not a subtitle file WolvenKit can read
                continue
            for e in entries:
                if 'stringId' in e:
                    texts.setdefault('%016x' % int(e['stringId']),
                                     e.get('femaleVariant') or e.get('maleVariant') or '')
    lines = {h: {'text': texts[h], 'audio': a} for h, a in wems.items() if texts.get(h)}
    out = {'sets': sorted(set(sets)), 'lines': lines}
    os.makedirs(data, exist_ok=True)
    json.dump(out, open(path, 'w', encoding='utf-8'))
    shutil.rmtree(work, ignore_errors=True)
    log('%d lipsync sets, %d lines with audio and text' % (len(out['sets']), len(lines)))
    return out


RIG = r'base\characters\head\pwa\h0_000_pwa_c__basehead\h0_000_pwa_c__basehead_skeleton.rig'


def track_names(wk, data):
    """The 414 face track names, read from one face rig and cached in
    DATA/track_names.json. Every face rig checked lists the same names in
    the same order."""
    from .wolvenkit import depot_regex
    path = os.path.join(data, 'track_names.json')
    if os.path.exists(path):
        return json.load(open(path))
    with tempfile.TemporaryDirectory() as tmp:
        content = os.path.join(wk.game, 'archive', 'pc', 'content')
        rig = wk.unbundle(tmp, depot_regex(RIG), under=content)[0]
        names = [n['$value'] for n in wk.read(rig)['Data']['RootChunk']['trackNames']]
    json.dump(names, open(path, 'w'))
    return names


def pick_sets(idx, count, seed=0, exclude=()):
    """Random quest sets, leaving out V's own sets."""
    pool = [s for s in idx['sets'] if '\\quest\\' in s
            and not os.path.basename(s).startswith('v_') and os.path.basename(s) != 'v.anims'
            and not any(x in s for x in exclude)]
    random.Random(seed).shuffle(pool)
    return pool[:count]


def _usable(row):
    clean = [a for a in row['audio'] if a['dir'] == 'vo']
    speakers = {WEM.match(os.path.basename(a['path'])[:-4]).group(1) for a in clean}
    return clean if len(speakers) == 1 and '<' not in row['text'] else None


def extract(wk, data, count=40, seed=0, exclude=(), log=print):
    """Fill DATA with `count` random quest sets, their lines' audio and text,
    and the aligner's timings. Returns the number of lines written. wk is a
    wolvenkit.WolvenKit."""
    from .wolvenkit import depot_regex
    idx = index(wk, data, log)
    track_names(wk, data)
    voice = [v for v, _t in _archives(wk.game)]
    audio_dir = os.path.join(data, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    written = []
    for depot in pick_sets(idx, count, seed, exclude):
        scene, actor = depot.split('\\')[-2], os.path.basename(depot)[:-len('.anims')]
        out = os.path.join(data, 'glb', '%s__%s' % (scene, actor))
        done = os.path.join(out, 'done.txt')     # written once the set's audio is out
        if os.path.exists(done):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            found = []
            for v in voice:
                found += wk.unbundle(tmp, depot_regex(depot), under=v)
            if not found:
                continue
            wk.export(found[0], out)
        glbs = glob.glob(os.path.join(out, '*.glb'))
        if not glbs:
            continue
        from . import glb
        hexes = [n[2:].lower() for n in glb.animations(glbs[0])]
        wanted = {h: _usable(idx['lines'][h]) for h in hexes if h in idx['lines']}
        wanted = {h: a for h, a in wanted.items() if a}
        if not wanted:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            pattern = '(' + '|'.join(sorted(wanted)) + ')'
            raw = []
            for v in voice:
                raw += wk.unbundle(os.path.join(tmp, 'raw'), pattern, under=v)
            exported = []
            for f in raw:
                if f.lower().endswith('.wem') and os.sep + 'vo' + os.sep in f:
                    exported += wk.export(f, os.path.dirname(f))
            for f in exported:
                m = WEM.match(os.path.splitext(os.path.basename(f))[0])
                if f.lower().endswith('.ogg') and m and m.group(3) in wanted:
                    h = m.group(3)
                    shutil.copy(f, os.path.join(audio_dir, h + '.ogg'))
                    with open(os.path.join(audio_dir, h + '.lab'), 'w', encoding='utf-8') as f:
                        f.write(idx['lines'][h]['text'])
                    written.append(h)
        with open(done, 'w', encoding='utf-8') as f:
            f.write(depot + '\n')
        log('%s/%s: %d lines' % (scene, actor, len(wanted)))
    # Every line with audio and no timing yet, this run's and any an earlier,
    # interrupted run left.
    aligned = os.path.join(data, 'aligned')
    os.makedirs(aligned, exist_ok=True)
    todo = []
    for lab in sorted(glob.glob(os.path.join(audio_dir, '*.lab'))):
        h = os.path.basename(lab)[:-len('.lab')]
        ogg = os.path.join(audio_dir, h + '.ogg')
        if os.path.exists(ogg) and not os.path.exists(os.path.join(aligned, h + '.TextGrid')):
            with open(lab, encoding='utf-8') as f:
                todo.append((h, ogg, f.read()))
    if todo:
        timed = aligner.align(todo, workdir=os.path.join(data, '_align'), log=log)
        for tg in glob.glob(os.path.join(data, '_align', 'aligned', '**', '*.TextGrid'), recursive=True):
            shutil.copy(tg, aligned)
        shutil.rmtree(os.path.join(data, '_align'), ignore_errors=True)
        log('aligned %d of %d lines' % (len(timed), len(todo)))
    return len(set(written))
