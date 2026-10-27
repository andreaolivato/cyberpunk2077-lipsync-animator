"""Time each line's sounds with Montreal Forced Aligner.

MFA needs Kaldi, which pip cannot install, so it lives in its own conda
environment (see README). This module finds it in this order:

1. the command in the LIPSYNC_MFA environment variable, for example
   `mamba run -n mfa mfa`
2. `mfa` on the PATH
3. `mamba run -n mfa mfa` from a Miniforge install in the user folder

The English models are downloaded once with
`mfa model download acoustic english_us_arpa`, the same for `dictionary`
and `g2p`. The g2p model guesses the sounds of words the dictionary does not
know, which every invented name needs."""
import glob
import os
import re
import shlex
import shutil
import subprocess
import tempfile

from . import sounds

MODEL = 'english_us_arpa'
MFA_ROOT = os.environ.get('MFA_ROOT_DIR') or os.path.join(os.path.expanduser('~'), 'Documents', 'MFA')
DICTIONARY = os.path.join(MFA_ROOT, 'pretrained_models', 'dictionary', MODEL + '.dict')


def command():
    if os.environ.get('LIPSYNC_MFA'):
        # posix=False keeps Windows backslashes; it also keeps the quotes
        # around a path with spaces, which the program name must not have.
        cmd = [t.strip('"') for t in shlex.split(os.environ['LIPSYNC_MFA'], posix=False)]
        return cmd, dict(os.environ)
    if shutil.which('mfa'):
        return ['mfa'], dict(os.environ)
    root = os.path.join(os.path.expanduser('~'), 'miniforge3')
    mamba = os.path.join(root, 'Library', 'bin', 'mamba.exe')
    if os.path.exists(mamba):
        env = dict(os.environ, MAMBA_ROOT_PREFIX=root)
        return [mamba, 'run', '-n', 'mfa', 'mfa'], env
    return None, None


def available():
    return command()[0] is not None


def small_dictionary(lines, out):
    """Write a copy of the aligner's English dictionary that holds only the
    words of these lines, and return its path; None if the dictionary is
    not downloaded. The aligner rebuilds its whole dictionary (about 200,000
    words) on every run: with only the line's words it gives the same timing
    for every sound, needs about a third of the memory and starts in about
    15 s instead of 40 s. The aligner guesses words missing from the copy
    from their spelling (the g2p model)."""
    if not os.path.exists(DICTIONARY):
        return None
    words = set()
    for _n, _a, text in lines:
        for token in re.findall(r"[\w'\-]+", text.lower()):
            for w in [token] + token.split('-'):
                words.update((w, w.strip("'")))
                # The aligner splits "hell're" into "hell" and "'re", or
                # "re" when that is the entry it finds.
                head, _sep, tail = w.partition("'")
                if tail:
                    words.update((head, "'" + tail, tail))
    with open(DICTIONARY, encoding='utf-8') as src, open(out, 'w', encoding='utf-8') as dst:
        for line in src:
            if line.split('\t', 1)[0] in words:
                dst.write(line)
    return out


def align(lines, workdir=None, jobs=4, log=print, full_dictionary=False):
    """lines: [(name, audio path, text)]. Returns {name: timed sounds}. A line
    the aligner could not place is missing from the result. The aligner
    gets a dictionary of only these lines' words (see small_dictionary),
    unless full_dictionary is set."""
    cmd, env = command()
    if cmd is None:
        raise RuntimeError('Montreal Forced Aligner not found; see README, or use --no-aligner')
    tmp = workdir or tempfile.mkdtemp(prefix='lipsync_')
    try:
        return _align(cmd, env, lines, tmp, jobs, log, full_dictionary)
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)


def _align(cmd, env, lines, tmp, jobs, log, full_dictionary):
    corpus = os.path.join(tmp, 'corpus', 'speaker')
    out = os.path.join(tmp, 'aligned')
    os.makedirs(corpus, exist_ok=True)
    for name, audio, text in lines:
        ext = os.path.splitext(audio)[1].lower()
        shutil.copy(audio, os.path.join(corpus, name + ext))
        with open(os.path.join(corpus, name + '.lab'), 'w', encoding='utf-8') as f:
            f.write(text)
    dictionary = None if full_dictionary else small_dictionary(lines, os.path.join(tmp, 'words.dict'))
    args = cmd + ['align', '--clean', '--single_speaker', '-j', str(jobs),
                  '--g2p_model_path', MODEL, os.path.join(tmp, 'corpus'), dictionary or MODEL,
                  MODEL, out]
    log('aligning %d line(s); the aligner takes about 15 s to start' % len(lines))
    try:
        res = subprocess.run(args, env=env, capture_output=True, text=True)
    except OSError as e:
        raise RuntimeError('aligner failed to start: %s' % e) from e
    if res.returncode != 0:
        raise RuntimeError('aligner failed:\n' + (res.stderr or res.stdout)[-2000:])
    found = {}
    for tg in glob.glob(os.path.join(out, '**', '*.TextGrid'), recursive=True):
        found[os.path.basename(tg)[:-len('.TextGrid')]] = sounds.from_textgrid(tg)
    return found
