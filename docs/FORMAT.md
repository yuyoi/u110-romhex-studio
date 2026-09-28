# SN-U110 card format

Reverse-engineered in 2026 from the MAME SN-U110 card set and verified on a real U-110.
The PCM-side layout is the same one MAME documents for the CM-32P internal ROM (`roland_cm32p.cpp`).

## Address and data scrambling

A card is 512 KB (19 address lines). The PCM chip (MB87419/MB87420) sees a *proper* address space. The chip
pins see a scrambled one.

**Connector order** (slot pins), with proper = bitswap<19>(raw, ...) msb-first as in MAME's UNSCRAMBLE_ADDR:
```
18,17,15,14,16,12,11,7,9,13,10,8,3,2,1,6,4,5,0
```
**Card order** (MAME `sn-u110-xx.bin`) is the same with raw A8..A15 reversed.

**Data**, both orders: proper = bitswap<8>(raw, 1,2,7,3,5,0,4,6).

## Raw header (CPU side, plain ASCII, raw 0x00-0x7F, rest 0xFF)

| raw | content |
|---|---|
| 00-0F | `RolandU-110 N` `B1` `S` `AC`: fixed magic, compared by the firmware |
| 10-1F | card name, 16 chars (e.g. `SN-U110-13 1.00 `) |
| 20 | card number |

## Proper layout

| proper | content |
|---|---|
| 0x0080 | ID block, 16 bytes: card no, 3 spaces, 8-char internal name, 4-char version |
| 0x0100 | sample table, 10 bytes/entry, up to 384 entries, ends with an all-FF entry |
| 0x1000 | tone list, 128 slots x 0x50 bytes (0x1000-0x37FF) |
| 0x4000 | 00, first sample at 0x4001 |
| 0x40000 | bank boundary: 00 00 00 00, samples resume at 0x40004. **A sample never crosses 0x40000** (the chip's address counter is 18 bits; bit 18 comes from the bank register) |

### Sample entry (10 bytes)

| off | meaning |
|---|---|
| 0-1 | start bits 0-15, little-endian |
| 2 | bits 0-2 = start bits 16-18, bit 3 = card (1), bits 4-5 = bank (0), bits 6-7 = loop mode: 0 forward, 1 one-shot, 2 ping-pong |
| 3-4 | length - 1 |
| 5-6 | loop length (loop start = length - loop length; loops always run to the end). One-shots use 4 |
| 7 | usually 0x40 (fine tune?) |
| 8 | root note: the key that plays the data at 32000 Hz |
| 9 | usually 0x40 (level?) |

Every Roland card ends the table with an 8-byte silent one-shot sample. Empty tone slots point to it.

### Tone entry (0x50 bytes)

| off | meaning |
|---|---|
| 00 | name, 10 chars (LCD font: space, A-Z, a-z, 0-9, `-/+*.,:`) |
| 0A | type: 00 single, 01 dual, 02 detune, 03 velocity mix, 04 velocity switch, 80+ rhythm |
| 0B-0F | usually `00 40 00 00 00` |
| 10 | up to 11 split notes (upper key of each zone), FF-padded |
| 1B | up to 12 sample numbers (one more than the splits), FF-padded |
| 27 | 9 bytes, meaning unknown (copied from Roland: `7f 7f 7f 7f 7f 7f 00 5c 80`) |
| 30 / 3B / 47 | second layer, same layout, for types 01/03/04 |

## Sample coding

Each byte is a signed delta. With m = |byte|, sh = m >> 4 and mt = m & 15:
delta = sh ? (16+mt) << (sh-1) : mt, with the sign applied. The deltas accumulate into 12 bits, clamped at
+-0x7FF. Playback rate = 32000 * 2^((key - root)/12).

Rules every Roland sample follows, and this tool enforces:
- 3 leading 00 bytes.
- Peaks around 1500-1950.
- **The deltas inside a forward loop sum to exactly 0.** Otherwise every loop pass shifts the DC level
  until the voice sticks at the rail, which comes out as silence plus clicks.

## Open questions

Bytes 7 and 9 of sample entries, the 9-byte block at tone offset 0x27, the rhythm tone format (type 80+),
and whether the U-110 accepts card numbers above 15.
