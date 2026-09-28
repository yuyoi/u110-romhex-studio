# Hardware: getting a flash chip into the card slot

![Adapter schematic](adapter_schematic.png)

## U-110 card slot (from the U-110 service notes, connector CN1-4, Roland part 7508096A, 34 pins)

| Slot pin | Signal | Notes |
|---|---|---|
| 1 | +5 V | |
| 2-20 | A0-A18 | straight: pin 2 = A0 ... pin 20 = A18 |
| 21, 33 | n.c. | |
| 22 | CS | one per slot. **Active HIGH**, so it needs an inverter to drive a flash chip's CE# |
| 23 | /OE | shared by all slots, active low |
| 24-31 | D0-D7 | |
| 32 | GND | |
| 34 | SENS | card detect (the U-110 reads it as SENS1-4) |

## Chip: SST39SF040 (512K x 8, 5 V, DIP-32)

| Chip pin | Connect to |
|---|---|
| 12,11,10,9,8,7,6,5 (A0-A7) | slot A0-A7 |
| 27,26,23,25,4,28,29,3 (A8-A15) | slot A8-A15 |
| 2, 30, 1 (A16, A17, A18) | slot A16, A17, A18. **Pin 1 is A18, not VPP** as on 27C040 EPROM boards |
| 13-15, 17-21 (D0-D7) | slot D0-D7 |
| 22 (CE#) | inverted slot CS (e.g. one gate of a 74HCT04 / CD4069) |
| 24 (OE#) | slot /OE (or GND; CE# alone gates the bus) |
| 31 (WE#) | +5 V, so the synth can never write |
| 32 VDD / 16 VSS | +5 V / GND |

Wired this way (chip pin Ak = slot Ak), burn images in **connector order**. The app always outputs connector
order.

## Glitches? Decouple the logic

Symptoms like long samples cutting out, tone names flickering, and short sounds fine but long ones breaking
come from random read errors. In delta-coded audio, one bad byte offsets the rest of the note, so long
sounds show it first. What fixed a real adapter:

- **Tie every unused inverter input to GND.** Leave the unused outputs open. Floating CMOS inputs oscillate
  and inject noise.
- **100 nF ceramic capacitors** across the power pins, right at each chip: inverter 14-7, flash 32-16.
- Optional: use a 74HCT04 instead of a CD4069. It's pin-compatible and about 10x faster.

## Byte orders, briefly

- **connector order**: address bits as on the slot. MAME's `roland_d70_waverom-*.bin` are in this order.
  **Burn this.**
- **card order**: MAME's `sn-u110-xx.bin` dumps. Same as connector order but with A8..A15 reversed
  (A8<->A15, A9<->A14, A10<->A13, A11<->A12). `python src/u110card.py convert in.bin out.bin` fixes them.

Wrong order symptom: the card is detected, but every tone name shows as blocks except one blank slot, and
there's no sound.
