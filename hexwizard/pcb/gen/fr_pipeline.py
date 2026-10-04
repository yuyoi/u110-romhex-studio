"""Autoroute a generated board with Freerouting (needs KiCad's python for pcbnew).

  KiCad python:  fr_pipeline.py prep  <name> <workdir>   -> adds GND zones + keepout, exports <workdir>/<name>.dsn
  (run java -jar freerouting.jar -de <name>.dsn -do <name>.ses -mp N)
  KiCad python:  fr_pipeline.py post  <name> <workdir>   -> imports .ses, fills zones, saves into ../<name>/<name>.kicad_pcb
"""
import os
import re
import shutil
import sys
import uuid

import pcbnew

mode, name, work = sys.argv[1], sys.argv[2], sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(here, "..", name, name + ".kicad_pcb")
tmp = os.path.join(work, name + ".kicad_pcb")
NS = uuid.UUID("11112222-3333-4444-5555-666677778888")
uid = lambda k: str(uuid.uuid5(NS, k))

BW, BH, R = 53.0, 99.5, 2.5


def poly(pts):
    return "(polygon (pts %s))" % " ".join("(xy %.3f %.3f)" % p for p in pts)


if mode == "prep":
    os.makedirs(work, exist_ok=True)
    text = open(src, encoding="utf8").read()
    gnd = int(re.search(r'\(net (\d+) "GND"\)', text).group(1))
    i0 = 0.55
    cut = [(i0 + R, i0), (BW - i0 - R, i0), (BW - i0, i0 + R), (BW - i0, BH - i0), (i0, BH - i0), (i0, i0 + R)]
    zone = ('(zone (net %d) (net_name "GND") (layers "F.Cu" "B.Cu") (uuid "%s") (hatch edge 0.5) '
            '(connect_pads (clearance 0.2)) (min_thickness 0.2) (filled_areas_thickness no) '
            '(fill yes (thermal_gap 0.3) (thermal_bridge_width 0.3)) %s)' % (gnd, uid("zone"), poly(cut)))
    keep = ('(zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (uuid "%s") (name "antenna keepout") (hatch edge 0.5) '
            '(connect_pads (clearance 0)) (min_thickness 0.25) (keepout (tracks not_allowed) (vias not_allowed) '
            '(pads allowed) (copperpour not_allowed) (footprints allowed)) %s)' % (
                uid("keep"), poly([(3.0, 0.0), (25.5, 0.0), (25.5, 8.2), (3.0, 8.2)])))
    text = text.rstrip()
    assert text.endswith(")")
    text = text[:-1] + zone + "\n" + keep + "\n)\n"
    open(tmp, "w", encoding="utf8").write(text)
    board = pcbnew.LoadBoard(tmp)
    ok = pcbnew.ExportSpecctraDSN(board, os.path.join(work, name + ".dsn"))
    print("DSN export:", ok)
else:
    board = pcbnew.LoadBoard(tmp)
    ok = pcbnew.ImportSpecctraSES(board, os.path.join(work, name + ".ses"))
    print("SES import:", ok)
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(os.path.join(work, name + "_routed.kicad_pcb"), board)
    print("saved routed board, tracks:", len(board.GetTracks()))
