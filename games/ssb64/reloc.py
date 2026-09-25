"""SSB64 relocData container: table, vpk0 files, pointer chains.

relocData (ROM 0x1AC870, US) = table of (FILE_COUNT+1) 12-byte entries, then file blobs.
  entry: u32 dataOffset | 0x80000000 if vpk0, u16 internChainWord, u16 storedSizeWords,
         u16 externChainWord, u16 decompressedSizeWords
  blob:  vpk0 stream (or raw data), then at storedSize*4 one u16 file id per extern chain slot.
Pointers inside a file form linked chains: u32 = (nextWord << 16) | targetWord (0xFFFF ends).
"""
import os
import struct
import subprocess
import tempfile

RELOC_ROM = 0x1AC870
RELOC_END = 0xAC7340
VPK0 = os.environ.get("VPK0CMD", "C:/Users/andre/n64work/ssb64/tools/vpk0cmd.exe")


FILE_COUNT = 2132
TABLE_SIZE = (FILE_COUNT + 1) * 12


def parse(region):
    ents = []
    for i in range(FILE_COUNT + 1):
        w, intern, stored, extern, dec = struct.unpack_from(">IHHHH", region, i * 12)
        ents.append(dict(vpk0=bool(w & 0x80000000), data=w & 0x7FFFFFFF, intern=intern, stored=stored,
                         extern=extern, dec=dec))
    for i in range(FILE_COUNT):
        a = TABLE_SIZE + ents[i]["data"]
        b = TABLE_SIZE + ents[i + 1]["data"]
        ents[i]["blob"] = region[a:b]
    return ents


def vpk0(mode, data, cfg=None):
    """mode c/d. cfg = (method, offsets_tree, lengths_tree) forces the Huffman tree shapes: the game's
    decoder has room for only 64 tree nodes (both trees) and 20-deep stacks, so free-form trees crash it."""
    with tempfile.TemporaryDirectory() as d:
        i, o = os.path.join(d, "i.bin"), os.path.join(d, "o")
        open(i, "wb").write(data)
        if cfg and mode == "c":
            open(os.path.join(d, "i.vpk0_config"), "w").write("\n".join(str(x) for x in cfg))
        subprocess.run([VPK0, mode, i, o], check=True, stdout=subprocess.DEVNULL)
        return open(o, "rb").read()


def vpk0_info(blob):
    """(method, offsets_tree, lengths_tree) of a vpk0 stream."""
    with tempfile.TemporaryDirectory() as d:
        i = os.path.join(d, "i")
        open(i, "wb").write(blob)
        out = subprocess.run([VPK0, "i", i], check=True, capture_output=True, text=True).stdout
    kv = {l.split(":", 1)[0].strip(): l.split(":", 1)[1].strip() for l in out.splitlines() if ":" in l}
    method = 1 if "Method 1" in out else 0
    return [method, kv["Tree offsets"], kv["Tree lengths"]]


def file_data(e):
    """Decompressed file bytes (dec*4 long)."""
    if e["vpk0"]:
        d = vpk0("d", e["blob"])
    else:
        d = e["blob"][:e["dec"] * 4]
    return d[:e["dec"] * 4]


def extern_fids(e):
    """u16 file ids of the extern chain slots, in chain order."""
    n = len(chain(file_data(e), e["extern"])) if e["extern"] != 0xFFFF else 0
    base = e["stored"] * 4
    return [struct.unpack_from(">H", e["blob"], base + 2 * k)[0] for k in range(n)]


def chain(data, start):
    """[(pos_bytes, target_bytes)] following a pointer chain from word index `start`."""
    out = []
    w = start
    seen = set()
    while w != 0xFFFF and w * 4 + 4 <= len(data) and w not in seen:
        seen.add(w)
        v = struct.unpack_from(">I", data, w * 4)[0]
        out.append((w * 4, (v & 0xFFFF) * 4))
        w = v >> 16
    return out
