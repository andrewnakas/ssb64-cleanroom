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

## Works (2026-09-25 ~05:00)
- Clean ROM (16 MB, relocData re-packed in place, no code patches) boots, menus and character
  select work, attract demos play at 60 fps (tutorial match, 4-player Dream Land, stage fly-bys).
- Every texture/sprite/palette (4,540 + 724, found structurally + decomp declarations), 246 particle
  frames and 439 samples regenerated. Taint: 0 failing over 6,007 ranges.
- Site: N64Wasm + clean ROM, keyboard + gamepad. Published to andrewnakas/ssb64-cleanroom (gh-pages).

## Known issues / next
- Text is blurry (4x4 grids): menus, names, HUD need re-typesetting (priority 2).
- Portraits/icons/faces are colour grids: need briefs/renders (priority 3).
- Some fighters/posters partly dark: CI palette linking is heuristic for material textures.
- A few stage textures striped (Congo Jungle) - format of a few DL loads.
- N64Wasm in headless Edge is sometimes very slow in some scenes (retail too) - check in a real browser.
- Voices/announcer: placeholder pass + practice pack not done yet.

## For the morning
- Open the site in a real browser (desktop GPU), play 1P/VS: tell me what looks worst.
- Voice practice pack: not built yet (see next steps).
