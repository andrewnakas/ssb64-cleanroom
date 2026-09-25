# Super Smash Bros. clean room: status

## Decisions (log)
- 2026-09-25: ROM `Super Smash Bros. (USA).z64` from Downloads, sha1 e2929e10… matches the decomp (VetriTheRetri/ssb-decomp-re @ 7a85d55c7).
- **Web route = clean ROM + N64Wasm** (playbook §4 option 3). Why: no PC port with a web target
  (BattleShip = libultraship/C++, desktop only); N64Wasm (MIT, prebuilt ParaLLEl core) runs retail
  SSB64 at 60 fps even in headless SwiftShader; keyboard + gamepad + audio built in.
- The decomp build needs Linux-only tools (IDO IRIX4 frontend via qemu-irix, halAssetTool) and WSL
  is not installed, so the clean ROM is assembled by `games/ssb64/pack.py`: code/data segments are
  the decomp's matching output (identical bytes), asset regions are regenerated.
- relocData moves to ROM 0x1000000 (our vpk0 encoder is ~4% larger than retail's, so it can't stay
  in place); 59 lui/addiu pairs + 1 data word building `lLBRelocTableAddr` are patched; old slot
  zeroed. Verified with retail data: boots, intro and stage demo play.
- Kept as code (not art): IPL3 boot code, RSP microcode, libultra — same as any decomp build.

- vpk0: the game's decoder has room for only 64 Huffman nodes (both trees) and 20-deep stacks, so
  every file is recompressed with its retail tree *shapes* (compressor settings, recorded in
  spec/reloc_table.json), falling back to a small 16-bit tree when clean data needs longer codes.
- Reloc packing trap: the game reads every u16 between `stored*4` and the next file's start as an
  extern file id; any padding there made it load file 0 over and over (hang at the title). Fixed.
- Texture ranges are clipped at pointer slots and pointer targets (sprite nTLUT overshoots into the
  Bitmap structs; MObj palette-frame arrays), else sprite headers got overwritten.
- Dev harness note: N64Wasm speed in headless Edge is erratic for retail too (some intro scenes at
  1-2 fps); tests skip the intro (Start during the logo) and compare retail vs clean in the same run.

## Works
- Dev harness: `ports/emu/make_site.py` (N64Wasm + `?rom=`, `?keys=` hooks), `ports/emu/shot.py` (CDP screenshots).
- `games/ssb64/reloc.py` (table, vpk0 via vpk0cmd built from source, pointer chains), `pack.py`.

## Next
- Texture/palette/sprite census of the 2132 reloc files + particle banks; sound bank samples.
- Generate clean assets, build clean ROM, taint scan, publish.

## For the morning
- (pending)
