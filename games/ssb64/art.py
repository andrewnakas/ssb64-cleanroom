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


TAGS = {"38:258": "1P", "38:4f8": "2P", "38:798": "3P", "38:a38": "4P", "38:cd8": "CP",
        "34:49e8": "1P", "34:4b08": "2P", "34:4c28": "3P", "34:4d48": "4P"}


LABELS = {"80:25e8": "Timer", "80:2b48": "Damage", "80:b4f8": "Target"}


def retype(text, w, h, ink=(250, 235, 120), edge=(30, 20, 10)):
    th = max(5, h - 2)
    line = glyphs._fit_line(text, w - 2, th)
    m = np.zeros((h, w), np.float32)
    m[1:1 + th, 1:1 + line.shape[1]] = np.clip(line[:h - 1] * 1.6, 0, 1)
    ring = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ring = np.maximum(ring, np.roll(np.roll(m, dy, 0), dx, 1))
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = np.where(m[..., None] > 0.5, np.array(ink, np.float32), np.array(edge, np.float32))
    img[..., 3] = ring * 255
    return img


def results_floor(w, h, base):
    """Results backdrop: soft cloudy sky over a perspective checkerboard floor (our own drawing;
    brightness range from the kept grid)."""
    lum = base[..., :3].mean(-1)
    lo, hi = float(np.percentile(lum, 5)), float(np.percentile(lum, 95))
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    horizon = h * 0.62
    rng = np.random.default_rng(7)
    sky = np.zeros((h, w), np.float32)
    for k, amp in ((6, 0.5), (12, 0.3), (24, 0.2)):
        g = rng.random((k + 1, k + 1)).astype(np.float32)
        yi, xi = ys / h * k, xs / w * k
        y0, x0 = yi.astype(int), xi.astype(int)
        fy, fx = yi - y0, xi - x0
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        v = (g[y0, x0] * (1 - fx) + g[y0, x0 + 1] * fx) * (1 - fy) + (g[y0 + 1, x0] * (1 - fx) + g[y0 + 1, x0 + 1] * fx) * fy
        sky += amp * v
    sky = np.clip((sky - 0.35) * 2.0, 0, 1)
    val = lo + (hi - lo) * (0.55 + 0.45 * sky)
    fl = ys > horizon
    z = 1.0 / np.maximum(ys - horizon, 1.0) * h * 0.25
    u = (xs - w / 2) / w * z * 6
    chk = ((np.floor(u) + np.floor(z * 2.0)) % 2 == 0)
    val = np.where(fl, np.where(chk, hi, lo + (hi - lo) * 0.2), val)
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = val[..., None]
    img[..., 3] = 255
    return img


def badge_one(base):
    img = base.copy()
    H, W = img.shape[:2]
    th = int(H * 0.55)
    line = glyphs._fit_line("1", max(4, th // 2 + 2), th)
    m = np.zeros((H, W), np.float32)
    oy, ox = int(H * 0.12), (W - line.shape[1]) // 2
    m[oy:oy + th, ox:ox + line.shape[1]] = np.clip(line * 1.6, 0, 1)
    ring = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ring = np.maximum(ring, np.roll(np.roll(m, dy, 0), dx, 1))
    img[..., :3] = img[..., :3] * (1 - ring[..., None]) + np.array([40, 30, 0]) * ring[..., None]
    img[..., :3] = img[..., :3] * (1 - m[..., None]) + np.array([255, 225, 40]) * m[..., None]
    img[..., 3] = np.maximum(img[..., 3], ring * 255)
    return img
HUD_LETTERS = {"82:" + k for k in ("4d78", "a730", "c370", "e4a8", "f740", "127e0", "144e0", "16eb8", "18fe8",
                                    "1b6f8", "1de68", "20788")}   # G O ! T I M E U P S A G
FIRE = {"layers": [[1, [60, 10, 0]]], "fill": [[255, 230, 90], [215, 50, 10]]}
BLUE = {"layers": [[1, [10, 15, 50]]], "fill": [[200, 225, 255], [30, 70, 200]]}


def player_tag(text, w, h):
    """'1P' above a down-pointing triangle, white with a dark edge (the game tints it per player)."""
    th = max(5, int(h * 0.62))
    line = glyphs._fit_line(text, w - 1, th)
    m = np.zeros((h, w), np.float32)
    m[:th, :line.shape[1]] = np.clip(line * 1.6, 0, 1)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, top = (w - 1) / 2, th + 0.5
    tri = (ys >= top) & (np.abs(xs - cx) <= (h - 1 - ys) * 0.9) & (ys <= h - 1)
    m = np.maximum(m, tri.astype(np.float32))
    ring = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            ring = np.maximum(ring, np.roll(np.roll(m, dy, 0), dx, 1))
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = np.where(m[..., None] > 0.5, 250.0, 30.0)
    img[..., 3] = np.clip(ring, 0, 1) * 255
    return img


CHROME = {"layers": [[1, [20, 20, 30]]], "fill": [[250, 250, 255], [120, 125, 140]]}


def sprite_hook(key, w, h, base=None):
    if key in RIMS and base is not None:
        return rim_fill(RIMS[key], base)
    if key in TAGS:
        return player_tag(TAGS[key], w, h)
    if key in LABELS:
        return retype(LABELS[key], w, h)
    if key == "34:d5c8" and base is not None:
        return results_floor(w, h, base)
    if key == "34:e2a0" and base is not None:
        return badge_one(base)
    if key in HUD_LETTERS and base is not None:
        return rim_fill(FIRE if key in ("82:4d78", "82:a730", "82:c370") else BLUE, base)
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
