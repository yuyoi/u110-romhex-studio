"""Roland S-760 / S-770 sampler CD-ROM reader (the "S770 MR25A" disc format) -> patches + 16-bit samples.

Layout, reverse-engineered from real discs (all of them share one fixed layout):
  0x0000  header: 4 zero bytes, "S770 MR25A", system version text
  0x0100  volume record: name[16] ("ID0:..."), u32, then the entry counts u16 x5 for object types 0x40..0x44
  directories, 32 B per entry: name[16], type u8, 0, index u16 (bit 15 set), links..., (samples: start u16, len u16 at +28/+30)
      0x40 @ 0x0A0800  (x128)    0x41 @ 0x0A1800 (x512)   0x42 @ 0x0A5800 (x1024)
      0x43 @ 0x0AD800  (x4096)   0x44 @ 0x0CD800 (x8192)
  parameters, same slot number as the directory entry:
      0x40 @ 0x10D800 (0x100 B)  0x41 @ 0x115800 (0x200 B)  0x42 @ 0x155800 (0x200 B, a patch: key -> partial map)
      0x43 @ 0x1D5800 (0x80 B, a partial: up to 4 sample slots)   0x44 @ 0x255800 (0x30 B, a sample)
  audio: 16-bit little endian, 48 kHz, in blocks of 0x2400 bytes; block 0 is at 0x2B1000
"""
import struct

import numpy as np

HEAD_SIG = b'S770 MR25A'
DIR = {0x40: (0x0A0800, 128), 0x41: (0x0A1800, 512), 0x42: (0x0A5800, 1024), 0x43: (0x0AD800, 4096), 0x44: (0x0CD800, 8192)}
PAR = {0x40: (0x10D800, 0x100), 0x41: (0x115800, 0x200), 0x42: (0x155800, 0x200), 0x43: (0x1D5800, 0x80), 0x44: (0x255800, 0x30)}
AUDIO0 = 0x2B1000
BLOCK = 0x2400
RATE = 48000


def u24(b, o):
    return b[o] | b[o + 1] << 8 | b[o + 2] << 16


def printable(b):
    return all(32 <= c < 127 for c in b)


class Disc:
    """names may carry bytes >= 0x7F (the 16th byte is sometimes a flag), so only control bytes are rejected"""

    def __init__(self, path):
        self.path = path
        self.fh = open(path, 'rb')
        head = self.fh.read(0x200)
        if head[4:14] != HEAD_SIG:
            self.fh.close()
            raise ValueError('not a Roland S-7xx disc')
        self.volume = head[0x100:0x110].decode('latin1').strip()
        self.counts = {t: struct.unpack('<H', head[0x114 + 2 * i:0x116 + 2 * i])[0] for i, t in enumerate(sorted(DIR))}
        self.size = self.fh.seek(0, 2)

    def read(self, off, n):
        self.fh.seek(off)
        return self.fh.read(n)

    def entries(self, t):
        """directory slots of type t: [(slot, name)] for every used slot"""
        base, cap = DIR[t]
        raw = self.read(base, 32 * cap)
        out = []
        for s in range(cap):
            e = raw[32 * s:32 * s + 32]
            if e[16] == t and e[17] == 0 and min(e[:16]) >= 32:
                out.append((s, e[:16].decode('latin1').rstrip()))
        return out

    def param(self, t, slot):
        base, size = PAR[t]
        return self.read(base + size * slot, size)

    # ------------------------------------------------------------ samples
    def sample(self, slot):
        """-> dict(name, root, fine, loop=(start, end) or None, end, pcm int16) for a type-0x44 slot, or None"""
        base, _ = DIR[0x44]
        d = self.read(base + 32 * slot, 32)
        p = self.param(0x44, slot)
        start, nblk = struct.unpack('<HH', d[28:32])
        last = u24(p, 33)
        if nblk == 0 or last >= nblk * BLOCK // 2:
            return None
        if d[:16].replace(b' ', b'').replace(b'*', b'') != p[:16].replace(b' ', b'').replace(b'*', b''):
            return None                       # directory and parameter slot disagree (spacing differs on some discs)
        n = last + 1
        raw = self.read(AUDIO0 + start * BLOCK, n * 2)
        if len(raw) < n * 2 or n < 8:
            return None
        pcm = np.frombuffer(raw, '<i2').copy()
        ls, le = u24(p, 21), u24(p, 25)
        loop = (ls, le) if 0 <= ls < le < n and le - ls >= 8 else None
        fine = p[38] - 256 if p[38] > 127 else p[38]
        return dict(name=p[:16].decode('latin1').strip(), root=p[45], fine=fine, loop=loop, pcm=pcm, rate=RATE)

    def close(self):
        self.fh.close()
