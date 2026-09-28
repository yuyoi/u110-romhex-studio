"""U-110 card builder engine: project (tones -> zones -> WAVs) -> burn-ready card .bin.

Layout copied from Roland's own SN-U110 cards (see FORMAT.md):
  proper 0x0080  ID block: card no, 3 spaces, 8-char internal name, 4-char version
  proper 0x0100  sample table, 10 B/entry, up to 384 entries, last = 8-byte silent "null" sample
  proper 0x1000  tone list, 128 slots x 0x50 B, unused slots = blank entry pointing at the null sample
  proper 0x4001  samples, bank 0 up to 0x3FFFF; bank 1 from 0x40004 (a sample may not cross 0x40000)
Sample rules (all Roland samples obey them): 3 leading 00 bytes, peak ~1600-1950,
forward loops run to the end of the sample and their deltas sum to exactly 0.
A sample (and its loop) is at most 0x10000 bytes: 16-bit length fields.
Output is CONNECTOR order (slot pin order), which is what a straight-wired adapter needs.
"""
import json, os, re, struct
from fractions import Fraction
import numpy as np
import u110card as uc

NATIVE = 32000
MAX_TONES = 128
MAX_ZONES = 12            # 11 split points per tone layer
MAX_SAMPLES = 383         # + the null sample = 384 table entries (0x100-0xFFF)
MAX_LEN = 0x10000
PEAK = 1800
LEAD = 3
BANKS = [(0x4001, 0x40000), (0x40004, 0x80000)]
NULL_LEN = 8
NAME_CHARS = ' ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-/+*.,:'  # U-110 LCD font (fw 0x93B3)
MAGIC = b'RolandU-110 N\xb1S\xac'
LOOP_MODES = {'loop': 0, 'off': 1, 'pingpong': 2}
# Entry templates taken from Roland's SN-U110-13 (proven on real hardware)
TONE_FIXED = bytes.fromhex('0000400000')              # bytes 0x0B-0x0F of a single-layer tone
TONE_BLK27 = bytes.fromhex('7f7f7f7f7f7f005c80')
BLANK_TONE = bytearray.fromhex(
    '2020202020202020202000004000020000ffffffffffffffffffff1818ffffffffffffffffffff007f007f007f007f'
    'ffffffffffffffffffffffffffffffffffffffffffffffff7f7f7f7f7f7f7f7f00')
assert len(BLANK_TONE) == 0x50
ID_BLOCK = bytes.fromhex('0d202020752d313320202020312e3030')  # card 13, 'u-13', '1.00'

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_name(n):
    return '%s%d' % (NOTE_NAMES[n % 12], n // 12 - 1)  # 60 = C4


def parse_note(text):
    """root note from a file name: C3 / C#3 / Db3 / 60"""
    base = os.path.splitext(os.path.basename(text))[0]
    m = re.search(r'(?<![A-Za-z])([A-Ga-g])([#sb]?)(-?\d)(?!\d)', base)
    if m:
        n = 'CDEFGAB'.index(m.group(1).upper())
        n = [0, 2, 4, 5, 7, 9, 11][n] + {'#': 1, 's': 1, 'b': -1}.get(m.group(2), 0)
        return max(0, min(127, n + (int(m.group(3)) + 1) * 12))
    m = re.search(r'(?<!\d)(\d{2,3})(?!\d)', base)
    if m and 0 <= int(m.group(1)) <= 127:
        return int(m.group(1))
    return None


def clean_name(s, n):
    s = ''.join(c if c in NAME_CHARS else ' ' for c in s)
    return s[:n].ljust(n)


def rate_for(k):
    return NATIVE * 2 ** (-k / 12)


# ---------------------------------------------------------------- audio in
def read_smpl(path):
    """(unity_note, [(type, start, end_inclusive), ...]) from a WAV smpl chunk, or None"""
    try:
        with open(path, 'rb') as f:
            d = f.read()
    except OSError:
        return None
    if d[:4] != b'RIFF':
        return None
    i = 12
    while i + 8 <= len(d):
        cid = d[i:i + 4]; sz = struct.unpack('<I', d[i + 4:i + 8])[0]
        if cid == b'smpl' and sz >= 36:
            c = d[i + 8:i + 8 + sz]
            unity = struct.unpack('<I', c[12:16])[0]
            nl = struct.unpack('<I', c[28:32])[0]
            loops = []
            for k in range(nl):
                o = 36 + k * 24
                if o + 24 <= len(c):
                    _, typ, st, en, _, _ = struct.unpack('<6I', c[o:o + 24])
                    loops.append((typ, st, en))
            return unity, loops
        i += 8 + sz + (sz & 1)
    return None


class AudioCache:
    def __init__(self):
        self.d = {}

    def get(self, path):
        if path not in self.d:
            import soundfile as sf
            x, sr = sf.read(path, dtype='float64', always_2d=True)
            self.d[path] = (x.mean(axis=1), sr)
        return self.d[path]


def resample(x, sr_in, sr_out):
    if abs(sr_in - sr_out) < 1e-6:
        return x.copy()
    from scipy.signal import resample_poly
    fr = Fraction(sr_out / sr_in).limit_denominator(1000)
    return resample_poly(x, fr.numerator, fr.denominator)


def new_zone(path, cache):
    """zone dict for a WAV: root from smpl chunk or file name, loop from smpl chunk"""
    x, sr = cache.get(path)
    z = dict(path=path, root=60, hi=127, loop='off', start=0, end=len(x), loop_start=0, xfade_ms=0)
    meta = read_smpl(path)
    root = parse_note(path)
    if meta:
        if 0 < meta[0] <= 127 and root is None:
            root = meta[0]
        if meta[1]:
            typ, st, en = meta[1][0]
            if 0 <= st < en < len(x):
                z.update(loop='pingpong' if typ == 1 else 'loop', loop_start=st, end=en + 1)
    z['root'] = 60 if root is None else root
    return z


def auto_map(zones):
    """sort by root and put each split halfway between neighbouring roots"""
    zones.sort(key=lambda z: z['root'])
    for i, z in enumerate(zones):
        z['hi'] = 127 if i == len(zones) - 1 else (z['root'] + zones[i + 1]['root']) // 2


def auto_loop(z, cache, min_loop_s=0.08):
    """pick a seamless-ish forward loop in the tail: rising zero crossings with the best
    waveform match just before loop start vs loop end; adds a crossfade"""
    x, sr = cache.get(z['path'])
    a, b = z['start'], z['end']
    seg = x[a:b]
    n = len(seg)
    if n < sr * min_loop_s * 2:
        return False
    zc = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0] + 1
    if len(zc) < 4:
        return False
    end = int(zc[zc > n * 0.6][-1]) if np.any(zc > n * 0.6) else int(zc[-1])
    w = int(sr * 0.01)
    ref = seg[max(0, end - w):end]
    best = None
    for s in zc[(zc > n * 0.25) & (zc < end - sr * min_loop_s)]:
        s = int(s)
        cmp_ = seg[max(0, s - w):s]
        if len(cmp_) != len(ref):
            continue
        c = np.dot(ref, cmp_) / (np.linalg.norm(ref) * np.linalg.norm(cmp_) + 1e-12)
        score = c + 0.15 * (end - s) / n  # prefer longer loops on ties
        if best is None or score > best[0]:
            best = (score, s)
    if best is None:
        return False
    z.update(loop='loop', loop_start=a + best[1], end=a + end, xfade_ms=min(40, int((end - best[1]) / sr * 250)))
    return True


# ---------------------------------------------------------------- render + encode
def zone_k(z, cache, k_global):
    x, sr = cache.get(z['path'])
    n = z['end'] - z['start']
    k = k_global
    while k < 60 and n * rate_for(k) / sr + LEAD > MAX_LEN:
        k += 1
    return k


def render_zone(z, cache, k):
    """float audio at rate_for(k) + loop start index (in rendered samples, before LEAD)"""
    x, sr = cache.get(z['path'])
    seg = x[z['start']:z['end']].astype(np.float64)
    ls = z['loop_start'] - z['start'] if z['loop'] != 'off' else None
    if z['loop'] == 'loop' and z.get('xfade_ms', 0) > 0 and ls:
        c = min(int(sr * z['xfade_ms'] / 1000), ls, len(seg) - ls)
        if c > 8:
            t = np.linspace(0, np.pi / 2, c)
            seg[-c:] = seg[-c:] * np.cos(t) + seg[ls - c:ls] * np.sin(t)
    r = rate_for(k)
    y = resample(seg, sr, r)
    y = y[:MAX_LEN - LEAD]
    if ls is not None:
        ls = int(round(ls * r / sr))
        ls = min(max(ls, 1), len(y) - 16)
    return y, ls


def encode_zone(y, ls, mode, gain):
    t = np.clip(np.round(y * gain), -2000, 2000).astype(np.int32)
    if mode == 'off':  # one-shot: end at zero
        f = min(64, len(t))
        t[-f:] = (t[-f:] * np.linspace(1, 0, f)).astype(np.int32)
    tgt = np.concatenate([np.zeros(LEAD, np.int32), t])
    enc = uc.encode(tgt)
    enc[:LEAD] = 0
    if mode != 'off':
        enc = uc.close_loop(enc, ls + LEAD)
    return enc


def pack(sizes):
    """first-fit decreasing into the two banks; returns {idx: start} or None"""
    free = [list(b) for b in BANKS]
    free[0][1] -= NULL_LEN  # null sample lives at the end of bank 0
    pos = {}
    for i in sorted(range(len(sizes)), key=lambda i: -sizes[i]):
        for b in free:
            if b[1] - b[0] >= sizes[i]:
                pos[i] = b[0]; b[0] += sizes[i]; break
        else:
            return None
    return pos


def akey(z):
    """zones with the same audio key share one stored sample (Roland reuses samples across tones)"""
    lp = z['loop']
    return (z['path'], z['start'], z['end'], lp, z['loop_start'] if lp != 'off' else 0,
            z.get('xfade_ms', 0) if lp == 'loop' else 0)


def unique_audio(project):
    seen = {}
    for t in project['tones']:
        for z in t['zones']:
            seen.setdefault(akey(z), z)
    return seen


def plan(project, cache):
    """choose the global rate shift k; returns (k, used bytes, fits)"""
    uz = list(unique_audio(project).values())
    want = project.get('rate', 'auto')
    ks = range(0, 25) if want == 'auto' else [int(want)]
    sizes = []
    for k in ks:
        sizes = []
        for z in uz:
            x, sr = cache.get(z['path'])
            sizes.append(min(MAX_LEN, int((z['end'] - z['start']) * rate_for(zone_k(z, cache, k)) / sr) + LEAD + 2))
        if pack(sizes) is not None:
            return k, sum(sizes), True
    return ks[-1], sum(sizes), False


def capacity():
    return sum(b - a for a, b in BANKS) - NULL_LEN


# ---------------------------------------------------------------- build
def build(project, cache, progress=None):
    """-> (connector_order_bytes, card_order_bytes, report lines)"""
    tones = [t for t in project['tones'] if t['zones']]
    if len(tones) > MAX_TONES:
        raise ValueError('max %d tones' % MAX_TONES)
    k, _, fits = plan(project, cache)
    if not fits:
        raise ValueError("samples don't fit even at the lowest rate - shorten them")
    rep = ['rate shift -%d st = %.0f Hz' % (k, rate_for(k))]

    # 1. render each unique audio once; gain = the quietest tone gain among the tones using it,
    #    so every tone keeps its zones' relative levels and nothing clips
    uz = unique_audio({'tones': tones})
    rend = {}
    for key, z in uz.items():
        kz = zone_k(z, cache, k)
        rend[key] = (kz,) + render_zone(z, cache, kz)
    gain = {}
    for t in tones:
        g = PEAK / (max(np.max(np.abs(rend[akey(z)][1])) for z in t['zones']) or 1.0)
        for z in t['zones']:
            gain[akey(z)] = min(gain.get(akey(z), g), g)
    blobs, bidx = [], {}
    for n_done, (key, (kz, y, ls)) in enumerate(rend.items()):
        bidx[key] = len(blobs)
        blobs.append((encode_zone(y, ls, key[3], gain[key]), key[3], (ls + LEAD) if ls is not None else None, kz))
        if progress:
            progress(n_done + 1, len(rend))
    pos = pack([len(b[0]) for b in blobs])
    if pos is None:
        raise ValueError('packing failed')

    # 2. table entries: one per (audio, root) like Roland's cards
    entries, eidx = [], {}
    tone_ids = []
    for t in tones:
        ids = []
        for z in sorted(t['zones'], key=lambda z: z['hi']):
            b = bidx[akey(z)]
            root = z['root'] + blobs[b][3]
            if root > 127:
                rep.append('WARNING %s: root %d + shift %d > 127, clamped' % (os.path.basename(z['path']), z['root'], blobs[b][3]))
                root = 127
            ek = (b, root)
            if ek not in eidx:
                eidx[ek] = len(entries); entries.append(ek)
            ids.append(eidx[ek])
        tone_ids.append(ids)
    if len(entries) > MAX_SAMPLES:
        raise ValueError('max %d sample entries (unique sample+root) - have %d' % (MAX_SAMPLES, len(entries)))

    pr = np.full(uc.SIZE, 0xFF, np.uint8)
    pr[0x80:0x80 + len(ID_BLOCK)] = np.frombuffer(ID_BLOCK, np.uint8)
    pr[0x4000] = 0
    pr[0x40000:0x40004] = 0
    for i, (enc, _, _, _) in enumerate(blobs):
        pr[pos[i]:pos[i] + len(enc)] = enc
    tab = bytearray()
    meta = []
    for b, root in entries:
        enc, mode, ls, _ = blobs[b]
        s, n = pos[b], len(enc)
        looplen = 4 if mode == 'off' else n - ls
        tab += bytes([s & 0xFF, (s >> 8) & 0xFF, ((s >> 16) & 7) | 0x08 | (LOOP_MODES[mode] << 6),
                      (n - 1) & 0xFF, (n - 1) >> 8, looplen & 0xFF, looplen >> 8, 0x40, root, 0x40])
        meta.append(dict(mode=mode))
    null_id = len(entries)
    ns = BANKS[0][1] - NULL_LEN
    pr[ns:ns + NULL_LEN] = 0
    tab += bytes([ns & 0xFF, (ns >> 8) & 0xFF, ((ns >> 16) & 7) | 0x08 | (1 << 6), NULL_LEN - 1, 0, 4, 0, 0x40, 100, 0x40])
    pr[0x100:0x100 + len(tab)] = np.frombuffer(bytes(tab), np.uint8)

    blank = bytearray(BLANK_TONE); blank[0x1B] = blank[0x1C] = null_id
    for slot in range(MAX_TONES):
        a = 0x1000 + slot * 0x50
        if slot < len(tones):
            zs = tones[slot]['zones']
            name = tones[slot]['name'].strip() or 'TONE %d' % (slot + 1)
            e = bytearray(clean_name(name, 10).encode('ascii')) + b'\x00' + TONE_FIXED
            splits = [z['hi'] for z in sorted(zs, key=lambda z: z['hi'])][:-1]
            e += bytes(splits) + b'\xff' * (11 - len(splits))
            e += bytes(tone_ids[slot]) + b'\xff' * (12 - len(zs))
            e += TONE_BLK27 + b'\xff' * 23 + b'\x00' * 9
            pr[a:a + 0x50] = np.frombuffer(bytes(e), np.uint8)
        else:
            pr[a:a + 0x50] = np.frombuffer(bytes(blank), np.uint8)

    header = bytearray(b'\xff' * uc.HEADER_RAW)
    header[0:16] = MAGIC
    header[16:32] = clean_name(project.get('card_name', 'MY CARD'), 16).encode('ascii')
    header[32] = project.get('card_no', 13)
    conn = uc.to_d70(pr, bytes(header))
    card = uc.to_raw(pr, bytes(header))

    # verify by reading the result back the way the U-110 does
    back = np.empty(uc.SIZE, np.uint8); back[uc.PROPER_OF_RAW_D70] = uc.D_UNSCR[np.frombuffer(conn, np.uint8)]
    ss, ts = uc.samples(back), uc.tones(back)
    assert len(ss) == len(entries) + 1 and len(ts) == len(tones)
    for s, m in zip(ss, meta):
        body = back[s['start']:s['start'] + s['length']]
        assert np.abs(uc.decode(body)).max() < 2047
        if m['mode'] != 'off':
            assert int(uc.delta(body[s['length'] - s['looplen']:]).sum()) == 0
    used = sum(len(b[0]) for b in blobs)
    rep.append('%d tones, %d samples (%d table entries), %d / %d bytes (%.0f%%)' % (
        len(tones), len(blobs), len(entries), used, capacity(), 100 * used / capacity()))
    rep.append('verified: tables read back, no clipping, every loop closes')
    return conn, card, rep


# ---------------------------------------------------------------- import a card
def import_card(path, out_dir):
    """Roland/own card .bin (either order) -> project dict + extracted WAVs"""
    import soundfile as sf
    raw = open(path, 'rb').read()
    if len(raw) != uc.SIZE:
        raise ValueError('expected a 512 KB card image, got %d bytes' % len(raw))
    pr, order = uc.any_to_proper(raw)
    ts = uc.tones(pr)
    ss = uc.samples(pr)
    os.makedirs(out_dir, exist_ok=True)
    wavs = {}
    for s in ss:
        if s['length'] < 64 or s['start'] in wavs:
            continue
        pcm = uc.decode(pr[s['start']:s['start'] + s['length']]) << 4
        fn = os.path.join(out_dir, 'smp%03d_%s.wav' % (s['i'], note_name(s['note'])))
        sf.write(fn, pcm.astype(np.int16), NATIVE)
        wavs[s['start']] = fn
    proj = dict(card_name=raw[16:32].decode('latin1').strip(), card_no=13, rate='auto', tones=[])
    for t in ts:
        if t['type'] >= 0x80:
            continue  # rhythm set tones: not supported yet
        zones = []
        splits = t['notes1'] + [127]
        for j, sidx in enumerate(t['smp1']):
            s = ss[sidx] if sidx < len(ss) else None
            if s is None or s['start'] not in wavs:
                continue
            n = s['length']
            mode = {'loop': 'loop', 'one-shot': 'off', 'ping-pong': 'pingpong'}.get(s['loop'], 'off')
            zones.append(dict(path=wavs[s['start']], root=s['note'], hi=splits[j] if j < len(splits) else 127,
                              loop=mode, start=0, end=n, loop_start=(n - s['looplen']) if mode != 'off' else 0, xfade_ms=0))
        if zones:
            proj['tones'].append(dict(name=t['name'].strip(), zones=zones))
    return proj, order


def save_project(proj, path):
    base = os.path.dirname(os.path.abspath(path))
    p = json.loads(json.dumps(proj))
    for t in p['tones']:
        for z in t['zones']:
            try:
                z['path'] = os.path.relpath(z['path'], base)
            except ValueError:
                pass
    with open(path, 'w') as f:
        json.dump(p, f, indent=1)


def load_project(path):
    base = os.path.dirname(os.path.abspath(path))
    with open(path) as f:
        p = json.load(f)
    for t in p['tones']:
        for z in t['zones']:
            if not os.path.isabs(z['path']):
                z['path'] = os.path.normpath(os.path.join(base, z['path']))
    return p
