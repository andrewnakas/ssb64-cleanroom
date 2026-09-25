"""Render a fighter from the game's own model data with our clean textures (portraits, icons).

    python -m games.ssb64.fighter_render <clean rom> <fighter> <out.png> [--size 128] [--yaw 0] [--head]

Reads the clean ROM only: FTData.o_attributes -> FTAttributes.commonparts_container (+0x2D4) ->
commonparts[0].dobjdesc (skeleton: depth-coded id, DL, translate/rotate/scale, terminated by id 18) and
walks each joint's F3DEX2 display list (VTX, TRI1/TRI2, DL call/branch, texture image/TLUT/tile state,
geometry mode, prim colour). Textures decode through the spec facts (format/size/palette link).
"""
import argparse
import json
import math
import os
import struct

import numpy as np

from cleanroom.gfx import c_render, texfmt

from . import reloc, texscan

HERE = os.path.dirname(os.path.abspath(__file__))
FIGHTERS = {  # name: (main file, attributes offset)   (from the decomp's ftdata.c)
    "mario": (203, 0x428), "fox": (209, 0x46C), "donkey": (213, 0x4A4), "samus": (217, 0x610),
    "luigi": (221, 0x580), "link": (225, 0x708), "kirby": (229, 0x808), "purin": (233, 0x474),
    "captain": (236, 0x488), "ness": (239, 0x5BC), "pikachu": (243, 0x41C), "yoshi": (247, 0x47C)}
FMTN = {"RGBA": 0, "YUV": 1, "CI": 2, "IA": 3, "I": 4}
SIZN = {4: 0, 8: 1, 16: 2, 32: 3}


class Rom:
    def __init__(self, path):
        rom = open(path, "rb").read()
        self.ents = reloc.parse(rom[reloc.RELOC_ROM:reloc.RELOC_END])
        self.files = {}
        self.facts = {(t["fid"], t["off"]): t for t in json.load(open(os.path.join(HERE, "spec", "textures.json")))}
        self.images = {}

    def f(self, fid):
        if fid not in self.files:
            e = self.ents[fid]
            d = reloc.file_data(e)
            n = len(reloc.chain(d, e["extern"])) if e["extern"] != 0xFFFF else 0
            fids = [struct.unpack_from(">H", e["blob"], e["stored"] * 4 + 2 * k)[0] for k in range(n)]
            self.files[fid] = texscan.File(fid, d, e, fids)
        return self.files[fid]

    def ptr(self, fid, pos):
        return self.f(fid).ptr.get(pos)

    def image(self, key):
        """key = (fid, off, pal_fid, pal_off, fmt, siz, w, h) -> RGBA float array."""
        if key in self.images:
            return self.images[key]
        fid, off, pf, po, fmt, siz, w, h = key
        t = self.facts.get((fid, off))
        if t:
            fmt, siz, w, h = FMTN.get(t["fmt"], fmt), SIZN.get(t["siz"], siz), t["w"], t["h"]
            if t.get("pal") and po is None:
                pf, po = t["pal"][0], t["pal"][1]
        d = self.f(fid).data
        nb = w * h * texfmt.BITS[siz] // 8
        raw = d[off:off + nb] + bytes(max(0, off + nb - len(d)))
        pal = None
        if fmt == 2:
            pd = self.f(pf).data if po is not None else None
            n = 16 if siz == 0 else 256
            if pd is not None:
                v = np.frombuffer(pd[po:po + 2 * n].ljust(2 * n, b"\0"), ">u2").astype(np.int64)
                pal = np.stack([((v >> 11) & 31) * 255 // 31, ((v >> 6) & 31) * 255 // 31,
                                ((v >> 1) & 31) * 255 // 31, (v & 1) * 255], -1).astype(np.uint8)
        try:
            img = texfmt.decode(raw, w, h, fmt, siz, pal).astype(np.float32)
        except ValueError:
            img = np.full((max(h, 1), max(w, 1), 4), 200, np.float32)
        self.images[key] = img
        return img


def euler(rx, ry, rz):
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    X = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Z @ Y @ X


def skeleton(R, name):
    main, att = FIGHTERS[name]
    cc = R.ptr(main, att + 0x2D4)
    desc = R.ptr(cc[0], cc[1])
    fid, off = desc
    d = R.f(fid).data
    mp = R.ptr(cc[0], cc[1] + 4)                 # commonparts[0].p_mobjsubs: MObjSub** per joint
    joints, stack = [], {}
    while off + 44 <= len(d):
        jid = struct.unpack_from(">i", d, off)[0]
        if jid == 18:
            break
        depth = jid & 0xFFF
        t = np.array(struct.unpack_from(">3f", d, off + 8))
        r = struct.unpack_from(">3f", d, off + 20)
        s = np.array(struct.unpack_from(">3f", d, off + 32))
        M = np.eye(4)
        M[:3, :3] = euler(*r) * s
        M[:3, 3] = t
        parent = stack.get(depth - 1, np.eye(4)) if depth else np.eye(4)
        W = parent @ M
        stack[depth] = W
        mob = None
        if mp:
            lst = R.ptr(mp[0], mp[1] + 4 * len(joints))
            if lst:
                first = R.ptr(lst[0], lst[1])
                if first:
                    mob = first
        joints.append((W, R.ptr(fid, off + 4), mob))
        off += 44
    return joints


def walk_dl(R, dl, W, tris, depth=0):
    if dl is None or depth > 8:
        return
    fid, k = dl
    d = R.f(fid).data
    st = walk_dl.state
    while k + 8 <= len(d):
        w0, w1 = struct.unpack_from(">II", d, k)
        op = w0 >> 24
        if op == 0x01:
            n = (w0 >> 12) & 0xFF
            v0 = ((w0 & 0xFF) >> 1) - n
            p = R.ptr(fid, k + 4)
            if p:
                vd = R.f(p[0]).data
                for i in range(n):
                    o = p[1] + 16 * i
                    if o + 16 > len(vd):
                        break
                    x, y, z, _, s, t, cr, cg, cb, ca = struct.unpack_from(">hhhHhhBBBB", vd, o)
                    pos = W @ np.array([x, y, z, 1.0])
                    st["vtx"][(v0 + i) & 63] = (pos[:3], (s, t), (cr, cg, cb, ca))
        elif op in (0x05, 0x06, 0x07):
            tri_sets = [((w0 >> 16) & 0xFF, (w0 >> 8) & 0xFF, w0 & 0xFF)]
            if op == 0x06:
                tri_sets.append(((w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF))
            elif op == 0x07:
                a, b, c = tri_sets[0]
                tri_sets.append(((w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF))
            for tri in tri_sets:
                vs = [st["vtx"].get((i >> 1) & 63) for i in tri]
                if any(v is None for v in vs):
                    continue
                tex = None
                if st["textured"] and st.get("loaded") and st.get("tsize"):
                    fmt, siz, line = st.get("tile", (0, 2, 0))
                    pf, po = st["tlut"] if (fmt == 2 and st.get("tlut")) else (None, None)
                    tex = (st["loaded"][0], st["loaded"][1], pf, po, fmt, siz, *st["tsize"])
                sc = st["scale"]
                uv = np.array([[v[1][0] * sc[0] / 65536 / 32, v[1][1] * sc[1] / 65536 / 32] for v in vs], np.float32)
                col = np.array([v[2] for v in vs], np.float32)
                lit = bool(st["geom"] & 0x00020000)
                if lit or tex is None:
                    col = np.tile(np.array(st["prim"], np.float32), (3, 1)) if tex is None else np.full((3, 4), 255.0)
                tris.append((np.array([v[0] for v in vs], np.float32), uv, col, tex, lit or tex is None))
        elif op == 0xDE:
            p = R.ptr(fid, k + 4)
            if p is None and (w1 >> 24) == 0x0E and st.get("mobj"):
                # material DL the engine builds from the joint's MObjSub: texture (+ palette) image
                mf, mo = st["mobj"]
                md = R.f(mf).data
                flags = struct.unpack_from(">H", md, mo + 0x30)[0]
                tp = R.ptr(mf, mo + 4)
                frame = R.ptr(tp[0], tp[1]) if tp else None
                pp = R.ptr(mf, mo + 0x2C)
                pal = R.ptr(pp[0], pp[1]) if pp else None
                # same order as gcDrawMObjForDObj: palette image (+TLUT), block load, current image last
                if flags & 0x04 and pal:
                    st["timg"] = pal
                    if flags & 0x03:
                        st["tlut"] = pal
                if flags & 0x12 and frame:
                    st["timg"] = frame
                    if flags & 0x11:
                        st["loaded"] = frame
                if flags & 0x11 and frame:
                    st["timg"] = frame
            walk_dl(R, p, W, tris, depth + 1)
            if (w0 >> 16) & 0xFF == 1:
                return
        elif op == 0xDF:
            return
        elif op == 0xD7:
            st["scale"] = ((w1 >> 16) or 0xFFFF, (w1 & 0xFFFF) or 0xFFFF)
            st["textured"] = bool(w0 & 0xFF) or True
        elif op == 0xD9:
            st["geom"] = (st["geom"] & (w0 & 0xFFFFFF)) | w1
        elif op == 0xFD:
            st["timg"] = R.ptr(fid, k + 4)
            st["timg_fmt"] = ((w0 >> 21) & 7, (w0 >> 19) & 3, (w0 & 0xFFF) + 1)
        elif op == 0xF0 and st.get("timg"):
            st["tlut"] = st["timg"]
        elif op in (0xF3, 0xF4) and st.get("timg"):
            st["loaded"] = st["timg"]
        elif op == 0xF5 and (w1 >> 24) & 7 == 0:
            st["tile"] = ((w0 >> 21) & 7, (w0 >> 19) & 3, (w0 >> 9) & 0x1FF)
        elif op == 0xF2 and (w1 >> 24) & 7 == 0 and st.get("loaded"):
            tw = (((w1 >> 12) & 0xFFF) - ((w0 >> 12) & 0xFFF)) // 4 + 1
            th = ((w1 & 0xFFF) - (w0 & 0xFFF)) // 4 + 1
            st["tsize"] = (max(1, tw), max(1, th))
        elif op == 0xFA:
            st["prim"] = (w1 >> 24, (w1 >> 16) & 0xFF, (w1 >> 8) & 0xFF, w1 & 0xFF)
        k += 8


def fighter_tris(R, name):
    tris = []
    walk_dl.state = {"vtx": {}, "tex": None, "textured": False, "scale": (0xFFFF, 0xFFFF), "geom": 0,
                     "prim": (200, 200, 200, 255)}
    for W, dl, mob in skeleton(R, name):
        walk_dl.state["mobj"] = mob
        walk_dl(R, dl, W, tris)
    return tris


def render(R, name, size=128, yaw=0.0, head=False, bg=None):
    tris = fighter_tris(R, name)
    pts = np.concatenate([t[0] for t in tris])
    lo, hi = pts.min(0), pts.max(0)
    if head:                                  # upper 38% of the body, centred on the head
        top = hi[1]
        span = (hi[1] - lo[1]) * 0.38
        sel = pts[pts[:, 1] > top - span]
        lo, hi = sel.min(0), sel.max(0)
    c = (lo + hi) / 2
    r = max(hi - lo) / 2
    yw = math.radians(yaw)
    eye = c + np.array([math.sin(yw), 0.08, math.cos(yw)]) * r * 3.2
    img = c_render.render(R, tris, eye.tolist(), c.tolist(), 36, size, size,
                          bg=bg if bg is not None else np.array([40, 40, 60], np.float32), ss=2)
    return np.clip(img, 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("fighter")
    ap.add_argument("out")
    ap.add_argument("--size", type=int, default=128)
    ap.add_argument("--yaw", type=float, default=0)
    ap.add_argument("--head", action="store_true")
    a = ap.parse_args()
    from PIL import Image
    R = Rom(a.rom)
    names = list(FIGHTERS) if a.fighter == "all" else [a.fighter]
    ims = [render(R, n, a.size, a.yaw, a.head) for n in names]
    Image.fromarray(np.concatenate(ims, 1)).save(a.out)
    print(a.out, len(ims))


if __name__ == "__main__":
    main()
