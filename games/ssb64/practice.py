"""Voice practice pack for the announcer lines (PERSONAL USE: decoded from the user's own ROM, written
outside the repo, never published).

    python -m games.ssb64.practice <baserom> <out dir>

Same layout as cleanroom.voice.practice: clips/NN_<name>.wav, practice_announcer_call_and_response.wav
(clip, 0.3 s, 880 Hz beep, a gap of 1.5x+1.5 s to repeat) and SCRIPT.txt with the text and max length.
Recordings go to <out>/takes/; cleanroom.voice.takes cuts them in the same order.
"""
import json
import os
import sys
import wave

import numpy as np

from cleanroom.audio import vadpcm

from . import audio

HERE = os.path.dirname(os.path.abspath(__file__))
HZ = 22050


def main():
    rom = open(sys.argv[1], "rb").read()
    out = sys.argv[2]
    lines = {k: v for k, v in json.load(open(os.path.join(HERE, "voice_lines.json"))).items() if not k.startswith("_")}
    slots = json.load(open(os.path.join(HERE, "spec", "samples.json")))
    spec = json.load(open(audio.SPEC))["sounds2"]
    name, c0, c1, t0, t1 = audio.BANKS[1]
    ctl = rom[c0:c1]
    os.makedirs(os.path.join(out, "clips"), exist_ok=True)
    os.makedirs(os.path.join(out, "takes"), exist_ok=True)

    def wr(path, x):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(HZ)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

    beep = (0.2 * np.sin(2 * np.pi * 880 * np.arange(int(0.08 * HZ)) / HZ)).astype(np.float32)
    track = []
    script = ["Announcer practice script: record in this order, 2-3 takes each, big stadium announcer voice.",
              "Play practice_announcer_call_and_response.wav and speak after each beep.",
              "Save recordings as takes/announcer.wav (one long file) or takes/NN.wav per line.", ""]
    seen = set()
    order = sorted(lines.items(), key=lambda kv: kv[1]["voice_id"])
    for i, (p, v) in enumerate(order, 1):
        w = p.split("/")[1][:-5]
        s = spec[w]
        bk = audio.book_at(ctl, s["book_off"])
        pcm = vadpcm.decode(rom[t0 + s["base"]:t0 + s["base"] + s["len"]], bk).astype(np.float32) / 32768
        sr = slots[p]["rate"]
        x = np.interp(np.arange(0, len(pcm) * HZ / sr) * sr / HZ, np.arange(len(pcm)), pcm).astype(np.float32)
        tag = v["voice_id"].replace("nSYAudioVoiceAnnounce", "")
        wr(os.path.join(out, "clips", f"{i:02d}_{tag}.wav"), x)
        if v["text"] not in seen:          # the call-and-response track asks for each distinct line once
            seen.add(v["text"])
            track += [x, np.zeros(int(0.3 * HZ), np.float32), beep, np.zeros(int((len(x) / HZ * 1.5 + 1.5) * HZ), np.float32)]
        script.append(f"{i:02d}  {tag:22s} max {slots[p]['nframes'] / sr:.1f}s  \"{v['text']}\"")
    wr(os.path.join(out, "practice_announcer_call_and_response.wav"), np.concatenate(track))
    script += ["", "These clips come from your own ROM: practice only, do not share or commit them."]
    open(os.path.join(out, "SCRIPT.txt"), "w", encoding="utf8").write("\n".join(script))
    print(f"practice pack: {len(order)} clips ({len(seen)} distinct lines) -> {out}")


if __name__ == "__main__":
    main()
