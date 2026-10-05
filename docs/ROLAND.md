# Importing Roland S-760 / S-770 sampler CDs

Same dialog as the Akai import: **File > Import sampler CD (Akai / Roland S-7xx)...**. Roland patches become tones.
The format is not publicly documented; everything below was reverse-engineered from about 40 real discs, so treat it as
"works on those discs", not as a spec.

## What it does
- Left list: patch **groups** (the 3-letter tag in front of each name: `GTR`, `BS`, `STR`, `KIK`...). Right list: the patches.
- A **patch** is a key map to **partials**; a partial points at up to 4 samples. Each run of keys sharing a partial becomes one
  zone (first valid sample slot of the partial). Root key, loop points and fine tune come from the sample.
- Samples are 16-bit, **48 kHz**, written out as mono WAVs next to your project (`cd_wavs/<disc>/<volume>/`).
- More than 12 zones in a patch (big multisamples) are split over several tones. **Fit to card** trims the new samples like
  the Akai import does, and drops trailing new tones when the card is full.
- Velocity layers, envelopes, filters and LFOs are not converted (the U-110 card format has no equivalent here).

## Not supported
Roland **S-50 / S-550 / S-330 / W-30** discs (`L-CD1`, `LCD1`), E-mu discs (`LA Composer vol. 3`), and blank images.
Loop mode is guessed (any loop of 32+ samples is used); the sample rate is assumed to be 48 kHz.

## Disc layout (all S-7xx discs share one fixed layout)
Offsets are from the start of the image.

| | |
|---|---|
| `0x0000` | 4 zero bytes, `S770 MR25A`, system version text |
| `0x0100` | volume record: name[16] (`ID0:Guitar&Bass`), u32, then the entry counts u16 x5 for object types 0x40..0x44 |
| directories (32 B/entry) | name[16], type, 0, index u16 (bit 15 set on newer discs), links; samples carry **start u16 / length u16 in 0x2400-byte blocks** at +28/+30. Type 0x40 `0x0A0800` (x128), 0x41 `0x0A1800` (x512), 0x42 `0x0A5800` (x1024), 0x43 `0x0AD800` (x4096), 0x44 `0x0CD800` (x8192) |
| parameters (same slot number) | 0x40 `0x10D800` (0x100 B), 0x41 `0x115800` (0x200 B), **0x42 patch** `0x155800` (0x200 B), **0x43 partial** `0x1D5800` (0x80 B), **0x44 sample** `0x255800` (0x30 B) |
| audio | 16-bit little endian, block 0 at `0x2B1000`, block size `0x2400` (9216 bytes) |

- **Patch** (0x42): `+0x100` is a map of 96 u16 partial numbers (`0xFFFF` = none); entry *i* is MIDI key **i + 21** (A0..G#8).
  Patches without a map point at the partial with the same name.
- **Partial** (0x43): four 16-byte sample slots from `+0x10`; the first u16 of a slot is the sample number (`0xFFFF` = none).
- **Sample** (0x44): u24 little endian at `+21` loop start, `+25` loop end, `+33` last sample index; `+38` fine tune (s8, cents);
  `+42` u16 length in blocks; `+45` root key (MIDI note). Audio is zero padded to the block.
- Names can carry bytes above 0x7F (the 16th byte is sometimes a flag) and the directory and parameter copies of a sample name
  may differ in spacing, so the reader compares them loosely.
