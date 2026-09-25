"""Which SFX-bank samples are voice lines: gmFGMVoiceID -> fgm.ucd script -> set_articulation ->
fgm.tbl program -> trigger (sound index in B1_sounds2's instrument) -> wave.

    python -m games.ssb64.voicemap <baserom> <decomp tree>   -> spec/voice_slots.json

Uses the decomp's tools/extract_fgm.py decoders and the gmFGMVoiceID names (src/gm/gmsound.h,
preprocessed with clang for REGION_US).
"""
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys

from . import audio

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "spec", "voice_slots.json")
CLANG = os.path.expanduser("~/.local/clang+llvm-23.1.2-x86_64-pc-windows-msvc/bin/clang.exe")


def voice_names(tree):
    src = subprocess.run([CLANG, "-E", "-I", "include", "-I", ".", "-DREGION_US", "-x", "c", "-"], cwd=tree,
                         input=b'#include "src/gm/gmsound.h"\n', capture_output=True).stdout.decode()
    m = re.search(r"typedef enum\s+gmFGMVoiceID\s*\{(.*?)\}\s*gmFGMVoiceID", src, re.S)
    return [re.sub(r"=.*", "", x).strip() for x in m.group(1).split(",") if x.strip()]


def main():
    rom = open(sys.argv[1], "rb").read()
    tree = sys.argv[2]
    spec = importlib.util.spec_from_file_location("fx", os.path.join(tree, "tools", "extract_fgm.py"))
    fx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fx)
    tbl = fx.decode_fgm_tbl(rom[0xF57BF0:0xF5A9C0])["entries"]
    ucd = fx.decode_fgm_ucd(rom[0xF5A9C0:0xF5F4E0])["entries"]
    names = voice_names(tree)
    # sound index -> wave offset (sounds2 has one instrument)
    name, c0, c1, t0, t1 = audio.BANKS[1]
    ctl = rom[c0:c1]
    rev, n = struct.unpack_from(">hh", ctl, 0)
    bo = struct.unpack_from(">I", ctl, 4)[0]
    cnt = struct.unpack_from(">h", ctl, bo)[0]
    inst = struct.unpack_from(">I", ctl, bo + 12)[0]
    ns = struct.unpack_from(">h", ctl, inst + 14)[0]
    sounds = struct.unpack_from(">%dI" % ns, ctl, inst + 16)
    wave_of = [struct.unpack_from(">I", ctl, so + 8)[0] for so in sounds]
    out = {}
    for vid, nm in enumerate(names):
        if "Voice" not in nm or vid >= len(ucd):
            continue
        arts = [a[1] for a in ucd[vid]["program"] if a[0] == "set_articulation"]
        trig = []
        for a in arts:
            if a < len(tbl):
                trig += [p[1] for p in tbl[a]["program"] if p[0] == "trigger"]
        if trig:
            out[nm] = {"id": vid, "sounds": trig, "waves": [wave_of[s] for s in trig if s < len(wave_of)]}
    json.dump(out, open(OUT, "w"), indent=0)
    ann = sum(1 for k in out if "Announce" in k)
    print(f"voice ids with samples: {len(out)} (announcer {ann}) -> {OUT}")


if __name__ == "__main__":
    main()
