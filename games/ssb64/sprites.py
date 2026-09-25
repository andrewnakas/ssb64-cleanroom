"""Whole-sprite view: libultra Sprites are stored as strips (one Bitmap per band of rows).

sprite_groups(textures) -> {(fid, sprite_off): [texture facts in bitmap order]}
compose(parts, images) -> one (H, W, 4) image;  split(img, parts) -> per-bitmap images
sheet: python -m games.ssb64.sprites sheet <work> <fid,fid-fid,...> <out.png>   (dirty, labelled ids)
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec")


def sprite_groups(textures):
    g = {}
    for t in textures:
        if t.get("sprite"):
            g.setdefault(tuple(t["sprite"]), []).append(t)
    for k in g:
        g[k].sort(key=lambda t: t.get("bm") or 0)
    return g


def layout(parts):
    """Row offsets of each strip; width = max strip width."""
    ys, y = [], 0
    for t in parts:
        ys.append(y)
        y += t["h"]
    return ys, max(t["w"] for t in parts), y


def compose(parts, images):
    ys, W, H = layout(parts)
    out = np.zeros((H, W, 4), np.float32)
    for t, y, im in zip(parts, ys, images):
        out[y:y + im.shape[0], :im.shape[1]] = im
    return out


def split(img, parts):
    ys, W, H = layout(parts)
    return [img[y:y + t["h"], :t["w"]] for t, y in zip(parts, ys)]


def _ids(spec):
    out = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def sheet(work, fids, path, maxw=256, rom_path=None):
    from PIL import Image, ImageDraw
    from .extract_spec import image_of, load_files
    if rom_path:        # decode from another ROM (e.g. the clean build) instead of the dirty extraction
        from . import reloc

        class _F:
            pass
        rom = open(rom_path, "rb").read()
        ents = reloc.parse(rom[reloc.RELOC_ROM:reloc.RELOC_END])
        files = {}
        for i in range(reloc.FILE_COUNT):
            f = _F()
            f.data = reloc.file_data(ents[i]) if i in fids or True else b""
            files[i] = f
    else:
        rom = open("C:/Users/andre/n64work/ssb64/rom/baserom.us.z64", "rb").read()
        ents, files = load_files(rom, work)
    tex = json.load(open(os.path.join(SPEC, "textures.json")))
    groups = sprite_groups([t for t in tex if t["sprite"] and t["sprite"][0] in fids])
    tiles = []
    for key, parts in sorted(groups.items()):
        ims = []
        for t in parts:
            im = image_of(files, t)
            ims.append(im if im is not None else np.zeros((t["h"], t["w"], 4), np.uint8))
        img = compose(parts, ims).astype(np.uint8)
        im = Image.fromarray(img, "RGBA")
        if im.width > maxw:
            im = im.resize((maxw, max(1, im.height * maxw // im.width)))
        bg = Image.new("RGB", (max(im.width, 90), im.height + 12), (60, 30, 90))
        bg.paste(im, (0, 12), im)
        ImageDraw.Draw(bg).text((1, 0), f"{key[0]}:{key[1]:x}", fill=(255, 255, 0))
        tiles.append(bg)
    W = 1400
    x = y = rowh = 0
    pos = []
    for t in tiles:
        if x + t.width > W:
            x, y, rowh = 0, y + rowh + 2, 0
        pos.append((x, y))
        x += t.width + 2
        rowh = max(rowh, t.height)
    S = Image.new("RGB", (W, y + rowh + 2), (20, 20, 20))
    for t, p in zip(tiles, pos):
        S.paste(t, p)
    S.save(path)
    print(f"{len(tiles)} sprites -> {path} ({S.width}x{S.height})")


if __name__ == "__main__":
    if sys.argv[1] == "sheet":
        sheet(sys.argv[2], _ids(sys.argv[3]), sys.argv[4], rom_path=sys.argv[5] if len(sys.argv) > 5 else None)
