"""Merge audio fragments from stock. --check is read-only; --output stages a build."""
from __future__ import annotations
import argparse
import copy
import hashlib
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from audio_paths import game_path, run_cobra as _run_cobra
from wwise_ids import chunks, parse_hirc, didx_entries

GAME_ARG = "Jurassic World Evolution 3"
OWNER = "VLAudioLoader"
COBRA = None
STOCK = "Content0/Audio/MetaData/audiometadata.ovl"
MERGED = "VLAudioLoader/Audio/audiometadata.ovl"
MANIFEST = "audio_manifest.sha256"

def run_cobra(args):
    return _run_cobra(args, COBRA)

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def inputs(ov):
    files = [ov / STOCK]
    for mod in sorted(ov.iterdir(), key=lambda p: p.name.casefold()):
        if not mod.is_dir() or mod.name.startswith(".") or mod.name.lower().startswith("content"):
            continue
        audio = mod / "Audio"
        if audio.is_dir():
            files.extend(sorted((p for p in audio.iterdir() if p.is_file() and
                                 p.name.lower().endswith((".bnk", ".wmetasb.add"))),
                                key=lambda p: p.name.casefold()))
    return files

def snapshot(ov):
    return {p.relative_to(ov).as_posix(): sha256(p) for p in inputs(ov)}

def canonical(node):
    # Cobra omits zero defaults and adds empty events containers.
    attrs = tuple(sorted((k, v) for k, v in node.attrib.items()
                         if k != "pool_type" and v not in ("0", "0.0", "false")))
    children = tuple(canonical(c) for c in node
                     if not (c.tag == "events" and not len(c) and not (c.text or "").strip()))
    return node.tag, attrs, (node.text or "").strip(), children

def bank_id(node):
    if node.tag != "bnkmetanew":
        raise ValueError("unexpected registry element: " + node.tag)
    value = int(node.attrib["fnv"])
    if not 0 < value <= 0xffffffff:
        raise ValueError("invalid bank ID: " + str(value))
    return value

def bank_ids(xml):
    return [bank_id(n) for n in ET.fromstring(xml).iter("bnkmetanew")]

def merge_xml(stock, fragments):
    root = ET.fromstring(stock)
    banks = root.find("bnks")
    if banks is None:
        raise ValueError("stock registry has no bnks element")
    owners = {bank_id(n): ("stock", canonical(n)) for n in banks}
    # Shipped metadata repeats some bank IDs. Preserve every stock row exactly;
    # uniqueness is enforced for mod contributions, not imposed on vanilla.
    stock_ids, declared = set(owners), {}
    for path in fragments:
        fragment = ET.fromstring("<fragment>" + path.read_text(encoding="utf-8-sig") + "</fragment>")
        if not len(fragment):
            raise ValueError(f"empty registry fragment: {path}")
        local = set()
        for node in fragment:
            bid = bank_id(node)
            if bid in local:
                raise ValueError(f"duplicate bank 0x{bid:08X} inside {path}")
            local.add(bid)
            if bid in stock_ids:
                raise ValueError(f"{path} claims stock bank 0x{bid:08X}")
            if bid in owners:
                owner, previous = owners[bid]
                if canonical(node) != previous:
                    raise ValueError(f"bank 0x{bid:08X} conflicts: {owner} and {path}")
                print(f"identical registry declaration deduplicated: {path} (0x{bid:08X})")
            else:
                owners[bid] = (str(path), canonical(node))
                banks.append(copy.deepcopy(node))
            declared.setdefault(path.parent, set()).add(bid)
    ET.indent(root, space="\t")
    return ET.tostring(root, encoding="unicode") + "\n", declared, stock_ids

def validate_banks(paths, declared, stock_ids):
    owners, found, objects, media = {}, {}, {}, {}
    for path in paths:
        if path.suffix.lower() != ".bnk":
            continue
        data = path.read_bytes()
        ch = chunks(data)
        if not data.startswith(b"BKHD") or len(data) < 24 or ch.get("BKHD", (0, 0))[1] < 8:
            raise ValueError(f"not a real BKHD soundbank: {path}")
        bid = struct.unpack_from("<I", data, 12)[0]
        if bid in stock_ids or bid not in declared.get(path.parent, set()):
            raise ValueError(f"bank 0x{bid:08X} has no mod-owned declaration in {path.parent}")
        digest = hashlib.sha256(data).hexdigest()
        if bid in owners:
            owner, previous = owners[bid]
            if digest != previous:
                raise ValueError(f"different banks share ID 0x{bid:08X}: {owner} and {path}")
        else:
            owners[bid] = (path, digest)
            for obj in parse_hirc(data):
                payload = bytes(data[obj.offset:obj.offset + 5 + obj.size])
                previous = objects.get(obj.obj_id)
                if previous and previous[1] != payload:
                    raise ValueError(f"HIRC ID 0x{obj.obj_id:08X} conflicts: {previous[0]} and {path}")
                objects[obj.obj_id] = (path, payload)
            base = ch.get("DATA", (0, 0))[0]
            for mid, offset, size in didx_entries(data):
                payload = bytes(data[base + offset:base + offset + size])
                previous = media.get(mid)
                if previous and previous[1] != payload:
                    raise ValueError(f"media ID 0x{mid:08X} conflicts: {previous[0]} and {path}")
                media[mid] = (path, payload)
        found.setdefault(path.parent, set()).add(bid)
    for folder, ids in declared.items():
        missing = ids - found.get(folder, set())
        if missing:
            raise ValueError(f"{folder}: declared banks have no .bnk files: {sorted(missing)}")

def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".vlaudio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def build(a):
    ov = game_path(a.game) / "Win64/ovldata"
    if not (ov / STOCK).is_file():
        raise ValueError(f"stock registry not found: {ov / STOCK}")
    before = snapshot(ov)
    files = [ov / p for p in before]
    fragments = [p for p in files if p.name.lower().endswith(".wmetasb.add")]
    # --work is an existing parent, never a directory we delete.
    with tempfile.TemporaryDirectory(prefix="vlaudio-", dir=a.work) as tmp:
        work = Path(tmp)
        extracted = work / "stock"
        out = run_cobra(["extract", ov / STOCK, "-o", extracted, "-g", GAME_ARG])
        xml_path = extracted / "wwisemetadatasoundbanks.wmetasb"
        if not all(s in out for s in ("Validating succeeded", "Collecting succeeded")) or not xml_path.is_file():
            raise RuntimeError("stock extraction failed:\n" + out[-4000:])
        merged, declared, stock_ids = merge_xml(xml_path.read_text(encoding="utf-8"), fragments)
        validate_banks(files, declared, stock_ids)
        print(f"Validated {len(fragments)} fragments; {len(bank_ids(merged))} total registry banks")
        if a.check:
            if snapshot(ov) != before:
                raise RuntimeError("audio inputs changed during validation; run again")
            print("--check: inputs valid; no game files written")
            return 0
        xml_path.write_text(merged, encoding="utf-8", newline="")
        staged = work / "audiometadata.ovl"
        shutil.copy2(ov / STOCK, staged)
        if list((ov / STOCK).parent.glob("audiometadata.ovs.*")):
            raise RuntimeError("stock metadata has OVS companions; update staging support first")
        built = work / "audiometadata_merged.ovl"
        out = run_cobra(["inject", staged, "-f", xml_path, "-o", built, "-g", GAME_ARG])
        if not built.is_file():
            raise RuntimeError("registry injection failed:\n" + out[-4000:])
        verify = work / "verify"
        out = run_cobra(["extract", built, "-o", verify, "-g", GAME_ARG])
        if not all(s in out for s in ("Validating succeeded", "Collecting succeeded")):
            raise RuntimeError("registry round trip failed:\n" + out[-4000:])
        back = ET.parse(verify / "wwisemetadatasoundbanks.wmetasb").getroot()
        if canonical(back) != canonical(ET.fromstring(merged)):
            raise RuntimeError("registry content changed on round trip (bank/event/parameter mismatch)")
        if snapshot(ov) != before:
            raise RuntimeError("audio inputs changed during build; nothing deployed, run again")
        manifest = dict(before)
        manifest[MERGED] = sha256(built)
        text = "VLAUDIO1\n" + "".join(f"{digest}\t{path}\n" for path, digest in sorted(manifest.items()))
        dest = Path(a.output).resolve() if a.output else ov / OWNER / "Audio"
        # Commit manifest last: a crash between files is detected at startup.
        atomic_write(dest / "audiometadata.ovl", built.read_bytes())
        atomic_write(dest / MANIFEST, text.encode("utf-8"))
        print(f"Verified all registry records; wrote {dest}")
        print("Restart after deploying the registry, manifest and matching loader.")
        return 0

def main():
    global COBRA
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--game", help="game root; otherwise auto-detect or use JWE3_GAME")
    ap.add_argument("--cobra", help="Cobra tools directory; alternatively JWE3_COBRA_TOOLS")
    ap.add_argument("--work", help="existing parent for private temporary scratch")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="validate without writing game files")
    group.add_argument("--output", help="build to staging instead of installing")
    a = ap.parse_args()
    COBRA = a.cobra
    try:
        return build(a)
    except (OSError, ValueError, RuntimeError, ET.ParseError, KeyError) as exc:
        print(f"Audio merge failed: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
