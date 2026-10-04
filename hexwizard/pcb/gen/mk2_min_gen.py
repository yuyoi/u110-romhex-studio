"""Generate the Hex Wizard MK2 card KiCad project (schematic + placed PCB).

Run:  python mk2_gen.py            -> writes ../mk2_card/*
Everything electrical lives in the PARTS table below; placement in PLACE.
Own footprint for the card edge: ../SN-U110_CardEdge.pretty (geometry only).
"""
import json
import os
import uuid

from sexp import *

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "mk2_min")
PROJ = "mk2_min"
NS = uuid.UUID("12345678-1234-5678-1234-567812345678")

SST_FP = "Package_SO:TSOP-I-32_12.4x8mm_P0.5mm"  # 8x14 mm TSOP; 8x20 mm parts use ..._18.4x8mm
BOARD_W, BOARD_H = 53.0, 99.5  # card outline measured from the clone card (mm)
CORNER_R = 2.5  # rounded back corners
FINGER_MIRROR = True  # fingers on B.Cu, pin 1 on the right when viewed from the top


def uid(*key):
    return str(uuid.uuid5(NS, "/".join(key)))


# ---------------------------------------------------------------- parts (MINIMUM version)
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT235 = "Package_TO_SOT_SMD:SOT-23-5"

PARTS = []


def part(ref, lib, sym, value, fp, nets, rename=None, renumber=None):
    PARTS.append(dict(ref=ref, lib=lib, sym=sym, value=value, fp=fp, nets=nets,
                      renumber=renumber))


def res(ref, val, a, b):
    part(ref, "Device", "R", val, R0603, {"1": a, "2": b})


def cap(ref, val, a, b, fp=C0603):
    part(ref, "Device", "C", val, fp, {"1": a, "2": b})


def dio(ref, val, anode, cathode):
    part(ref, "Device", "D_Schottky", val, "Diode_SMD:D_SOD-123", {"1": cathode, "2": anode})


def dip_to_tsop(n):
    return str((int(n) + 8 - 1) % 32 + 1)


NOTE = ("HEX WIZARD MK2 MINIMUM card: SST39SF040 (TSOP-32) + ESP32-S3-WROOM-1-N16. "
        "ESP GPIOs go straight to the SST bus (no series resistors; the ESP is powered in the synth too, so 5 V bus lines reach its pins). "
        "Slot CS is active HIGH: one 2N7002 inverts it into CE#. CS, /OE and WE# have pull-ups so a card that is out of the synth "
        "has CE# low, OE# high and WE# high. Q2 (N-FET in the ESP ground leg, gate on the 5 V rail) switches the ESP on by itself when the card is inserted or USB is plugged. "
        "Needs N16 (no octal PSRAM) because IO35-37 are used as address lines.")

# card edge: finger -> net
EDGE = {1: "SLOT_5V", 22: "CS", 23: "SLOT_OE_N", 32: "GND", 34: "SLOT_5V"}
for i in range(19):
    EDGE[2 + i] = "A%d" % i
for i in range(8):
    EDGE[24 + i] = "D%d" % i
part("J1", "Connector_Generic", "Conn_01x34", "SN-U110 card edge",
     "SN-U110_CardEdge:SN-U110_CardEdge", {str(k): v for k, v in EDGE.items()})

sst = {"VCC": "V5", "GND": "GND", "CE": "SST_CE_N", "OE": "SLOT_OE_N", "PGM": "SST_WE_N"}
for i in range(19):
    sst["A%d" % i] = "A%d" % i
for i in range(8):
    sst["D%d" % i] = "D%d" % i
part("U1", "Memory_Flash", "SST39SF040", "SST39SF040-70-4C-TU", SST_FP, sst, renumber=dip_to_tsop)
cap("C1", "100n", "V5", "GND")

# ESP GPIO for each bus line (N16: IO35-37 free; avoid straps 0/3/45/46 for the bus)
GPIO = {}
a_pins = [18, 8, 9, 10, 11, 12, 13, 14, 21, 35, 36, 37, 38, 39, 40, 41, 42, 47, 48]
d_pins = [1, 2, 4, 5, 6, 7, 15, 16]
for i, g in enumerate(a_pins):
    GPIO["A%d" % i] = g
for i, g in enumerate(d_pins):
    GPIO["D%d" % i] = g
GPIO["WE"] = 17

busnet = lambda n: "SST_WE_N" if n == "WE" else n
ebus = busnet  # ESP GPIO wired straight to the bus

# CS inverter (slot CS is active HIGH, SST CE# active LOW) + pull-ups for the "card out of synth" state
part("Q1", "Transistor_FET", "2N7002", "2N7002", "Package_TO_SOT_SMD:SOT-23",
     {"1": "CS", "2": "GND", "3": "SST_CE_N"})
res("R2", "10k", "SST_CE_N", "V5")
res("R3", "100k", "CS", "V5")
res("R4", "100k", "SLOT_OE_N", "V5")
res("R5", "100k", "SST_WE_N", "V5")

# power: 5 V rail from slot or USB, ESP only from USB (JP1 = also from slot)
dio("D1", "SS14W", "SLOT_5V", "V5")
dio("D2", "SS14W", "VBUS", "V5")
part("U3", "Regulator_Linear", "AP2112K-3.3", "AP2112K-3.3", SOT235,
     {"1": "V5", "2": "ESP_GND", "3": "V5", "5": "3V3"})
cap("C2", "10u", "V5", "ESP_GND", C0805)
cap("C3", "10u", "3V3", "ESP_GND", C0805)

part("Q2", "Transistor_FET", "2N7002", "2N7002 (AO3400 if it droops)", "Package_TO_SOT_SMD:SOT-23",
     {"1": "V5", "2": "GND", "3": "ESP_GND"})

# USB-C
part("J4", "Connector", "USB_C_Receptacle_USB2.0_16P", "USB-C",
     "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
     {"GND": "GND", "VBUS": "VBUS", "CC1": "CC1", "CC2": "CC2", "D+": "USB_DP",
      "D-": "USB_DM", "SHIELD": "GND"})
res("R6", "5k1", "CC1", "GND")
res("R7", "5k1", "CC2", "GND")

# ESP
esp = {"GND": "ESP_GND", "3V3": "3V3", "EN": "EN", "IO0": "BOOT", "USB_D+": "USB_DP", "USB_D-": "USB_DM",
       "IO3": "SDA", "IO46": "SCL"}
for n, g in GPIO.items():
    esp["IO%d" % g] = ebus(n)
part("U2", "RF_Module", "ESP32-S3-WROOM-1", "ESP32-S3-WROOM-1-N16", "RF_Module:ESP32-S3-WROOM-1", esp)
cap("C4", "100n", "3V3", "ESP_GND")
res("R1", "10k", "EN", "3V3")
cap("C5", "1u", "EN", "ESP_GND")
part("SW1", "Switch", "SW_Push", "BOOT / USER", "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2",
     {"1": "BOOT", "2": "ESP_GND"})
part("J2", "Connector_Generic", "Conn_01x04", "OLED I2C",
     "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical",
     {"1": "ESP_GND", "2": "3V3", "3": "SCL", "4": "SDA"})

# ---------------------------------------------------------------- placement
FY = BOARD_H
PLACE = {
    "U1": (26.5, 74.0, 180), "C1": (26.5, 67.8, 0),
    "U2": (14.0, 13.5, 0), "C4": (26.0, 36.0, 0),
    "R1": (6.0, 33.0, 0), "C5": (9.0, 33.0, 0),
    "SW1": (6.0, 40.0, 0),
    "J4": (45.0, 3.4, 180), "R6": (40.0, 11.5, 0), "R7": (50.0, 11.5, 0),
    "U3": (45.0, 24.0, 0), "C2": (38.5, 24.0, 0), "C3": (49.5, 29.0, 0), "Q2": (44.5, 31.0, 0),
    "D1": (31.0, 34.0, 0), "D2": (38.0, 34.0, 0),
    "J2": (50.0, 40.0, 0),
    "Q1": (6.0, 70.0, 0), "R2": (6.0, 74.5, 0), "R3": (5.0, 79.0, 0), "R4": (12.0, 79.0, 0),
    "R5": (46.0, 74.0, 0),
}


# ---------------------------------------------------------------- schematic
def build_lib_symbols():
    libs = {}
    for p in PARTS:
        key = (p["lib"], p["sym"], bool(p["renumber"]))
        if key in libs:
            continue
        s = load_symbol(p["lib"], p["sym"])
        s = parse(dump(s))[0]  # deep copy
        name = p["sym"] + ("_TSOP32" if p["renumber"] else "")
        old = p["sym"]
        libid = p["lib"] + ":" + name

        def ren(n):
            for i, x in enumerate(n):
                if isinstance(x, list) and x:
                    if x[0] == "symbol" and i > 0:
                        x[1] = Q(str(x[1]).replace(old, name, 1))
                    if x[0] == "number" and p["renumber"]:
                        x[1] = Q(p["renumber"](str(x[1])))
                    if isinstance(x, list):
                        ren(x)
        ren(s[2:] if False else s)
        s[1] = Q(libid)
        libs[key] = (libid, s)
    return libs


def pin_net_map(p, pins):
    """number -> net for one part, using pin number or pin name keys."""
    out = {}
    for num, name, *_ in pins:
        net = p["nets"].get(num, p["nets"].get(name))
        out[num] = net
    return out


def esc(s):
    return s.replace('"', '\\"')


def sch_text():
    libs = build_lib_symbols()
    root = uid("root")
    lib_nodes = [dump(v[1]) for v in libs.values()]
    inst, labels, ncs = [], [], []
    # shelf packing
    x, y, rowh = 40.0, 40.0, 0.0
    maxw = 760.0
    for p in PARTS:
        key = (p["lib"], p["sym"], bool(p["renumber"]))
        libid, s = libs[key]
        pins = symbol_pins(s)
        # after rename numbers are already TSOP for U1
        xs = [q[2] for q in pins]
        ys = [q[3] for q in pins]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        w = (maxx - minx) + 70.0
        h = (maxy - miny) + 16.0
        if x + w > maxw:
            x = 40.0
            y += rowh + 10.0
            rowh = 0.0
        ox = x + 35.0 - minx
        oy = y + 8.0 + maxy
        ox = round(ox / 2.54) * 2.54
        oy = round(oy / 2.54) * 2.54
        x += w
        rowh = max(rowh, h)
        nets = pin_net_map(p, pins)
        refy = oy - maxy - 4.0
        valy = oy - miny + 4.0
        props = (
            '(property "Reference" "%s" (at %.2f %.2f 0) (effects (font (size 1.27 1.27))))'
            '(property "Value" "%s" (at %.2f %.2f 0) (effects (font (size 1.27 1.27))))'
            '(property "Footprint" "%s" (at %.2f %.2f 0) (effects (font (size 1.27 1.27)) (hide yes)))'
            '(property "Datasheet" "" (at %.2f %.2f 0) (effects (font (size 1.27 1.27)) (hide yes)))'
        ) % (p["ref"], ox, refy, esc(p["value"]), ox, valy, p["fp"], ox, oy, ox, oy)
        pinu = "".join('(pin "%s" (uuid "%s"))' % (q[0], uid(p["ref"], "pin", q[0])) for q in pins)
        inst.append(
            '(symbol (lib_id "%s") (at %.2f %.2f 0) (unit 1) (exclude_from_sim no) (in_bom yes) '
            '(on_board yes) (dnp no) (uuid "%s") %s %s '
            '(instances (project "%s" (path "/%s" (reference "%s") (unit 1)))))'
            % (libid, ox, oy, uid(p["ref"]), props, pinu, PROJ, root, p["ref"]))
        seen = set()
        for num, name, px, py, ang, ln in pins:
            ax, ay = round(ox + px, 2), round(oy - py, 2)
            if (ax, ay) in seen:
                continue
            seen.add((ax, ay))
            net = nets.get(num)
            if net:
                rot, just = {0: (180, "right"), 180: (0, "left"), 90: (270, "right"),
                             270: (90, "left")}[int(ang) % 360]
                labels.append('(label "%s" (at %.2f %.2f %d) (effects (font (size 1.27 1.27)) '
                              '(justify %s bottom)) (uuid "%s"))'
                              % (net, ax, ay, rot, just, uid(p["ref"], "lbl", num)))
            elif not p["ref"].startswith(("R", "C", "D", "SW", "JP")) and p["ref"] not in ("J2",):
                ncs.append('(no_connect (at %.2f %.2f) (uuid "%s"))' % (ax, ay, uid(p["ref"], "nc", num)))
    note = NOTE
    head = ('(kicad_sch (version 20250114) (generator "eeschema") (generator_version "9.0") '
            '(uuid "%s") (paper "A1") (lib_symbols %s)' % (root, "".join(lib_nodes)))
    text = '(text "%s" (at 40 20 0) (effects (font (size 2 2)) (justify left)) (uuid "%s"))' % (
        esc(note), uid("note"))
    tail = '(sheet_instances (path "/" (page "1"))) (embedded_fonts no))'
    return head + "".join(inst) + "".join(labels) + "".join(ncs) + text + tail


# ---------------------------------------------------------------- PCB
def net_ids():
    names = set()
    for p in PARTS:
        for v in p["nets"].values():
            if v:
                names.add(v)
    ordered = sorted(names)
    return {n: i + 1 for i, n in enumerate(ordered)}


def lib_pad_nets(p):
    """pad number -> net for PCB (pin numbers identical to pad numbers)."""
    s = load_symbol(p["lib"], p["sym"])
    pins = symbol_pins(parse(dump(s))[0])
    if p["renumber"]:
        pins = [(p["renumber"](q[0]),) + q[1:] for q in pins]
    return pin_net_map(p, pins)


def edge_footprint(ids):
    pads = []
    n = 34
    for i in range(1, n + 1):
        x = (BOARD_W / 2 + 24.75 - (i - 1) * 1.5) if FINGER_MIRROR else (BOARD_W / 2 - 24.75 + (i - 1) * 1.5)
        length = 5.5 if i == 32 else 4.5
        cy = FY - (2.8 if i == 32 else 3.3)
        net = EDGE.get(i)
        netsx = '(net %d "%s")' % (ids[net], net) if net else ""
        pads.append('(pad "%d" smd rect (at %.3f %.3f) (size 1 %.1f) (layers "B.Cu" "B.Mask") '
                    '(solder_mask_margin 0.1) %s (uuid "%s"))' % (i, x, cy, length, netsx, uid("finger", str(i))))
    return ('(footprint "SN-U110_CardEdge:SN-U110_CardEdge" (layer "B.Cu") (uuid "%s") (at 0 0) '
            '(descr "card edge fingers on bottom, own geometry") (attr smd) '
            '(property "Reference" "J1" (at %.2f %.2f 0) (layer "B.SilkS") (uuid "%s") (effects (font (size 1 1) (thickness 0.15)) (justify mirror))) '
            '(property "Value" "SN-U110 card edge" (at %.2f %.2f 0) (layer "B.Fab") (uuid "%s") (hide yes) (effects (font (size 1 1) (thickness 0.15)) (justify mirror))) '
            '(path "/%s") %s)' % (uid("J1fp"), BOARD_W / 2, FY - 9, uid("J1ref"), BOARD_W / 2, FY - 9,
                                  uid("J1val"), uid("J1"), "".join(pads)))


def footprint_node(p, x, y, rot, ids):
    lib, name = p["fp"].split(":")
    path = os.path.join(KICAD, "footprints", lib + ".pretty", name + ".kicad_mod")
    node = parse(open(path, encoding="utf8").read())[0]
    out = [node[0], Q(p["fp"])]
    padnets = lib_pad_nets(p)
    pad_i = 0
    for el in node[2:]:
        if isinstance(el, list) and el:
            h = el[0]
            if h in ("version", "generator", "generator_version"):
                continue
            if h == "layer":
                out.append(el)
                out.append(["uuid", Q(uid(p["ref"], "fp"))])
                out.append(["at", "%.3f" % x, "%.3f" % y, "%d" % rot] if rot else ["at", "%.3f" % x, "%.3f" % y])
                continue
            if h == "property":
                nm = str(el[1])
                el = list(el)
                if nm == "Reference":
                    el[2] = Q(p["ref"])
                elif nm == "Value":
                    el[2] = Q(p["value"])
                if find(el, "uuid") is None:
                    el.append(["uuid", Q(uid(p["ref"], "prop", nm))])
                out.append(el)
                continue
            if h == "pad":
                pad_i += 1
                el = list(el)
                num = str(el[1])
                net = padnets.get(num)
                if net:
                    el.append(["net", str(ids[net]), Q(net)])
                if find(el, "uuid") is None:
                    el.append(["uuid", Q(uid(p["ref"], "pad", str(pad_i)))])
                out.append(el)
                continue
        out.append(el)
    out.append(["path", Q("/" + uid(p["ref"]))])
    return dump(out)


def edge_cuts():
    w, h, r = BOARD_W, BOARD_H, CORNER_R
    ec = []
    k = [0]

    def line(a, b, c, d):
        k[0] += 1
        ec.append('(gr_line (start %.3f %.3f) (end %.3f %.3f) (stroke (width 0.1) (type default)) '
                  '(layer "Edge.Cuts") (uuid "%s"))' % (a, b, c, d, uid("ec", str(k[0]))))

    def arc(sx, sy, mx, my, ex, ey):
        k[0] += 1
        ec.append('(gr_arc (start %.3f %.3f) (mid %.3f %.3f) (end %.3f %.3f) (stroke (width 0.1) (type default)) '
                  '(layer "Edge.Cuts") (uuid "%s"))' % (sx, sy, mx, my, ex, ey, uid("ec", str(k[0]))))

    import math
    c = r * (1 - math.sqrt(0.5))
    line(r, 0, w - r, 0)
    arc(w - r, 0, w - c, c, w, r)
    line(w, r, w, h)
    line(w, h, 0, h)
    line(0, h, 0, r)
    arc(0, r, c, c, r, 0)
    return "".join(ec)


def pcb_text():
    ids = net_ids()
    layers = ('(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (9 "F.Adhes" user "F.Adhesive") '
              '(11 "B.Adhes" user "B.Adhesive") (13 "F.Paste" user) (15 "B.Paste" user) '
              '(5 "F.SilkS" user "F.Silkscreen") (7 "B.SilkS" user "B.Silkscreen") (1 "F.Mask" user) '
              '(3 "B.Mask" user) (17 "Dwgs.User" user "User.Drawings") (19 "Cmts.User" user "User.Comments") '
              '(21 "Eco1.User" user "User.Eco1") (23 "Eco2.User" user "User.Eco2") (25 "Edge.Cuts" user) '
              '(27 "Margin" user) (31 "F.CrtYd" user "F.Courtyard") (29 "B.CrtYd" user "B.Courtyard") '
              '(35 "F.Fab" user) (33 "B.Fab" user))')
    out = ['(kicad_pcb (version 20260206) (generator "pcbnew") (generator_version "10.0") '
           '(general (thickness 1.6) (legacy_teardrops no)) (paper "A4") %s '
           '(setup (pad_to_mask_clearance 0))' % layers, '(net 0 "")']
    for n, i in sorted(ids.items(), key=lambda t: t[1]):
        out.append('(net %d "%s")' % (i, n))
    out.append(edge_footprint(ids))
    for p in PARTS:
        if p["ref"] == "J1":
            continue
        x, y, rot = PLACE[p["ref"]]
        out.append(footprint_node(p, x, y, rot, ids))
    out.append(edge_cuts())
    out.append(")")
    return "\n".join(out)


def main():
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, PROJ + ".kicad_sch"), "w", encoding="utf8").write(sch_text())
    open(os.path.join(OUT, PROJ + ".kicad_pcb"), "w", encoding="utf8").write(pcb_text())
    pro = {"meta": {"filename": PROJ + ".kicad_pro", "version": 3},
           "board": {"design_settings": {"rules": {"min_clearance": 0.15, "min_track_width": 0.15,
                                                     "min_through_hole_diameter": 0.2}}},
           "net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.2,
                                          "via_diameter": 0.6, "via_drill": 0.3}], "meta": {"version": 3}}}
    json.dump(pro, open(os.path.join(OUT, PROJ + ".kicad_pro"), "w"), indent=2)
    open(os.path.join(OUT, "fp-lib-table"), "w").write(
        '(fp_lib_table (version 7) (lib (name "SN-U110_CardEdge") (type "KiCad") '
        '(uri "${KIPRJMOD}/../SN-U110_CardEdge.pretty") (options "") (descr "own card edge")))\n')
    print("parts:", len(PARTS), "nets:", len(net_ids()))


if __name__ == "__main__":
    main()


