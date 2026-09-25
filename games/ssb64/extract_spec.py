"""Dirty room: ROM -> games/ssb64/spec (facts only).

    python -m games.ssb64.extract_spec <baserom.us.z64> <work dir> [--sheet N]

Writes:
  <work>/reloc/<fid>.bin           decompressed retail reloc files (dirty, never published)
  games/ssb64/spec/reloc_table.json  container layout (sizes/flags/chain heads: structure, not art)
  games/ssb64/spec/textures.json     per texture: fid, off, nbytes, fmt, siz, w, h, pal link, 4x4 grid, 2-bit alpha
  games/ssb64/spec/palettes.json     per palette: fid, off, count (colours are NOT kept)
"""
import argparse
import re
import json
import os
import struct
import sys

import numpy as np

from cleanroom.decomp.spec import alpha2, grid
from cleanroom.gfx import texfmt

from . import reloc, texscan

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")
DESC = "C:/Users/andre/n64work/ssb64/pristine/tools/relocFileDescriptions.us.txt"
FMTN = {"RGBA": 0, "YUV": 1, "CI": 2, "IA": 3, "I": 4}
SIZN = {4: 0, 8: 1, 16: 2, 32: 3}


def load_files(rom, work):
    ents = reloc.parse(rom[reloc.RELOC_ROM:reloc.RELOC_END])
    os.makedirs(os.path.join(work, "reloc"), exist_ok=True)
    files = []
    for i in range(reloc.FILE_COUNT):
        p = os.path.join(work, "reloc", f"{i}.bin")
        if os.path.exists(p):
            d = open(p, "rb").read()
        else:
            d = reloc.file_data(ents[i])
            open(p, "wb").write(d)
        e = ents[i]
        n = len(reloc.chain(d, e["extern"])) if e["extern"] != 0xFFFF else 0
        fids = [struct.unpack_from(">H", e["blob"], e["stored"] * 4 + 2 * k)[0] for k in range(n)]
        files.append(texscan.File(i, d, e, fids))
    return ents, files


def pal_rgba(data, off, count):
    v = np.frombuffer(data[off:off + count * 2], ">u2").astype(np.int64)
    out = np.zeros((len(v), 4), np.uint8)
    out[:, 0] = ((v >> 11) & 31) * 255 // 31
    out[:, 1] = ((v >> 6) & 31) * 255 // 31
    out[:, 2] = ((v >> 1) & 31) * 255 // 31
    out[:, 3] = (v & 1) * 255
    return out


def resolve(hits):
    """Dedupe by (fid, off, kind); prefer dl > mobj > sprite for format; link CI textures to palettes."""
    rank = {"dl": 0, "mobj": 1, "sprite": 2}
    by = {}
    for h in hits:
        k = (h["fid"], h["off"], h["kind"])
        if k not in by or rank[h["src"]] < rank[by[k]["src"]]:
            by[k] = dict(h)
    # sizes: a range never runs into the next known range; MObj "frames" that are really palette
    # frames (0x28 apart) become palettes; the last frame of an array gets its siblings' size
    rs = sorted(by.values(), key=lambda v: (v["fid"], v["off"], v["kind"] == "tex"))
    for a, b in zip(rs, rs[1:]):
        if a["fid"] == b["fid"] and b["off"] < a["off"] + a["nbytes"] and b["off"] > a["off"]:
            a["clipped_from"] = a["nbytes"]
            a["nbytes"] = b["off"] - a["off"]
    groups = {}
    for v in by.values():
        if v["src"] == "mobj" and v["kind"] == "tex":
            groups.setdefault(tuple(v["at"]), []).append(v)
    for g in groups.values():
        sizes = [v["nbytes"] for v in g if "clipped_from" in v]
        if sizes:
            m = min(sizes)
            for v in g:
                v["nbytes"] = min(v["nbytes"], m)
        for v in g:
            if v["nbytes"] <= 0x28 and v["fmt"] == "CI":
                v["kind"] = "pal"
                v["fmt"], v["siz"], v["w"], v["h"] = "RGBA", 16, v["nbytes"] // 2, 1
    for v in by.values():
        if v["kind"] == "tex" and v.get("clipped_from"):
            v["h"] = max(1, v["nbytes"] * 8 // (v["siz"] * v["w"]))
    tex = [v for v in by.values() if v["kind"] == "tex"]
    pal = list({(v["fid"], v["off"]): v for v in by.values() if v["kind"] == "pal"}.values())
    # palette link: sprites carry it; dl textures -> nearest TLUT load in the same DL; mobj -> same struct
    pal_at = {}
    for p in [h for h in hits if h["kind"] == "pal"]:
        pal_at.setdefault(tuple(p["at"]), []).append((p["fid"], p["off"], p["nbytes"] // 2))
    dl_tluts = {}
    for p in [h for h in hits if h["kind"] == "pal" and h["src"] == "dl"]:
        dl_tluts.setdefault(p["at"][0], []).append((p["at"][1], (p["fid"], p["off"], p["nbytes"] // 2)))
    frames_of = {}
    for h in hits:
        if h["src"] == "mobj" and h["kind"] == "tex":
            frames_of.setdefault(tuple(h["at"]), []).append((h["fid"], h["off"]))
    for t in tex:
        if t["fmt"] != "CI":
            continue
        link = None
        if t["src"] == "sprite" and t.get("pal"):
            pf, po = t["pal"]
            c = next((p for p in pal if p["fid"] == pf and p["off"] == po), None)
            link = (pf, po, c["nbytes"] // 2 if c else (16 if t["siz"] == 4 else 256))
        elif t["src"] == "mobj":
            ps = pal_at.get(tuple(t["at"]))
            if ps:
                fr = frames_of.get(tuple(t["at"]), [])
                k = fr.index((t["fid"], t["off"])) if (t["fid"], t["off"]) in fr else 0
                link = ps[min(k, len(ps) - 1)]
        if link is None:
            cands = dl_tluts.get(t["at"][0], [])
            best = None
            for at, pl in cands:
                dist = t["at"][1] - at
                if -0x40 <= dist <= 0x100 and (best is None or abs(dist) < abs(best[0])):
                    best = (dist, pl)
            if best:
                link = best[1]
        t["pal"] = list(link) if link else None
    return tex, pal


DECL_RE = re.compile(r'(u8|u16|u32)\s+d\w*?_(Tex|Lut|LUT|Image|Palette)_0x([0-9A-Fa-f]+)\w*\[(0x[0-9A-Fa-f]+|\d+)\]\s*=')
ANN_RE = re.compile(r'@tex fmt=(\w+?)(\d+)? dim=(\d+)x(\d+)(?: lut=\w*?_(?:Lut|LUT)_0x([0-9A-Fa-f]+))?')
FMT_TOK = {"CI": "CI", "I": "I", "IA": "IA", "RGBA": "RGBA"}


def decl_blocks(src_dir):
    """Texture/LUT blocks the decomp declares in src/relocData/*.c, with their @tex annotations."""
    out = []
    for f in sorted(os.listdir(src_dir)):
        if not f.endswith(".c") or not f.split("_")[0].isdigit():
            continue
        fid = int(f.split("_")[0])
        lines = open(os.path.join(src_dir, f), encoding="utf-8", errors="replace").read().splitlines()
        for i, l in enumerate(lines):
            m = DECL_RE.search(l)
            if not m:
                continue
            size = int(m.group(4), 0) * {"u8": 1, "u16": 2, "u32": 4}[m.group(1)]
            ann = ANN_RE.search(" ".join(lines[max(0, i - 3):i]))
            out.append(dict(fid=fid, off=int(m.group(3), 16), size=size, kind=m.group(2).lower(), ann=ann.groups() if ann else None))
    return out


def add_decl_fallback(tex, pal, src_dir):
    """Decomp-declared blocks my structural scan missed become ranges too (format from @tex)."""
    import bisect
    cov = {}
    for r in tex + pal:
        cov.setdefault(r["fid"], []).append((r["off"], r["off"] + r["nbytes"]))
    for k in cov:
        cov[k].sort()
    common = {}
    for t in tex:
        common.setdefault(t["fid"], {}).setdefault((t["fmt"], t["siz"]), 0)
        common[t["fid"]][(t["fmt"], t["siz"])] += 1
    added = 0
    for b in decl_blocks(src_dir):
        rs = cov.get(b["fid"], [])
        lo, hi = b["off"], b["off"] + b["size"]
        covered = sum(max(0, min(hi, e) - max(lo, s)) for s, e in rs)
        if b["size"] - covered < 16:
            continue            # already covered
        # uncovered gaps inside the block (structural ranges keep their exact facts)
        gaps, cur = [], lo
        for s, e in rs:
            if e <= cur or s >= hi:
                continue
            if s > cur:
                gaps.append((cur, s))
            cur = max(cur, e)
        if cur < hi:
            gaps.append((cur, hi))
        gaps = [(s, e) for s, e in gaps if e - s >= 16]
        if b["kind"] in ("lut", "palette"):
            for s, e in gaps:
                pal.append(dict(fid=b["fid"], off=s, nbytes=e - s, kind="pal", src="decl", fmt="RGBA", siz=16,
                                w=(e - s) // 2, h=1, at=[b["fid"], s]))
                added += 1
            continue
        if covered:
            (fmt, bits) = max(common.get(b["fid"], {("CI", 4): 1}).items(), key=lambda kv: kv[1])[0]
            if b["ann"]:
                fmt = FMT_TOK.get(b["ann"][0], "I")
                bits = int(b["ann"][1] or (16 if fmt in ("RGBA", "IA") else 8))
            for s, e in gaps:
                w = max(1, min(32, (e - s) * 8 // bits))
                tex.append(dict(fid=b["fid"], off=s, nbytes=e - s, kind="tex", src="decl", fmt=fmt, siz=bits, w=w,
                                h=max(1, (e - s) * 8 // (bits * w)), at=[b["fid"], s], pal=None))
                added += 1
            continue
        if b["ann"]:
            f, bits, w, h, lut = b["ann"]
            fmt = FMT_TOK.get(f, "I")
            bits = int(bits or (16 if fmt in ("RGBA", "IA") else 8))
            w, h = int(w), int(h)
        else:
            (fmt, bits) = max(common.get(b["fid"], {("CI", 4): 1}).items(), key=lambda kv: kv[1])[0]
            w, lut = 32, None
            h = max(1, b["size"] * 8 // (bits * w))
        n = b["size"] - (b["size"] % max(1, w * bits // 8))   # whole rows over the whole block
        n = n or b["size"]
        t = dict(fid=b["fid"], off=b["off"], nbytes=n, kind="tex", src="decl", fmt=fmt, siz=bits, w=w,
                 h=max(1, n * 8 // (bits * w)), at=[b["fid"], b["off"]], pal=None)
        if fmt == "CI" and lut:
            t["pal"] = [b["fid"], int(lut, 16), 16 if bits == 4 else 256]
        tex.append(t)
        added += 1
    return added


def link_by_smoothness(files, tex, pal):
    """CI textures whose palette comes from a TLUT loaded elsewhere (MObj materials): pick, among the
    same file's palettes of the right size, the one that decodes the texture most smoothly."""
    by_file = {}
    for p in pal:
        by_file.setdefault(p["fid"], []).append(p)
    n = 0
    for t in tex:
        if t["fmt"] != "CI" or t.get("pal") or t["siz"] not in (4, 8):
            continue
        need = 16 if t["siz"] == 4 else 256
        cands = [p for p in by_file.get(t["fid"], []) if p["nbytes"] // 2 >= need]
        if not cands:
            continue
        d = files[t["fid"]].data
        raw = d[t["off"]:t["off"] + t["nbytes"]]
        raw = raw + bytes(max(0, t["w"] * t["h"] * t["siz"] // 8 - len(raw)))
        idx = texfmt.decode(raw, t["w"], t["h"], 2, SIZN[t["siz"]],
                            np.stack([np.arange(256)] * 4, -1).astype(np.uint8))[..., 0].astype(np.int64)
        best = None
        for p in cands:
            pr = pal_rgba(files[p["fid"]].data, p["off"], need).astype(np.float64)
            img = pr[np.clip(idx, 0, need - 1)][..., :3]
            tv = np.abs(np.diff(img, axis=0)).mean() + np.abs(np.diff(img, axis=1)).mean()
            if best is None or tv < best[0]:
                best = (tv, p)
        t["pal"] = [best[1]["fid"], best[1]["off"], need]
        t["pal_guess"] = True
        n += 1
    return n


def image_of(files, t):
    d = files[t["fid"]].data
    raw = d[t["off"]:t["off"] + t["nbytes"]]
    w, h = t["w"], t["h"]
    need = w * h * t["siz"] // 8
    raw = raw + bytes(max(0, need - len(raw)))
    if t["src"] == "sprite":
        raw = texscan.swizzle(raw, w, t["siz"])
    fmt, siz = FMTN[t["fmt"]], SIZN[t["siz"]]
    palette = None
    if fmt == 2:
        if t.get("pal"):
            pf, po, pc = t["pal"]
            palette = pal_rgba(files[pf].data, po, max(pc, 16 if siz == 0 else 256))
        else:
            palette = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
    if (fmt, siz) not in ((0, 2), (0, 3), (3, 2), (3, 1), (3, 0), (4, 1), (4, 0), (2, 0), (2, 1)):
        return None
    return texfmt.decode(raw, w, h, fmt, siz, palette)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("work")
    ap.add_argument("--sheet", type=int, default=0, help="write a dirty contact sheet of N textures")
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    ents, files = load_files(rom, a.work)
    hits = texscan.scan_all(files, DESC)
    tex, pal = resolve(hits)
    n_decl = add_decl_fallback(tex, pal, "C:/Users/andre/n64work/ssb64/pristine/src/relocData")
    print(f"decl fallback: {n_decl} blocks the structural scan missed")
    print(f"palette links by smoothness: {link_by_smoothness(files, tex, pal)}")
    os.makedirs(SPEC, exist_ok=True)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(16) as ex:
        infos = list(ex.map(lambda e: reloc.vpk0_info(e["blob"]) if e.get("vpk0") and "blob" in e else None, ents))
    for e, inf in zip(ents, infos):
        if inf:
            e["vpk"] = inf
    json.dump([{k: v for k, v in e.items() if k != "blob"} for e in ents],
              open(os.path.join(SPEC, "reloc_table.json"), "w"))
    facts, bad = [], 0
    imgs = []
    for t in sorted(tex, key=lambda t: (t["fid"], t["off"])):
        img = image_of(files, t)
        f = {k: t.get(k) for k in ("fid", "off", "nbytes", "fmt", "siz", "w", "h", "src", "pal", "at", "sprite", "bm")}
        if img is None:
            bad += 1
            f["grid"] = None
        else:
            n = 16 if max(t["w"], t["h"]) >= 128 else 4
            f["grid"] = grid(img.astype(np.float64), n)
            if (img[..., 3] < 250).any():
                f["alpha2"] = alpha2(img[..., 3])
            imgs.append((t, img))
        facts.append(f)
    json.dump(facts, open(os.path.join(SPEC, "textures.json"), "w"))
    json.dump([{k: p[k] for k in ("fid", "off", "nbytes", "src")} for p in sorted(pal, key=lambda p: (p["fid"], p["off"]))],
              open(os.path.join(SPEC, "palettes.json"), "w"))
    print(f"textures {len(facts)} (undecodable {bad}), palettes {len(pal)}, "
          f"CI without palette {sum(1 for t in tex if t['fmt'] == 'CI' and not t.get('pal'))}")
    if a.sheet:
        sheet(imgs, a.sheet, os.path.join(a.work, "dirty_sheet.png"))


def sheet(imgs, n, path, cell=64, cols=24):
    from PIL import Image
    step = max(1, len(imgs) // n)
    pick = imgs[::step][:n]
    rows = (len(pick) + cols - 1) // cols
    S = Image.new("RGB", (cols * cell, rows * cell), (40, 40, 60))
    for i, (t, img) in enumerate(pick):
        im = Image.fromarray(img, "RGBA")
        im.thumbnail((cell - 2, cell - 2))
        bg = Image.new("RGB", im.size, (255, 0, 255))
        bg.paste(im, (0, 0), im)
        S.paste(bg, ((i % cols) * cell + 1, (i // cols) * cell + 1))
    S.save(path)
    print("sheet ->", path)


if __name__ == "__main__":
    main()
