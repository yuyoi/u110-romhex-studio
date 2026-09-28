"""Roland SN-U110 PCM card format (U-110 / U-20 / U-220 / D-70 / CM-32P family).

Three views of the same 512 KB chip:
  proper     - what the PCM chip (MB87419/MB87420) sees; all tables and samples live here
  connector  - byte order at the card slot (A0-A18 on slot pins 2-20). Burn THIS on a straight-wired
               adapter (chip pin Ak = slot pin Ak). Same order as MAME's roland_d70 wave ROMs.
  card       - byte order of the MAME sn-u110-xx.bin dumps (address lines A8..A15 reversed vs the slot)
Data lines are scrambled the same way in both raw orders.

Layout in proper space (same as the CM-32P internal ROM, see MAME roland_cm32p.cpp):
  0x0080  ID block    0x0100  sample table (10 B/entry)    0x1000  tone list (128 x 0x50 B)
  0x4001  samples: 8-bit companded DPCM (MAME roland_lp.cpp), 12-bit accumulator, 32 kHz at the root note
Raw 0x00-0x7F (both orders) holds a plain ASCII header read by the CPU: "RolandU-110 N\\xb1S\\xac", name, card no.

command line:
  python u110card.py info    card.bin            tables of a card image (either order)
  python u110card.py wavs    card.bin outdir     extract the samples as 32 kHz WAVs
  python u110card.py convert card.bin out.bin    MAME card-order dump -> connector order (burnable)
"""
import sys, os, wave
import numpy as np

SIZE = 1 << 19
HEADER_RAW = 0x80
# proper address bit -> card-order raw bit
P2R = {0: 0, 1: 5, 2: 4, 3: 6, 4: 1, 5: 2, 6: 3, 7: 15, 8: 13, 9: 10, 10: 14,
       11: 7, 12: 12, 13: 11, 14: 16, 15: 9, 16: 8, 17: 17, 18: 18}
# connector order: proper = bitswap<19>(raw, ...) as in MAME's UNSCRAMBLE_ADDR (msb first)
_UA = [18, 17, 15, 14, 16, 12, 11, 7, 9, 13, 10, 8, 3, 2, 1, 6, 4, 5, 0]
# data: proper = bitswap<8>(raw, 1,2,7,3,5,0,4,6) (MAME UNSCRAMBLE_DATA)
D_SRC = [1, 2, 7, 3, 5, 0, 4, 6]


def _dlut():
    unscr = np.zeros(256, np.uint8)
    for v in range(256):
        r = 0
        for b in D_SRC:
            r = (r << 1) | ((v >> b) & 1)
        unscr[v] = r
    scr = np.zeros(256, np.uint8)
    scr[unscr] = np.arange(256, dtype=np.uint8)
    return unscr, scr


D_UNSCR, D_SCR = _dlut()
_p = np.arange(SIZE)
RAW_OF_PROPER = np.zeros(SIZE, np.int64)          # card order
for _pb, _rb in P2R.items():
    RAW_OF_PROPER |= ((_p >> _pb) & 1) << _rb
PROPER_OF_RAW_CONN = np.zeros(SIZE, np.int64)     # connector order
for _b in _UA:
    PROPER_OF_RAW_CONN = (PROPER_OF_RAW_CONN << 1) | ((_p >> _b) & 1)
PROPER_OF_RAW_D70 = PROPER_OF_RAW_CONN


def to_proper(raw):
    """card-order raw image -> proper"""
    raw = np.frombuffer(raw, np.uint8)
    assert len(raw) == SIZE, 'expected a 512 KB image'
    return D_UNSCR[raw[RAW_OF_PROPER]]


def conn_to_proper(raw):
    """connector-order raw image -> proper"""
    raw = np.frombuffer(raw, np.uint8)
    assert len(raw) == SIZE, 'expected a 512 KB image'
    out = np.empty(SIZE, np.uint8)
    out[PROPER_OF_RAW_CONN] = D_UNSCR[raw]
    return out


def to_raw(proper, header):
    """proper -> card order (MAME dump order), header bytes put back in raw 0x00-0x7F"""
    out = np.zeros(SIZE, np.uint8)
    out[RAW_OF_PROPER] = D_SCR[proper]
    out[:HEADER_RAW] = np.frombuffer(header[:HEADER_RAW], np.uint8)
    return out.tobytes()


def to_connector(proper, header):
    """proper -> connector order (burn this on a straight-wired adapter)"""
    out = D_SCR[proper[PROPER_OF_RAW_CONN]].copy()
    out[:HEADER_RAW] = np.frombuffer(header[:HEADER_RAW], np.uint8)
    return out.tobytes()


to_d70 = to_connector


def delta(b):
    s = np.asarray(b).astype(np.int8).astype(np.int32)
    m = np.abs(s); sh = m >> 4; mt = m & 15
    v = np.where(sh > 0, (16 + mt) << np.maximum(sh - 1, 0), mt)
    return np.where(s < 0, -v, v)


def decode(buf):
    """hardware-style: accumulate the deltas, clamp to +-0x7FF"""
    out = np.empty(len(buf), np.int32); acc = 0
    for i, d in enumerate(delta(buf)):
        acc = max(-0x7FF, min(0x7FF, acc + int(d)))
        out[i] = acc
    return out


_DV = delta(np.arange(256, dtype=np.uint8))
_ORDER = np.argsort(_DV, kind='stable')
_DV_SORTED = _DV[_ORDER]


def encode(target):
    """closed-loop greedy DPCM: int array in +-2047 -> bytes whose decode tracks it"""
    out = np.empty(len(target), np.uint8); acc = 0
    for i, t in enumerate(target):
        j = int(np.searchsorted(_DV_SORTED, int(t) - acc))
        best = None
        for k in (j - 1, j):
            if 0 <= k < 256:
                nv = max(-0x7FF, min(0x7FF, acc + int(_DV_SORTED[k])))
                if best is None or abs(nv - t) < abs(best[1] - t):
                    best = (k, nv)
        out[i] = _ORDER[best[0]]; acc = best[1]
    return out


def close_loop(enc, ls):
    """nudge the last bytes so decode(end) == decode(ls-1): the loop's deltas sum to exactly 0.
    Without this every loop pass shifts the DC level until the voice pins at the rail."""
    enc = enc.copy()
    before = int(decode(enc[:ls])[-1]) if ls > 0 else 0
    r = int(decode(enc)[-1]) - before
    i = len(enc) - 1
    while r != 0 and i > ls:
        d = int(_DV[enc[i]])
        j = int(np.argmin(np.abs(_DV - (d - r))))
        r -= d - int(_DV[j])
        enc[i] = j
        i -= 1
    return enc


LOOP = {0: 'loop', 1: 'one-shot', 2: 'ping-pong', 3: '?3'}


def samples(pr):
    out = []
    for i in range(384):  # 0x100-0xFFF
        e = pr[0x100 + i * 10: 0x10A + i * 10]
        if np.all(e == 0xFF):
            break
        start = int(e[0]) | int(e[1]) << 8 | (int(e[2]) & 7) << 16
        out.append(dict(i=i, start=start, card=(e[2] >> 3) & 1, bank=(e[2] >> 4) & 3,
                        loop=LOOP[e[2] >> 6], length=(int(e[3]) | int(e[4]) << 8) + 1,
                        looplen=int(e[5]) | int(e[6]) << 8, b7=int(e[7]), note=int(e[8]),
                        b9=int(e[9]), raw=bytes(e).hex(' ')))
    return out


def tones(pr):
    out = []
    for i in range(128):  # 0x1000-0x37FF
        e = bytes(pr[0x1000 + i * 0x50: 0x1050 + i * 0x50])
        name = e[:10].decode('ascii', 'replace').replace('�', '?')
        if name.strip() == '' or e[0] == 0xFF:
            continue

        def ids(b):
            return [x for x in b if x != 0xFF]
        out.append(dict(i=i, name=name, type=e[10], notes1=ids(e[0x10:0x1B]), smp1=ids(e[0x1B:0x27]),
                        notes2=ids(e[0x30:0x3B]), smp2=ids(e[0x3B:0x47]), raw=e.hex(' ')))
    return out


def order_score(pr):
    """how card-like a proper image looks: sane sample entries + tone names with letters"""
    ok_s = 0
    for s in samples(pr):
        if s['card'] == 1 and 0x4000 <= s['start'] < SIZE and s['start'] + s['length'] <= SIZE and s['note'] < 128:
            ok_s += 1
        else:
            break
    ok_t = sum(1 for t in tones(pr) if any(c.isalpha() for c in t['name'])
               and all(32 <= ord(c) < 127 for c in t['name']) and all(i < 384 for i in t['smp1']))
    return ok_s + 2 * ok_t


def any_to_proper(raw):
    """detect the byte order (card or connector) of an image"""
    cands = [(order_score(fn(raw)), order, fn) for order, fn in (('card', to_proper), ('connector', conn_to_proper))]
    score, order, fn = max(cands, key=lambda c: c[0])
    if score == 0:
        raise ValueError('not an SN-U110 style card image (no readable tables in either byte order)')
    return fn(raw), order


def cmd_info(path):
    raw = open(path, 'rb').read()
    pr, order = any_to_proper(raw)
    print('header:', raw[:0x21], '  byte order:', order)
    for s in samples(pr):
        print('smp %3d  start %05X  len %05X  %-9s looplen %04X  root %3d' % (
            s['i'], s['start'], s['length'], s['loop'], s['looplen'], s['note']))
    for t in tones(pr):
        print('tone %3d  %s  type %02X  splits %s -> samples %s' % (t['i'], t['name'], t['type'], t['notes1'], t['smp1']))


def cmd_wavs(path, outdir):
    pr, _ = any_to_proper(open(path, 'rb').read())
    os.makedirs(outdir, exist_ok=True)
    seen = set()
    for s in samples(pr):
        if s['start'] in seen or s['length'] < 64:
            continue
        seen.add(s['start'])
        pcm = decode(pr[s['start']:s['start'] + s['length']]) << 4
        fn = os.path.join(outdir, 'smp%03d_root%d.wav' % (s['i'], s['note']))
        with wave.open(fn, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(32000)
            w.writeframes(pcm.astype('<i2').tobytes())
        print('wrote', fn)


def cmd_convert(src, dst):
    raw = open(src, 'rb').read()
    pr, order = any_to_proper(raw)
    if order == 'connector':
        print('already in connector order - nothing to do'); return
    open(dst, 'wb').write(to_connector(pr, raw))
    print('%s (card order) -> %s (connector order)' % (src, dst))


if __name__ == '__main__':
    a = sys.argv[1:]
    cmds = {'info': lambda: cmd_info(a[1]), 'wavs': lambda: cmd_wavs(a[1], a[2]),
            'convert': lambda: cmd_convert(a[1], a[2])}
    if not a or a[0] not in cmds:
        print(__doc__)
    else:
        cmds[a[0]]()
