"""Assemble the web site: N64Wasm (MIT, prebuilt ParaLLEl core) + our page hooks + a ROM.

    python ports/emu/make_site.py <out dir> <rom.z64> [--n64wasm C:/Users/andre/n64work/n64wasm/dist]

Hooks added to N64Wasm's script.js:
  ?rom=<url>    auto-load that ROM when the wasm module is ready (default: the site's ROM)
  ?keys=t:key:dur,...   scripted key presses (dev: headless checks)
The ROM is written as game.z64. Never point this at a retail ROM for a published site.
"""
import argparse
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

AUTOLOAD = r"""
    async initModule(){
        console.log('module initialized');
        myClass.rivetsData.moduleInitializing = false;
        let q = new URLSearchParams(location.search);
        let rom = q.get('rom') || window.SITE_ROM;
        if (rom) { myClass.rom_name = myClass.extractRomName(rom); myClass.load_url(rom); }
        if (q.get('keys')) window.cleanroomKeys(q.get('keys'));
    }
"""

KEYS_JS = r"""
// dev hook: ?keys=t:key:dur,... (seconds; key = KeyboardEvent.key, e.g. Enter, d, ArrowLeft)
window.cleanroomKeys = function (spec) {
  const t0 = performance.now();
  spec.split(',').forEach(item => {
    const [t, key, dur] = item.split(':');
    setTimeout(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: key, bubbles: true }));
      setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup', { key: key, bubbles: true })),
                 1000 * parseFloat(dur || '0.15'));
    }, 1000 * parseFloat(t));
  });
};
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("rom")
    ap.add_argument("--n64wasm", default="C:/Users/andre/n64work/n64wasm/dist")
    ap.add_argument("--index", default=os.path.join(HERE, "index.html"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for f in ("assets.zip", "input_controller.js", "n64wasm.js", "n64wasm.wasm", "settings.js"):
        shutil.copy(os.path.join(a.n64wasm, f), os.path.join(a.out, f))
    src = open(os.path.join(a.n64wasm, "script.js"), encoding="utf-8").read()
    old_start = src.index("    async initModule(){")
    old_end = src.index("    //not being used currently")
    src = src[:old_start] + AUTOLOAD.lstrip("\n") + "\n" + src[old_end:]
    open(os.path.join(a.out, "script.js"), "w", encoding="utf-8").write(KEYS_JS + src)
    open(os.path.join(a.out, "romlist.js"), "w").write("var ROMLIST = [];\nwindow.SITE_ROM = 'game.z64';\n")
    idx = a.index if os.path.exists(a.index) else os.path.join(a.n64wasm, "index.html")
    shutil.copy(idx, os.path.join(a.out, "index.html"))
    shutil.copy(a.rom, os.path.join(a.out, "game.z64"))
    print("site ->", a.out)


if __name__ == "__main__":
    main()
