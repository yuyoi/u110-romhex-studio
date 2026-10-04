"""Tiny KiCad s-expression reader/writer + library lookup helpers."""
import os
import re

KICAD = os.path.join(os.environ["LOCALAPPDATA"], "Programs", "KiCad", "10.0", "share", "kicad")


def parse(text):
    """Return nested lists; atoms are str, quoted strings are wrapped as Q(str)."""
    pos = 0
    n = len(text)
    stack = [[]]
    while pos < n:
        c = text[pos]
        if c in " \t\r\n":
            pos += 1
        elif c == "(":
            stack.append([])
            pos += 1
        elif c == ")":
            top = stack.pop()
            stack[-1].append(top)
            pos += 1
        elif c == '"':
            j = pos + 1
            buf = []
            while text[j] != '"':
                if text[j] == "\\":
                    buf.append(text[j:j + 2])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            stack[-1].append(Q("".join(buf)))
            pos = j + 1
        else:
            j = pos
            while j < n and text[j] not in " \t\r\n()":
                j += 1
            stack[-1].append(text[pos:j])
            pos = j
    return stack[0]


class Q(str):
    """A quoted string."""


def dump(node, indent=0):
    if isinstance(node, Q):
        return '"' + str(node) + '"'
    if isinstance(node, str):
        return node
    parts = [dump(x) for x in node]
    return "(" + " ".join(parts) + ")"


def find_all(node, head):
    return [x for x in node if isinstance(x, list) and x and x[0] == head]


def find(node, head):
    r = find_all(node, head)
    return r[0] if r else None


def load_symbol(lib, name):
    """Return the parsed (symbol ...) node for lib:name, with 'extends' resolved."""
    path = os.path.join(KICAD, "symbols", lib + ".kicad_sym")
    tree = parse(open(path, encoding="utf8").read())[0]
    syms = {s[1]: s for s in find_all(tree, "symbol")}
    s = syms[name]
    ext = find(s, "extends")
    if ext:
        base = syms[str(ext[1])]
        # derived symbol: take base body, own properties
        body = [x for x in base if not (isinstance(x, list) and x and x[0] == "property")]
        props = [x for x in s if isinstance(x, list) and x and x[0] == "property"]
        merged = [body[0], s[1]] + props + [x for x in body[2:]]
        # rename sub-symbols of the base to the new name
        base_name = str(ext[1])
        out = []
        for x in merged:
            if isinstance(x, list) and x and x[0] == "symbol":
                x = [x[0], Q(str(x[1]).replace(base_name, str(s[1]), 1))] + x[2:]
            out.append(x)
        return out
    return s


def symbol_pins(sym):
    """Yield (number, name, x, y, angle, length) for all pins of a symbol node."""
    pins = []

    def walk(n):
        for x in n:
            if isinstance(x, list) and x:
                if x[0] == "pin":
                    at = find(x, "at")
                    ln = find(x, "length")
                    nm = find(x, "name")
                    nu = find(x, "number")
                    pins.append((str(nu[1]), str(nm[1]), float(at[1]), float(at[2]),
                                 float(at[3]), float(ln[1])))
                elif x[0] == "symbol":
                    walk(x)
    walk(sym)
    return pins


def footprint_path(fp):
    lib, name = fp.split(":")
    return os.path.join(KICAD, "footprints", lib + ".pretty", name + ".kicad_mod")
