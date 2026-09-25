"""Taint scan: no retail pixels or samples may survive in the clean ROM.

    python -m games.ssb64.taint <baserom> <clean rom>

Checks every texture and palette range (decompressed reloc files) and every sample (sound bank .tbl):
a range FAILS if it shares a run of >= 32 bytes with the retail bytes at the same place that carries
detail (>= 8 distinct byte values). Flat areas (transparent, solid black/white, silence) coincide
by nature and are not content. Also reports how much
of the whole ROM outside relocData/.tbl is byte-identical (code and structure are expected to be).
"""
import json
import os
import sys

import numpy as np

from . import audio, reloc

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = 32


def shared_run(a, b):
    """Longest run where a == b, not counting runs made of one repeated byte value."""
    a = np.frombuffer(a, np.uint8)
    b = np.frombuffer(b[:len(a)], np.uint8)
    n = min(len(a), len(b))
    eq = a[:n] == b[:n]
    best = cur = 0
    start = 0
    for i in range(n):
        if eq[i]:
            if cur == 0:
                start = i
            cur += 1
            if cur >= RUN and len(set(a[start:i + 1].tolist())) >= 8:
                best = max(best, cur)
        else:
            cur = 0
    return best


def main():
    retail = open(sys.argv[1], "rb").read()
    clean = open(sys.argv[2], "rb").read()
    spec = os.path.join(HERE, "spec")
    tex = json.load(open(os.path.join(spec, "textures.json")))
    pal = json.load(open(os.path.join(spec, "palettes.json")))
    rf = reloc.parse(retail[reloc.RELOC_ROM:reloc.RELOC_END])
    cf = reloc.parse(clean[reloc.RELOC_ROM:reloc.RELOC_END])
    need = {t["fid"] for t in tex} | {p["fid"] for p in pal}
    rd = {i: reloc.file_data(rf[i]) for i in need}
    cd = {i: reloc.file_data(cf[i]) for i in need}
    fails, checked = [], 0
    for r in tex + pal:
        a = cd[r["fid"]][r["off"]:r["off"] + r["nbytes"]]
        b = rd[r["fid"]][r["off"]:r["off"] + r["nbytes"]]
        checked += 1
        if len(a) >= RUN and shared_run(a, b) >= RUN:
            fails.append(("tex", r["fid"], r["off"], r["nbytes"]))
    aspec = json.load(open(audio.SPEC))
    for name, c0, c1, t0, t1 in audio.BANKS:
        for wt, w in aspec[name].items():
            a = clean[t0 + w["base"]:t0 + w["base"] + w["len"]]
            b = retail[t0 + w["base"]:t0 + w["base"] + w["len"]]
            checked += 1
            if shared_run(a, b) >= RUN:
                fails.append(("wave", name, wt, w["len"]))
    from . import particles
    for d in json.load(open(particles.SPEC)):
        for off, n in [(d["rom"], d["nbytes"])] + ([(d["pal_rom"], d["pal_n"] * 2)] if "pal_rom" in d else []):
            checked += 1
            if shared_run(clean[off:off + n], retail[off:off + n]) >= RUN:
                fails.append(("particle", d["bank"], d["tex"], d["frame"]))
    same = sum(1 for i in range(0, reloc.RELOC_ROM, 4) if clean[i:i + 4] == retail[i:i + 4])
    print(f"taint: {checked} ranges checked, {len(fails)} failing")
    for f in fails[:20]:
        print("  FAIL", f)
    print(f"code/boot region identical: {100 * same * 4 / reloc.RELOC_ROM:.1f}% (expected ~100%: decomp code)")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
