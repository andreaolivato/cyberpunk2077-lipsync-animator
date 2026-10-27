"""Give every line of a scene in a WolvenKit project its own lipsync
animation, and wire it up, in one step.

For a project made in the WolvenKit app (a folder with a .cpmodproj file and
source\\archive, source\\resources inside), and one .scene in it:

1. Read the scene: which character speaks which line. A line is found by its
   ID (`locstringId`), the key every other file uses for it too.
2. Find each line's audio through the project's voice-over maps
   (locVoiceoverMap: line ID -> .wem) and its text through its subtitle
   files (line ID -> text).
3. Make one lipsync animation per line, named `f_` plus the line ID in 16 hex digits,
   the name WolvenKit and the game use.
4. Write one .anims per character at
   mod\\<project>\\localization\\en-us\\lipsync\\<scene>\\<character>.anims.
   It holds the new animations, plus an unchanged copy of the animation each of
   the character's other lines already names (a vanilla line, whose audio
   is not in the project), taken from the set the scene gave the character
   before.
5. Point the scene at those files and every new line at its animation.
   Characters with no new line keep their set, and their lipmap entry.
6. Add the scene to the project's lipmap (the file that tells the game which
   character of which scene uses which .anims), and register the lipmap with
   ArchiveXL in resources\\<project>_lipsync.archive.xl.

The file and folder names match the ones WolvenKit's "Generate vanilla
lipsync anim sets" command writes. That command keeps the animations it
finds there.

Close the scene in WolvenKit before running this: the app keeps an open
file in memory and would save its old copy over the changes."""
import glob
import json
import os
import re
import shutil
import tempfile
import zlib

from . import aligner, dictionary, fallback, glb, sounds

LANGUAGE = 'en-us'
FPS = sounds.FPS
CACHE = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'lipsync_animator')
MIN_FRAMES = 4      # 0.1 s: shorter audio holds no line to animate
# A small vanilla set from the player's own game: its rig and one animation's
# bones are the template for every new .anims; none of its animations are kept.
TEMPLATE_SET = (r'base\localization\en-us\lipsync\base\media\quests\scenes'
                r'\sq021_03_quest_hook_b\civ_mid_m_04_enus_30.anims')


def fnv1a64(text):
    h = 0xCBF29CE484222325
    for b in text.encode('utf-8'):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def path_hash(depot):
    """FNV1a64 of a depot path as the game keys it: WolvenKit hashes the
    path in lower case with backslashes, whatever case the file has."""
    return fnv1a64(depot.replace('/', '\\').lower())


def label(ruid):
    return 'f_%016X' % int(ruid)


def cname(text):
    return {'$type': 'CName', '$storage': 'string', '$value': text}


def resref(path, flags='Soft'):
    return {'DepotPath': {'$type': 'ResourcePath', '$storage': 'string', '$value': path},
            'Flags': flags}


def depot_of(ref):
    v = ref.get('DepotPath', {}).get('$value') if isinstance(ref, dict) else None
    return v if isinstance(v, str) else None


class Files:
    """Reading and writing game-format files with WolvenKit's own code
    (wolvenkit.py)."""

    def __init__(self, wk):
        self.wk, self.game = wk, wk.game

    def read(self, path):
        """A game-format file as WolvenKit's JSON."""
        return self.wk.read(path)

    def read_all(self, folder, extensions=('.json', '.lipmap')):
        """Every game-format file with one of these extensions under folder,
        as {path: JSON}. A plain JSON file, or any file WolvenKit cannot
        read, is left out."""
        out = {}
        for d, _s, names in os.walk(folder):
            for name in names:
                if name.lower().endswith(extensions):
                    src = os.path.join(d, name)
                    try:
                        out[src] = self.wk.read(src)
                    except Exception:   # noqa: BLE001, WolvenKit raises its own .NET errors
                        pass
        return out

    def write(self, doc, path):
        """WolvenKit's JSON back into a game-format file at path."""
        self.wk.write(doc, path)

    def export(self, path, out_dir):
        return self.wk.export(path, out_dir)

    def wem_to_ogg(self, wem, out_dir):
        return next((f for f in self.wk.export(wem, out_dir) if f.lower().endswith('.ogg')), None)

    def from_game(self, depot, out_dir):
        """A file of the game's voice archives (base game, then Phantom
        Liberty), extracted into out_dir. None if neither has it."""
        from . import wolvenkit
        places = list(getattr(self.wk, 'extra_archives', []))
        if self.game:
            places = [os.path.join(self.game, 'archive', 'pc', sub, 'lang_en_voice.archive')
                      for sub in ('content', 'ep1')] + places
        for voice in places:
            if os.path.exists(voice):
                got = self.wk.unbundle(out_dir, wolvenkit.depot_regex(depot), under=voice)
                if got:
                    return got[0]
        return None


class Project:
    def __init__(self, folder):
        self.folder = folder
        projs = glob.glob(os.path.join(folder, '*.cpmodproj'))
        self.name = os.path.splitext(os.path.basename(projs[0]))[0] if projs else os.path.basename(folder)
        self.archive = os.path.join(folder, 'source', 'archive')
        self.resources = os.path.join(folder, 'source', 'resources')
        if not os.path.isdir(self.archive):
            raise SystemExit('%s is not a WolvenKit project (no source\\archive)' % folder)

    def file(self, depot):
        return os.path.join(self.archive, depot)

    def depot(self, path):
        return os.path.relpath(path, self.archive)


def scene_lines(doc):
    """[(line, actor)] for every line a character (not the player) speaks."""
    root = doc['Data']['RootChunk']
    actors = {a['actorId']['id']: a for a in root['actors']}
    return [(ln, actors[ln['speaker']['id']]) for ln in root['screenplayStore']['lines']
            if ln['speaker']['id'] in actors]


def index_project(files, archive=None):
    """Line ID -> wem depot path, and line ID -> text, from every voice-over
    map and subtitle file in the project. The tool makes English lines, so
    it leaves out a file whose folder or name carries another language
    (de-de, it-it...)."""
    audio, text = {}, {}
    for path, doc in files.items():
        rel = os.path.relpath(path, archive) if archive else path
        langs = re.findall(r'(?:^|[\\/_.])([a-z]{2}-[a-z]{2})(?=[\\/_.])', rel.lower())
        if any(x != LANGUAGE for x in langs):
            continue
        root = doc.get('Data', {}).get('RootChunk', {})
        data = root.get('root', {}).get('Data', {}) if isinstance(root.get('root'), dict) else {}
        kind = data.get('$type')
        for e in data.get('entries', []) or []:
            if kind == 'locVoiceoverMap' and 'stringId' in e:
                p = depot_of(e.get('femaleResPath')) or depot_of(e.get('maleResPath'))
                if p:
                    audio[str(e['stringId'])] = p
            elif 'stringId' in e and ('femaleVariant' in e or 'maleVariant' in e):
                text.setdefault(str(e['stringId']), e.get('femaleVariant') or e.get('maleVariant') or '')
    return audio, text


def emptied(doc):
    """A lipsync set's JSON with its animations, their data and the fallback
    data cleared: the same set and head, holding nothing."""
    r = doc['Data']['RootChunk']
    r['animations'], r['animationDataChunks'] = [], []
    for k in [k for k in r if k.startswith('fallback')]:
        r[k] = [] if isinstance(r[k], list) else (0 if isinstance(r[k], (int, float)) else None)
    return doc


def replace_in_set(cli, start, glb_path, out_path, made):
    """Write out_path: the set start with the animations named in made taken
    from glb_path, and every other animation of start moved across byte for
    byte. Importing the whole exported set would re-encode CDPR's
    animations too. Returns the names written."""
    # Read the start set before writing: out_path may be the same file.
    start_doc = cli.read(start)
    with tempfile.TemporaryDirectory() as tmp:
        empty = os.path.join(tmp, 'empty.anims')
        cli.write(emptied(json.loads(json.dumps(start_doc))), empty)
        g, b = glb.read(glb_path)
        g['animations'] = [a for a in g['animations'] if a['name'] in made]
        work = os.path.join(tmp, 'made.anims.glb')
        glb.write(work, g, b)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        cli.wk.import_glb(work, empty, out_path)
    doc = cli.read(out_path)
    root = doc['Data']['RootChunk']
    have = set(made)
    start_root = start_doc['Data']['RootChunk']
    others = {e['Data']['animation']['Data']['name']['$value'] for e in start_root.get('animations', [])}
    moved = move_animations(root, start_root, others - have, have)
    cli.write(doc, out_path)
    return sorted(made) + moved


def template(cli, cache):
    """An empty .anims and a one-animation .glb from the player's game, cached."""
    empty = os.path.join(cache, 'empty.anims')
    tglb = os.path.join(cache, 'template.anims.glb')
    if os.path.exists(empty) and os.path.exists(tglb):
        return empty, tglb
    os.makedirs(cache, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = cli.from_game(TEMPLATE_SET, os.path.join(tmp, 'game'))
        if not src:
            raise SystemExit('could not find %s in the game' % TEMPLATE_SET)
        shutil.copy(cli.export(src, os.path.join(tmp, 'export'))[0], tglb)
        cli.write(emptied(cli.read(src)), empty)
    return empty, tglb


def anim_name(line):
    v = line.get('femaleLipsyncAnimationName') or line.get('maleLipsyncAnimationName') or {}
    v = v.get('$value') if isinstance(v, dict) else v
    return v if v and v != 'None' else None


def source_set(cli, project, depot, tmp):
    """A lipsync set as an .anims file in tmp: a copy of the project's own
    file if it has one (the run may write over that file before it is
    read), else extracted from the game's voice archives. None if neither
    has it."""
    path = project.file(depot) if project else depot
    folder = os.path.join(tmp, 'sets', '%016X' % path_hash(depot))
    if os.path.exists(path):
        os.makedirs(folder, exist_ok=True)
        return shutil.copy(path, os.path.join(folder, os.path.basename(path)))
    return cli.from_game(depot, folder)


def handles(x, found):
    """Every HandleId inside x, as numbers. WolvenKit writes them as text."""
    if isinstance(x, dict):
        if str(x.get('HandleId', '')).lstrip('-').isdigit():
            found.append(int(x['HandleId']))
        for v in x.values():
            handles(v, found)
    elif isinstance(x, list):
        for v in x:
            handles(v, found)
    return found


def renumber(x, new_ids):
    """Give every handle and reference to it in x its new number, written
    the way it was (text or number)."""
    if isinstance(x, dict):
        for key in ('HandleId', 'HandleRefId'):
            v = x.get(key)
            if str(v).lstrip('-').isdigit() and int(v) in new_ids:
                x[key] = type(v)(new_ids[int(v)])
        for v in x.values():
            renumber(v, new_ids)
    elif isinstance(x, list):
        for v in x:
            renumber(v, new_ids)


def buffer_ids(x, found):
    """Every BufferId inside x, as numbers."""
    if isinstance(x, dict):
        if str(x.get('BufferId', '')).isdigit():
            found.append(int(x['BufferId']))
        for v in x.values():
            buffer_ids(v, found)
    elif isinstance(x, list):
        for v in x:
            buffer_ids(v, found)
    return found


def renumber_buffers(x, new_ids):
    if isinstance(x, dict):
        v = x.get('BufferId')
        if str(v).isdigit() and int(v) in new_ids:
            x['BufferId'] = type(v)(new_ids[int(v)])
        for w in x.values():
            renumber_buffers(w, new_ids)
    elif isinstance(x, list):
        for w in x:
            renumber_buffers(w, new_ids)


def move_animations(root, source_root, wanted, have):
    """Copy the animations named in wanted from one set's JSON into another,
    byte for byte: the animation entry and its data chunk are moved as they
    are, and only the handle numbers, the buffer number and the chunk index
    change. Never through glTF: an export and import re-encodes the head and
    neck bones against the target set's rig, which bakes the difference
    between two heads (neck length) into the animation. Returns the names
    moved."""
    import copy
    moved = []
    chunks = root.setdefault('animationDataChunks', [])
    next_id = max(handles(root, []) + [-1]) + 1
    for entry in source_root.get('animations', []):
        anim = entry['Data']['animation']['Data']
        name = anim['name']['$value']
        if name not in wanted or name in have:
            continue
        entry = copy.deepcopy(entry)
        new_ids = {}
        for h in handles(entry, []):
            new_ids[h] = next_id
            next_id += 1
        renumber(entry, new_ids)
        buf = entry['Data']['animation']['Data']['animBuffer']['Data']
        address = buf.get('dataAddress') or {}
        chunk = None
        if 'unkIndex' in address:
            chunk = copy.deepcopy(source_root['animationDataChunks'][address['unkIndex']])
        # Buffers inside the animation and its data chunk are numbered across
        # the whole file, so they get numbers no other buffer in it uses.
        next_buffer = max(buffer_ids(root, []) + [-1]) + 1
        new_buffers = {}
        for b in buffer_ids([entry, chunk], []):
            if b not in new_buffers:
                new_buffers[b] = next_buffer
                next_buffer += 1
        renumber_buffers([entry, chunk], new_buffers)
        if chunk is not None:
            address['unkIndex'] = len(chunks)
            chunks.append(chunk)
        root.setdefault('animations', []).append(entry)
        have.add(name)
        moved.append(name)
    return moved


def write_set(cli, empty, tglb, lines, out_path, keep=(), rig=None):
    """An .anims holding the given (name, face, frames) lines, plus the
    animations named in keep, [(.anims path, [names])], copied byte for
    byte. rig, a resource reference, replaces the set's rig: the head the
    set is for. Returns the animation names written."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    names = []
    if lines:
        with tempfile.TemporaryDirectory() as tmp:
            work = os.path.join(tmp, 'set.anims.glb')
            glb.put_lines(tglb, work, lines)
            g, b = glb.read(work)
            mine = {n for n, _f, _k in lines}
            g['animations'] = [a for a in g['animations'] if a['name'] in mine]
            glb.write(work, g, b)
            cli.wk.import_glb(work, empty, out_path)
        names = [n for n, _f, _k in lines]
    else:
        shutil.copy(empty, out_path)
    if keep or rig:
        doc = cli.read(out_path)
        root = doc['Data']['RootChunk']
        have = set(names)
        for src, wanted in keep:
            names += move_animations(root, cli.read(src)['Data']['RootChunk'], set(wanted), have)
        if rig:
            root['rig'] = rig
        cli.write(doc, out_path)
    return names


def update_lipmap(cli, project, files, scene_depot, voicetags, set_depots, header, log):
    """Put the scene's entry in the project lipmap that already has it, or in
    the first English one, or in a new mod\\<project>\\localization\\en-us\\<project>.lipmap.
    Returns the lipmap's depot path."""
    key = str(path_hash(scene_depot))
    lipmaps = sorted((p, d) for p, d in files.items()
                     if d.get('Data', {}).get('RootChunk', {}).get('$type') == 'animLipsyncMapping')
    def lang(d):
        v = d['Data']['RootChunk'].get('languageCodeName', {})
        return v.get('$value') if isinstance(v, dict) else None
    english = [(p, d) for p, d in lipmaps if lang(d) in (LANGUAGE, None, 'None')]
    chosen = next(((p, d) for p, d in english if key in d['Data']['RootChunk']['scenePaths']), None) \
        or (english[0] if english else None)
    if chosen:
        path, doc = chosen
    else:
        path = project.file(os.path.join('mod', project.name, 'localization', LANGUAGE,
                                         project.name + '.lipmap'))
        doc = {'Header': dict(header, ArchiveFileName=path), 'Data': {'Version': 195, 'BuildVersion': 0, 'EmbeddedFiles': [],
                                      'RootChunk': {'$type': 'animLipsyncMapping',
                                                    'cookingPlatform': 'PLATFORM_PC',
                                                    'languageCodeName': cname(LANGUAGE),
                                                    'sceneEntries': [], 'scenePaths': [],
                                                    'scenePreviewPaths': []}}}
    r = doc['Data']['RootChunk']
    # Characters this run did not touch keep their entries.
    pairs = {}
    if key in r['scenePaths']:
        old = r['sceneEntries'][r['scenePaths'].index(key)]
        pairs = {str(v): s for v, s in zip(old.get('actorVoiceTags', []), old.get('animSets', []))}
    for v, p in zip(voicetags, set_depots):
        pairs[str(v)] = resref(p)
    entry = {'$type': 'animLipsyncMappingSceneEntry', 'actorVoiceTags': list(pairs),
             'animSets': list(pairs.values())}
    if key in r['scenePaths']:
        r['sceneEntries'][r['scenePaths'].index(key)] = entry
    else:
        r['scenePaths'].append(key)
        r['scenePreviewPaths'].append(str(path_hash(scene_depot + 'preview')))
        r['sceneEntries'].append(entry)
    cli.write(doc, path)
    log('lipmap: %s' % project.depot(path))
    return project.depot(path)


def register_lipmap(project, lipmap_depot, log):
    """Make sure an ArchiveXL file in resources lists the lipmap."""
    want = lipmap_depot.replace('/', '\\').lower()
    for xl in glob.glob(os.path.join(project.resources, '**', '*.xl'), recursive=True):
        if want in open(xl, encoding='utf-8', errors='replace').read().replace('/', '\\').lower():
            log('lipmap already registered in %s' % os.path.relpath(xl, project.folder))
            return
    os.makedirs(project.resources, exist_ok=True)
    xl = os.path.join(project.resources, project.name + '_lipsync.archive.xl')
    text = open(xl, encoding='utf-8').read() if os.path.exists(xl) else ''
    if not text.strip():
        text = 'localization:\n  lipmaps:\n'
    text = text.rstrip('\n') + '\n    %s: %s\n' % (LANGUAGE, lipmap_depot)
    open(xl, 'w', encoding='utf-8', newline='\n').write(text)
    log('registered the lipmap in %s' % os.path.relpath(xl, project.folder))


def time_lines(lines, dic, use_aligner=True, pron=None, log=print):
    """{name: timed sounds} for [(name, audio, text)]: the aligner's timing
    when it is installed, the pause-and-text guess for any line it could
    not place."""
    timed = {}
    if use_aligner and aligner.available():
        try:
            timed = aligner.align(lines, log=log)
        except RuntimeError as e:
            # Installed but broken, for example without its English models.
            log('the aligner failed, so the tool times the sounds from pauses and text. '
                'The aligner said:\n' + str(e)[-600:])
    elif use_aligner:
        log('Montreal Forced Aligner not found, so the tool times the sounds from pauses and text')
    missing = [x for x in lines if not timed.get(x[0])]
    if missing:
        pron = pron or fallback.default_pronunciations()
        for name, audio, text in missing:
            timed[name] = fallback.time_sounds(dic, text, sounds.loudness(audio)[0], pron)
    return timed


def seed_for(name):
    """The blink seed for an animation: the line ID's text for an f_<hex>
    name, as the scene command uses, so both routes give the same blinks."""
    if len(name) == 18 and name[:2] in ('f_', 'm_'):
        try:
            return zlib.crc32(str(int(name[2:], 16)).encode())
        except ValueError:
            pass
    return zlib.crc32(name.encode())


def build_anims(cli, sets, dic=None, use_aligner=True, pron=None, cache=None, log=print):
    """Write .anims files from audio and text, with no WolvenKit project:
    for a build that writes its own scenes and lipmap.

    sets: [{'out': path of the .anims to write,
            'lines': [{'name': 'f_<16 hex>', 'audio': path, 'text': words}],
            'copy': [{'from': .anims path on disk, or a depot path in the
                      game's voice archives, 'names': [animation names]}]}]
    'copy' is optional: those animations go into the new set unchanged, for
    lines that keep an animation they already have. Audio can be .wav,
    .ogg, .flac or .wem. All lines are timed in one aligner run. Returns
    {out path: [animation names written]}.

    cli can also be a function that returns the Files to use. It is then
    called after the aligner has finished, so the aligner and WolvenKit
    are never in memory together."""
    dic = dic or dictionary.load()
    cache = cache or CACHE
    written = {}
    with tempfile.TemporaryDirectory() as tmp:
        lines = []
        for i, s in enumerate(sets):
            for ln in s.get('lines', []):
                audio = ln['audio']
                if not os.path.exists(audio):
                    raise SystemExit('%s: audio file not found: %s' % (ln['name'], audio))
                if audio.lower().endswith('.wem'):
                    if callable(cli):
                        cli = cli()
                    audio = cli.wem_to_ogg(audio, os.path.join(tmp, 'audio', str(len(lines))))
                    if not audio:
                        raise SystemExit('could not read the audio of %s' % ln['name'])
                if sounds.frames(audio) < MIN_FRAMES:
                    raise SystemExit('%s: the audio is shorter than 0.1 s: %s' % (ln['name'], ln['audio']))
                lines.append((ln['name'], audio, ln['text']))
        names = [n for n, _a, _t in lines]
        if len(set(names)) != len(names):
            raise SystemExit('the same animation name is given twice')
        timed = time_lines(lines, dic, use_aligner, pron, log) if lines else {}
        if callable(cli):
            cli = cli()
        audio_of = {n: a for n, a, _t in lines}
        empty, tglb = template(cli, os.path.join(cache, 'template'))
        for i, s in enumerate(sets):
            made = []
            for ln in s.get('lines', []):
                name = ln['name']
                if not timed.get(name):
                    log('  %s: no sounds found, left out' % name)
                    continue
                db, level = sounds.loudness(audio_of[name])
                n = sounds.frames(audio_of[name])
                made.append((name, dictionary.face(dic, timed[name], n, db, level,
                                                   seed=seed_for(name)), n))
            keep, rig = [], None
            for c in s.get('copy', []):
                src = source_set(cli, None, c['from'], os.path.join(tmp, 'copy%d_%d' % (i, len(keep))))
                if not src:
                    raise SystemExit('could not find %s on disk or in the game' % c['from'])
                source_names = {e['Data']['animation']['Data']['name']['$value']
                                for e in cli.read(src)['Data']['RootChunk'].get('animations', [])}
                absent = set(c['names']) - source_names
                if absent:
                    raise SystemExit('%s has no animation named %s' % (c['from'], ', '.join(sorted(absent))))
                keep.append((src, set(c['names'])))
                # The set takes the head of the first set it copies from.
                rig = rig or cli.read(src)['Data']['RootChunk'].get('rig')
            if s.get('rig'):
                rig = resref(s['rig'], 'Default')
            out = os.path.abspath(s['out'])
            got = write_set(cli, empty, tglb, made, out, keep, rig)
            log('%s: %d new, %d copied' % (out, len(made), len(got) - len(made)))
            written[out] = got
    return written


BACKUP_DIR = 'lipsync_backup'


def backup(project, scene_path, scene_depot, log):
    """Copy every file this run may change into
    <project>\\lipsync_backup\\<date and time>\\, keeping their paths: the
    scene, the project's lipmaps and ArchiveXL files, and the scene's
    lipsync folder. The folder is outside source\\, so WolvenKit does not
    pack it. Returns the backup folder."""
    import time
    scene_name = os.path.splitext(os.path.basename(scene_depot))[0]
    lipsync = os.path.join(project.archive, 'mod', project.name, 'localization', LANGUAGE,
                           'lipsync', scene_name)
    paths = [scene_path]
    paths += glob.glob(os.path.join(project.archive, '**', '*.lipmap'), recursive=True)
    paths += glob.glob(os.path.join(project.resources, '**', '*.xl'), recursive=True)
    paths += glob.glob(os.path.join(lipsync, '*'))
    stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
    dest, k = os.path.join(project.folder, BACKUP_DIR, stamp), 2
    while os.path.exists(dest):     # two runs in the same second
        dest, k = os.path.join(project.folder, BACKUP_DIR, '%s_%d' % (stamp, k)), k + 1
    for p in paths:
        if os.path.isfile(p):
            target = os.path.join(dest, os.path.relpath(p, project.folder))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(p, target)
    log('backed up the files it changes to %s' % os.path.relpath(dest, project.folder))
    return dest


def scene_depot_of(project, given):
    """The scene's depot path (mod\\...\\x.scene) from what the modder typed:
    that path, the same with WolvenKit's `archive\\` or `source\\archive\\`
    folder in front, or the file's full path."""
    p = given.replace('/', '\\').strip().strip('"')
    if os.path.isabs(p):
        inside = os.path.normcase(os.path.abspath(project.archive)) + os.sep
        if not os.path.normcase(os.path.abspath(p)).startswith(inside):
            raise SystemExit('%s is not inside the project\'s source\\archive folder' % given)
        p = os.path.relpath(p, project.archive)
    for prefix in ('source\\archive\\', 'archive\\'):
        if p.lower().startswith(prefix):
            p = p[len(prefix):]
    if p.startswith('..') or os.path.isabs(p):
        raise SystemExit('%s is not inside the project\'s source\\archive folder' % given)
    return p


def run(project_dir, scene_depot, cli, dic=None, use_aligner=True, pron=None, cache=None, log=print):
    project = Project(project_dir)
    dic = dic or dictionary.load()
    scene_depot = scene_depot_of(project, scene_depot)
    scene_path = project.file(scene_depot)
    if not os.path.exists(scene_path):
        raise SystemExit('no scene at %s' % scene_path)
    cache = cache or CACHE
    log('reading the project')
    files = cli.read_all(project.archive)
    scene = cli.read(scene_path)
    audio_of, text_of = index_project(files, project.archive)

    by_actor, missing, others = {}, [], {}
    undo = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for line, actor in scene_lines(scene):
                ruid = str(line['locstringId']['ruid'])
                wem, text = audio_of.get(ruid), text_of.get(ruid)
                if not wem and anim_name(line):
                    # A line whose audio is not in the project, usually a vanilla
                    # line: it keeps the animation it already names.
                    others.setdefault(actor['actorId']['id'], set()).add(anim_name(line))
                    continue
                why = None
                if not wem:
                    why = 'no audio'
                elif not text:
                    why = 'no text'
                elif not os.path.exists(project.file(wem)):
                    why = 'audio file not in the project'
                else:
                    ogg = cli.wem_to_ogg(project.file(wem), os.path.join(tmp, ruid))
                    if not ogg:
                        why = 'could not read the audio'
                    elif sounds.frames(ogg) < MIN_FRAMES:
                        why = 'the audio is shorter than %.1f s' % ((MIN_FRAMES - 1) / FPS)
                if why:
                    missing.append((actor['actorName'], ruid, why))
                    # A skipped line keeps the animation it names, if any.
                    if anim_name(line):
                        others.setdefault(actor['actorId']['id'], set()).add(anim_name(line))
                    continue
                by_actor.setdefault(actor['actorId']['id'], []).append((line, ruid, ogg, text))
            for name, ruid, why in missing:
                log('  skipped a line of %s (%s): %s' % (name, ruid, why))
            if not by_actor:
                raise SystemExit('no line of this scene has both audio and text in the project')
            # Only now, with something to write, copy what the run will change.
            undo.append(os.path.relpath(backup(project, scene_path, scene_depot, log), project.folder))

            everything = [(label(r), ogg, text) for rows in by_actor.values() for _l, r, ogg, text in rows]
            timed = time_lines(everything, dic, use_aligner, pron, log)

            empty, tglb = template(cli, os.path.join(cache, 'template'))
            root = scene['Data']['RootChunk']
            actors = {a['actorId']['id']: a for a in root['actors']}
            scene_name = os.path.splitext(os.path.basename(scene_depot))[0]
            folder = os.path.join('mod', project.name, 'localization', LANGUAGE, 'lipsync', scene_name)
            # The scene's list of lipsync sets. Characters this run does not
            # touch keep theirs; a character it does touch gets its new set in
            # its old slot, unless another character shares that slot.
            sets = list(root['resouresReferences'].get('lipsyncAnimSets') or [])
            def slot(actor):
                i = (actor.get('lipsyncAnimSet') or {}).get('id', -1)
                return i if isinstance(i, int) and 0 <= i < len(sets) else None
            users = {}
            for a in root['actors']:
                if slot(a) is not None:
                    users[slot(a)] = users.get(slot(a), 0) + 1
            voicetags, set_depots, new_count, used = [], [], 0, set()
            for actor_id, rows in by_actor.items():
                actor = actors[actor_id]
                voicetag = actor.get('voicetagId', {}).get('id')
                if not voicetag or str(voicetag) == '0':
                    log('  %s has no voice tag (voicetagId is 0), skipped: in WolvenKit, set it to '
                        'any number, different for each speaking character in the scene'
                        % actor['actorName'])
                    continue
                made = []
                for line, ruid, ogg, text in rows:
                    if not timed.get(label(ruid)):
                        log('  %s: no words found in "%s", the lipsync animation stays still'
                            % (label(ruid), text))
                    db, level = sounds.loudness(ogg)
                    n = sounds.frames(ogg)
                    face = dictionary.face(dic, timed.get(label(ruid)) or [], n, db, level,
                                           seed=zlib.crc32(ruid.encode()))
                    made.append((label(ruid), face, n))
                # This character's other lines keep their animations, copied
                # unchanged from the set the scene gave the character before.
                # The new set also takes that set's head (its rig), so the
                # character keeps its own.
                keep, src_depot, rig = [], None, None
                wanted = others.get(actor_id, set()) - {n for n, _f, _k in made}
                old = slot(actor)
                src_depot = depot_of(sets[old].get('asyncRefLipsyncAnimSet', {})) if old is not None else None
                src = source_set(cli, project, src_depot, tmp) if src_depot else None
                if src:
                    rig = cli.read(src)['Data']['RootChunk'].get('rig')
                    if wanted:
                        keep.append((src, wanted))
                elif wanted:
                    log('  %s: %d other line(s) name animations in no set found, left as they are'
                        % (actor['actorName'], len(wanted)))
                # One file per character: two names that clean to the same file
                # name ("Guard 1", "guard_1") get _2, _3 after the second.
                fname = ''.join(c if c.isalnum() or c in '_-' else '_' for c in actor['actorName']) or 'actor'
                base, k = fname, 2
                while fname.lower() in used:
                    fname, k = '%s_%d' % (base, k), k + 1
                used.add(fname.lower())
                depot = os.path.join(folder, fname + '.anims')
                names = write_set(cli, empty, tglb, made, project.file(depot), keep, rig)
                kept = len(names) - len(made)
                log('%s: %d new lipsync animation(s)%s -> %s' % (
                    actor['actorName'], len(made), ', %d kept from %s' % (kept, src_depot) if kept else '',
                    depot))
                ref = {'$type': 'scnLipsyncAnimSetSRRef', 'asyncRefLipsyncAnimSet': resref(depot),
                       'lipsyncAnimSet': {'DepotPath': {'$type': 'ResourcePath', '$storage': 'uint64',
                                                        '$value': '0'}, 'Flags': 'Default'}}
                if old is not None and users.get(old) == 1:
                    sets[old] = ref
                else:
                    sets.append(ref)
                    actor['lipsyncAnimSet'] = {'$type': 'scnLipsyncAnimSetSRRefId', 'id': len(sets) - 1}
                new_count += 1
                voicetags.append(voicetag)
                set_depots.append(depot)
                for line, ruid, _ogg, _text in rows:
                    line['femaleLipsyncAnimationName'] = cname(label(ruid))
                    line['maleLipsyncAnimationName'] = cname(label(ruid))
            if not new_count:
                raise SystemExit('nothing written')
            root['resouresReferences']['lipsyncAnimSets'] = sets
            cli.write(scene, scene_path)
            log('scene: %s now lists %d lipsync set(s)' % (scene_depot, len(sets)))
            lipmap = update_lipmap(cli, project, files, scene_depot, voicetags, set_depots,
                                   scene.get('Header', {}), log)
            register_lipmap(project, lipmap, log)
    except BaseException as e:
        if undo and not isinstance(e, SystemExit):
            log('stopped part way: to undo the changes, copy the files in %s back into the project'
                % undo[0])
        raise
    return set_depots
