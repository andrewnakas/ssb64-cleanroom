"""Particle texture banks (*_txb): dirty facts -> clean images.

    python -m games.ssb64.particles extract <baserom>   -> spec/particles.json
    (generation is called from generate.py: particles.build(rom) -> {rom_off: bytes})

Layout from the decomp's tools/decode_txb.py (LBTexture: count, fmt, siz, w, h, flags, data[], images,
palettes). Kept per frame: format, size, 4x4 colour grid (16x16 from 128 px), 2-bit alpha outline.
"""
import importlib.util
import json
import os
import sys

import numpy as np

from cleanroom.decomp.spec import alpha2, grid
from cleanroom.gfx import texfmt

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec", "particles.json")
DECOMP_TOOLS = "C:/Users/andre/n64work/ssb64/pristine/tools"
BANKS = {"efcommon": (0xAC9DE0, 0xB16C80), "unk0": (0xB17060, 0xB174A0), "unk1": (0xB176A0, 0xB19700),
         "unk2": (0xB19850, 0xB1BCA0), "itcommon": (0xB1BDE0, 0xB1E640), "grpupupu": (0xB1E7E0, 0xB1F960),
         "grhyrule": (0xB1FC80, 0xB22980), "gryoster": (0xB22A00, 0xB22C30), "mntitle": (0xB22D40, 0xB277B0)}


def _txb():
    spec = importlib.util.spec_from_file_location("decode_txb", os.path.join(DECOMP_TOOLS, "decode_txb.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def extract(rom):
    T = _txb()
    out = []
    for name, (a, b) in BANKS.items():
        data = rom[a:b]
        bank = T.parse_bank(data)
        for k, (off, t) in enumerate(zip(bank["offsets"], bank["textures"])):
            if not t["count"]:
                continue
            fmt, siz, w, h = t["fmt"], t["siz"], t["width"], t["height"]
            isz = T.img_size(siz, w, h)
            img0 = a + off + 24 + t["ndata"] * 4
            psz = T.pal_size(fmt, siz)
            pal0 = img0 + t["count"] * isz
            for f in range(t["count"]):
                raw = rom[img0 + f * isz: img0 + (f + 1) * isz]
                pal = None
                if fmt == 2:
                    pi = 0 if t["flags"] & 1 else f
                    pal = pal_rgba(rom[pal0 + pi * psz: pal0 + (pi + 1) * psz])
                try:
                    img = texfmt.decode(raw, w, h, fmt, siz, pal)
                except ValueError:
                    img = None
                d = dict(bank=name, tex=k, frame=f, rom=img0 + f * isz, nbytes=isz, fmt=fmt, siz=siz, w=w, h=h)
                if fmt == 2:
                    d["pal_rom"] = pal0 + (0 if t["flags"] & 1 else f) * psz
                    d["pal_n"] = psz // 2
                if img is not None:
                    d["grid"] = grid(img.astype(np.float64), 16 if max(w, h) >= 128 else 4)
                    if (img[..., 3] < 250).any():
                        d["alpha2"] = alpha2(img[..., 3])
                out.append(d)
    json.dump(out, open(SPEC, "w"))
    print(f"particles: {len(out)} frames in {len(BANKS)} banks -> {SPEC}")


def pal_rgba(b):
    v = np.frombuffer(b, ">u2").astype(np.int64)
    o = np.zeros((len(v), 4), np.uint8)
    o[:, 0] = ((v >> 11) & 31) * 255 // 31
    o[:, 1] = ((v >> 6) & 31) * 255 // 31
    o[:, 2] = ((v >> 1) & 31) * 255 // 31
    o[:, 3] = (v & 1) * 255
    return o


def build():
    from .generate import base_image, pal_bytes, quantize, to_index
    frames = json.load(open(SPEC))
    patches = {}
    pal_groups = {}
    for d in frames:
        t = dict(d, fid=0x7000 + d["tex"], off=d["rom"], fmt={0: "RGBA", 2: "CI", 3: "IA", 4: "I"}.get(d["fmt"], "RGBA"),
                 siz={0: 4, 1: 8, 2: 16, 3: 32}[d["siz"]])
        d["_img"] = base_image(t)
        if d["fmt"] == 2:
            pal_groups.setdefault(d["pal_rom"], []).append(d)
    for prom, ds in pal_groups.items():
        n = ds[0]["pal_n"]
        pal = quantize(np.concatenate([x["_img"].reshape(-1, 4) for x in ds]), n, seed=prom & 0xFFFF)
        patches[prom] = pal_bytes(pal)
        for x in ds:
            x["_pal"] = pal
    for d in frames:
        if d["fmt"] == 2:
            idx = to_index(d["_img"], d["_pal"])
            b = texfmt.encode(np.stack([idx] * 4, -1), 2, d["siz"])
        else:
            try:
                b = texfmt.encode(d["_img"].astype(np.uint8), d["fmt"], d["siz"])
            except ValueError:
                b = bytes([0x80]) * d["nbytes"]
        patches[d["rom"]] = b[:d["nbytes"]] + bytes(max(0, d["nbytes"] - len(b)))
    return patches


if __name__ == "__main__":
    if sys.argv[1] == "extract":
        extract(open(sys.argv[2], "rb").read())
