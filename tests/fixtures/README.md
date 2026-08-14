# Test fixtures

Binary `.bin` watchface files used by the test suite. These are real
H26 watchfaces captured for parser testing only.

## Files

### `Clock20517_res.bin`

* **Size**: 91,076 bytes
* **Coverage**:
  * 66 LZ4pal32 image blocks
  * 14 UI items across 5 types (0x00 Layout, 0x01/0x02 frames, 0x0F
    hands with rotation pivots, 0x14 animations including a 14-frame
    sequence)
  * 0 unknown blocks
* **Notes**: complex analog watchface with both regular and AOD
  layouts, 3 hands × 2 layouts.

### `Clock21592_res.bin`

* **Size**: 234,188 bytes
* **Coverage**:
  * 35 LZ4pal32 image blocks
  * 8 UI items across 4 types (0x00 Layout, 0x01 frames, 0x0F
    hands, 0x14 animations)
  * 0 unknown blocks
* **Notes**: simpler analog watchface with a single layout, 2 hands,
  2 animations. Useful as a small-footprint regression target.

## License

Both fixtures are provided by the project author for parser
development and testing. Released under the same MIT license as the
project unless otherwise noted by the original creator. They contain
no user-identifying data, credentials, or proprietary material
beyond the binary watchface structure itself.

## Adding more fixtures

If you want to add more `.bin` files here:

1. Strip any branding from the watchface name and rendered images
   first.
2. Document the expected block / UI-item distribution in this
   README.
3. Confirm the file round-trips byte-perfect through
   `analyzer.serialize()` before committing.

## Discovery

The test suite auto-discovers every `*.bin` file in this directory,
so dropping a new fixture in is enough — no test code change needed.
