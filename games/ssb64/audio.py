"""Sound banks (B1_sounds1/2 .ctl + .tbl): dirty facts -> resynthesised clean samples.

    python -m games.ssb64.audio extract <baserom>          -> spec/audio.json (facts only)
    python -m games.ssb64.audio build <baserom> <out.bin>  -> clean patches (pickled {rom_off: bytes})

Kept per wave: byte length (so every sample keeps its frame count), loop start/end/count, predictor
count of its codebook (so the .ctl keeps its size), a coarse spectral outline (cleanroom.audio.descriptor)
and the median pitch. Generated: the waveform, our own VADPCM codebook, the loop state.
Music sequences (S1_music.sbk) and the FGM sound-effect scripts are note/event data: kept.
"""
import json
import os
import pickle
import struct
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from cleanroom.audio import descriptor, vadpcm
from cleanroom.audio.pitch import median_f0

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(HERE, "spec", "audio.json")
OVR = os.path.join(HERE, "overrides", "sounds")
RATE = 32000          # nominal: only used to express the outline; synthesis uses the same rate
BANKS = [("sounds1", 0xB4E5C0, 0xB54CE0, 0xB54CE0, 0xC6B650),
         ("sounds2", 0xC6B650, 0xC7B1F0, 0xC7B1F0, 0xF573D0)]
PRED_FAMILY = {4: vadpcm.PREDICTORS, 2: [(1.0, 0.0), (1.9, -0.92)]}


def waves_of(ctl):
    """{wave_off: dict(base, len, loop_off, book_off)} reachable from the bank file."""
    out = {}
    rev, n = struct.unpack_from(">hh", ctl, 0)
    for bo in struct.unpack_from(">%dI" % n, ctl, 4):
        if not bo:
            continue
        cnt, fl, pad, rate, perc = struct.unpack_from(">hBBiI", ctl, bo)
        insts = [i for i in struct.unpack_from(">%dI" % cnt, ctl, bo + 12) if i] + ([perc] if perc else [])
        for io in insts:
            ns = struct.unpack_from(">h", ctl, io + 14)[0]
            for so in struct.unpack_from(">%dI" % ns, ctl, io + 16):
                wt = struct.unpack_from(">I", ctl, so + 8)[0]
                base, ln, typ, wfl, lp, bk = struct.unpack_from(">IiBBxxII", ctl, wt)
                out[wt] = dict(base=base, len=ln, type=typ, loop_off=lp, book_off=bk)
    return out


def book_at(ctl, off):
    order, npred = struct.unpack_from(">ii", ctl, off)
    return {"order": order, "npred": npred,
            "book": list(struct.unpack_from(">%dh" % (order * npred * 8), ctl, off + 8))}


def _describe(args):
    key, data, book, loop = args
    pcm = vadpcm.decode(data, book)
    d = descriptor.describe(pcm, RATE)
    f0 = median_f0(pcm.astype(np.float32) / 32768.0, RATE) if len(pcm) > 2048 else None
    return key, d, f0, int(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))


def extract(rom):
    spec = {}
    jobs = []
    for name, c0, c1, t0, t1 in BANKS:
        ctl, tbl = rom[c0:c1], rom[t0:t1]
        ws = waves_of(ctl)
        spec[name] = {}
        for wt, w in sorted(ws.items()):
            bk = book_at(ctl, w["book_off"])
            loop = None
            if w["loop_off"]:
                s, e, c = struct.unpack_from(">III", ctl, w["loop_off"])
                loop = [s, e, c]
            spec[name][str(wt)] = dict(base=w["base"], len=w["len"], npred=bk["npred"], order=bk["order"],
                                        loop=loop, book_off=w["book_off"], loop_off=w["loop_off"])
            jobs.append(((name, str(wt)), tbl[w["base"]:w["base"] + w["len"]], bk, loop))
    with ProcessPoolExecutor(12) as ex:
        for (name, wt), d, f0, rms in ex.map(_describe, jobs, chunksize=4):
            spec[name][wt].update(desc=d, f0=f0, rms=rms)
    json.dump(spec, open(SPEC, "w"))
    n = sum(len(v) for v in spec.values())
    print(f"audio: {n} waves, {sum(1 for v in spec.values() for w in v.values() if w['loop'])} looped -> {SPEC}")


def _make(args):
    name, wt, w = args
    nsamp = w["len"] // 9 * 16
    ovr = os.path.join(OVR, name, f"{wt}.wav")
    if not os.path.exists(ovr) and name == "sounds2":
        ovr = os.path.join(HERE, "voices", f"{wt}.wav")     # announcer lines: TTS placeholder or user takes
    if os.path.exists(ovr):
        import scipy.io.wavfile as wavfile
        sr, x = wavfile.read(ovr)
        x = x.astype(np.float32) / (32768.0 if x.dtype == np.int16 else 1.0)
        if x.ndim > 1:
            x = x.mean(1)
        x = np.interp(np.linspace(0, len(x) - 1, nsamp), np.arange(len(x)), x) if len(x) != nsamp else x
    else:
        x = descriptor.synthesize(w["desc"], nsamp, RATE, seed=int(wt) * 7 + len(name))
    if w["loop"] and w["loop"][2]:
        s, e = w["loop"][0], min(w["loop"][1], nsamp)
        if e - s > 64:
            x = descriptor.make_loop_seamless(np.asarray(x, np.float64), s, e)
    x = np.asarray(x, np.float64)
    peak = np.abs(x).max() + 1e-9
    target = max(w["rms"], 16) / 32768.0
    cur = np.sqrt(np.mean(x ** 2)) + 1e-9
    x = x * min(target / cur, 0.95 / peak)
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype(np.int64)
    book = vadpcm.make_book(PRED_FAMILY[w["npred"]])
    data, book, dec = vadpcm.encode(pcm, book)
    data = data[:w["len"]] + bytes(max(0, w["len"] - len(data)))
    state = vadpcm.loop_state(dec, w["loop"][0]) if w["loop"] else None
    return name, wt, data, book, state


def build(rom):
    spec = json.load(open(SPEC))
    patches = {}
    jobs = [(name, wt, w) for name in spec for wt, w in spec[name].items()]
    res = {}
    with ProcessPoolExecutor(6) as ex:
        for name, wt, data, book, state in ex.map(_make, jobs, chunksize=2):
            res[(name, wt)] = (data, book, state)
    for name, c0, c1, t0, t1 in BANKS:
        ctl = bytearray(rom[c0:c1])
        tbl = bytearray(t1 - t0)            # nothing retail survives in the tbl
        for wt, w in spec[name].items():
            data, book, state = res[(name, wt)]
            tbl[w["base"]:w["base"] + w["len"]] = data
            struct.pack_into(">%dh" % len(book["book"]), ctl, w["book_off"] + 8, *book["book"])
            if w["loop_off"] and state is not None:
                struct.pack_into(">16h", ctl, w["loop_off"] + 12, *[max(-32768, min(32767, v)) for v in state])
        patches[c0] = bytes(ctl)
        patches[t0] = bytes(tbl)
    return patches


if __name__ == "__main__":
    rom = open(sys.argv[2], "rb").read()
    if sys.argv[1] == "extract":
        extract(rom)
    else:
        p = build(rom)
        pickle.dump(p, open(sys.argv[3], "wb"))
        print("audio patches:", {hex(k): len(v) for k, v in p.items()})
