# Super Smash Bros. (N64) — clean room web build

Play: **https://andrewnakas.github.io/ssb64-cleanroom/**

Super Smash Bros. built from the [ssb-decomp-re](https://github.com/VetriTheRetri/ssb-decomp-re)
decompilation, with **every asset the decomp extracts from a ROM regenerated**: textures, sprites,
palettes, particle images and every instrument/sound sample. The result is a clean N64 ROM image that
runs in the browser on [N64Wasm](https://github.com/nbarkhina/N64Wasm) (MIT, ParaLLEl core).

Controls: arrow keys = stick · `D` = A · `S` = B · `A` = Z · `Q`/`E` = L/R · `Enter` = Start ·
`I J K L` = C buttons · gamepads work too.

## What is kept, what is generated

| Asset | Kept fact | Generated |
|---|---|---|
| Textures, sprites, materials (4,540 in 2,132 reloc files) | format, size, a 4×4 colour grid (16×16 from 128 px), a 2-bit alpha outline, which palette a CI texture uses | colour from the grid, a faint ordered dither, the alpha outline; CI palettes by k-means over every texture that shares them |
| Palettes (724) | size | quantised from our images |
| Particle images (246 frames, 9 banks) | format, size, grid, alpha outline | as textures |
| Samples (439 in two banks) | byte length (frame count), loop points, codebook predictor count, a coarse spectral outline, median pitch, level | resynthesised; our own VADPCM codebooks; loop states recomputed |
| Music sequences, FGM sound-effect scripts | note/event data (kept, as the decomp) | — |
| Game code, display lists, vertices, animations, collision | the decomp's matching code/data | — |

Found by structure, not by name: display-list texture loads, `MObjSub` material frame arrays,
libultra `Sprite`/`Bitmap` records (sprite bitmaps are stored TMEM-swizzled), plus every block the
decomp declares in `src/relocData/*.c` (`@tex` annotations give the format).

`python -m games.ssb64.taint <baserom> <clean rom>` compares every texture, palette, particle frame and
sample against the retail bytes at the same place: **0 failing** (a range fails if it shares a
32-byte run with detail, ≥ 8 distinct byte values, with the original).

## Build

```sh
# dirty room, once: needs your own US ROM (sha1 e2929e10fccc0aa84e5776227e798abc07cedabf), never published
python -m games.ssb64.extract_spec baserom.us.z64 work/        # -> games/ssb64/spec (facts only)
python -m games.ssb64.audio extract baserom.us.z64
python -m games.ssb64.particles extract baserom.us.z64
# clean room
python -m games.ssb64.generate baserom.us.z64 out/             # -> out/ssb64_clean.z64
python -m games.ssb64.taint baserom.us.z64 out/ssb64_clean.z64
python ports/emu/make_site.py site/ out/ssb64_clean.z64
```

The ROM's code segments are the decomp's matching build output (byte-identical by construction); the
generator takes them from the base image and rewrites only asset regions. The reloc files are
re-packed in place with vpk0 using the original Huffman tree *shapes* (the game's decoder has room for
only 64 tree nodes).

Voices and the announcer are placeholders for now.
