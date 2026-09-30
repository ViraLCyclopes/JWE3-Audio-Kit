# JWE3 Audio Kit

**Complete illustrated workflow:** [Open the printable guide](CUSTOM_AUDIO_GUIDE.html),
[read the Markdown source](CUSTOM_AUDIO_GUIDE.md), or
[open the workflow diagram](CUSTOM_AUDIO_WORKFLOW.svg). Covers end-user setup,
installation, custom WEMs, mod authoring, graph continuation, merging, and testing.

**Loader v6.1:** see [installation and daily workflow](END_USER_INSTALL.md),
[species authoring](USING_A_REPLACEMENT_SOUND_MOD.md), and
[fixes and validation notes](FIXES_20260906.md). The original v6 DLL had a startup
stack-buffer defect; use the corrected v6.1 build.
The merge needs **Python 3.11+**, four packages
(`python -m pip install -r requirements.txt`), and **your own cobra-tools
checkout** — the folder containing `ovl_tool_cmd.py`.

cobra-tools is **GPLv3**, so this kit deliberately does **not** redistribute it.
Get it from [github.com/OpenNaja/cobra-tools](https://github.com/OpenNaja/cobra-tools)
(Code → Download ZIP), unzip it anywhere, and note the folder that directly
contains `ovl_tool_cmd.py`. Then point the kit at it once:

```bat
python audio_kit_gui.py
```

Set **Cobra tools**, **Save settings**, then **Check (read-only)** or **Merge
registry**. The path is stored in `audio_tools.json` beside the scripts and used
by every command-line tool here. On the command line, `--cobra PATH` beats
`JWE3_COBRA_TOOLS` beats `audio_tools.json`.

`audio_tools.json` holds your machine's paths — it is gitignored and should never
ship with a mod.

Full walkthrough, including Python and the packages: [END_USER_INSTALL.md](END_USER_INSTALL.md#one-time-setup).

Give a donor-based species its **own** sounds without touching a single stock
file and without colliding with other mods.

## The problem this solves

A replacement-sound mod ships the **same media ids and the same bank id** as
stock, so renaming its file changes nothing — both banks fight over the same
slots. Real separation means re-ID'ing every id in both banks and re-homing the
events bank onto the new media ids.

And one thing gates the whole system: **`wwisemetadatasoundbanks` decides whether
an event is ever POSTED.** An event missing from it is never fired by the game,
no matter how correctly the motiongraph names it or the bank defines it — with no
error anywhere. That single fact is the difference between a silent animal and a
working one.

## Layout

| File | Role |
|---|---|
| `wwise_ids.py` | FNV-1 hashing, chunk walking, HIRC parsing, id remapping |
| `build_species_audio.py` | builds a species' two banks + its registry fragment |
| `merge_audio_registry.py` | folds every mod's fragment into one shared registry |
| `merge_registry.bat` | double-click version of the merge |
| `dll/` | the C sources for the loader and the diagnostic tools |

## Building a species' audio

**There is a GUI for this.** The motiongraph editor's **Audio Events** tab does
the build and the event rename together - see
[USING_A_REPLACEMENT_SOUND_MOD.md](USING_A_REPLACEMENT_SOUND_MOD.md). The command
line below is the same thing for scripting.

```bat
python build_species_audio.py --donor Indoraptor --prefix Indocapi --game "C:/.../Jurassic World Evolution 3" --out ./out --sound-mod ".../Canon Indoraptor Sounds/.../Indoraptor_media.ovl"
```

Other input modes:

* `--sounds <dir>` — your own `.wem` files, named after event suffixes
  (`HeroRoarA.wem`). Convert wav→wem in Wwise; see the cobra-tools audio guide.
  `sounds_available.txt` lists every name you can fill.
* `--marker-from <media.ovl>` — every sound becomes one distinctive clip. Use it
  to test by ear: random containers otherwise make an A/B comparison meaningless.

Copy the three outputs into `<Mod>/Audio/`, then run `merge_registry.bat`.

## Installing / uninstalling any audio mod

Run `merge_registry.bat` with the game closed. It rebuilds from the **stock**
registry, including when the last mod is removed. Conflicting declarations or
bank payloads stop the merge; identical duplicates are deduplicated. The merged
registry and its `audio_manifest.sha256` belong together. If the manifest is
missing or content has changed, v6.1 logs the mismatch, disables custom-bank
loading, and uses the stock registry. Rerun after changing bank/fragment contents
or after a stock metadata update; no merge is needed for an unchanged launch.

The local install has a `merge_registry.bat` beside `JWE3.exe`, forwarding to
the installed `JWE3 Audio Kit` scripts. The generated manifest is local to that
mod installation; species releases must not ship a pre-merged registry/manifest.

**Any change to a `.bnk` requires a re-merge.** The manifest hashes the bank
files, so replacing them - even a rebuild that leaves `.wmetasb.add`
byte-identical - invalidates it, and the loader then disables every mod's
custom audio and falls back to stock. The symptom is total silence.

`--check` validates inputs without writing game files. `--output DIR` builds a
staged registry/manifest pair; deploy both with the game closed. A successful
check does not regenerate or prove freshness of the installed pair.

## Rules that are not obvious

* **Never ship your own `audiometadata.ovl`.** It is one global file; only one mod
  could win and the rest go silent. Ship a `.wmetasb.add` fragment instead.
* **Some event names live in SHARED banks** (for Indoraptor: `RoarShortSelects`,
  `SocialCall`, `SocialReply`, `BreathLocomotion`, two `SinisterHissVoxLong`).
  Renaming those in the motiongraph orphans them in both directions — the sound
  goes silent. `report.json` lists which to rename and which to leave alone.
* **Keep the prefab's `AudioCore.Name` set to the DONOR.** It prefixes
  engine-generated events (footsteps, death, predation) that live in shared
  banks; changing it silences them.
* **`MotionGraphName` on the prefab selects the graph**, not
  `AnimationPackageNameOverride` alone.
* **A Sound stores its media's byte size** and Wwise refuses a voice whose size
  disagrees with the DIDX entry. The tool patches this; a hand-built bank must.
* **The real bank is the `..._bnk_b.aux`**, not cobra's 84-byte `.bnk` stub, and
  it must be trimmed to its walked chunk extent.

## Testing gotcha

**Posting an event yourself does NOT prove the game will post it.** A hand
`PostEvent` bypasses the registry gate entirely, so it happily plays events the
creature will never fire. Verify through the creature's actions in a park and
check stock audio and other mods too. The archived spy DLL sources are research
tools, not installation dependencies. Any future live spy must avoid file I/O
inside exception handlers and must not stack handlers from previous spies.

## Why the registry step cannot be removed

Traced by disassembly (JWE3 1.4.1, exe base `0x140000000`): the posting wrapper
at `exe+0x1742B0` bails out immediately if `[r9+0x170] == -1`, and on the success
path that same `+0x170` is passed as the first argument to the posting helper.
It is not a permission flag — it is the event's **resolved data**, and `-1` means
the registry never resolved it. Patching the branch out would hand the poster a
`-1` handle, which crashes rather than plays.

So declaring events is load-bearing. Merging fragments into one shared registry
is the correct design, not a workaround for a check that could be skipped.
