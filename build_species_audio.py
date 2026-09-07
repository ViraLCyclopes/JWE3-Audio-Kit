"""Build a self-contained, non-conflicting audio bank pair for a donor-based JWE3 species.

The problem this solves: a replacement-sound mod ships the SAME media ids and the
SAME bank id as stock, so renaming its file changes nothing - both banks fight
over the same slots. Giving a new species its own audio means re-ID'ing every id
in both banks, and re-homing the events bank onto the new media ids.

Usage:
    python build_species_audio.py --donor Indoraptor --prefix Indocapi \
        --game "C:/.../Jurassic World Evolution 3" --out ./out

    # take the audio payload from a replacement-sound mod instead of stock:
        --sound-mod ".../Canon Indoraptor Sounds/.../Indoraptor_media.ovl"

    # build a marker bank where EVERY sound is one clip - defeats random
    # containers, so an A/B test by ear cannot be fooled by variation:
        --marker-from ".../Singing Indominus/.../IndominusRex_media.ovl"

Writes <prefix>_events.bnk and <prefix>_media.bnk for <Mod>/Audio/, plus a
report.json naming exactly which motiongraph strings to rename and which to
leave alone.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wwise_ids import (EVENT, chunks, didx_entries, fnv1_32, parse_hirc,
                        remap_ids, walked_extent)
from audio_paths import run_cobra

COBRA = None
GAME_ARG = "Jurassic World Evolution 3"
PACKS = ("Content0", "ContentPDLC3", "ContentPDLC1", "ContentDeluxe",
         "ContentPDLCRebirth")

# The engine builds these from AudioCore.Name; the motiongraph never mentions them.
ENGINE_SUFFIXES = ["FootPlantFront", "FootPlantRear", "PredatedKilled",
                   "PredatedSurvive", "Deathroll", "DeathRoll", "Footstep",
                   "Death", "Hurt"]


def extract(ovl, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    out = run_cobra(["extract", os.path.abspath(ovl), "-o", os.path.abspath(out_dir), "-g", GAME_ARG], COBRA)
    if not all(s in out for s in ("Validating succeeded", "Collecting succeeded")) or not os.listdir(out_dir):
        raise RuntimeError("extract failed for %s\n%s" % (ovl, out[-2000:]))
    return out_dir


def find_aux(d):
    hits = [f for f in os.listdir(d) if f.endswith("_bnk_b.aux")]
    if len(hits) != 1:
        raise RuntimeError("no '..._bnk_b.aux' in %s - that companion IS the bank" % d)
    return os.path.join(d, hits[0])


def load_bank(path):
    raw = Path(path).read_bytes()
    return bytearray(raw[:walked_extent(raw)])


def audio_ovl(ov, name):
    for pack in PACKS:
        p = os.path.join(ov, pack, "Audio", name, name + ".ovl")
        if os.path.exists(p):
            return p
    raise SystemExit("could not find %s.ovl in any content pack" % name)


def species_ovl(ov, donor):
    for realm in ("Land", "Water", "Air", "Shared"):
        p = os.path.join(ov, "Content0", "Dinosaurs", realm, donor, donor + ".ovl")
        if os.path.exists(p):
            return p
    raise SystemExit("could not find the species OVL for %s" % donor)


def recover_names(motiongraph, donor):
    """Event names live in the motiongraph - a bank stores no name strings."""
    txt = Path(motiongraph).read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"%s_[A-Za-z0-9_]+" % re.escape(donor), txt)))


def expand(suffixes):
    """A looping vocalisation posts <name>_start and <name>_stop as well as the
    bare name, so all three need name-derived ids or the sound is silent."""
    out = set()
    for s in list(suffixes) + ENGINE_SUFFIXES:
        out.update({s, s + "_start", s + "_stop", s + "_oc",
                    s + "_oc_start", s + "_oc_stop"})
    return out


def build_media(src_aux, prefix, marker_blob):
    b = load_bank(src_aux)
    ent = didx_entries(b)
    if not ent:
        raise RuntimeError("media bank has no DIDX chunk")

    used = {e[0] for e in ent}
    mapping = {}
    for mid, _, _ in ent:
        nv = fnv1_32("%s_wem_%08x" % (prefix.lower(), mid))
        while nv in used or nv == 0:
            nv = (nv * 0x01000193 + 1) & 0xFFFFFFFF
        used.add(nv)
        mapping[mid] = nv

    if marker_blob is None:
        base = chunks(b)["DIDX"][0]
        for i, (mid, _, _) in enumerate(ent):
            struct.pack_into("<I", b, base + i * 12, mapping[mid])
        struct.pack_into("<I", b, 0x0C, fnv1_32("%s_media" % prefix.lower()))
        return b, mapping

    head = bytearray(b[:chunks(b)["DIDX"][0] - 8])          # BKHD chunk only
    struct.pack_into("<I", head, 0x0C, fnv1_32("%s_media" % prefix.lower()))
    didx = b"".join(struct.pack("<III", mapping[m], 0, len(marker_blob))
                    for m, _, _ in ent)
    out = (head + b"DIDX" + struct.pack("<I", len(didx)) + didx
                + b"DATA" + struct.pack("<I", len(marker_blob)) + marker_blob)
    return bytearray(out), mapping



def reachable_media(bank, objs, donor, event_suffix):
    """Media ids an event can reach, without needing per-type format knowledge.

    Every named event here targets a random/sequence container rather than a
    single Sound, so mapping "event -> audio file" means walking the hierarchy.
    Rather than decode NodeBaseParams for each object type (version-specific and
    brittle), treat any 4-byte value inside an object body that equals another
    DEFINED object id as an edge, and breadth-first search to the Sounds.
    """
    from wwise_ids import SOUND as _SOUND
    by_id = {o.obj_id: o for o in objs}
    start = fnv1_32("%s_%s" % (donor, event_suffix))
    if start not in by_id:
        return set()
    seen, queue, media = {start}, [start], set()
    while queue:
        o = by_id[queue.pop()]
        if o.type_id == _SOUND:
            media.add(struct.unpack_from("<I", bank, o.offset + 9 + 5)[0])
            continue
        body_end = o.offset + 5 + o.size
        for i in range(o.offset + 9, body_end - 3):
            v = struct.unpack_from("<I", bank, i)[0]
            if v in by_id and v not in seen:
                seen.add(v)
                queue.append(v)
    return media


def apply_custom_sounds(media_bank, media_map, events_bank, donor, sounds_dir):
    """Swap in user-supplied .wem files, named <EventSuffix>.wem."""
    objs = parse_hirc(events_bank)
    ent = didx_entries(media_bank)
    data_off = chunks(media_bank)["DATA"][0]
    blobs = {mid: bytes(media_bank[data_off + off:data_off + off + size])
             for mid, off, size in ent}
    # Both banks have already been remapped. Keep the new IDs throughout.
    replacements = {}

    filled, unmatched = [], []
    for fn in sorted(os.listdir(sounds_dir)):
        if not fn.lower().endswith(".wem"):
            continue
        suffix = os.path.splitext(fn)[0]
        targets = reachable_media(events_bank, objs, donor, suffix)
        if not targets:
            unmatched.append(fn)
            continue
        wem = Path(sounds_dir, fn).read_bytes()
        if not wem:
            raise ValueError(f"empty replacement WEM: {fn}")
        n = 0
        for new_id in targets:
            if new_id in blobs:
                if new_id in replacements and replacements[new_id][1] != wem:
                    raise ValueError(f"{fn} and {replacements[new_id][0]} share media {new_id}; supply the same clip or only one replacement")
                replacements[new_id] = (fn, wem)
                blobs[new_id] = wem
                n += 1
        if not n:
            unmatched.append(fn)
        else:
            filled.append((suffix, n, len(wem)))

    if unmatched:
        raise ValueError("No replaceable media for: " + ", ".join(unmatched))

    head = bytearray(media_bank[:chunks(media_bank)["DIDX"][0] - 8])
    didx, data = bytearray(), bytearray()
    for mid, _, _ in ent:
        blob = blobs[mid]
        while len(data) % 16:                 # Wwise expects 16-byte alignment
            data.append(0)
        didx += struct.pack("<III", mid, len(data), len(blob))
        data += blob
    out = (head + b"DIDX" + struct.pack("<I", len(didx)) + bytes(didx)
                + b"DATA" + struct.pack("<I", len(data)) + bytes(data))
    return bytearray(out), filled, unmatched


def build_registry_fragment(ov, donor, prefix, owned_suffixes, work):
    """Emit this mod's registry contribution as a standalone fragment.

    wwisemetadatasoundbanks GATES posting: an event that is not declared there is
    NEVER fired by the game, however correctly the motiongraph names it and the
    bank defines it. But it is ONE GLOBAL FILE, so a mod must not ship its own
    whole copy - only one could ever win. Each mod emits a fragment instead, and
    merge_audio_registry.py folds them all into the shared loader's copy.
    """
    meta = extract(os.path.join(ov, "Content0", "Audio", "MetaData",
                                "audiometadata.ovl"), os.path.join(work, "meta"))
    reg = open(os.path.join(meta, "wwisemetadatasoundbanks.wmetasb"),
               encoding="utf-8").read()

    remap = {}
    for suffix in owned_suffixes:
        for v in (suffix, suffix + "_start", suffix + "_stop", suffix + "_oc",
                  suffix + "_oc_start", suffix + "_oc_stop"):
            remap[fnv1_32("%s_%s" % (donor, v))] = fnv1_32("%s_%s" % (prefix, v))

    donor_bank = fnv1_32("%s_events" % donor.lower())
    m = re.search(r'(\t\t<bnkmetanew fnv="%d".*?</bnkmetanew>\n)' % donor_bank,
                  reg, re.S)
    if not m:
        raise SystemExit("donor bank %s_events is not in the registry" % donor)

    def swap(mo):
        v = int(mo.group(2))
        return '%s="%d"' % (mo.group(1), remap.get(v, v))

    block = re.sub(r'(event_fnv|stop_start_fnv|start_fnv)="(\d+)"', swap, m.group(1))
    block = block.replace('fnv="%d"' % donor_bank,
                          'fnv="%d"' % fnv1_32("%s_events" % prefix.lower()), 1)
    block += ('\t\t<bnkmetanew fnv="%d" flag="0" unk_2="0">\n'
              '\t\t\t<type_name>SFX</type_name>\n'
              '\t\t\t<events pool_type="4" />\n'
              '\t\t</bnkmetanew>\n' % fnv1_32("%s_media" % prefix.lower()))
    rows = len(re.findall(r"<evententry", block))
    changed = sum(1 for v in re.findall(r'event_fnv="(\d+)"', m.group(1))
                  if int(v) in remap)
    return block, rows, changed


def build_events(src_aux, donor, prefix, names, media_map, media_sizes=None):
    b = load_bank(src_aux)
    objs = parse_hirc(b)
    defined = {o.obj_id for o in objs}
    event_ids = {o.obj_id for o in objs if o.type_id == EVENT}

    known, owned = {}, []
    for suffix in sorted(names):
        h = fnv1_32("%s_%s" % (donor, suffix))
        if h in event_ids:
            known[h] = "%s_%s" % (prefix, suffix)
            owned.append(suffix)

    mapping = {}
    named_ids = {oid: fnv1_32(name) for oid, name in known.items()}
    if len(set(named_ids.values())) != len(named_ids):
        raise RuntimeError("named events collide after hashing; choose another prefix")
    if set(named_ids.values()) & (defined | set(media_map) | set(media_map.values()) | {0}):
        raise RuntimeError("named event IDs collide with existing objects/media; choose another prefix")
    used = set(named_ids.values())

    def claim(v):
        while (v in used or v in defined or v in media_map
               or v in media_map.values() or v == 0):
            v = (v * 0x01000193 + 1) & 0xFFFFFFFF
        used.add(v)
        return v

    for o in objs:
        if o.obj_id in mapping:
            continue
        if o.type_id == EVENT and o.obj_id in known:
            nv = named_ids[o.obj_id]
            if nv in defined:
                raise RuntimeError("new id for %s collides with an existing id"
                                   % known[o.obj_id])
            used.add(nv)
        else:
            nv = claim(fnv1_32("%s_obj_%08x" % (prefix.lower(), o.obj_id)))
        mapping[o.obj_id] = nv

    full = dict(mapping)
    if set(mapping) & set(media_map):
        raise RuntimeError("donor reuses IDs across HIRC and media; requires typed remapping")
    full.update(media_map)                    # re-home sounds onto OUR media
    base = chunks(b)["HIRC"][0]
    refs = remap_ids(b, full, objs, base + 4)
    struct.pack_into("<I", b, 0x0C, fnv1_32("%s_events" % prefix.lower()))

    after = parse_hirc(b)                     # raises if the walk desynchronised
    if len(after) != len(objs):
        raise RuntimeError("object count changed during remap")
    if {o.obj_id for o in after} != set(mapping.values()):
        raise RuntimeError("ids did not remap cleanly")

    # A Sound carries the byte size of its media, and Wwise refuses the voice if
    # that disagrees with the DIDX entry. The events bank comes from STOCK, so
    # every size is a stock size - but a replacement-sound mod ships files of
    # DIFFERENT lengths, and a marker bank one length for all of them. Without
    # this patch the mismatched voices are silent on a real emitter while a bare
    # PostEvent can still appear to work.
    patched = 0
    if media_sizes:
        from wwise_ids import SOUND as _SOUND
        for o in parse_hirc(b):
            if o.type_id != _SOUND:
                continue
            body = o.offset + 9
            src = struct.unpack_from("<I", b, body + 5)[0]
            if src in media_sizes:
                cur = struct.unpack_from("<I", b, body + 9)[0]
                if cur != media_sizes[src]:
                    struct.pack_into("<I", b, body + 9, media_sizes[src])
                    patched += 1
    return b, owned, refs, patched


def pick_marker(ov, donor, marker_ovl, work):
    """Longest WEM the marker mod actually CHANGES versus its own stock bank.

    The marker source is often a DIFFERENT species than the donor (a Singing
    Indominus clip used to mark an Indoraptor-derived species, say), so it must
    be diffed against ITS OWN stock bank - diffing it against the donor's finds
    no shared media ids at all and silently reports 'identical to stock'.
    """
    marker_species = os.path.splitext(os.path.basename(marker_ovl))[0]
    if marker_species.lower().endswith("_media"):
        marker_species = marker_species[:-len("_media")]
    stock = load_bank(find_aux(extract(audio_ovl(ov, marker_species + "_media"),
                                       os.path.join(work, "stockmedia"))))
    mk = load_bank(find_aux(extract(marker_ovl, os.path.join(work, "marker"))))
    sbase = chunks(stock)["DATA"][0]
    mbase = chunks(mk)["DATA"][0]
    sm = {m: (o, z) for m, o, z in didx_entries(stock)}
    best = None
    for mid, off, size in didx_entries(mk):
        if mid not in sm:
            continue
        so, sz = sm[mid]
        if mk[mbase + off:mbase + off + size] != stock[sbase + so:sbase + so + sz]:
            if best is None or size > best[2]:
                best = (mid, off, size)
    if best is None:
        raise SystemExit("--marker-from has no changed media versus stock "
                         "%s_media; nothing distinctive to mark with"
                         % marker_species)
    return best[0], bytes(mk[mbase + best[1]:mbase + best[1] + best[2]])


def main():
    global COBRA
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--donor", required=True, help="stock species, e.g. Indoraptor")
    ap.add_argument("--prefix", required=True, help="new prefix, e.g. Indocapi")
    ap.add_argument("--game", required=True, help="JWE3 install root")
    ap.add_argument("--cobra", help="Cobra tools directory, or set JWE3_COBRA_TOOLS")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sound-mod", help="replacement-sound mod's <Donor>_media.ovl")
    ap.add_argument("--marker-from", help="media OVL to take a single marker clip from")
    ap.add_argument("--sounds", help="folder of <EventSuffix>.wem files to swap in")
    ap.add_argument("--work", help="scratch dir (default <out>/_work)")
    a = ap.parse_args()
    COBRA = a.cobra
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", a.prefix):
        ap.error("prefix must start with a letter and contain only ASCII letters, digits or underscores")
    if a.prefix.lower() == a.donor.lower():
        ap.error("prefix must differ from the donor")

    work = a.work or os.path.join(a.out, "_work")
    os.makedirs(a.out, exist_ok=True)
    ov = os.path.join(a.game, "Win64", "ovldata")

    ev_src = audio_ovl(ov, a.donor + "_events")
    md_src = a.sound_mod or audio_ovl(ov, a.donor + "_media")
    print("donor events : %s" % ev_src)
    print("media payload: %s" % md_src)

    ev_dir = extract(ev_src, os.path.join(work, "events"))
    md_dir = extract(md_src, os.path.join(work, "media"))

    marker = None
    if a.marker_from:
        mid, marker = pick_marker(ov, a.donor, a.marker_from, work)
        print("marker clip  : id 0x%08X, %d bytes (every sound becomes this)"
              % (mid, len(marker)))

    media, media_map = build_media(find_aux(md_dir), a.prefix, marker)
    media_sizes = {mid: size for mid, _, size in didx_entries(media)}

    mg_dir = extract(species_ovl(ov, a.donor), os.path.join(work, "species"))
    mgs = [f for f in os.listdir(mg_dir) if f.endswith(".motiongraph")]
    if not mgs:
        raise SystemExit("no .motiongraph inside the species OVL")
    graph_names = recover_names(os.path.join(mg_dir, mgs[0]), a.donor)
    print("graph names  : %d recovered from %s" % (len(graph_names), mgs[0]))

    suffixes = [n.split(a.donor + "_", 1)[1] for n in graph_names]
    events, owned, refs, patched = build_events(find_aux(ev_dir), a.donor, a.prefix,
                                                expand(suffixes), media_map, media_sizes)

    if a.sounds:
        media, filled, unmatched = apply_custom_sounds(media, media_map, events,
                                                       a.prefix, a.sounds)
        media_sizes = {mid: size for mid, _, size in didx_entries(media)}
        # sizes changed, so rebuild the events bank against the NEW payload
        events, owned, refs, patched = build_events(find_aux(ev_dir), a.donor, a.prefix,
                                                    expand(suffixes), media_map, media_sizes)
        print("\ncustom sounds:")
        for suffix, n, sz in filled:
            print("  %-34s -> %d media entries, %d bytes" % (suffix, n, sz))
        for fn in unmatched:
            print("  %-34s NO MATCHING EVENT - check the name against sounds_available.txt" % fn)

    owned_set = set(owned)
    graph_owned = sorted(s for s in suffixes if s in owned_set)
    graph_shared = sorted(s for s in suffixes if s not in owned_set)

    frag, frag_rows, frag_remapped = build_registry_fragment(
        ov, a.donor, a.prefix, graph_owned, work)
    fp = os.path.join(a.out, "%s.wmetasb.add" % a.prefix.lower())
    Path(fp).write_text(frag, encoding="utf-8", newline="")

    ep = os.path.join(a.out, "%s_events.bnk" % a.prefix.lower())
    mp = os.path.join(a.out, "%s_media.bnk" % a.prefix.lower())
    Path(ep).write_bytes(bytes(events))
    Path(mp).write_bytes(bytes(media))

    report = {
        "events_bnk": ep,
        "media_bnk": mp,
        "events_bank_id": "0x%08X" % fnv1_32("%s_events" % a.prefix.lower()),
        "media_bank_id": "0x%08X" % fnv1_32("%s_media" % a.prefix.lower()),
        "media_entries_reid": len(media_map),
        "events_named": len(owned),
        "id_references_rewritten": refs,
        "media_sizes_patched": patched,
        "motiongraph_RENAME": ["%s_%s" % (a.donor, s) for s in graph_owned],
        "motiongraph_LEAVE_ALONE": ["%s_%s" % (a.donor, s) for s in graph_shared],
        "prefab_MotionGraphName": "set this to your renamed graph resource",
        "prefab_AudioCore_Name": a.donor,
    }
    Path(a.out, "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with open(os.path.join(a.out, "sounds_available.txt"), "w") as fh:
        fh.write("# Name a .wem after any of these and pass --sounds <folder>.\n")
        fh.write("# e.g. HeroRoarA.wem replaces the audio behind %s_HeroRoarA\n\n"
                 % a.donor)
        for suffix in sorted(owned):
            fh.write(suffix + "\n")

    print("\nwrote %s\nwrote %s\nwrote %s" % (ep, mp, fp))
    print("  registry fragment: %d evententry rows, %d event fnvs remapped"
          % (frag_rows, frag_remapped))
    print("  -> copy all three into <Mod>/Audio/, then run merge_audio_registry.py")
    print("  events bank %s, media bank %s"
          % (report["events_bank_id"], report["media_bank_id"]))
    print("  %d media entries re-ID'd, %d events named, %d id references rewritten"
          % (len(media_map), len(owned), refs))
    print("  %d sound media-size fields corrected to match the new payload" % patched)
    print("\nRENAME these %d motiongraph strings to %s_*:" % (len(graph_owned), a.prefix))
    print("  (see report.json for the full list)")
    print("\nLEAVE ALONE these %d - they live in SHARED banks, and renaming them"
          % len(graph_shared))
    print("orphans the sound in both directions (this is what silences the roar):")
    for s in graph_shared:
        print("    %s_%s" % (a.donor, s))
    print("\nAlso: keep the prefab's AudioCore.Name = '%s'." % a.donor)
    print("It prefixes ENGINE-generated events (footsteps, death, predation) that")
    print("live in shared banks - changing it silences them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
