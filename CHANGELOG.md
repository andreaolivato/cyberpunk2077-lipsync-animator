# Changelog

## 0.1.0 - 2026-10-27

First release.

- `scene` makes a lipsync animation for each line of a scene in your
  WolvenKit project, from the line's recording and its subtitle. Run it,
  pack the project, and in game each character's lips match the words in
  your recordings.
- Lines whose audio is not in your project, such as the game's own lines,
  keep the lipsync animation they already have.
- `scene` first saves a copy of each file it will change, in a
  `lipsync_backup` folder in your project.
- A new line moves the mouth, jaw, tongue and cheeks, and blinks. The rest
  of the face, the head and the neck stay as the game has them for that
  character.
- `anims` makes lipsync animations from audio and words for mods made
  with a script, instead of the more common WolvenKit.
- `make` and `import` add or replace single lines in an existing lipsync
  file. The file's other animations stay exactly as they were.
- With Montreal Forced Aligner installed, the tool finds when each sound
  is spoken. Without it, the tool estimates the timing from the pauses and
  the words.
- The tool comes with a sound dictionary built from 1,148 lines of game
  versions 2.31 and 2.5. With `extract`, `build-dictionary` and `evaluate`
  you can build and score a new one from your own game.
- Works with the WolvenKit app 9.1 or later, or the WolvenKit CLI 9.1 or
  later (the CLI needs .NET 10 installed). Python 3.12 to 3.15, on Windows.
