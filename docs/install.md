# Install, step by step

For Windows, with a check after each step. You install everything for your
user only, without administrator rights.

## 1. Python

1. Download Python from [python.org](https://www.python.org/downloads/)
   and run the installer. Versions 3.12 to 3.15 work.
2. On its first screen, tick "Add python.exe to PATH" before clicking
   "Install Now". It is unticked by default, and without it Windows cannot
   find the commands below.

Check: open a new terminal (Start menu, type "Terminal") and run

    python --version

It should print `Python 3.` and a number from 12 to 15.

## 2. Python packages

In the same terminal:

    pip install numpy soundfile pythonnet

Check: it should end with "Successfully installed".

## 3. WolvenKit

Download `WolvenKitSetup-<version>.exe`, version 9.1 or later, from
[WolvenKit's release page](https://github.com/WolvenKit/WolvenKit/releases)
and run it. It installs into `%LOCALAPPDATA%\Programs\WolvenKit`, where the
tool looks for it.

If you use the zip version of WolvenKit instead, the tool cannot find it on
its own: add `--wolvenkit` and its folder to every command, for example
`--wolvenkit "D:\Tools\WolvenKit"`.

Check: WolvenKit opens.

## 4. The aligner (recommended)

The aligner finds exactly when each sound is spoken in your audio file. With
it, the lips match the words about twice as well.

1. Download `Miniforge3-Windows-x86_64.exe` from
   [Miniforge's release
   page](https://github.com/conda-forge/miniforge/releases) and run it.
2. Choose "Just Me" and keep the suggested folder
   (`C:\Users\<you>\miniforge3`): the tool looks for the aligner there.
   Leave the PATH box unticked.
3. From the Start menu, open "Miniforge Prompt" and run these one at a
   time. The first one downloads a lot and takes several minutes.

       mamba create -n mfa -c conda-forge montreal-forced-aligner
       mamba run -n mfa mfa model download acoustic english_us_arpa
       mamba run -n mfa mfa model download dictionary english_us_arpa
       mamba run -n mfa mfa model download g2p english_us_arpa

   When `mamba create` asks to proceed, answer `y`.

Check, in the same prompt:

    mamba run -n mfa mfa version

It should print a version number, such as `3.4.3`.

## 5. This tool

1. On this project's GitHub page, click Code, then Download ZIP.
2. Unzip it somewhere, for example `C:\Tools\lipsync-animator`.
3. Open that folder, right-click an empty part of it and choose "Open in
   Terminal". On Windows 10, hold Shift while right-clicking and choose
   "Open PowerShell window here".

Check:

    python -m lipsync_animator --help

It should list the commands: `scene`, `make`, `import` and the others.

When you run the tool on a scene and it prints `aligning 1 line(s); the
aligner takes about 15 s to start`, it has found the aligner. The number of
lines depends on the scene.

## If something goes wrong

- "python is not recognized": Python is not on the PATH. Run the Python
  installer again, choose Modify, and tick "Add Python to environment
  variables". Or type `py` instead of `python`, and `py -m pip` instead of
  `pip`.
- "No module named lipsync_animator": the terminal is not in the tool's
  folder. Open it there as in step 5.
- "No module named numpy" (or soundfile, or pythonnet): run step 2 again.
- "WolvenKit not found": WolvenKit is not in its usual folder. Add
  `--wolvenkit` and its folder.
- "the tool needs 9.1 or later": update WolvenKit.
- The tool works but never prints "aligning": it did not find the aligner.
  Check that Miniforge is in `C:\Users\<you>\miniforge3` and that step 4's
  check works. If it is elsewhere, put the command that runs it in the
  `LIPSYNC_MFA` environment variable, for example
  `D:\miniforge3\Library\bin\mamba.exe run -n mfa mfa`.
- "the aligner failed, so the tool times the sounds from pauses and text": the
  aligner is installed but did not run, often because a model from step 4
  is missing. The lines after it show the aligner's own error.
- "Cyberpunk 2077 not found": your game is not in Steam's default folder.
  Add `--game` and the game's folder, the one that contains `bin` and
  `archive`.
