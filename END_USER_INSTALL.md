# Installing a mod with custom audio — end user instructions

For loader v6.1, install with the game closed. The merge requires **Python 3.11
or newer**, four Python packages (one `pip` command, below), and **your own
cobra-tools checkout** — it is not bundled, because cobra-tools is GPLv3 and this
kit does not redistribute it. Point the kit at yours once with
`python audio_kit_gui.py`. See [current setup and fixes](FIXES_20260906.md).
Keep the generated `audio_manifest.sha256` alongside `audiometadata.ovl` in
`VLAudioLoader/Audio/`. Re-run the merge after a stock metadata update too.

Template you can copy into any mod release that ships its own sounds. Replace
`<ModName>` with your mod's folder name.

Custom dinosaur audio needs the shared loader, the species mod, and a successful
registry merge. v6.1 logs missing or mismatched manifests and disables custom
bank loading until the merge is regenerated. Vanilla audio can still work.

## Everyday workflow

1. Close JWE3.
2. Install, update, or remove the audio mod under `Win64/ovldata/`.
3. Run **`merge_registry.bat` beside `JWE3.exe`** and require success.
4. Launch and test the animal's sounds in a park.

Repeat after changing any bank/fragment contents or after a game update changes
stock audio metadata. No merge is needed before an unchanged launch. The
manifest is generated automatically; never edit it by hand.

---

## What gets installed

| # | what | where |
|---|---|---|
| 1 | `xinput1_4.dll` | the **game root**, next to `JWE3.exe` |
| 2 | `VLAudioLoader/` folder | `Win64/ovldata/` |
| 3 | `<ModName>/` folder (including its `Audio/`) | `Win64/ovldata/` |
| 4 | the whole `JWE3 Audio Kit/` folder | game root; copy it whole |
| 5 | run `merge_registry.bat` | game root, after any audio install/update/removal |

Paths, for a default Steam install:

```
...\steamapps\common\Jurassic World Evolution 3\xinput1_4.dll
...\steamapps\common\Jurassic World Evolution 3\Win64\ovldata\VLAudioLoader\
...\steamapps\common\Jurassic World Evolution 3\Win64\ovldata\<ModName>\
```

### 1. `xinput1_4.dll` — the loader hook

Goes beside `JWE3.exe`, **not** in `Win64` and **not** in `ovldata`. Windows loads
it at process start, which is what lets the audio loader run early enough to
register banks.

If you already have another mod's `xinput1_4.dll`, do not overwrite it blindly —
two mods cannot both own that filename. Ask before replacing.

### 2. `VLAudioLoader` — the shared component

One copy, shared by every audio mod. It owns the merged sound registry. If another
audio mod already installed it, you do **not** need a second copy; keep the newer
one. The proxy handles automatic loading; the optional `VLAudioLoader.dll` is
for legacy Lua entry points and does not need to be called manually. Diagnostic
and spy DLLs are not required.

### 3. Your mod

Standard mod folder. The audio lives in `<ModName>/Audio/` and is three files:

```
<ModName>/Audio/<prefix>_events.bnk      the event definitions
<ModName>/Audio/<prefix>_media.bnk       the actual sounds
<ModName>/Audio/<prefix>.wmetasb.add     the registry fragment
```

All three must be present. The `.add` file is not optional — see below.

### 4. Run the registry merge

**Double-click `merge_registry.bat` in the game root with JWE3 closed.**
The root launcher forwards to the scripts in `JWE3 Audio Kit/`.

The game keeps one global registry, `wwisemetadatasoundbanks`, that decides
whether a sound event is ever *posted*. An event that is not in it is never
fired, no matter how correct the banks are. v6.1 now reports mismatched merge
inputs in `VLAudioLoader.log`; check the latest launch's messages.

The merge reads the **stock** registry plus every installed mod's `.wmetasb.add`
fragment, and writes the combined result. Because it always rebuilds from stock:

* installing another audio mod → run it again
* **removing** an audio mod → run it again
* updating bank or fragment contents, or stock audio metadata → run it again
* conflicting declarations or bank payloads stop the merge; identical duplicates
  are deduplicated

It writes **both** `audiometadata.ovl` and `audio_manifest.sha256` to
`Win64/ovldata/VLAudioLoader/Audio/`. Keep this generated pair together. It belongs
to your installed combination of mods, not to an individual species release.

Then restart the game. A failed merge needs the reported problem corrected;
rerunning alone will not resolve conflicting mod IDs.

### One-time setup

**1. Install Python 3.11 or newer** and tick *Add python.exe to PATH*. 3.10 will
not work — the constants loader rejects it.

**2. Install the four packages** the merge needs. Open Command Prompt in the
`JWE3 Audio Kit` folder and run:

```bat
python -m pip install -r requirements.txt
```

That is numpy, imageio, bitarray and pillow. `merge_registry.bat` checks for both
the Python version and these packages up front and tells you which is missing, so
you will not get a raw traceback.

### Third step — tell the kit where cobra-tools is

cobra-tools is **GPLv3** and is deliberately **not** shipped with this kit, so you
need your own copy: the folder containing `ovl_tool_cmd.py`, with the packages
above installed. Get it from the cobra-tools project.

The easy way — run it once and the setting is remembered:

```bat
python audio_kit_gui.py
```

Set **Cobra tools**, press **Save settings**, then **Check (read-only)** to
validate without writing anything, and **Merge registry** to apply. It writes
`audio_tools.json` beside the scripts, which every command-line tool here reads.

Prefer the command line? Any of these work, in this order of precedence:

```json
{"cobra_tools": "D:/path/to/cobra-tools-master"}
```

`--cobra PATH` beats `JWE3_COBRA_TOOLS` beats `audio_tools.json`. The game root is
found from the scripts' location or your Steam libraries; override with `--game`
or `JWE3_GAME`.

`audio_tools.json` holds *your* paths — never ship it with a mod.

From Command Prompt in the game root:

```bat
merge_registry.bat --game "C:\Path\Jurassic World Evolution 3" --cobra "D:\Tools\cobra-tools-master"
merge_registry.bat --check
```

`--check` validates inputs without writing game files. It does not regenerate
or prove freshness of an already installed registry/manifest; run a normal merge
for that. `--output DIR` builds a staged pair instead of installing it. Set
`VLAUDIO_NO_PAUSE=1` for unattended use. If Windows reports access denied under
Program Files, run from a terminal with write access to the installation.

---

## Uninstalling

Delete `<ModName>/` and run `merge_registry.bat` again. That drops your fragment
out of the registry cleanly.

Leave `xinput1_4.dll` and `VLAudioLoader/` if any other audio mod is still
installed; remove them only when yours was the last one.

---

## Troubleshooting

**The dinosaur is silent.**
Check the latest launch in `VLAudioLoader.log`: look for `VLAudioLoader v6.1`,
`Audio manifest verified`, and each bank's `AKRESULT=1`. A missing/mismatched
manifest disables custom banks and uses stock metadata. Rerun the merge, then
test creature-driven sounds; successful bank loading alone is not playback proof.

By far the most common cause is **a `.bnk` was replaced without re-running the
merge**. The manifest hashes the bank files, so *any* change to them invalidates
it — including a rebuild with the same prefix that leaves `.wmetasb.add`
byte-identical. The log names the file:

```
Audio content changed/missing: <Mod>/Audio/<prefix>_events.bnk
Audio manifest mismatch: install/remove/update detected. Run merge_registry.bat
Custom banks disabled until a valid registry merge is installed.
```

Note the failure is **all-or-nothing**: one stale bank disables *every* mod's
custom audio, not just that species. Re-run the merge and the line becomes
`Audio manifest verified (N files, SHA-256)`.

**It still sounds like the vanilla species.**
The mod is installed but its events are not being fired. Check that
`<ModName>/Audio/` really contains all three files.

**"Cobra tools not found" / "Configured Cobra directory is invalid".**
The kit has no cobra-tools path, or the one it has does not contain
`ovl_tool_cmd.py`. Run `python audio_kit_gui.py`, set **Cobra tools** to your
checkout and press Save settings. The message names the
first offending paths. Re-copy the whole `JWE3 Audio Kit` folder from the same
release. Then rerun the command
that failed. If a merge failed, it still needs to complete before launching.

**Another mod's audio broke after installing this.**
Run `merge_registry.bat` to rebuild for all installed mods. If it reports an ID
collision or a missing bank, correct the offending mod files first.

**The game will not start.**
Restore the previous loader and matching registry from your backup, and retain
the crash log/dump. The original v6 DLL had a startup stack-buffer defect fixed
in v6.1. Do not use the original v6 build. Other proxy conflicts or game errors
can also prevent startup; the crash evidence determines the cause.

---

## For mod authors

Nothing here touches a stock game file and nothing is installed into `Content0`,
so the workflow does not overwrite stock content. Re-merge after stock metadata
updates, and check loader compatibility after game updates. These conventions keep
it that way, and both matter for interoperability:

* **prefix everything** with your species token, so two mods never claim the same
  bank or event name
* **ship the `.wmetasb.add` fragment** rather than a pre-merged registry — a
  pre-merged one can erase other mods' registrations. Do not ship a generated
  manifest or your machine-specific `audio_tools.json` with a species mod; the
  cobra-tools is NOT shipped with the kit; each user points it at their own copy.
