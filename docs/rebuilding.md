# Rebuilding the dictionary

Optional: the tool ships with a dictionary made from game versions 2.31
and 2.5. To make your own from your game, with the aligner installed:

    python -m lipsync_animator extract DATA --sets 45
    python -m lipsync_animator build-dictionary --compact --out my-dictionary.json DATA
    python -m lipsync_animator evaluate DATA

`extract` copies the lines of 45 random quest characters from the game,
each character in one scene. The first run takes a few minutes. If it
stops part way, run it again: it carries on where it stopped.

`build-dictionary` makes the dictionary. To use it, add `--dictionary
my-dictionary.json` to the tool's commands.

`evaluate` tells you how good the dictionary is. It leaves out one
character at a time, builds a dictionary from the others, remakes the
left-out character's lines and compares them with CDPR's.

`DATA` holds the game's own files: keep it to yourself.
