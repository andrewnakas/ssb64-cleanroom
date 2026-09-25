"""Hand-made art for textures where a colour grid is not enough (portraits, labels).

hook(t) -> (h, w, 4) float RGBA or None             per texture (default: grid + outline)
sprite_hook(key, w, h) -> (H, W, 4) float or None   whole sprite, key "fid:offset" (hex); split into strips
"""
import json
import os

import numpy as np

from cleanroom.gfx import facepaint, glyphs

HERE = os.path.dirname(os.path.abspath(__file__))
_PORTRAITS = None


def portraits():
    global _PORTRAITS
    if _PORTRAITS is None:
        _PORTRAITS = {k: v for k, v in json.load(open(os.path.join(HERE, "portrait_briefs.json"))).items()
                      if not k.startswith("_")}
    return _PORTRAITS


def name_plate(img, text, h=7):
    """Re-typeset name: white stroke letters with a dark outline, top left."""
    H, W = img.shape[:2]
    m = glyphs._fit_line(text, min(W - 2, len(text) * 5 + 2), h)
    mask = np.zeros((H, W), np.float32)
    mask[1:1 + h, 1:1 + m.shape[1]] = m[:min(h, H - 1)]
    ring = np.zeros_like(mask)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ring = np.maximum(ring, np.roll(np.roll(mask, dy, 0), dx, 1))
    img[..., :3] = img[..., :3] * (1 - ring[..., None]) + np.array([20, 20, 30]) * ring[..., None]
    img[..., :3] = img[..., :3] * (1 - mask[..., None]) + np.array([255, 245, 200]) * mask[..., None]
    return img


_ICONS = None
STYLES = {"light": {"bg": [225, 225, 225], "line": [25, 25, 25], "fill": [225, 225, 225]},
          "dark": {"bg": [120, 120, 120], "line": [20, 20, 20], "fill": [120, 120, 120]}}


def icons():
    global _ICONS
    if _ICONS is None:
        raw = json.load(open(os.path.join(HERE, "icon_briefs.json")))
        _ICONS = {}
        for k, v in raw.items():
            if k.startswith("_") or "use" not in v:
                continue
            st = STYLES[v.get("style", "light")]
            ops = []
            for op in raw[v["use"]]["ops"]:
                op = dict(op)
                op["c"] = st[op["c"]] if isinstance(op.get("c"), str) else op.get("c")
                ops.append(op)
            _ICONS[k] = {"base": st["bg"], "ops": ops, "keep_alpha": True}
    return _ICONS


def hook(t):
    return None


def sprite_hook(key, w, h):
    ic = icons().get(key)
    if ic is not None:
        img = facepaint.render(ic, w, h)
        img[..., 3] = -1                   # keep the kept alpha outline of each strip
        return img
    b = portraits().get(key)
    if b is None:
        return None
    img = facepaint.render(b, w, h)
    if b.get("name"):
        img = name_plate(img, b["name"])
    img[..., 3] = 255
    return img
