# cyberpunk2077-lipsync-animator

Generates lipsync animations for custom voice lines in Cyberpunk 2077 mods.
From an audio file and its subtitles (text), it builds a mouth animation
that shapes the words actually spoken, timed to the voice.

Most modders today reuse the lipsync animation of a vanilla line that
matches the length of their own. The mouth moves while the character talks,
but it shapes the words of the vanilla line.

This generator instead tries to match each sound of your audio with the
corresponding mouth shape. The result is an `.anims` file, the format the
game uses for lipsync animations. It can be imported and used in WolvenKit
easily (instructions below).

## Install

The tool runs on Windows, like WolvenKit.

1. [Python](https://www.python.org/downloads/) 3.12 to 3.15.
2. In a terminal: `pip install numpy soundfile pythonnet`
3. The [WolvenKit](https://github.com/WolvenKit/WolvenKit/releases) app, 9.1
   or later. If WolvenKit is not in `%LOCALAPPDATA%\Programs\WolvenKit`,
   add `--wolvenkit` and its folder. The tool also reads your installed
   game. If the game is not in Steam's default folder, add `--game` and its
   folder.
4. Recommended: [Montreal Forced
   Aligner](https://montreal-forced-aligner.readthedocs.io/). It finds exactly
   when each sound is spoken, so the lips are about twice as accurate.
   Install [Miniforge](https://github.com/conda-forge/miniforge) for your user
   only, open "Miniforge Prompt" and run:

       mamba create -n mfa -c conda-forge montreal-forced-aligner
       mamba run -n mfa mfa model download acoustic english_us_arpa
       mamba run -n mfa mfa model download dictionary english_us_arpa
       mamba run -n mfa mfa model download g2p english_us_arpa

5. This tool: download it and open a terminal in its folder.
   `python -m lipsync_animator --help` should list the commands.

> [!TIP]
> New to Python, or something not working? See
> [docs/install.md](docs/install.md) for step-by-step instructions and fixes for common problems.

## Usage

In WolvenKit, set up the scene as for any voiced mod: give each character a
voice tag (any number, different for each character), and add each line's
audio file and subtitle. Close the scene's tab, then run:

    python -m lipsync_animator scene "C:\Mods\MyMod" mod\mymod\scenes\talk.scene

The first part is your project folder. The second is the scene's path, as
WolvenKit's Project Explorer shows it. The tool makes a lipsync animation
for every line and links it to the line. Reopen the scene, then pack and install
as usual.

First, the tool copies each file it will change into a `lipsync_backup`
folder in your project. Keep a backup of your own as well.

Players of your mod need ArchiveXL, as for most voiced mods.

> [!TIP]
> For a more detailed tutorial, screenshots from WolvenKit, single-line
> usage, and recording tips for the audio, see
> [docs/usage.md](docs/usage.md).

## How good it is

The tool rebuilt the lines of ten game characters it had never seen, then
scored each one against CDPR's own animation. 1 means identical, 0 means
unrelated.

| Part of the mouth | With the aligner | Without | Borrowed animation |
|---|---|---|---|
| lips closing ("m", "b", "p") | 0.85 | 0.43 | 0.01 |
| jaw | 0.78 | 0.67 | 0.26 |
| lips rounding ("w", "oo") | 0.68 | 0.44 | 0.02 |
| lower lip under the teeth ("f", "v") | 0.85 | 0.49 | 0.02 |
| corners of the mouth | 0.67 | 0.53 | 0.09 |

The tool learned the mouth shape of each sound from 1,148 of the game's
own lines: it averaged what CDPR's animations do on that sound. This list
of sounds and shapes comes with the tool. It contains numbers only, no game
files. To build your own from your game, see
[docs/rebuilding.md](docs/rebuilding.md). The measurements behind it are in
[docs/dictionary.md](docs/dictionary.md) and
[docs/face-tracks.md](docs/face-tracks.md).

## Limits

- English only. To add a language, see
  [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-language).
- Only the mouth moves with the words, and the eyes blink. In CDPR's own
  lines the eyebrows and the direction of the eyes also move a little
  while the character talks. In lines made by this tool, they don't.
- Tested in game on game version 2.5, on Windows.

## Contributing

Bug reports and pull requests are welcome, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT, see `LICENSE`. The pronunciation list
`lipsync_animator/data/cmudict.dict` is the CMU Pronouncing Dictionary,
under its own BSD licence (`cmudict-LICENSE`).
This is an unofficial fan work and is not approved or endorsed by CD
PROJEKT RED. Cyberpunk 2077, its names, trademarks and game content belong
to CD PROJEKT RED.
