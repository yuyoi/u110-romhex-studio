"""Component-free U-110 card that breaks all 34 fingers out to labelled 2.54 mm holes + a blank perf field.

Single sided (all copper on B.Cu with the fingers), no vias, 0.4 mm tracks, holes are unplated
(solder on the bottom).  Run:  python mk2_vero_gen.py   ->  ../mk2_vero/mk2_vero.kicad_pcb
"""
import json
import math
import os
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "mk2_vero")
PROJ = "mk2_vero"
NS = uuid.UUID("aaaa1111-2222-3333-4444-555566667777")
uid = lambda *k: str(uuid.uuid5(NS, "/".join(k)))

BW, BH, CR = 53.0, 99.5, 2.5
TRACK = 0.4
PAD, DRILL = 1.7, 1.0
PERF_ROWS = 11              # rows of blank pads behind the breakout rows (back of the card)
ROW1_Y = 40.0               # breakout row nearest the fingers (even slots); all holes sit at the BACK of the card (outside the synth)
ROW2_Y = ROW1_Y - 2.54      # second row, shifted half a pitch (odd slots)
BAND_Y = 47.0               # where the 45 degree fan-out starts (tracks run straight up from the fingers to here)

# ---- signal per finger (pin number 1..34)
SIG = {1: "+5V", 21: "P21", 22: "CS", 23: "/OE", 32: "GND", 33: "P33", 34: "SENS"}
for i in range(19):
    SIG[2 + i] = "A%d" % i
for i in range(8):
    SIG[24 + i] = "D%d" % i
netnames = [SIG[i] for i in range(1, 35)]
nid = {n: i + 1 for i, n in enumerate(sorted(set(netnames)))}

CX = BW / 2
fx = lambda pin: CX + 24.75 - (pin - 1) * 1.5          # finger centre x (pin 1 on the right, fingers on the bottom)
FIN_Y = BH - 3.3
FIN_TOP = BH - 5.55                                     # top end of a finger (4.5 long)
slots = sorted(range(1, 35), key=fx)                    # pins left to right
px = lambda k: CX + (k - 16.5) * 1.27                   # breakout pad x for slot k

items = []   # footprints / segments / texts
fin_pads, br_pads, perf_pads, segs, texts = [], [], [], [], []

for pin in range(1, 35):
    length = 5.5 if pin == 32 else 4.5
    cy = BH - (2.8 if pin == 32 else 3.3)
    fin_pads.append('(pad "%d" smd rect (at %.3f %.3f) (size 1 %.1f) (layers "B.Cu" "B.Mask") '
                    '(solder_mask_margin 0.1) (net %d "%s") (uuid "%s"))' % (
                        pin, fx(pin), cy, length, nid[SIG[pin]], SIG[pin], uid("f", str(pin))))

n_seg = 0


def seg(x1, y1, x2, y2, net):
    global n_seg
    if abs(x1 - x2) < 1e-6 and abs(y1 - y2) < 1e-6:
        return
    n_seg += 1
    segs.append('(segment (start %.3f %.3f) (end %.3f %.3f) (width %.2f) (layer "B.Cu") (net %d) (uuid "%s"))' % (
        x1, y1, x2, y2, TRACK, nid[net], uid("s", str(n_seg))))


for k, pin in enumerate(slots):
    name = SIG[pin]
    x_f, x_p = fx(pin), px(k)
    y_pad = ROW1_Y if k % 2 == 0 else ROW2_Y
    d = x_p - x_f
    top = FIN_TOP + 0.2
    br_pads.append('(pad "%d" thru_hole circle (at %.3f %.3f) (size %.1f %.1f) (drill %.1f) '
                   '(layers "B.Cu" "B.Mask") (remove_unused_layers no) (net %d "%s") (uuid "%s"))' % (
                       pin, x_p, y_pad, PAD, PAD, DRILL, nid[name], name, uid("b", str(pin))))
    # finger tip -> straight up -> 45 degree jog -> straight up to the pad
    seg(x_f, top, x_f, BAND_Y, name)
    y_end = BAND_Y - abs(d)
    seg(x_f, BAND_Y, x_p, y_end, name)
    seg(x_p, y_end, x_p, y_pad, name)
    ty = y_pad + 2.9 if k % 2 == 0 else y_pad - 2.9
    texts.append('(gr_text "%s" (at %.3f %.3f 90) (layer "F.SilkS") (uuid "%s") '
                 '(effects (font (size 1 1) (thickness 0.15))))' % (name, x_p, ty, uid("t", str(pin))))

# blank perf field on the 2.54 mm grid of the even slots
pcol = [px(0) + j * 2.54 for j in range(17)]
y0 = ROW2_Y - 3.2 - 2.54 * 0
n = 0
for r in range(PERF_ROWS):
    for x in pcol:
        n += 1
        perf_pads.append('(pad "%d" thru_hole circle (at %.3f %.3f) (size %.1f %.1f) (drill %.1f) '
                         '(layers "B.Cu" "B.Mask") (remove_unused_layers no) (uuid "%s"))' % (
                             n, x, ROW2_Y - 6.5 - 2.54 * r, PAD, PAD, DRILL, uid("p", str(n))))


def fp(ref, value, lib, pads_txt):
    return ('(footprint "%s" (layer "B.Cu") (uuid "%s") (at 0 0) (attr through_hole) '
            '(property "Reference" "%s" (at 0 -2 0) (layer "B.SilkS") (uuid "%s") (hide yes) '
            '(effects (font (size 1 1) (thickness 0.15)) (justify mirror))) '
            '(property "Value" "%s" (at 0 2 0) (layer "B.Fab") (uuid "%s") (hide yes) '
            '(effects (font (size 1 1) (thickness 0.15)) (justify mirror))) %s)' % (
                lib, uid(ref), ref, uid(ref, "r"), value, uid(ref, "v"), "".join(pads_txt)))


def edge_cuts():
    w, h, r = BW, BH, CR
    c = r * (1 - math.sqrt(0.5))
    e = []
    k = [0]

    def line(a, b, c_, d):
        k[0] += 1
        e.append('(gr_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width 0.1) (type default)) '
                 '(layer "Edge.Cuts") (uuid "%s"))' % (a, b, c_, d, uid("ec", str(k[0]))))

    def arc(sx, sy, mx, my, ex, ey):
        k[0] += 1
        e.append('(gr_arc (start %.3f %.3f) (mid %.3f %.3f) (end %.3f %.3f) (stroke (width 0.1) (type default)) '
                 '(layer "Edge.Cuts") (uuid "%s"))' % (sx, sy, mx, my, ex, ey, uid("ec", str(k[0]))))
    line(r, 0, w - r, 0)
    arc(w - r, 0, w - c, c, w, r)
    line(w, r, w, h)
    line(w, h, 0, h)
    line(0, h, 0, r)
    arc(0, r, c, c, r, 0)
    return "".join(e)


layers = ('(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (9 "F.Adhes" user "F.Adhesive") (11 "B.Adhes" user "B.Adhesive") '
          '(13 "F.Paste" user) (15 "B.Paste" user) (5 "F.SilkS" user "F.Silkscreen") (7 "B.SilkS" user "B.Silkscreen") '
          '(1 "F.Mask" user) (3 "B.Mask" user) (17 "Dwgs.User" user "User.Drawings") (19 "Cmts.User" user "User.Comments") '
          '(21 "Eco1.User" user "User.Eco1") (23 "Eco2.User" user "User.Eco2") (25 "Edge.Cuts" user) (27 "Margin" user) '
          '(31 "F.CrtYd" user "F.Courtyard") (29 "B.CrtYd" user "B.Courtyard") (35 "F.Fab" user) (33 "B.Fab" user))')
head = ('(kicad_pcb (version 20260206) (generator "pcbnew") (generator_version "10.0") '
        '(general (thickness 1.6) (legacy_teardrops no)) (paper "A4") %s (setup (pad_to_mask_clearance 0))' % layers)
body = [head, '(net 0 "")'] + ['(net %d "%s")' % (i, n) for n, i in sorted(nid.items(), key=lambda t: t[1])]
body.append(fp("J1", "SN-U110 card edge", "SN-U110_CardEdge:SN-U110_CardEdge", fin_pads))
body.append(fp("J2", "breakout", "VeroBreakout:Breakout_2x17", br_pads))
body.append(fp("J3", "perf field", "VeroBreakout:PerfField", perf_pads))
body += segs + texts
body.append('(gr_text "VERO CARD (parts on this side, solder on finger side)" (at %.2f 2.8 0) (layer "F.SilkS") (uuid "%s") '
            '(effects (font (size 1.2 1.2) (thickness 0.18))))' % (CX, uid("title")))
body.append(edge_cuts())
body.append(")")

os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, PROJ + ".kicad_pcb"), "w", encoding="utf8").write("\n".join(body))
pro = {"meta": {"filename": PROJ + ".kicad_pro", "version": 3},
       "board": {"design_settings": {"rules": {"min_clearance": 0.2, "min_track_width": 0.3,
                                                 "min_through_hole_diameter": 0.8}}},
       "net_settings": {"classes": [{"name": "Default", "clearance": 0.2, "track_width": TRACK,
                                      "via_diameter": 0.8, "via_drill": 0.4}], "meta": {"version": 3}}}
json.dump(pro, open(os.path.join(OUT, PROJ + ".kicad_pro"), "w"), indent=2)
print("pads: breakout %d, perf %d, segments %d" % (len(br_pads), len(perf_pads), n_seg))


