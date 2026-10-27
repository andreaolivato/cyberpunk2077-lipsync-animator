# The sound dictionary

The dictionary holds the mouth shape CDPR's animators used for each of the
39 English sounds, plus pauses, averaged over many game lines. A sound looks
different depending on the sounds around it, so each sound has a version for
each kind of neighbour.

To make a lipsync animation, the tool finds when each sound is spoken, puts
the matching shape there and blends from one to the next.

The dictionary that comes with the tool
(`lipsync_animator/data/dictionary.json`) is made from 1,148 lines of game
versions 2.31 and 2.5, base game and Phantom Liberty. It holds numbers
only, no game files.

## How it is made

For each game line:

1. Montreal Forced Aligner marks where each sound starts and ends, from the
   line's audio file and subtitle.
2. The tool reads the face 70 ms before the middle of each sound, because the
   mouth moves ahead of the voice
   ([details](face-tracks.md#the-mouth-moves-ahead-of-the-voice)). It keeps
   only the 187 tracks that move.
3. A gap of 0.15 s or more between words is a pause.
4. It averages all readings of the same sound with the same neighbours.

Louder speech also opens the jaw a little more (0.0018 per decibel).

Lines left out: placeholders that barely move, lines recorded by two
actors, and lines whose audio file and animation differ in length by more
than 0.3 s.

In the averages, "p", "b" and "m" have almost the same mouth shape, as do
"f" and "v", "sh", "ch" and "j", and "w" and "oo".

## Neighbours or whole words

The mouth shape of a sound depends on the sounds next to it. The tool
tried two ways to handle that, on ten characters the dictionary had never
seen. 1 means identical to CDPR's animation, 0 means unrelated.

- Neighbours: one average per sound for each combination of the sound
  before and after, in eight groups (closed lips, lower lip, rounded lips,
  open vowel, other vowel, other consonant, pause, start or end). A
  combination with fewer than 10 examples uses one neighbour, or none.
- Whole words: the full mouth movement of words seen at least 20 times.

| Part of the mouth | Plain average | Neighbours | Whole words |
|---|---|---|---|
| lips closing | 0.828 | 0.846 | 0.814 |
| jaw | 0.759 | 0.777 | 0.770 |
| lips rounding | 0.645 | 0.679 | 0.693 |
| lower lip under the teeth | 0.809 | 0.851 | 0.822 |
| lips pushed forward | 0.750 | 0.758 | 0.765 |
| corners of the mouth | 0.615 | 0.671 | 0.674 |

Neighbours beat the plain average on every part of the mouth. Whole words
are slightly better on rounding and corners, but worse on lip closing, and
they cannot help with invented names. A mix of the two gained at most
0.013, too little to see in game. So the tool uses neighbours alone.

The final scores are in the [README](../README.md#how-good-it-is).

## Without the aligner

The tool guesses when each sound is spoken:

1. Pauses are stretches of at least 0.15 s, 25 dB quieter than the speech.
2. Each word's sounds come from the CMU Pronouncing Dictionary. Unknown
   words are split into known words ("japantown") or sounded out from
   their spelling.
3. Each sound gets its typical length, scaled to fill the speech between
   pauses.

The jaw comes out nearly as good (0.67 against 0.78), because it follows
loudness. The lips come out about half as good (0.43 to 0.53), because the
lips have to close within 70 ms of the right moment.

## The rest of the face

A lipsync animation adds to the face and head the character already has:
each value is a change, and 0 changes nothing. So a line made by the tool
changes only what speech moves, and every character keeps their own neck,
head and expression.

- The lips, jaw, cheeks, tongue, nose, throat and neck muscles follow the
  sounds.
- Every other face control is 0, so the character's own expression stays.
- The head bones stay at rest for the whole line, so the neck and head keep
  their own shape and pose.
- The lipsync fades in from 0.3 s before the first sound and out over the
  last 0.3 s, as in the game's lines.
- The eyes blink about 1.2 s in, then every 1.3 to 2.1 s, as in the
  game's lines.
- Everything fades to rest over the first and last 0.1 s, as in every game
  line. Without it, the game opens the mouth once more after the last
  word.
