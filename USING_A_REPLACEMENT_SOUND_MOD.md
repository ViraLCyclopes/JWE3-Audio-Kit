# Giving one species a replacement sound mod's audio

Updated for loader **v6.1**. See [end-user setup](END_USER_INSTALL.md) for Python,
its four packages, the game-root merge launcher, and log checks. cobra-tools is
not bundled (it is GPLv3) - set your checkout once with `python audio_kit_gui.py`.
Close JWE3 before copying any mod files or merging; the loader scans once per launch.

Worked example: make **UltimasaurusCE** use the *Canon Indominus Rex Sounds*
replacement mod, while **vanilla Indominus keeps its stock voice**.

This is the common case — someone has already produced good sounds as a
*replacement* mod, and you want them on your species only.

---

## Why you can't just install it

A replacement sound mod ships `Content0/Audio/IndominusRex_media/IndominusRex_media.ovl`
— the **same file path, same bank id and same media ids as stock**. Installing it:

* overwrites the stock bank, so **every** Indominus in the game changes, not just yours
* lives in `Content0`, i.e. it edits base game data
* collides with any other mod that touches Indominus audio

Renaming the file changes nothing, because the ids inside are what the engine
matches on. Real separation means **re-ID'ing every id in both banks** and
re-homing the events bank onto the new media ids. That is what
`build_species_audio.py` does.

---

## Step 1 — build your species' own banks

### The GUI way (recommended)

Everything for steps 1 and 2 lives in one place — the **Audio Events** tab of the
motiongraph editor:

Open your existing motiongraph editor with the **Audio Events** tab. This GUI
lives in the full cobra-tools checkout, so
it is only available if you have one. The CLI bank builder below runs off the
kit and needs no such checkout.

1. open your species OVL, and set a staging folder in **Stage / Apply**
2. go to **Audio Events** and fill in the three fields at the top:
   * **Game folder** — your JWE3 install root
   * **Donor species** — `IndominusRex`
   * **New prefix** — `UltimasaurusCE`
3. in **1. Build this species' own sound banks**:
   * **Replacement sound mod** — browse to the downloaded
     `Content0/Audio/IndominusRex_media/IndominusRex_media.ovl`.
     Leave it blank to re-ID the **stock** audio instead.
   * **Output folder** — anywhere; the built banks land here
   * press **Build species audio banks**
4. it reports what it produced, and the log shows the builder's output

The tab searches for a nearby `JWE3 Audio Kit` folder and invokes its builder.
The builder uses the cobra-tools path you configured; override it with
`JWE3_COBRA_TOOLS` or `audio_tools.json` only if you want it to use a checkout of
your own instead. Copy the `.wmetasb.add` as well as both `.bnk` files even if the
GUI's status message only mentions banks.

### The command line way

Identical result, if you prefer it or want to script a batch of species:

```bat
cd "JWE3 Audio Kit"

python build_species_audio.py ^
    --donor IndominusRex ^
    --prefix UltimasaurusCE ^
    --game "C:/Program Files (x86)/Steam/steamapps/common/Jurassic World Evolution 3" ^
    --out ./out ^
    --sound-mod "C:/Users/<you>/Downloads/Canon Indominus Rex Sounds .../Content0/Audio/IndominusRex_media/IndominusRex_media.ovl"
```

### What you get

| file | goes to |
|---|---|
| `ultimasaurusce_events.bnk` | `<Mod>/Audio/` |
| `ultimasaurusce_media.bnk` | `<Mod>/Audio/` |
| `ultimasaurusce.wmetasb.add` | `<Mod>/Audio/`, discovered by the merge in step 3 |
| `report.json` | tells you which motiongraph strings to rename |

Nothing stock is touched, and nothing goes in `Content0`.

For your own WEMs, use `--sounds <folder>` with event-suffix filenames such as
`VoxRoarHero.wem`; `sounds_available.txt` lists recognized suffixes. The builder
now rejects unmatched/empty files and conflicting replacements of shared media.
If two events use the same media, supply the same replacement or replace only
one of them. Rebuild, copy the full output trio, and merge after every change.

**This produces a NON-replacement mod.** It consumes the replacement mod's audio
payload but re-IDs every id onto your prefix, so your species gets its own banks
and vanilla Indominus keeps its stock voice.

---

## Step 2 — point the motiongraph at the new event names

Your species' graph still fires the **donor's** event names
(`IndominusRex_VoxRoarHero`, `IndominusRex_GrowlShort`, …). Until those are
renamed to your prefix, the animal keeps using the stock bank and the new one is
never heard.

Same tab, next section down. The buttons are numbered in the order you press
them:

* press **2. Scan graph for audio events**
* tick the safe ones — the tab **greys out names that resolve from shared
  banks**; renaming one of those orphans the sound in both directions and it goes
  silent with no error
* press **Rename ticked events in staged family**
* press **Write registry fragment** if you did not already get one from step 1

`report.json` from step 1 lists exactly which names to rename and which to leave.

> **Longer prefixes depend on the graph-editing tool.** The audio bank builder
> accepts a longer prefix. A graph rename also needs relocation support. The
> inspected GUI still has a scan-time length guard, even though its apply path
> includes relocation. Do not assume the scan accepts a longer prefix; use a
> compatible editor/relocation workflow and verify every requested rename.

> **Leave `AudioCore.Name` on the DONOR** in the prefab. It prefixes
> engine-generated footstep and death events that live in shared banks; changing
> it silences them.

---

## Step 3 — merge the registry

**This step is not optional.** `wwisemetadatasoundbanks` decides whether an event
is ever *posted*. An event missing from it is never fired — no matter how correct
the bank and the motiongraph are. v6.1 reports missing or stale merge inputs in
the loader log, but the game still needs the registry declarations to post events.

Copy **all three outputs** to `<game>/Win64/ovldata/<Mod>/Audio/`, deploy your
verified staged graph/prefab changes, then double-click `merge_registry.bat`
beside `JWE3.exe` with the game closed. No GUI build/rename button substitutes
for this merge step.

It rebuilds from **stock**, including after the last mod is removed. Conflicting
declarations or bank payloads fail the merge; identical duplicates are deduplicated.
Run again after installing, removing, or changing audio files, and after stock
metadata updates. A failed merge needs its reported problem fixed first.

The result is a shared pair under `VLAudioLoader/Audio/`: `audiometadata.ovl`
and `audio_manifest.sha256`. The manifest hashes the banks, fragments, and
stock/merged metadata. Missing or mismatched inputs disable custom banks and
use stock metadata. Do not manually edit or distribute this generated pair with
your species mod; users generate it for their own installed mod combination.

---

## Step 4 — verify

1. **Launch and check the latest loader log section.** Look for `VLAudioLoader
   v6.1`, `Audio manifest verified`, each bank's `AKRESULT=1`, and the successful
   unique-bank count. An unexpected already-loaded result needs investigation;
   it is not the expected v6.1 automatic-loader path.
2. **Listen for the difference.** If you cannot tell the banks apart by ear,
   rebuild with `--marker-from` so every sound becomes one distinctive clip —
   random containers otherwise make an A/B test meaningless.
3. **Check vanilla is untouched.** Spawn a stock Indominus. It must still sound
   stock. If it changed, something was installed into `Content0`.

---

## Things that will waste your day

* **A bank that loads is not a bank that plays.** Loading succeeds long before
  anything is audible; the registry gate (step 3) is the usual reason for silence.
* **Not every name a graph uses is in that species' bank.** Some resolve from
  shared/common banks. Renaming those breaks them — hence the greyed-out entries.
* **Input OVLs and output banks are different.** Keep a downloaded replacement
  OVL with its hashed `.aux` companions while building: Cobra's extracted `.bnk`
  is a stub. The kit's generated `.bnk` outputs contain real BKHD banks and are
  installed directly with the `.wmetasb.add`; do not ship the extraction stubs.
* **A load failure needs its exact log result investigated.** Check the input
  files and manifest before assuming an ID clash or rebuilding the graph.
