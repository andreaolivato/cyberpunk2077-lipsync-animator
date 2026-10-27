# How the game moves a face

In Cyberpunk 2077, 414 controls called tracks move a face. Each holds
a number per frame, mostly between 0 and 1: how far the jaw is open, how
tightly the lips press together. A lipsync animation is these numbers over
time, at 30 frames a second. All the numbers here come from the game's own
lines.

## Track names

The names are in each head's rig file (`trackNames`). In an `.anims.glb`
exported by WolvenKit, each value's `trackIndex` is its position in that
list. Three heads, male and female, on game versions 2.31 and 2.5, all have
the same 414 names in the same order.

| Positions | Names end in | Move during speech? |
|---|---|---|
| 0 to 153 | nothing | only 0 to 12 and 100 to 124 (eyes, neck) |
| 154 to 239 | `AnimOverrideWeight` | yes |
| 240 to 380 | `LipsyncPoseOutput` | yes |
| 381 to 413 | `Wrnkl` | no |

The mouth is in the `LipsyncPoseOutput` tracks. Most have a partner in the
`AnimOverrideWeight` group that mirrors them.

## Control tracks

| Position | Name | During a line |
|---|---|---|
| 4 | `lipSyncEnvelope` | rises from 0 to 1 at the start, back to 0 at the end |
| 7 | `jaliJaw` | changes every frame, about -0.55 to 0.71 |
| 8 | `jaliLips` | changes every frame, about -0.51 to 0.92 |
| 9 | `muzzleLips` | 0 to 1 |

JALI is the research tool CDPR made the game's lipsync with.

## The mouth, part by part

The highest value seen in 62 lines, per part:

| Part | Tracks | Up to |
|---|---|---|
| lips pressing together | `lips_together_up`, `lips_together_dn` | 1.13 |
| jaw opening | `jaw_mid_open` | 0.60 |
| lips rounding | `lips_l_purse`, `lips_r_purse`, `lips_l_funnel`, `lips_r_funnel` | 0.56 |
| lips rolling in | `lips_suck_up`, `lips_suck_dn` | 0.60 |
| lips pushing out | `lips_puff_up`, `lips_puff_dn` | 0.35 |
| mouth corners | `lips_l_corner_up`, `_pull`, `_stretch`, `_corner_dn` and others, both sides | 0.42 |
| chin | `lips_chin_raise` | 0.22 |
| cheeks | `cheek_l_puff`, `cheek_r_puff` | 0.24 |
| tongue | `tongue_mid_*` | 1.03 |
| throat | `neck_throat_*`, `neck_tighten` | 0.81 |

## The mouth moves ahead of the voice

Measured on 204 lines by six characters (a generic NPC, Jackie, Takemura,
Panam, Judy and Rogue). A track matches a sound best 60 to 70 ms (about
two frames) before the middle of that sound:

| Sounds | Track | At the sound | 60 to 70 ms earlier | Other sounds |
|---|---|---|---|---|
| m, b, p | `lips_together_up` | 0.49 | 0.98 | 0.08 |
| f, v | `lips_suck_dn` | 0.24 | 0.37 | 0.03 |
| w, oo | `lips_l_purse` | 0.16 | 0.23 | 0.04 |
| sh, ch, j | `lips_l_funnel` | 0.15 | 0.21 | 0.00 |
| open vowels | `jaw_mid_open` | 0.23 | 0.30 | 0.18 |

The lead is the same for all six characters. The jaw follows the loudness
of the voice more than the sound itself. `jaliJaw` follows neither the
loudness nor any group of sounds.

## Reading the numbers

An animation stores a value only where a track changes. To compare tracks,
first fill in the frames in between with straight lines.
