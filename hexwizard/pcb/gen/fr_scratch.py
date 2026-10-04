"""Autoroute an UNROUTED generated board with GND treated as ordinary copper (KiCad python).

  fr_scratch.py prep <unrouted.kicad_pcb> <work>   add only the antenna keep-out, export <work>/s.dsn
  fr_scratch.py post <unrouted.kicad_pcb> <work> <out.kicad_pcb>   import s.ses, add the solid GND pour, refill, save
"""
import os
import re
import sys
import uuid

import pcbnew

mode, src, work = sys.argv[1], sys.argv[2], sys.argv[3]
tmp = os.path.join(work, "s.kicad_pcb")
BW, BH, R = 53.0, 99.5, 2.5
NS = uuid.UUID("33334444-5555-6666-7777-88889999aaaa")
uid = lambda k: str(uuid.uuid5(NS, k))


def poly(pts):
    return "(polygon (pts %s))" % " ".join("(xy %.3f %.3f)" % p for p in pts)


KEEP = ('(zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (uuid "%s") (name "antenna keepout") (hatch edge 0.5) '
        '(connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks not_allowed) (vias not_allowed) '
        '(pads allowed) (copperpour not_allowed) (footprints allowed)) %s)' % (
            uid("keep"), poly([(3.0, 0.0), (25.5, 0.0), (25.5, 7.6), (3.0, 7.6)])))

if mode == "prep":
    os.makedirs(work, exist_ok=True)
    text = open(src, encoding="utf8").read().rstrip()
    open(tmp, "w", encoding="utf8").write(text[:-1] + KEEP + "\n)\n")
    b = pcbnew.LoadBoard(tmp)
    print("DSN:", pcbnew.ExportSpecctraDSN(b, os.path.join(work, "s.dsn")))
else:
    out = sys.argv[4]
    b = pcbnew.LoadBoard(tmp)
    print("SES:", pcbnew.ImportSpecctraSES(b, os.path.join(work, "s.ses")))
    pcbnew.SaveBoard(out, b)
    text = open(out, encoding="utf8").read()
    gnd = int(re.search(r'\(net (\d+) "GND"\)', text).group(1))
    i0 = 0.55
    cut = [(i0 + R, i0), (BW - i0 - R, i0), (BW - i0, i0 + R), (BW - i0, BH - i0), (i0, BH - i0), (i0, i0 + R)]
    zone = ('(zone (net %d) (net_name "GND") (layers "F.Cu" "B.Cu") (uuid "%s") (hatch edge 0.5) '
            '(connect_pads yes (clearance 0.2)) (min_thickness 0.2) (filled_areas_thickness no) '
            '(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3)) %s)' % (gnd, uid("z"), poly(cut)))
    open(out, "w", encoding="utf8").write(text.rstrip()[:-1] + zone + "\n)\n")
    b = pcbnew.LoadBoard(out)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(out, b)
    print("saved", out)
