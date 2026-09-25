"""Voice practice pack for EVERY voice line (announcer, fighters, Pokemon, crowd, other).
PERSONAL USE: reference clips are decoded from the user's own ROM; write outside the repo, never publish.

    python -m games.ssb64.practice_all <baserom> <out dir>

Per group: clips/<group>/NNN_<line>.wav, practice_<group>_call_and_response.wav (clip, 0.3 s, 880 Hz
beep, a gap of 1.5x+1.5 s to repeat). One SCRIPT.txt lists every line with its max length.
Playback rate per group is estimated from the median pitch outline (a target voice pitch per group).
"""
import json
import os
import re
import sys
import wave

import numpy as np

from cleanroom.audio import vadpcm

from . import audio

HERE = os.path.dirname(os.path.abspath(__file__))
HZ = 22050
GROUPS = ["Announce", "Mario", "Luigi", "Donkey", "Samus", "Link", "Yoshi", "Kirby", "Fox", "Pikachu", "Purin",
          "Captain", "Ness", "MBall", "Public"]
TARGET_F0 = {"Announce": 110, "Mario": 210, "Luigi": 190, "Donkey": 120, "Samus": 260, "Link": 230, "Yoshi": 330,
             "Kirby": 420, "Fox": 170, "Pikachu": 450, "Purin": 450, "Captain": 150, "Ness": 300, "MBall": 250,
             "Public": 200, "Other": 200}
NICE = {"Announce": "announcer", "Donkey": "donkey_kong", "Purin": "jigglypuff", "Captain": "captain_falcon",
        "MBall": "pokemon", "Public": "crowd"}


def group_of(name):
    rest = re.sub(r"^nSYAudioVoice", "", name)
    return next((g for g in GROUPS if rest.startswith(g)), "Other"), rest


def words(rest, g):
    tail = rest[len(g):] if rest.startswith(g) else rest
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tail).strip() or rest


def main():
    rom = open(sys.argv[1], "rb").read()
    out = sys.argv[2]
    slots = json.load(open(os.path.join(HERE, "spec", "voice_slots.json")))
    lines = {k: v for k, v in json.load(open(os.path.join(HERE, "voice_lines.json"))).items() if not k.startswith("_")}
    ann_text = {v["voice_id"]: v["text"] for v in lines.values()}
    spec = json.load(open(audio.SPEC))["sounds2"]
    name, c0, c1, t0, t1 = audio.BANKS[1]
    ctl = rom[c0:c1]
    groups = {}
    for vname, e in slots.items():
        g, rest = group_of(vname)
        for k, w in enumerate(dict.fromkeys(e["waves"])):
            groups.setdefault(g, []).append((vname, rest, str(w), k))
    beep = (0.2 * np.sin(2 * np.pi * 880 * np.arange(int(0.08 * HZ)) / HZ)).astype(np.float32)

    def wr(path, x):
        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(HZ)
            f.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())

    script = ["SUPER SMASH BROS. VOICE PRACTICE SCRIPT (all voice lines)",
              "How to use: pick a character track (practice_<who>_call_and_response.wav), listen to each clip,",
              "and after the beep perform it in your own voice. Record each character as ONE file named",
              "takes/<who>.wav (same order as below), or single lines as takes/<who>/NNN.wav.",
              "Grunts/efforts: match the length and energy, not the exact sound. Announcer: big stadium voice.",
              "Reference clips come from your own ROM: practice only, do not share or commit them.", ""]
    total = 0
    order = [g for g in GROUPS + ["Other"] if g in groups]
    for g in order:
        who = NICE.get(g, g.lower())
        items = sorted(groups[g], key=lambda x: (x[0], x[3]))
        f0s = [spec[w]["f0"] for _, _, w, _ in items if spec[w].get("f0")]
        rate = int(np.clip(32000 * TARGET_F0.get(g, 200) / (np.median(f0s) if f0s else 480), 5000, 22050))
        os.makedirs(os.path.join(out, "clips", who), exist_ok=True)
        track = []
        script.append(f"=== {who.upper()}  ({len(items)} lines, track practice_{who}_call_and_response.wav) ===")
        for i, (vname, rest, w, k) in enumerate(items, 1):
            s = spec[w]
            bk = audio.book_at(ctl, s["book_off"])
            pcm = vadpcm.decode(rom[t0 + s["base"]:t0 + s["base"] + s["len"]], bk).astype(np.float32) / 32768
            x = np.interp(np.arange(0, len(pcm) * HZ / rate) * rate / HZ, np.arange(len(pcm)), pcm).astype(np.float32)
            label = re.sub(r"\W+", "_", rest)[:48] + (f"_{k + 1}" if k else "")
            wr(os.path.join(out, "clips", who, f"{i:03d}_{label}.wav"), x)
            track += [x, np.zeros(int(0.3 * HZ), np.float32), beep,
                      np.zeros(int((len(x) / HZ * 1.5 + 1.5) * HZ), np.float32)]
            say = ann_text.get(vname) or f"({words(rest, g)})"
            script.append(f"{i:03d}  max {len(x) / HZ:4.1f}s  {say}")
            total += 1
        wr(os.path.join(out, f"practice_{who}_call_and_response.wav"), np.concatenate(track))
        script.append("")
    os.makedirs(os.path.join(out, "takes"), exist_ok=True)
    open(os.path.join(out, "SCRIPT.txt"), "w", encoding="utf8").write("\n".join(script))
    print(f"practice pack: {total} lines in {len(order)} groups -> {out}")


if __name__ == "__main__":
    main()
