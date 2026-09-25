"""Dirty room: ROM -> games/ssb64/spec (facts only).

    python -m games.ssb64.extract_spec <baserom.us.z64> <work dir> [--sheet N]

Writes:
  <work>/reloc/<fid>.bin           decompressed retail reloc files (dirty, never published)
  games/ssb64/spec/reloc_table.json  container layout (sizes/flags/chain heads: structure, not art)
  games/ssb64/spec/textures.json     per texture: fid, off, nbytes, fmt, siz, w, h, pal link, 4x4 grid, 2-bit alpha
  games/ssb64/spec/palettes.json     per palette: fid, off, count (colours are NOT kept)
"""
import argparse
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
    tex = [v for v in by.values() if v["kind"] == "tex"]
    pal = [v for v in by.values() if v["kind"] == "pal"]
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


def image_of(files, t):
    d = files[t["fid"]].data
    raw = d[t["off"]:t["off"] + t["nbytes"]]
    w, h = t["w"], t["h"]
    need = w * h * t["siz"] // 8
    raw = raw + bytes(max(0, need - len(raw)))
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
    os.makedirs(SPEC, exist_ok=True)
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
