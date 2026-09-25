"""Dev check: run the same key script on the retail (dirty, local only) and clean sites; one A/B sheet.

    python -m games.ssb64.check <name> --secs 16,22 --keys "12:Enter,..." [--only clean] [--gpu]

Retail site: http://localhost:8091 (devsite_retail), clean: http://localhost:8092 (devsite_clean).
Rows: retail on top, clean below. Output: C:/Users/andre/n64work/ssb64/shots/<name>/ab.png
"""
import argparse
import os
import subprocess
import sys

from PIL import Image, ImageDraw

ROOT = "C:/Users/andre/n64work/ssb64/shots"
SITES = {"retail": "http://localhost:8091/index.html?rice=1", "clean": "http://localhost:8092/index.html?rice=1"}
FLOWS = {
    # title -> mode select -> 1P game -> character select
    "css1p": ("16,24,34,40", "12:Enter:0.3,20:Enter:0.3,24:Enter:0.3,30:Enter:0.3"),
    # ... pick the fighter under the cursor, start, into the 1P intro and first match
    "match1p": ("34,44,50,58,66,80", "12:Enter:0.3,20:Enter:0.3,24:Enter:0.3,30:Enter:0.3,"
                "36:d:0.3,40:Enter:0.3,46:Enter:0.3,52:Enter:0.3,60:ArrowRight:1.5,62:d:0.2,63:d:0.2,70:s:0.3"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--secs")
    ap.add_argument("--keys", default="")
    ap.add_argument("--only", default=None)
    ap.add_argument("--gpu", action="store_true")
    a = ap.parse_args()
    secs, keys = a.secs, a.keys
    if a.name in FLOWS and not secs:
        secs, keys = FLOWS[a.name]
    here = os.path.dirname(os.path.abspath(__file__))
    shot = os.path.join(here, "..", "..", "ports", "emu", "shot.py")
    rows = []
    for which in ([a.only] if a.only else ["retail", "clean"]):
        out = os.path.join(ROOT, a.name, which)
        cmd = [sys.executable, shot, out, "--url", SITES[which], "--secs", secs, "--keys", keys]
        if a.gpu:
            cmd.append("--gpu")
        subprocess.run(cmd, capture_output=True)
        ims = []
        for s in secs.split(","):
            p = os.path.join(out, f"shot_{float(s):g}.png")
            ims.append(Image.open(p).convert("RGB").crop((110, 134, 750, 614)).resize((320, 240)) if os.path.exists(p)
                       else Image.new("RGB", (320, 240)))
        rows.append((which, ims))
    W = 320 * len(rows[0][1])
    sheet = Image.new("RGB", (W, 240 * len(rows)))
    for r, (which, ims) in enumerate(rows):
        for c, im in enumerate(ims):
            sheet.paste(im, (c * 320, r * 240))
        ImageDraw.Draw(sheet).text((4, r * 240 + 4), which, fill=(255, 255, 0))
    path = os.path.join(ROOT, a.name, "ab.png")
    sheet.save(path)
    print(path)


if __name__ == "__main__":
    main()
