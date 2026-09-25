"""Assemble a ROM: code image + relocData moved to 0x1000000 + replaced asset regions.

relocData no longer fits its retail slot once recompressed with our vpk0 encoder, so it
moves past the 16 MB mark and the 59 lui/addiu pairs (plus one data word) that build
lLBRelocTableAddr are patched. The old slot is zeroed.
"""
import struct

from . import reloc

NEW_RELOC_ROM = 0x1000000
PATCH_DATA_WORDS = [0x41F08]


def int32(x):
    return x & 0xFFFFFFFF


def crcs(buf, seed=0xA3886759, start=0x1000, end=0x101000):
    """CIC-610x boot checksum (same algorithm as the decomp's tools/n64crc.py)."""
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    for (d,) in struct.iter_unpack(">I", bytes(buf[start:end])):
        r = int32((d << (d & 0x1F)) | (d >> (32 - (d & 0x1F))))
        if int32(t6 + d) < t6:
            t4 = int32(t4 + 1)
        t3 ^= d
        t6 = int32(t6 + d)
        t2 ^= r if t2 > d else t6 ^ d
        t5 = int32(t5 + r)
        t1 = int32(t1 + (t5 ^ d))
    return int32((t6 ^ t4) + t3), int32((t5 ^ t2) + t1)


def find_base_sites(code_rom):
    """[(lui_off, lo_off)] for lui r,0x001B ... addiu/ori x,r,0xC870 in 0x1000..0x1AC870."""
    lo, hi = 0x1000, reloc.RELOC_ROM
    n = (hi - lo) // 4
    ins = struct.unpack_from(">%dI" % n, code_rom, lo)
    sites = []
    for i, w in enumerate(ins):
        if (w >> 26) in (0x09, 0x0D) and (w & 0xFFFF) == 0xC870:
            rs = (w >> 21) & 31
            for j in range(i - 1, max(0, i - 64), -1):
                v = ins[j]
                if v >> 26 == 0x0F and ((v >> 16) & 31) == rs and (v & 0xFFFF) == 0x001B:
                    sites.append((lo + j * 4, lo + i * 4))
                    break
    return sites


def patch_base(rom, new_base, sites):
    hi = (new_base + 0x8000) >> 16
    lo16 = new_base & 0xFFFF
    for lui, low in sites:
        w = struct.unpack_from(">I", rom, lui)[0]
        struct.pack_into(">I", rom, lui, (w & 0xFFFF0000) | hi)
        w = struct.unpack_from(">I", rom, low)[0]
        if (w >> 26) == 0x0D:   # ori: no sign extension
            struct.pack_into(">I", rom, lui, (struct.unpack_from(">I", rom, lui)[0] & 0xFFFF0000) | (new_base >> 16))
        struct.pack_into(">I", rom, low, (w & 0xFFFF0000) | lo16)
    for off in PATCH_DATA_WORDS:
        assert struct.unpack_from(">I", rom, off)[0] in (reloc.RELOC_ROM, new_base)
        struct.pack_into(">I", rom, off, new_base)


def build(code_rom, reloc_region, seed_rom=None):
    """code_rom: 16 MB image whose non-reloc regions are final. Returns the new ROM bytes."""
    rom = bytearray(code_rom[:0x1000000])
    slot = reloc.RELOC_END - reloc.RELOC_ROM
    if len(reloc_region) <= slot:   # fits the retail slot: no code patch at all
        rom[reloc.RELOC_ROM:reloc.RELOC_END] = reloc_region + bytes(slot - len(reloc_region))
        return rom
    sites = find_base_sites(rom)
    assert len(sites) == 59, len(sites)
    rom[reloc.RELOC_ROM:reloc.RELOC_END] = bytes(reloc.RELOC_END - reloc.RELOC_ROM)
    patch_base(rom, NEW_RELOC_ROM, sites)
    rom += reloc_region
    rom += bytes((-len(rom)) % 0x100000)
    return rom


def set_crc(rom, ref_header_rom):
    """Recompute CRC1/2 with whichever CIC seed reproduces ref_header_rom's CRCs."""
    want = struct.unpack_from(">II", ref_header_rom, 0x10)
    for seed in (0xF8CA4DDC, 0xA3886759, 0xDF26F436, 0x1FEA617A):
        if crcs(ref_header_rom, seed) == want:
            struct.pack_into(">II", rom, 0x10, *crcs(rom, seed))
            return seed
    raise RuntimeError("no CIC seed reproduces the reference CRCs")
