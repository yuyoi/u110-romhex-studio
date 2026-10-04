"""Check schematic nets == PCB pad nets.  usage: python verify.py mk2_min   (or mk2_fancy)"""
import os
import subprocess
import sys

from sexp import *

cli = os.path.join(KICAD, "..", "..", "bin", "kicad-cli.exe")
name = sys.argv[1]
proj = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", name)
netfile = os.path.join(proj, "n.net")
subprocess.run([cli, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", netfile,
                os.path.join(proj, name + ".kicad_sch")], check=True, capture_output=True)
net = parse(open(netfile, encoding="utf8").read())[0]
sch = {}
for n in find(net, "nets")[1:]:
    nm = str(find(n, "name")[1]).lstrip("/")
    for nd in find_all(n, "node"):
        sch[(str(find(nd, "ref")[1]), str(find(nd, "pin")[1]))] = nm
pcb = parse(open(os.path.join(proj, name + ".kicad_pcb"), encoding="utf8").read())[0]
pc = {}
for fp in find_all(pcb, "footprint"):
    ref = None
    for pr in find_all(fp, "property"):
        if str(pr[1]) == "Reference":
            ref = str(pr[2])
    for pad in find_all(fp, "pad"):
        nt = find(pad, "net")
        if nt:
            pc[(ref, str(pad[1]))] = str(nt[-1])
bad = [(k, sch.get(k), pc.get(k)) for k in set(sch) | set(pc)
       if sch.get(k) != pc.get(k) and not str(sch.get(k)).startswith("unconnected")]
print(name, "sch nodes", len(sch), "pcb nodes", len(pc), "real mismatches", len(bad))
for b in sorted(bad)[:30]:
    print(b)
os.remove(netfile)

