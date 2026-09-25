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


# lettering painted from its own kept silhouette: layers by distance (px) from the transparent edge
RIMS = {
    "167:245c8": {"layers": [[2, [25, 10, 10]]], "fill": [[215, 25, 20], [180, 15, 15]],
                  "text": "SMASH", "ink": [[255, 240, 70], [245, 140, 20]], "edge": [90, 10, 10]},
    "167:16728": {"layers": [[2, [15, 15, 15]]], "fill": [[250, 250, 250], [220, 220, 220]],
                  "text": "SUPER", "ink": [[20, 20, 20], [20, 20, 20]]},
    "167:25188": {"layers": [[2, [15, 15, 15]]], "fill": [[250, 250, 250], [220, 220, 220]],
                  "text": "BROS.", "ink": [[20, 20, 20], [20, 20, 20]]},
}


def _edge_distance(alpha):
    solid = alpha >= 128
    dist = np.zeros(alpha.shape, np.float32)
    cur = solid.copy()
    for d in range(1, 16):
        dist[cur] = d
        nxt = cur.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nxt &= np.roll(np.roll(cur, dy, 0), dx, 1)
        if not nxt.any():
            break
        cur = nxt
    return dist


def rim_fill(spec, base):
    a = base[..., 3]
    dist = _edge_distance(a)
    H = a.shape[0]
    t = (np.arange(H, dtype=np.float32) / max(1, H - 1))[:, None, None]
    top, bot = (np.asarray(c, np.float32) for c in spec["fill"])
    img = np.zeros(base.shape, np.float32)
    img[..., :3] = top * (1 - t) + bot * t
    lo = 0
    for upto, c in spec["layers"]:
        m = (dist > lo) & (dist <= upto)
        img[m, :3] = c
        lo = upto
    if spec.get("text"):
        from cleanroom.gfx import strokefont
        ys, xs = np.nonzero(a >= 128)
        y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
        bh, bw = int((y1 - y0) * 0.62), int((x1 - x0) * 0.86)
        th = max(2, bh // 5)
        line = strokefont.render_line(spec["text"], bh, thickness=th)
        xi = np.linspace(0, line.shape[1] - 1, bw)
        line = np.stack([np.interp(xi, np.arange(line.shape[1]), r) for r in line])
        m = np.zeros(a.shape, np.float32)
        oy, ox = y0 + ((y1 - y0) - bh) // 2, x0 + ((x1 - x0) - bw) // 2
        m[oy:oy + bh, ox:ox + bw] = np.clip(line * 1.5, 0, 1)
        m *= (dist > 2)
        tt = (np.arange(a.shape[0], dtype=np.float32) - oy) / max(1, bh)
        tt = np.clip(tt, 0, 1)[:, None, None]
        top, bot = (np.asarray(c, np.float32) for c in spec["ink"])
        ink = top * (1 - tt) + bot * tt
        if spec.get("edge"):
            ring = m.copy()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ring = np.maximum(ring, np.roll(np.roll(m, dy, 0), dx, 1))
            img[..., :3] = img[..., :3] * (1 - ring[..., None]) + np.asarray(spec["edge"], np.float32) * ring[..., None]
        img[..., :3] = img[..., :3] * (1 - m[..., None]) + ink * m[..., None]
    img[..., 3] = a
    return img


def hook(t):
    return None


CHROME = {"layers": [[1, [20, 20, 30]]], "fill": [[250, 250, 255], [120, 125, 140]]}


def sprite_hook(key, w, h, base=None):
    if key in RIMS and base is not None:
        return rim_fill(RIMS[key], base)
    if key.startswith("37:") and base is not None:      # announcer letters (GO!, GAME SET...)
        img = rim_fill(CHROME, base)
        H = img.shape[0]
        band = (np.abs(np.arange(H) - H * 0.55) < max(1, H * 0.06))[:, None]
        img[..., :3] = np.where(band[..., None] & (img[..., 3:4] > 0), img[..., :3] * 0.55, img[..., :3])
        return img
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
