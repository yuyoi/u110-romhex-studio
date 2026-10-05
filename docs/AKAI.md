# Importing Akai sampler CDs

**File > Import sampler CD (Akai / Roland S-7xx)...** reads the raw disc image of an Akai S1000/S1100 sample CD
(`.iso`, `.img`, `.tao`, or Nero `.nrg`; these discs are not ISO 9660) and turns programs into tones.
Roland S-760/S-770 discs open in the same dialog: see ROLAND.md.

## What it does
- Lists volumes and programs. Select any number of programs, press **Add to card**.
- Each **keygroup** (key range + sample) becomes one zone. A tone holds 12 zones, so a bigger program (a drum
  kit with 40 keys) is split into several tones.
- **Velocity layers:** the tool has no velocity layers, so it uses the layer sounding at the chosen velocity (default 100).
- **Stereo pairs** (`-L` / `-R` samples sounding together) are mixed to mono when they line up (same length, rate,
  root and loop). Otherwise the first sample is used and the report says so.
- Root note, transpose/fine tune and the first loop are kept. The sample's own start/end markers are applied.
  Playback mode of the keygroup wins over the sample's loop mode.
- **Fit to card** (the combo box): trims the longest samples (one-shots lose their tail, loops get a shorter
  crossfaded body) until everything fits at the chosen rate, then drops the last new tones if it still does not.
  Tones you already had are never trimmed or dropped.
- WAVs are extracted next to your project (`cd_wavs/<disc name>/<volume>/`), or into
  `Documents\U110 RomHex Studio\cd_wavs` for an unsaved project. They are ordinary 16-bit mono WAVs.
- Programs that point at samples stored in a sibling volume of the same disc (copied programs) are resolved across the whole disc.

## Supported / not supported
| | |
|---|---|
| Akai S1000 / S1100 programs and samples (file types `p` and `s`) | yes, tested on 15 real sample CD images (incl. AMG, Spectrasonics, Best Service) |
| Akai S900 | no |
| Akai S3000 / CD3000 samples (type 0xF3) | read as plain samples, **untested**, loops ignored |
| S3000 programs (type 0xF0), `.akp` | no (no disc to test against) |
| Envelopes, filters, LFOs, velocity crossfades | ignored: the U-110 has no equivalent in this card format |

## Disk layout (what the reader assumes)
Reverse-engineered from real discs, for anyone who wants to extend it.

- The disc is a run of **60 MB partitions** (`0x3C00000` apart; the last one can be shorter).
- Partition: `u16` cluster count at 0 (7680 for a full one), volume list at `0xCA` (100 entries x 16 B: name[12],
  type u16, start-cluster u16), **FAT at `0x70A`** (one u16 per cluster: `0` free, `0x4000` system, `0xC000` end of
  chain, else next cluster). Cluster = 8 KB, cluster 3 holds the first volume directory.
- Directory: 126 entries x 24 B: name[12], pad[4], type u8, size u24, start-cluster u16, tag u16.
  Names use the charset `0-9`, space, `A-Z`, `#+-.` coded `0..40`.
- **S1000 sample** (type `0x73`): 150-byte header, then 16-bit little-endian PCM. Header: byte 2 root note,
  3..14 name, 0x10 loop count, 0x11 first loop, 0x13 loop mode, 0x14 tune (s16 in 1/256 semitone; 48 kHz samples carry about +1.47,
  the compensation for the sampler playing at 44.1 kHz), 0x1A length,
  0x1E start, 0x22 end, loops at 0x26 (12 B each: at u32, fine u16, length u32, time u16), 0x8A sample rate u16.
- **S1000 program** (type `0x70`): 150-byte header (name at 3), then 150-byte keygroups back to back (the pointers
  in the file are RAM addresses, ignore them). Keygroup: byte 3/4 low/high key, 5/6 tune, four 24-byte velocity
  zones from byte 34: sample name[12], low/high velocity, tune (s16, cents), loudness, filter, pan, playback mode. Keygroup tune: byte 5 cents, byte 6 semitones.
