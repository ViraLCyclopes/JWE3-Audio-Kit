"""Shared Wwise/OVL primitives for JWE3 audio work.

Everything here is derived from measurements recorded in the project notes:
  * a Wwise object/bank/event id is FNV-1 32-bit over the LOWERCASED name
  * the real bank is the '..._bnk_b.aux' companion, NOT cobra's 84-byte .bnk stub
  * a bank must be trimmed to its walked chunk extent or Wwise rejects it
"""
from __future__ import annotations
import struct
from dataclasses import dataclass


def fnv1_32(name: str) -> int:
    """Wwise id for a name. FNV-1 (not 1a), 32-bit, over the lowercased bytes."""
    h = 0x811C9DC5
    for b in name.lower().encode():
        h = (h * 0x01000193) & 0xFFFFFFFF
        h ^= b
    return h


def walked_extent(data: bytes) -> int:
    """End offset of the last well-formed chunk.

    Banks ship with trailing padding that Wwise treats as a malformed file, so
    every bank must be cut to this length before use.
    """
    off = 0
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        if not tag.isalpha():
            break
        size = struct.unpack_from("<I", data, off + 4)[0]
        if off + 8 + size > len(data):
            raise ValueError(f"truncated {tag!r} chunk at {off}")
        off += 8 + size
    return off


def chunks(data: bytes) -> dict[str, tuple[int, int]]:
    """{tag: (payload_offset, payload_size)}"""
    out, off = {}, 0
    while off + 8 <= len(data):
        tag = data[off:off + 4]
        if not tag.isalpha():
            break
        size = struct.unpack_from("<I", data, off + 4)[0]
        if off + 8 + size > len(data):
            raise ValueError(f"truncated {tag!r} chunk at {off}")
        if tag.decode() in out:
            raise ValueError(f"duplicate chunk {tag!r}")
        out[tag.decode()] = (off + 8, size)
        off += 8 + size
    return out


@dataclass
class HircObject:
    type_id: int
    offset: int      # start of the 5-byte header
    size: int        # body size as declared
    obj_id: int


EVENT = 4
SOUND = 2


def parse_hirc(data: bytes) -> list[HircObject]:
    """Walk the HIRC chunk. Raises if the walk does not land exactly on the end."""
    ch = chunks(data)
    if "HIRC" not in ch:
        return []
    base, size = ch["HIRC"]
    if size < 4:
        raise ValueError("HIRC has no object count")
    count = struct.unpack_from("<I", data, base)[0]
    pos, objs = base + 4, []
    for _ in range(count):
        if pos + 9 > base + size:
            raise ValueError("truncated HIRC object header")
        t = data[pos]
        sz = struct.unpack_from("<I", data, pos + 1)[0]
        if sz < 4 or pos + 5 + sz > base + size:
            raise ValueError("HIRC object exceeds chunk or has no ID")
        oid = struct.unpack_from("<I", data, pos + 5)[0]
        objs.append(HircObject(t, pos, sz, oid))
        pos += 5 + sz
    if pos != base + size:
        raise ValueError(f"HIRC walk ended at {pos}, chunk ends at {base + size}")
    return objs


def didx_entries(data: bytes) -> list[tuple[int, int, int]]:
    """[(media_id, offset_into_DATA, size)] from the DIDX chunk."""
    ch = chunks(data)
    if "DIDX" not in ch:
        return []
    base, size = ch["DIDX"]
    if size % 12 or "DATA" not in ch:
        raise ValueError("invalid DIDX extent or missing DATA")
    entries = [struct.unpack_from("<III", data, base + i * 12) for i in range(size // 12)]
    if len({e[0] for e in entries}) != len(entries):
        raise ValueError("duplicate media IDs in DIDX")
    if any(offset + length > ch["DATA"][1] for _, offset, length in entries):
        raise ValueError("DIDX media exceeds DATA chunk")
    return entries


def remap_ids(data: bytearray, mapping: dict[int, int], objs: list[HircObject],
              start: int) -> int:
    """Rewrite every 4-byte LE value that appears in `mapping`.

    Each object's 4-byte size field is protected, because a size that happens to
    equal an id would otherwise be corrupted and desynchronise the whole walk.
    """
    # Protect type and size, including writes which start before a header.
    protected = {k for o in objs for k in range(o.offset, o.offset + 5)}
    hits, i = 0, start
    while i + 4 <= len(data):
        if any(k in protected for k in range(i, i + 4)):
            i += 1
            continue
        v = struct.unpack_from("<I", data, i)[0]
        if v in mapping:
            struct.pack_into("<I", data, i, mapping[v])
            hits += 1
            i += 4
        else:
            i += 1
    return hits
