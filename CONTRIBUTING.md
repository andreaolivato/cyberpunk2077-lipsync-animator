# Contributing

Bug reports and pull requests are welcome.

## Reporting a bug

Include:

- the command you ran and everything it printed
- your WolvenKit and game versions
- for a lipsync animation that looks wrong in game: the audio file, its
  exact words, and what the mouth does wrong

## Changing the tool

If you change how the tool makes lipsync animations, include the `evaluate`
scores before and after (see [Rebuilding the dictionary](docs/rebuilding.md)).
Lower scores need a reason. Check the result in game too: the scores
measure only six parts of the mouth.

## Adding a language

The tool is English only.

The tool learns from the game's own lines: audio file, subtitle and CDPR's
lipsync animation. So it can only work for a language the game is dubbed
in. Each dubbed language has its own voice archive
(`lang_<code>_voice.archive`) with its own lipsync folder. Italian, for
example, has 5,504 lipsync sets under `base\localization\it-it\lipsync`.
Some of them have `enus` in their names, so check first that CDPR made them
for the Italian voices and did not copy the English ones.

A new language needs:

1. An aligner model, from [Montreal Forced Aligner's
   list](https://mfa-models.readthedocs.io/). English is `english_us_arpa`
   (`MODEL` in `aligner.py`).
2. Its sounds sorted into mouth groups in `dictionary.CLASSES` (closed
   lips, lower lip, rounded lips, open vowel, other vowel).
   `sounds.from_textgrid` also strips English stress marks (0, 1, 2) from
   sound names.
3. Its game files in place of the English ones: `lang_en_voice.archive`,
   `lang_en_text.archive`, `en-us` and `LANGUAGE` in `extract.py` and
   `scene.py`.
4. For use without the aligner: a pronunciation list (`--pronunciations`)
   and spelling rules (`LETTERS` and `DIGRAPHS` in `fallback.py`).
5. Its own dictionary. After steps 1 to 4, build it from that language's
   lines as in [Rebuilding the dictionary](docs/rebuilding.md), and put its
   `evaluate` scores in the pull request. The tool uses the English
   dictionary unless you give it another file with `--dictionary`. It
   cannot pick one by language yet.
