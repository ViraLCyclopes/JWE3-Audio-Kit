# Installing a mod with custom audio — end user instructions

Install with the game closed. Custom dinosaur audio needs three things: the
shared loader, the species mod, and a successful **registry merge**.

> ### 🡒 First time on this machine?
> Do **[One-time setup](#one-time-setup)** first — Python 3.11+, four packages,
> and a cobra-tools folder. It takes a few minutes and you never repeat it.
> cobra-tools is **not bundled** (it is GPLv3), so you supply your own copy and
> point the kit at it once with `python audio_kit_gui.py`.

Template you can copy into any mod release that ships its own sounds. Replace
`<ModName>` with your mod's folder name. See also
[current setup and fixes](FIXES_20260906.md).

## Everyday workflow

1. Close JWE3.
2. Install, update, or remove the audio mod under `Win64/ovldata/`.
3. **Run the merge** and require success — either
   `merge_registry.bat` beside `JWE3.exe`, or `python audio_kit_gui.py` →
   **Merge registry**.
4. Launch and test the animal's sounds in a park.

Repeat after changing **any** bank or fragment contents, and after a game update
changes stock audio metadata. No merge is needed before an unchanged launch.

Two things worth knowing up front, because both look like a broken mod:

* **The merge is not optional and not one-time.** It rebuilds from stock plus
  every fragment currently installed, so it must be re-run when a mod is
  **removed** as well as added.
* **Replacing a `.bnk` invalidates the manifest.** The loader then disables
  *every* mod's custom audio — not just that species — and falls back to stock.
  The symptom is total silence. Re-run the merge and it comes back.

The manifest is generated automatically; never edit it by hand, and keep
`audio_manifest.sha256` alongside `audiometadata.ovl` in `VLAudioLoader/Audio/`.

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

**Never done this before?** Complete [One-time setup](#one-time-setup) first —
this step needs Python and a cobra-tools folder, and will stop with a message
naming whichever is missing.

**Double-click `merge_registry.bat` in the game root with JWE3 closed.**
The root launcher forwards to the scripts in `JWE3 Audio Kit/`.

Or run `python audio_kit_gui.py` and press **Merge registry** — same thing, with
the output in a window and **Check (read-only)** available first.

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

## One-time setup

Do this once per machine, before the first merge. Three things: Python, four
packages, and a cobra-tools folder.

### 1. Python 3.11 or newer

Install from [python.org](https://www.python.org/downloads/) and tick
**Add python.exe to PATH** in the installer. 3.10 will not work — the constants
loader rejects it. Check it took:

```bat
python --version
```

If that says *'python' is not recognized*, PATH was not ticked — re-run the
installer and choose **Modify**.

### 2. The four packages

Open Command Prompt in the `JWE3 Audio Kit` folder and run:

```bat
python -m pip install -r requirements.txt
```

That is numpy, imageio, bitarray and pillow. `merge_registry.bat` checks the
Python version and these packages up front and names whatever is missing, so you
get a plain message instead of a traceback.

### 3. A cobra-tools folder

cobra-tools is **GPLv3**, so this kit deliberately does **not** ship a copy — you
supply your own. Download it from
[github.com/OpenNaja/cobra-tools](https://github.com/OpenNaja/cobra-tools)
(**Code → Download ZIP**, or clone it) and unzip it anywhere you like — it does
not need to live near the game or the kit.

What you want is the folder that directly contains **`ovl_tool_cmd.py`**. If you
unzipped it you will have something like
`…\Downloads\cobra-tools-master\cobra-tools-master\` — the inner folder is
usually the right one. The kit checks and tells you if you pick the wrong level.

Then point the kit at it:

```bat
python audio_kit_gui.py
```

1. **Cobra tools** → *Browse…* → select that folder. The status line turns green
   when it finds `ovl_tool_cmd.py`.
2. **Game root** → leave blank; it auto-detects from your Steam libraries. Only
   set it if you have several JWE3 installs.
3. **Save settings** — writes `audio_tools.json` beside the scripts, which every
   command-line tool here reads. You will not have to do this again.
4. **Check (read-only)** — validates everything without writing a single game
   file. A good first run.
5. **Merge registry** — does it for real.

The packages from step 2 need to be installed for the Python that runs
cobra-tools; if you only have one Python, that is already the case.

<details>
<summary>Command line instead of the GUI</summary>

Three ways to supply the path, in order of precedence — `--cobra PATH`, then the
`JWE3_COBRA_TOOLS` environment variable, then `audio_tools.json` beside the
scripts:

```json
{"cobra_tools": "D:/path/to/cobra-tools-master"}
```

The game root is found from the scripts' location or your Steam libraries;
override with `--game` or `JWE3_GAME`.

</details>

**Never ship `audio_tools.json` with a mod** — it holds your machine's paths. It
is gitignored for the same reason.

### Setup done — from here on

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

**"Cobra tools not found".**
The kit has not been told where cobra-tools is. See
[One-time setup step 3](#3-a-cobra-tools-folder): download it from
[github.com/OpenNaja/cobra-tools](https://github.com/OpenNaja/cobra-tools), then
run `python audio_kit_gui.py`, set **Cobra tools**, and press **Save settings**.

**"Configured Cobra directory is invalid".**
The path is set but that folder has no `ovl_tool_cmd.py` — almost always one
level off. A downloaded zip usually nests as
`cobra-tools-master\cobra-tools-master\`, and it is the **inner** one you want.
Open the folder and confirm you can see `ovl_tool_cmd.py` sitting in it. The GUI's
status line turns green when the path is right, so fix it there and re-save.

**"'python' is not recognized" or a Python version complaint.**
Python is missing or older than 3.11, or it was installed without
*Add python.exe to PATH*. Re-run the Python installer and choose **Modify** to
tick that box. Verify with `python --version`.

**A missing package (numpy, imageio, bitarray, pillow).**
Run `python -m pip install -r requirements.txt` from the `JWE3 Audio Kit` folder.
If you have several Python installs, use the same one cobra-tools runs under.

After fixing any of these, **rerun the command that failed** — a merge that did
not complete still needs to before you launch.

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
