"""Command line.

    python -m lipsync_animator scene PROJECT_FOLDER mod\\myproject\\scenes\\talk.scene
    python -m lipsync_animator anims (--lines LINES.json --out OUT.anims | --sets SETS.json)
    python -m lipsync_animator make --set IN.anims.glb --out OUT.anims.glb
           (--lines LINES.json | --name f_... --audio LINE.wav --text "...")
           [--dictionary DICT.json] [--no-aligner] [--template f_...]
    python -m lipsync_animator import --glb OUT.anims.glb --anims IN.anims --out OUT.anims
    python -m lipsync_animator extract DATA [--sets 40]
    python -m lipsync_animator build-dictionary [--compact] --out DICT.json DATA [DATA ...]
    python -m lipsync_animator evaluate DATA

LINES.json is a list of {"name": "f_<16 hex digits>", "audio": "path", "text": "..."}.
In JSON, write Windows paths with forward slashes or doubled backslashes.
Audio can be .wav, .ogg, .flac or .wem. For the whole route from an audio file to
the game, see docs/usage.md."""
import argparse
import json
import os
import sys

from . import dictionary, fallback, glb, scene, sounds

MADE = 'lipsync_animator_made'      # the .glb's note of which animations make wrote


def read_json(path, what):
    """A JSON file, or a one-line error that names the file and the place."""
    try:
        return json.load(open(path, encoding='utf-8'))
    except FileNotFoundError:
        sys.exit('%s not found: %s' % (what, path))
    except json.JSONDecodeError as e:
        hint = ' (a single backslash in a Windows path? use / or \\\\)' if 'escape' in e.msg else ''
        sys.exit('%s is not valid JSON: %s, line %d, column %d%s' % (path, e.msg, e.lineno, e.colno, hint))


def read_lines(path):
    """LINES.json, checked: every line has a name, audio and text, and the
    audio paths survived JSON's escapes."""
    lines = read_json(path, 'the lines file')
    if not isinstance(lines, list):
        sys.exit('%s: expected a list of lines' % path)
    for k, x in enumerate(lines):
        absent = [key for key in ('name', 'audio', 'text') if not isinstance(x, dict) or key not in x]
        if absent:
            sys.exit('%s: line %d has no %s' % (path, k + 1, ', '.join(absent)))
        if any(ord(c) < 32 for c in x['audio']):
            sys.exit('%s: the audio path of %s holds a control character: write Windows paths '
                     'with / or \\\\, since JSON reads \\n, \\t and \\b as escapes'
                     % (path, x['name']))
    return lines


def files_for(a):
    from . import scene, wolvenkit
    return scene.Files(wolvenkit.get(a.wolvenkit, a.game or wolvenkit.DEFAULT_GAME,
                                     archives=getattr(a, 'archive', None) or ()))


def cmd_build(a):
    names = _track_names(a)
    # A line ID in hex, with or without f_, or part of a set's path.
    exclude = {x.lower()[2:] if x.lower()[:2] in ('f_', 'm_') else x.lower() for x in a.exclude or []}
    data = dictionary.load_lines(a.data, exclude=exclude)
    dic = dictionary.build(names, data)
    dictionary.save(dic, a.out, compact_form=a.compact)
    print('%d lines, %d sounds, %d moving tracks -> %s'
          % (dic['lines'], len(dic['phones']), len(dic['tracks']), a.out))


def cmd_make(a):
    import tempfile
    dic = dictionary.load(a.dictionary)
    if a.lines:
        lines = [(x['name'], x['audio'], x['text']) for x in read_lines(a.lines)]
    elif a.name and a.audio and a.text:
        lines = [(a.name, a.audio, a.text)]
    else:
        sys.exit('give --lines, or --name, --audio and --text')
    with tempfile.TemporaryDirectory() as tmp:
        files = None
        for i, (name, audio, text) in enumerate(lines):
            if not os.path.exists(audio):
                sys.exit('%s: audio file not found: %s' % (name, audio))
            if audio.lower().endswith('.wem'):
                files = files or files_for(a)
                ogg = files.wem_to_ogg(audio, os.path.join(tmp, str(i)))
                if not ogg:
                    sys.exit('%s: WolvenKit could not read %s' % (name, audio))
                lines[i] = (name, ogg, text)
            if sounds.frames(lines[i][1]) < scene.MIN_FRAMES:
                sys.exit('%s: the audio is shorter than 0.1 s: %s' % (name, audio))
        pron = fallback.load_pronunciations(a.pronunciations) if a.pronunciations else None
        timed = scene.time_lines(lines, dic, not a.no_aligner, pron)
        made = []
        for name, audio, text in lines:
            if not timed.get(name):
                print('%s: no words found, left out' % name)
                continue
            db, level = sounds.loudness(audio)
            n = sounds.frames(audio)
            face = dictionary.face(dic, timed[name], n, db, level, seed=scene.seed_for(name))
            made.append((name, face, n))
            print('%s: %.2f s, %d sounds' % (name, (n - 1) / sounds.FPS,
                                             sum(p != sounds.SILENCE for *_x, p in timed[name])))
    if not made:
        sys.exit('no line could be made, nothing written')
    names = glb.put_lines(a.set, a.out, made, a.template)
    # Note which animations are new, so that import keeps the others byte
    # for byte instead of writing them again.
    g, b = glb.read(a.out)
    g.setdefault('extras', {})[MADE] = [n for n, _f, _k in made]
    glb.write(a.out, g, b)
    print('wrote %s (%d animations, %d made)' % (a.out, len(names), len(made)))


def _track_names(a):
    if a.rig:
        rig = read_json(a.rig, 'the rig file')['Data']['RootChunk']
        return [n['$value'] for n in rig['trackNames']]
    for d in a.data:
        p = os.path.join(d, 'track_names.json')
        if os.path.exists(p):
            return json.load(open(p))
    sys.exit('no track names: run extract first, or give --rig')


def cmd_evaluate(a):
    from . import evaluate
    pron = fallback.load_pronunciations(a.pronunciations) if a.pronunciations else None
    evaluate.report(evaluate.run(_track_names(a), a.data, a.sets, a.seed, pron))


def cmd_extract(a):
    from . import extract, wolvenkit
    wk = wolvenkit.get(a.wolvenkit, a.game or wolvenkit.DEFAULT_GAME)
    n = extract.extract(wk, a.data, a.sets, a.seed, exclude=a.exclude or [])
    print('%d lines in %s' % (n, a.data))


def cmd_scene(a):
    pron = fallback.load_pronunciations(a.pronunciations) if a.pronunciations else None
    scene.run(a.project, a.scene, files_for(a), dictionary.load(a.dictionary),
              use_aligner=not a.no_aligner, pron=pron)


def cmd_anims(a):
    if a.sets:
        if a.lines or a.out or a.rig:
            sys.exit('give either --sets, or --lines and --out (with --rig): not both')
        sets = read_json(a.sets, 'the sets file')
        if not isinstance(sets, list) or not all(isinstance(s, dict) and 'out' in s for s in sets):
            sys.exit('%s: expected a list of sets, each with "out"' % a.sets)
    elif a.lines and a.out:
        sets = [{'out': a.out, 'lines': read_lines(a.lines)}]
        if a.rig:
            sets[0]['rig'] = a.rig
    else:
        sys.exit('give --sets, or --lines and --out')
    pron = fallback.load_pronunciations(a.pronunciations) if a.pronunciations else None
    scene.build_anims(files_for(a), sets, dictionary.load(a.dictionary),
                      use_aligner=not a.no_aligner, pron=pron)


def cmd_import(a):
    a.anims, a.out = os.path.abspath(a.anims), os.path.abspath(a.out)
    g, _b = glb.read(a.glb)
    made = (g.get('extras') or {}).get(MADE)
    files = files_for(a)
    if made:
        names = scene.replace_in_set(files, a.anims, os.path.abspath(a.glb), a.out, set(made))
        print('wrote %s: %d made, %d kept byte for byte' % (a.out, len(made), len(names) - len(made)))
    else:
        print('this .glb was not written by make, so every animation in it is written again')
        files.wk.import_glb(os.path.abspath(a.glb), a.anims, a.out)
        print('wrote', a.out)


def main(argv=None):
    p = argparse.ArgumentParser(prog='lipsync_animator', description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)

    def common(x, aligner_options=True):
        if aligner_options:
            x.add_argument('--dictionary', help='a sound dictionary from build-dictionary '
                                                '(default: the one shipped with the tool)')
            x.add_argument('--no-aligner', action='store_true',
                           help='time the sounds from the pauses and the text, even when the '
                                'aligner is installed')
            x.add_argument('--pronunciations',
                           help='a pronunciation list for --no-aligner: a CMU (cmudict.dict) or '
                                'Montreal Forced Aligner (.dict) file (default: the CMU list '
                                'shipped with the tool)')
        x.add_argument('--wolvenkit', help='WolvenKit folder: the app or the CLI, 9.1 or later '
                                           '(default: the app, then the CLI)')
        x.add_argument('--game', help='Cyberpunk 2077 folder (default: Steam\'s)')

    e = sub.add_parser('extract', help='pull training lines out of your game and align them')
    e.add_argument('data', help='folder to fill')
    e.add_argument('--sets', type=int, default=40, help='how many random quest sets (default 40)')
    e.add_argument('--seed', type=int, default=0)
    e.add_argument('--exclude', nargs='*', help='leave out sets whose path contains any of these')
    common(e, aligner_options=False)
    e.set_defaults(func=cmd_extract)

    b = sub.add_parser('build-dictionary', help='measure the sound dictionary from vanilla lines')
    b.add_argument('--rig', help='a face rig serialized to JSON by WolvenKit; '
                                 'default: the track names extract saved')
    b.add_argument('--out', required=True)
    b.add_argument('--exclude', nargs='*', help='lines to leave out, by animation name (f_ and 16 hex '
                                             'digits), or sets, by part of their path')
    b.add_argument('--compact', action='store_true', help='write only what making a line needs')
    b.add_argument('data', nargs='+', help='folders holding glb/, aligned/ and audio/')
    b.set_defaults(func=cmd_build)

    v = sub.add_parser('evaluate', help='score the method on speakers the dictionary never saw')
    v.add_argument('data', nargs='+')
    v.add_argument('--rig')
    v.add_argument('--sets', type=int, default=10, help='how many sets to leave out in turn')
    v.add_argument('--seed', type=int, default=1)
    v.add_argument('--pronunciations', help='a pronunciation list for the no-aligner score')
    v.set_defaults(func=cmd_evaluate)

    m = sub.add_parser('make', help='make lipsync animations for recorded lines, into an exported set')
    m.add_argument('--set', required=True, help='an exported .anims.glb to write into')
    m.add_argument('--out', required=True, help='the .anims.glb to write; then run import')
    m.add_argument('--lines', help='LINES.json, several lines at once')
    m.add_argument('--name', help='one line: its animation name, f_ and the line ID in 16 hex digits')
    m.add_argument('--audio', help='one line: its audio, .wav, .ogg, .flac or .wem')
    m.add_argument('--text', help='one line: its exact words')
    m.add_argument('--template', help='animation whose bone layout a new line borrows '
                                      '(default: the set\'s first)')
    common(m)
    m.set_defaults(func=cmd_make)

    n = sub.add_parser('anims', help='write .anims files straight from audio and text, for builds '
                                     'that wire their own scenes and lipmap')
    n.add_argument('--lines', help='LINES.json, for one .anims; give --out with it')
    n.add_argument('--out', help='the .anims to write, with --lines')
    n.add_argument('--rig', help='with --lines: the depot path of the head (.rig) the set is for '
                                 '(default: the tool\'s template head; made lines move no bones, '
                                 'so they suit any head)')
    n.add_argument('--sets', help='instead of --lines and --out: a JSON list of sets, all timed in '
                                  'one aligner run. Each is {"out": path, "lines": [...as in '
                                  'LINES.json...], "copy": [{"from": an .anims file or a depot path '
                                  'in the game\'s voice archives, "names": [animation names]}], '
                                  '"rig": depot path of the head}. "lines" may be empty, and "copy" '
                                  'and "rig" may be left out. "copy" moves existing animations in '
                                  'byte for byte, and the set then takes the head of the first set '
                                  'it copies from. Copy only when one character speaks both new and '
                                  'CDPR lines in the same scene: a character who speaks only CDPR '
                                  'lines should point at CDPR\'s own set instead')
    n.add_argument('--archive', action='append',
                   help='another .archive to look in for "copy" depot paths, such as a second '
                        'language\'s voice archive; may be given several times')
    common(n)
    n.set_defaults(func=cmd_anims)

    s = sub.add_parser('scene', help='give every line of a scene in a WolvenKit project its lipsync '
                                     'animation, and wire it up')
    s.add_argument('project', help='the WolvenKit project folder (the one with the .cpmodproj)')
    s.add_argument('scene', help='the scene inside the project, as WolvenKit shows its path, '
                                 'for example mod\\myproject\\scenes\\talk.scene')
    common(s)
    s.set_defaults(func=cmd_scene)

    i = sub.add_parser('import', help='write an .anims.glb from make into an .anims with WolvenKit')
    i.add_argument('--glb', required=True, help='the .anims.glb make wrote')
    i.add_argument('--anims', required=True, help='the .anims the .glb was exported from')
    i.add_argument('--out', required=True, help='the .anims to write: the new lines, and the set\'s '
                                                'other animations byte for byte')
    common(i, aligner_options=False)
    i.set_defaults(func=cmd_import)

    a = p.parse_args(argv)
    a.func(a)
