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

## Works (2026-09-25 ~07:30)
- Live: https://andrewnakas.github.io/ssb64-cleanroom/ (clean 16 MB ROM + N64Wasm, keyboard + gamepad).
- Boots; menus, 1P menu, character select work; attract demos play at 60 fps (tutorial match,
  4-player Dream Land, stage fly-bys). Clean ROM = retail code + regenerated assets, relocData
  re-packed in place (no code patches).
- Regenerated: 4,540 textures/sprites + 724 palettes (found structurally + every block the decomp
  declares), 246 particle frames, 439 samples; announcer = Piper TTS placeholders (62 slots).
  Taint: 0 failing (6,007 ranges). Publishing is gated on taint (`ssb64/publish.sh`).
- Readable: menu labels (I/IA sprites rebuilt from the kept outline), CSS labels, HUD digits.

- Character-select portraits: painted from our own briefs (`portrait_briefs.json`, facepaint) with
  re-typeset names; preview in shots/portraits0.png.

- Title logo re-typeset (SMASH / SUPER / BROS. in our stroke font inside the kept silhouettes);
  mode-select icons drawn from our own line briefs (`icon_briefs.json`).

- Big multi-strip sprites (stage wallpapers, backgrounds, pictures >= 128 px) use one 16x16 grid for
  the whole picture (spec/sprites.json) instead of a grid per 6-row strip: no more banding/stripes.

## Known issues / next
- IA icons whose detail is in the intensity (mode-select controller/console icons) are plain discs:
  need briefs.
- Portraits, stage art, big RGBA pictures are colour grids (blurry). Plan: render fighters from their
  own models (`games/ssb64/fighter_render.py`, skeleton + DL walk working; texture/palette binding
  still wrong for some fighters) for CSS portraits / results / stock icons.
- Some fighters render dark/noisy in game: CI palette links for material textures are heuristic;
  fix by recording the TLUT actually loaded in each DL walk (in progress).
- Speed: in headless Edge the title screen and some intro scenes crawl (2-17 fps) for the RETAIL ROM
  too (N64Wasm's default GLideN64 path on that full-screen effect; not SRAM, not particles, not our
  textures - all tested). `?rice=1` (Rice renderer) was usually faster. Please check a real browser;
  if the title is slow there too, I'll make Rice the default or skip-to-menu faster.
- CI palettes: model/material textures now share one palette per (file, CI4/CI8) group so whichever
  TLUT the game loads the colours are right; costume colour variants collapse to one set for now.
- Fighter voices (grunts) are resynthesised noise-like placeholders; only announcer lines are TTS.

## For the morning
1. Play the site in a real browser (desktop, GPU): 1P and VS. Tell me what looks/sounds worst.
2. Record the announcer: `C:/Users/andre/n64work/ssb64/practice/` has SCRIPT.txt (62 lines, 60
   distinct), `practice_announcer_call_and_response.wav` (listen, speak after each beep) and `clips/`
   (reference, personal use only, never committed). Put your takes in `practice/takes/`; I will cut
   them (cleanroom.voice.takes) into `games/ssb64/voices/<slot>.wav` and rebuild.
