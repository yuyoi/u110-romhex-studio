# U110 HexWizard

The U-110 flavour of the [ESP32 maskrom programmer](https://github.com/yuyoi/esp32-maskrom-programmer).
Same hardware and burn firmware, plus a 128x64 OLED that plays a boot animation and then idles as a small
creature while the programmer is ready. **Working prototype**: the programmer and the OLED animation run on the
author's bench; the three-button ladder below is designed and calculated but not yet tested on real hardware.

![intro preview](art/u110_intro_preview.gif)

The general programmer repo stays plain (status screen only). Everything here is specific to this project.

## What it does

- **Boot:** "U110" types in, "HEX WIZARD" types under it, the picture dissolves in, zooms to her face, and the
  logo block settles beside her head (about 6 s, once).
- **Idle:** she blinks about every 3 seconds and a thin glitch band runs across the lower half now and then.
- **Status screen:** IP address, stored cards with their tone names, free flash, burn progress. It takes over
  during a burn and when a burn finishes or fails, and falls back to the creature after 20 s.
- **Buttons:** short press on the single button, or UP / DOWN / SELECT on the ladder (see below).

> **Warning:** never leave the ESP wired to the chip while it is in a synth. See the warning in the
> [programmer README](https://github.com/yuyoi/esp32-maskrom-programmer#readme).

## Display settings (web page, Display tab)

Join the WiFi network `SST-PROG` (password `u110cards`), open the programmer's page (`http://192.168.4.1/`, or `http://sstprog.local/` once you have added your home WiFi on the Cards tab) and pick the **Display** tab:

- **Glitch band** on or off.
- **Show the IP** at the bottom left of the creature screen (small 4x6 text, it cuts into the picture a little).
- **Idle animation:** *Look around*, *Gasp*, *Look at the rack*, *Random* (picks one every few seconds), or *Off* (blink only). **Play it now** previews the chosen one.
- **Storage:** flash used and total, percent filled, card count and free space. The OLED status screen shows the same in its bottom line, for example `2 cards 10%/9.8M`.

- **Screen tab:** a live mirror of the OLED (about 3 frames a second) with **Up / Down / Select** buttons that work like the real ones, so you can browse the stored cards and switch between the creature and the status screen from a browser. It pauses while a burn runs, because the WiFi radio is off then.

Settings are saved on the device. From a terminal the same thing is `UI gl=0 ip=1 an=2 play=1` over the serial port (921600 baud), and plain `UI` prints the current state.

## Wiring (on top of the programmer's pin map)

| OLED (0.96" SSD1306, I2C) | ESP32-S3 |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | GPIO4 |
| SCL | GPIO5 |

GPIO6 is the button input. Nothing else on the DevKitC-1 (N16R8) is free: the bus uses the rest, GPIO35 to 37
belong to the PSRAM, and 43/44 are the USB-UART lines.

### Buttons

**Single button:** GPIO6 to GND. A press goes from the creature to the status screen, then steps through the stored
cards, then back to the creature.

**Three buttons on one pin (resistor ladder, all E12 values):**

```
3V3 --[6.8k]--+-----------+----> GPIO6 (ADC)
              |           |
           [18k]        [100nF]
              |           |
             GND         GND

node --[1.5k]-- UP ------- GND
node --[4.7k]-- DOWN ----- GND
node --[15k]--  SELECT --- GND
```

| State | Voltage |
|---|---|
| idle | 2.40 V |
| SELECT | 1.80 V |
| DOWN | 1.17 V |
| UP | 0.56 V |

The values come from `oled_anim/ladder_opt.py`, which searches E12 resistors for the widest gaps (0.56 V) and
checks 1 % tolerances (worst case 0.54 V). The firmware detects at boot whether a ladder is fitted (the
serial log prints "GPIO6 reads ... mV" and which mode it chose) and otherwise treats GPIO6 as a plain button.
UP and DOWN step through the stored cards and repeat while held. SELECT switches between the creature and
the status screen.

## Build and flash

Same as the programmer: Arduino CLI with the `esp32:esp32` core and the U8g2 library, through the board's
**UART** USB-C port.

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=app3M_fat9M_16MB" firmware/sst_programmer
arduino-cli upload -p COMx --fqbn "esp32:esp32:esp32s3:FlashSize=16M,PartitionScheme=app3M_fat9M_16MB" firmware/sst_programmer
```

Flashing the app does not touch the stored cards.

The OLED runs on I2C at 1 MHz with the panel oscillator at its maximum, which keeps camera shots of the screen free of tearing. If your display shows garbled pixels, drop `setBusClock` and `Wire.setClock` back to 400000.

## Changing the animation

`oled_anim/anim3.py` turns the drawings in `art/` into the firmware frames (`firmware/sst_programmer/splash.h`,
62 unique 128x64 frames, about 60 KB) and a preview GIF. It needs Python with Pillow and NumPy.

```bash
cd oled_anim
python anim3.py
```

- `art/girl_redraw2.png`: black ink on white, 1280 x 600. `art/girl_closed.png`: the same drawing with the eyes closed, used for the blink.
- Far view uses a sharpened, dithered downscale; the zoom dissolves into a cleaner contrast-stretched one. At 128x64,
  bold single strokes survive and hairlines and dense hatching do not.
- Text uses a hand-made 5x7 pixel font defined in the script.
- The idle animations (look left and right, look at the rack, gasp) are built from the drawing by redrawing the eyes and mouth. To use your own drawings instead, save full frames at 1280 x 600 as `art/girl_look_left.png`, `art/girl_look_right.png`, `art/girl_look_rack.png`, `art/girl_gasp1.png` and `art/girl_gasp2.png`, then run the script; it uses any of those that exist.

## Built one? Tell us

If you build any of it, please [open an issue](https://github.com/yuyoi/u110-romhex-studio/issues) with what you
built, what worked and what didn't, and a photo of the wiring if you can. Reports of failures are as useful as
reports of successes.

Drawings by JunkSmithWizard (JSW). Firmware and scripts written with Claude (Anthropic's AI).
