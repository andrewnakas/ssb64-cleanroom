"""Find every texture, palette and sprite bitmap in the reloc files (dirty room).

Sources (all structural, from the decompressed files and their pointer chains):
  dl      G_SETTIMG whose address word is a chain pointer, followed by LOADBLOCK/LOADTILE/LOADTLUT;
          format/size from the render tile (SETTILE/SETTILESIZE after the load)
  mobj    MObjSub (material) frame arrays: sprites[k] textures + palettes[k]
  sprite  libultra Sprite structs (offsets from tools/relocFileDescriptions.us.txt) -> Bitmap -> buf, LUT

Output: list of dict(fid, off, nbytes, kind=tex|pal, fmt, siz, w, h, src, pal=(fid,off)|None)
"""
import re
import struct

from . import reloc

FMT = {0: "RGBA", 1: "YUV", 2: "CI", 3: "IA", 4: "I"}
BITS = {0: 4, 1: 8, 2: 16, 3: 32}


def u32(d, o):
    return struct.unpack_from(">I", d, o)[0]


def s16(d, o):
    return struct.unpack_from(">h", d, o)[0]


def u16(d, o):
    return struct.unpack_from(">H", d, o)[0]


class File:
    def __init__(self, fid, data, ent, fids):
        self.fid, self.data, self.ent = fid, data, ent
        self.ptr = {}            # pos -> (fid, target)
        for p, t in reloc.chain(data, ent["intern"]) if ent["intern"] != 0xFFFF else []:
            self.ptr[p] = (fid, t)
        ext = reloc.chain(data, ent["extern"]) if ent["extern"] != 0xFFFF else []
        for (p, t), f in zip(ext, fids):
            self.ptr[p] = (f, t)


def scan_dl(F, out):
    d = F.data
    for p, tgt in F.ptr.items():
        q = p - 4
        if q < 0 or q % 8 or d[q] != 0xFD:
            continue
        w0 = u32(d, q)
        tfmt, tsiz, twidth = (w0 >> 21) & 7, (w0 >> 19) & 3, (w0 & 0xFFF) + 1
        tiles = {}
        texcmd = []
        # render tile state set before this SETTIMG (walk back to the previous load/draw)
        k = q - 8
        while k >= 0 and q - k <= 8 * 16:
            c0, c1 = u32(d, k), u32(d, k + 4)
            op = c0 >> 24
            if op in (0xDF, 0x01, 0x05, 0x06, 0xF3, 0xF4):
                break
            if op == 0xD7 and not texcmd:
                texcmd.append((c0 >> 8) & 7)
            if op == 0xF5:
                t = (c1 >> 24) & 7
                if t != 7 and "fmt" not in tiles.get(t, {}):
                    tiles.setdefault(t, {}).update(fmt=(c0 >> 21) & 7, siz=(c0 >> 19) & 3, line=(c0 >> 9) & 0x1FF,
                                    pal=(c1 >> 20) & 0xF, after_load=True)
            elif op == 0xF2:
                t = (c1 >> 24) & 7
                v = tiles.setdefault(t, {})
                v.setdefault("sw", (((c1 >> 12) & 0xFFF) - ((c0 >> 12) & 0xFFF)) // 4 + 1)
                v.setdefault("sh", ((c1 & 0xFFF) - (c0 & 0xFFF)) // 4 + 1)
            k -= 8
        load = None
        k = q + 8
        n = 0
        while k + 8 <= len(d) and n < 24:
            c0, c1 = u32(d, k), u32(d, k + 4)
            op = c0 >> 24
            if op == 0xF5:
                t = (c1 >> 24) & 7
                tiles.setdefault(t, {}).update(fmt=(c0 >> 21) & 7, siz=(c0 >> 19) & 3, line=(c0 >> 9) & 0x1FF,
                                               pal=(c1 >> 20) & 0xF, after_load=(load is not None or t != 7))
            elif op == 0xF3 and load is None:
                texels = ((c1 >> 12) & 0xFFF) + 1
                load = ("block", texels, c1 & 0xFFF)
            elif op == 0xF4 and load is None:
                uls, ult = (c0 >> 12) & 0xFFF, c0 & 0xFFF
                lrs, lrt = (c1 >> 12) & 0xFFF, c1 & 0xFFF
                load = ("tile", uls >> 2, ult >> 2, lrs >> 2, lrt >> 2)
            elif op == 0xF0 and load is None:
                load = ("tlut", ((c1 >> 14) & 0x3FF) + 1)
            elif op == 0xF2:
                t = (c1 >> 24) & 7
                if load is not None:
                    tiles.setdefault(t, {}).update(sw=(((c1 >> 12) & 0xFFF) - ((c0 >> 12) & 0xFFF)) // 4 + 1,
                                                   sh=((c1 & 0xFFF) - (c0 & 0xFFF)) // 4 + 1)
            elif op == 0xD7:
                texcmd.insert(0, (c0 >> 8) & 7)
            elif op in (0xFD, 0xDF, 0x01, 0x05, 0x06, 0xDE) and n > 0:
                break
            k += 8
            n += 1
        if load is None:
            continue
        tf, to = tgt
        if load[0] == "tlut":
            out.append(dict(fid=tf, off=to, nbytes=load[1] * 2, kind="pal", src="dl", fmt="RGBA", siz=16,
                            w=load[1], h=1, at=(F.fid, q)))
            continue
        # render tile = first tile set after the load that isn't the load tile (7), else tile 0
        good = [t for t, v in sorted(tiles.items()) if t != 7 and v.get("line")]
        rt = texcmd[0] if texcmd and texcmd[0] in good else (good[0] if good else 0)
        r = tiles.get(rt, {})
        fmt = r.get("fmt", tfmt)
        siz = r.get("siz", tsiz)
        bits = BITS[siz]
        if load[0] == "block":
            nbytes = load[1] * BITS[tsiz] // 8
            line = r.get("line", 0)
            w = line * 64 // bits if line else r.get("sw", 0)
            if not w:
                w = r.get("sw", 1)
            h = max(1, nbytes * 8 // (bits * w))
            off = to
        else:
            _, uls, ult, lrs, lrt = load
            rowb = twidth * BITS[tsiz] // 8
            off = to + ult * rowb
            h = lrt - ult + 1
            nbytes = h * rowb
            w = twidth * BITS[tsiz] // bits
        out.append(dict(fid=tf, off=off, nbytes=nbytes, kind="tex", src="dl", fmt=FMT.get(fmt, "?"), siz=bits,
                        w=w, h=h, sw=r.get("sw"), sh=r.get("sh"), palidx=r.get("pal", 0), at=(F.fid, q),
                        dxt=load[2] if load[0] == "block" else None))


def scan_mobj(F, out):
    """MObjSub: +2 fmt, +3 siz, +4 sprites**, +0xC w, +0xE h, +0x2C palettes**, +0x32 block_fmt, +0x33 block_siz,
    +0x34 block_dxt (w), +0x36 h."""
    d = F.data
    for p in list(F.ptr):
        s = p - 4
        if s < 0 or s % 4:
            continue
        if u16(d, s) != 0 or d[s + 2] > 4 or d[s + 3] > 3 or s + 0x78 > len(d):
            continue
        fmt, siz = d[s + 0x32], d[s + 0x33]
        w, h = u16(d, s + 0x34), u16(d, s + 0x36)
        if fmt > 4 or siz > 3 or (fmt == 0 and siz == 0):
            continue
        pals = s + 0x2C
        if not (0 < w <= 256 and 0 < h <= 256):
            continue
        if not (pals in F.ptr or u32(d, pals) == 0):
            continue
        arr_f, arr = F.ptr[p]
        if arr_f != F.fid:
            continue
        frames = []
        a = arr
        while a in F.ptr and len(frames) < 64:
            frames.append(F.ptr[a])
            a += 4
        if not frames:
            continue
        bits = BITS[siz]
        for (tf, to) in frames:
            out.append(dict(fid=tf, off=to, nbytes=w * h * bits // 8, kind="tex", src="mobj", fmt=FMT.get(fmt, "?"),
                            siz=bits, w=w, h=h, at=(F.fid, s)))
        if pals in F.ptr:
            pf, pa = F.ptr[pals]
            a = pa
            n = 0
            while a in F.ptr and n < 64:
                tf, to = F.ptr[a]
                out.append(dict(fid=tf, off=to, nbytes=(16 if siz == 0 else 256) * 2, kind="pal", src="mobj",
                                fmt="RGBA", siz=16, w=16 if siz == 0 else 256, h=1, at=(F.fid, s)))
                a += 4
                n += 1


def sprite_offsets(desc_path):
    """{fid: [offsets of Sprite structs]} from relocFileDescriptions."""
    res = {}
    fid = None
    for line in open(desc_path, encoding="utf-8"):
        m = re.match(r"^\[(\d+)\]", line)
        if m:
            fid = int(m.group(1))
            continue
        parts = line.split()
        if fid is not None and len(parts) >= 3 and parts[0] == "Sprite":
            try:
                res.setdefault(fid, []).append(int(parts[-1], 16))
            except ValueError:
                pass
    return res


def scan_sprites(F, offs, out):
    d = F.data
    for s in offs:
        if s + 0x44 > len(d) or (s + 0x34) not in F.ptr:
            continue
        fmt, siz = d[s + 0x30], d[s + 0x31]
        nbm = s16(d, s + 0x28)
        bits = BITS.get(siz, 4)   # HAL sprites use bmsiz=4 for 4-bit data
        bmf, bm = F.ptr[s + 0x34]
        pal = None
        ntl = s16(d, s + 0x1E)
        if (s + 0x20) in F.ptr and ntl > 0:
            pf, po = F.ptr[s + 0x20]
            pal = (pf, po)
            out.append(dict(fid=pf, off=po, nbytes=ntl * 2, kind="pal", src="sprite", fmt="RGBA", siz=16, w=ntl, h=1,
                            at=(F.fid, s)))
        for k in range(max(0, nbm)):
            b = bm + 16 * k
            if (b + 8) not in F.ptr:
                continue
            wimg, ah = s16(d, b + 2), s16(d, b + 0xC)
            w = s16(d, b)
            tf, to = F.ptr[b + 8]
            out.append(dict(fid=tf, off=to, nbytes=wimg * ah * bits // 8, kind="tex", src="sprite",
                            fmt=FMT.get(fmt, "?"), siz=bits, w=wimg, h=ah, vis_w=w, pal=pal, at=(F.fid, s),
                            sprite=(F.fid, s), bm=k))


def scan_all(files, desc_path):
    out = []
    spr = sprite_offsets(desc_path)
    for F in files:
        scan_dl(F, out)
        scan_mobj(F, out)
        scan_sprites(F, spr.get(F.fid, []), out)
    # pixel data never holds pointer slots: clip each range at the first one inside it
    import bisect
    slots = {F.fid: set(F.ptr) for F in files}
    for F in files:                      # pointer targets start other objects: clip there too
        for (tf, to) in F.ptr.values():
            if 0 <= tf < len(files):
                slots[tf].add(to)
    slots = {k: sorted(v) for k, v in slots.items()}
    for o in out:
        ps = slots.get(o["fid"], [])
        j = bisect.bisect_right(ps, o["off"])
        if j < len(ps) and ps[j] < o["off"] + o["nbytes"]:
            o["clipped_from"] = o["nbytes"]
            o["nbytes"] = ps[j] - o["off"]
        o["nbytes"] = max(0, min(o["nbytes"], len(files[o["fid"]].data) - o["off"]))
    return out
