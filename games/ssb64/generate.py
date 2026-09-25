"""Clean room: spec + overrides -> clean reloc files -> clean relocData region.

    python -m games.ssb64.generate <code image rom> <out dir>

<code image rom> supplies ONLY the non-art bytes: code segments and the reloc files' structure
(display lists, vertices, animation, pointer chains). Every texture and palette byte range from
spec/textures.json and spec/palettes.json is overwritten with generated data before packing;
taint.py checks that none of the retail pixel bytes survive.
"""
import argparse
import json
import os
import struct
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from cleanroom.decomp.gen import detail, h32, unpack_alpha2, upsample_grid
from cleanroom.gfx import texfmt

from . import reloc

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
OVR = os.path.join(HERE, "overrides")
FMTN = {"RGBA": 0, "YUV": 1, "CI": 2, "IA": 3, "I": 4}
SIZN = {4: 0, 8: 1, 16: 2, 32: 3}
DECODABLE = {(0, 2), (0, 3), (3, 2), (3, 1), (3, 0), (4, 1), (4, 0), (2, 0), (2, 1)}


def base_image(t, hook=None):
    """(h, w, 4) float RGBA 0..255 for texture fact t."""
    w, h = t["w"], t["h"]
    if hook:
        img = hook(t)
        if img is not None:
            return img.astype(np.float32)
    g = t.get("grid")
    if g is None:
        img = np.full((h, w, 4), 128, np.float32)
    else:
        n = int(round(len(g) ** 0.5))
        img = upsample_grid(g, n, w, h)
        img[..., :3] *= detail(h32("ssb64", t["fid"], t["off"]), w, h)[..., None]
    if t.get("alpha2"):
        a = unpack_alpha2(t["alpha2"], w, h)
        img[..., 3] = np.where(a >= 128, 255, np.where(a > 0, a, 0))
    elif g is not None:
        img[..., 3] = 255
    return np.clip(img, 0, 255)


def quantize(pixels, k, seed=0):
    """k-means palette for (N, 4) float pixels -> (k, 4) uint8 palette."""
    rng = np.random.default_rng(seed)
    px = pixels.reshape(-1, 4).astype(np.float32)
    uniq = np.unique(np.round(px / 8) * 8, axis=0)
    if len(uniq) <= k:
        pal = np.zeros((k, 4), np.float32)
        pal[:len(uniq)] = uniq
        return np.clip(pal, 0, 255).astype(np.uint8)
    samp = px[rng.choice(len(px), min(len(px), 4096), replace=False)]
    cent = samp[rng.choice(len(samp), k, replace=False)].copy()
    for _ in range(12):
        dist = ((samp[:, None, :] - cent[None]) ** 2).sum(-1)
        lab = dist.argmin(1)
        for j in range(k):
            m = samp[lab == j]
            if len(m):
                cent[j] = m.mean(0)
    return np.clip(cent, 0, 255).astype(np.uint8)


def pal_bytes(pal):
    p = pal.astype(np.uint32)
    v = ((p[:, 0] >> 3) << 11) | ((p[:, 1] >> 3) << 6) | ((p[:, 2] >> 3) << 1) | (p[:, 3] >= 128)
    return v.astype(">u2").tobytes()


def pal_decode(pal):
    """What the RDP will show for our palette (5551 rounding), for index matching."""
    return np.frombuffer(pal_bytes(pal), ">u2")


def to_index(img, pal):
    px = img.reshape(-1, 4).astype(np.float32)
    p = pal.astype(np.float32)
    idx = np.empty(len(px), np.uint8)
    for s in range(0, len(px), 8192):
        idx[s:s + 8192] = ((px[s:s + 8192, None, :] - p[None]) ** 2).sum(-1).argmin(1)
    return idx.reshape(img.shape[:2])


def generate_bytes(textures, palettes, hook=None):
    """{(fid, off): bytes} for every texture and palette range."""
    out = {}
    by_pal = {}
    for t in textures:
        if t["fmt"] == "CI" and t.get("pal"):
            by_pal.setdefault((t["pal"][0], t["pal"][1]), []).append(t)
    imgs = {}
    for t in textures:
        imgs[(t["fid"], t["off"])] = base_image(t, hook)
    # palettes: quantize all textures that use them together
    pal_count = {(p["fid"], p["off"]): p["nbytes"] // 2 for p in palettes}
    made_pal = {}
    for key, ts in by_pal.items():
        count = pal_count.get(key, 16 if ts[0]["siz"] == 4 else 256)
        k = min(count, 16 if ts[0]["siz"] == 4 else 256)
        allpx = np.concatenate([imgs[(t["fid"], t["off"])].reshape(-1, 4) for t in ts])
        pal = quantize(allpx, k, seed=h32(*key))
        full = np.zeros((count, 4), np.uint8)
        full[:k] = pal
        made_pal[key] = pal
        out[key] = pal_bytes(full)
    for key, n in pal_count.items():
        if key not in out:   # palette nobody links to: neutral ramp
            ramp = np.linspace(0, 255, n)
            out[key] = pal_bytes(np.stack([ramp, ramp, ramp, np.full(n, 255)], -1).astype(np.uint8))
    for t in textures:
        key = (t["fid"], t["off"])
        fmt, siz = FMTN.get(t["fmt"], 0), SIZN[t["siz"]]
        img = imgs[key]
        if (fmt, siz) not in DECODABLE:
            b = bytes([0x80]) * t["nbytes"]
        elif fmt == 2:
            pal = made_pal.get((t["pal"][0], t["pal"][1])) if t.get("pal") else None
            if pal is not None:
                idx = to_index(img, pal)
            else:   # no palette known: index ramp from luminance
                lum = img[..., :3].mean(-1) / 255.0
                idx = np.clip(lum * (15 if siz == 0 else 255), 0, 255).astype(np.uint8)
            b = texfmt.encode(np.stack([idx] * 4, -1), 2, siz)
        else:
            b = texfmt.encode(img.astype(np.uint8), fmt, siz)
        b = b[:t["nbytes"]] + bytes(max(0, t["nbytes"] - len(b)))
        out[key] = b
    return out


def apply(files_data, ranges):
    """Overwrite ranges into per-file bytearrays."""
    for (fid, off), b in ranges.items():
        d = files_data[fid]
        n = min(len(b), len(d) - off)
        if n > 0:
            d[off:off + n] = b[:n]


def pack_region(table, files_data, blobs_tail, compress):
    """Rebuild the relocData region. table: spec reloc_table (FILE_COUNT+1 entries)."""
    n = reloc.FILE_COUNT

    def job(i):
        e = table[i]
        data = bytes(files_data[i])
        if e["vpk0"]:
            c = compress(data)
            c += bytes((-len(c)) % 4)
        else:
            c = data
        return c

    with ThreadPoolExecutor(16) as ex:
        comp = list(ex.map(job, range(n)))
    head = bytearray()
    body = bytearray()
    for i in range(n):
        e = table[i]
        stored = len(comp[i]) // 4
        blob = comp[i] + blobs_tail[i]
        blob += bytes((-len(blob)) % 8)
        w = len(body) | (0x80000000 if e["vpk0"] else 0)
        head += struct.pack(">IHHHH", w, e["intern"], stored, e["extern"], e["dec"])
        body += blob
    e = table[n]
    head += struct.pack(">IHHHH", len(body), e["intern"], e["stored"], e["extern"], e["dec"])
    return bytes(head + body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("out")
    a = ap.parse_args()
    from . import pack
    rom = open(a.rom, "rb").read()
    table = json.load(open(os.path.join(SPEC, "reloc_table.json")))
    textures = json.load(open(os.path.join(SPEC, "textures.json")))
    palettes = json.load(open(os.path.join(SPEC, "palettes.json")))
    ents = reloc.parse(rom[reloc.RELOC_ROM:reloc.RELOC_END])
    files_data = [bytearray(reloc.file_data(e)) for e in ents[:reloc.FILE_COUNT]]
    tails = []
    for e in ents[:reloc.FILE_COUNT]:
        n = len(reloc.chain(bytes(files_data[len(tails)]), e["extern"])) if e["extern"] != 0xFFFF else 0
        tails.append(e["blob"][e["stored"] * 4:e["stored"] * 4 + 2 * n])
    from . import art
    ranges = generate_bytes(textures, palettes, hook=art.hook)
    apply(files_data, ranges)
    region = pack_region(table, files_data, tails, lambda d: reloc.vpk0("c", d))
    newrom = pack.build(rom, region)
    seed = pack.set_crc(newrom, rom)
    os.makedirs(a.out, exist_ok=True)
    open(os.path.join(a.out, "ssb64_clean.z64"), "wb").write(newrom)
    print(f"ranges {len(ranges)}, relocData {len(region)} bytes, rom {len(newrom):#x}, cic seed {seed:#x}")


if __name__ == "__main__":
    main()
