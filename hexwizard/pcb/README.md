# Hex Wizard MK2 cards (KiCad 10) — UNTESTED

**None of these boards has been built, fabricated or tested.** The finger order, footprints, power switching and routing are all unverified. Check everything against a real U-110 card before ordering anything.

| Board | What it is | State |
|---|---|---|
| `mk2_min/` | SST39SF040 (TSOP-32) + ESP32-S3-WROOM-1-N16 on a U-110 card edge. 23 parts: ESP GPIOs straight to the SST bus, one 2N7002 inverts the slot's active-high CS, two diodes OR slot/USB 5 V, an N-FET in the ESP ground leg closes automatically when 5 V appears. | Schematic + PCB, autorouted (Freerouting) with GND pour, **6 connections still open** (A12/A16/D1/D5 ESP links, 2x ESP_GND link) and a few starved-thermal warnings |
| `mk2_vero/` | No components. All 34 fingers traced to two labeled rows of 2.54 mm holes at the back of the card (outside the synth) plus a blank perf field. Single sided, 0.4 mm tracks, no vias, made for a hobby mill. | PCB only, DRC clean apart from the expected finger edge-clearance |

Previews are in `img/`. Regenerate with `gen/mk2_min_gen.py` / `gen/mk2_vero_gen.py` (needs KiCad 10 installed for its libraries); regenerating `mk2_min` rebuilds it **unrouted**. `gen/fr_pipeline.py` + a Freerouting jar and Java 25 reproduce the autoroute.

## Known caveats
- **Pin 1 side / finger order is a guess.** Fingers are on the bottom copper, mirrored so pin 1 is on the right when viewed from the top. Card pins 21 and 33 are left open (function unknown); pin 34 SENS is tied to +5 V on the original.
- **`mk2_min` puts 5 V straight on the ESP pins when the card is in the synth**, and the ESP now powers up there too. That can damage the ESP; there is no isolation by design (minimum parts). Needs N16 (IO35-37 are address lines) and native USB.
- Q2 is a 2N7002 (about 2-3 ohm); swap for an AO3400 if the ESP browns out on WiFi bursts.
- The TSOP footprint is the 8 x 14 mm package (`TSOP-I-32_12.4x8mm`); change `SST_FP` for the 8 x 20 mm one.
- The card outline (53 x 99.5 mm) was measured from a clone card, not a Roland spec; the slot height limit is unknown.
- Fine-pitch TSOP and 143 vias make `mk2_min` a fab job, not a mill job.
- The card-edge footprint (`SN-U110_CardEdge.pretty`) is an original drawing from measured contact positions (pitch, width, length); no third-party artwork or routing is included.

GPIO map for `mk2_min`: A0..A18 = 18, 8, 9, 10, 11, 12, 13, 14, 21, 35, 36, 37, 38, 39, 40, 41, 42, 47, 48; D0..D7 = 1, 2, 4, 5, 6, 7, 15, 16; WE# = 17; OLED SDA/SCL = 3/46; BOOT/user button = 0; USB = 19/20. The firmware has not been ported to this pin map.
