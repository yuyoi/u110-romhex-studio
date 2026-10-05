"""Akai sampler CD / disk image reader: S900, S1000 and S3000 volumes -> programs + samples.

Layout (reverse-engineered from real S1000/S3000 CD-ROM images):
  A CD image is a run of Akai *partitions*, 60 MB apart (0x3C00000). The last one may be shorter.
  partition: 0x0000  u16 cluster count (0x1E00 for a full 60 MB one), then a 0xCA-byte header
             0x00CA  volume list, 100 x 16 B: name[12] type u16 start-cluster u16
             0x070A  FAT, one u16 per cluster: 0 free, 0x4000 system, 0xC000 end of chain, else next cluster
  cluster size 0x2000, cluster 0 is the partition start, clusters 0-3 are system, cluster 3 = volume 1 directory.
  directory: 126 x 24 B: name[12] pad[4] type u8 size u24 start-cluster u16 tag u16
  names use the Akai charset 0-9 ' ' A-Z # + - .
"""
import os
import re
import struct

import numpy as np

AKAI_CHARS = '0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-.'
AKAI_SIG = bytes.fromhex('050d0a1a0f271434')   # bytes 4..11 of every partition header (a run of 0x0D05 steps)
CLUSTER = 0x2000
PART_STEP = 0x3C00000
FAT_AT = 0x70A
VOL_AT = 0xCA


def akai_name(b):
    return ''.join(AKAI_CHARS[c] if c < len(AKAI_CHARS) else '?' for c in b).rstrip()


class Partition:
    def __init__(self, fh, base, letter):
        self.fh, self.base, self.letter = fh, base, letter
        fh.seek(base)
        head = fh.read(0x8000)
        self.n_clusters = struct.unpack('<H', head[:2])[0]
        if not (4 < self.n_clusters <= 0x1E00):
            raise ValueError('not an Akai partition header')
        self.fat = struct.unpack('<%dH' % self.n_clusters, head[FAT_AT:FAT_AT + 2 * self.n_clusters])
        self.volumes = []
        for k in range(100):
            e = head[VOL_AT + 16 * k:VOL_AT + 16 * k + 16]
            typ, start = struct.unpack('<HH', e[12:16])
            if typ and start >= 3 and start < self.n_clusters and e[:12] != b'\x00' * 12:
                self.volumes.append((akai_name(e[:12]), typ, start))

    def chain(self, start, size):
        out, c = [], start
        need = (size + CLUSTER - 1) // CLUSTER
        while c and c < self.n_clusters and len(out) < need:
            out.append(c)
            nxt = self.fat[c]
            if nxt in (0xC000, 0x4000, 0):
                break
            c = nxt
        return out

    def read(self, start, size):
        buf = bytearray()
        for c in self.chain(start, size):
            self.fh.seek(self.base + c * CLUSTER)
            buf += self.fh.read(CLUSTER)
        return bytes(buf[:size])

    def directory(self, vol_start):
        self.fh.seek(self.base + vol_start * CLUSTER)
        d = self.fh.read(126 * 24)
        files = []
        for i in range(126):
            e = d[i * 24:i * 24 + 24]
            if e[:12] == b'\x00' * 12 or len(e) < 24:
                continue
            size = e[17] | e[18] << 8 | e[19] << 16
            start = e[20] | e[21] << 8
            if size == 0 or start < 4 or start >= self.n_clusters:
                continue
            files.append(dict(name=akai_name(e[:12]), type=e[16], size=size, start=start))
        return files


def open_image(path):
    """list of Partition for an Akai CD / disk image, or [] if it is not one"""
    fh = open(path, 'rb')
    size = os.fstat(fh.fileno()).st_size
    # plain .iso/.tao start at 0; Nero .nrg rips carry a 150-sector (0x4B000) lead-in before the first partition
    first = fh.read(0x100000)
    org = 0
    if first[4:12] != AKAI_SIG:
        i = first.find(AKAI_SIG)
        if i < 4 or (i - 4) % 2048:
            fh.close()
            return []
        org = i - 4
    parts = []
    for i, base in enumerate(range(org, size, PART_STEP)):
        try:
            parts.append(Partition(fh, base, chr(65 + i)))
        except (ValueError, struct.error):
            break
    return parts


# ---------------------------------------------------------------- S1000 samples and programs
S1000_PROG, S1000_SAMPLE = 0x70, 0x73
S3000_SAMPLE = 0xF3            # header is 192 bytes; loops not decoded (no S3000 disc to test against)
SAMPLE_HEAD = {S1000_SAMPLE: 150, S3000_SAMPLE: 192}
NOTE_RE = re.compile(r'[^A-Za-z0-9._ +#-]')


def s8(v):
    return v - 256 if v > 127 else v


def read_sample(data, ftype=S1000_SAMPLE):
    """-> dict(name, rate, root, pcm int16, loop=(start, end_inclusive) or None, loop_mode, cents)  or None"""
    hl = SAMPLE_HEAD.get(ftype, 150)
    if len(data) < hl + 4 or data[0] != 3:
        return None
    n = struct.unpack('<I', data[26:30])[0]
    n = min(n, (len(data) - hl) // 2)
    if n < 8:
        return None
    pcm = np.frombuffer(data, '<i2', n, hl).copy()
    rate = struct.unpack('<H', data[0x8A:0x8C])[0]
    if not 4000 <= rate <= 96000:
        rate = 44100 if data[1] else 22050
    start, end = struct.unpack('<II', data[30:38])
    loop = None
    if ftype == S1000_SAMPLE and data[16]:
        li = min(data[17], 7)
        at, fine, ln = struct.unpack('<IHI', data[38 + 12 * li:38 + 12 * li + 10])
        ls = at - ln
        if ln >= 8 and 0 <= ls < at < n:
            loop = (ls, at)
    # tune is a signed 16-bit value in 1/256 semitone; 48 kHz material carries ~+1.47 st, the compensation for
    # the sampler playing everything at 44.1 / 22.05 kHz. So the audio really plays at base_rate * 2^(tune/12).
    tune = struct.unpack('<h', data[20:22])[0] * 100.0 / 256
    return dict(name=akai_name(data[3:15]), rate=rate, base_rate=44100 if data[1] else 22050, root=data[2], pcm=pcm,
                loop=loop, loop_mode=data[19], cents=tune, start=min(start, n - 1), end=min(max(end, 1), n - 1))


def read_program(data):
    """S1000 program -> dict(name, keygroups=[dict(lo, hi, tune, zones=[dict(sample, lovel, hivel, tune, pan, playback)])])"""
    if len(data) < 150 or data[0] != 1:
        return None
    kgs = []
    # keygroups follow the header back to back; the pointers in the file are RAM addresses, not file offsets
    for addr in range(150, len(data) - 149, 150):
        kg = data[addr:addr + 150]
        if kg[0] != 2:
            break
        zones = []
        for i in range(4):
            z = kg[34 + 24 * i:58 + 24 * i]
            name = akai_name(z[:12])
            if not name:
                continue
            zones.append(dict(sample=name, lovel=z[12], hivel=z[13], tune=struct.unpack('<h', z[14:16])[0],   # cents
                              pan=s8(z[18]), playback=z[19]))
        kgs.append(dict(lo=kg[3], hi=kg[4], tune=100 * s8(kg[6]) + s8(kg[5]), zones=zones))
    return dict(name=akai_name(data[3:15]), keygroups=kgs)


class Volume:
    def __init__(self, part, name, start):
        self.part, self.name, self.start = part, name, start
        self.files = part.directory(start)
        self.samples = {f['name']: f for f in self.files if f['type'] in SAMPLE_HEAD}
        self.programs = [f for f in self.files if f['type'] == S1000_PROG]

    image = None

    def owner(self, name):
        """the volume that actually holds sample `name`: this one, else another volume of the disc (programs copied
        between volumes keep pointing at samples that only exist in the original volume)"""
        if name in self.samples:
            return self
        if self.image is not None:
            for v in sorted(self.image.index.get(name, ()), key=lambda v: v.part is not self.part):
                return v
        return None

    def sample(self, name):
        f = self.samples.get(name)
        if f is None:
            return None
        return read_sample(self.part.read(f['start'], f['size']), f['type'])

    def program(self, f):
        return read_program(self.part.read(f['start'], f['size']))


class Image:
    """an Akai CD / disk image: .volumes = [Volume], each with .programs (S1000) and .samples"""

    def __init__(self, path):
        self.path = path
        self.parts = open_image(path)
        if not self.parts:
            raise ValueError('not an Akai sampler disk image (no Akai partition found)')
        self.volumes = []
        for p in self.parts:
            for name, typ, start in p.volumes:
                try:
                    v = Volume(p, name, start)
                except (struct.error, OSError):
                    continue
                if v.programs or v.samples:
                    self.volumes.append(v)
        self.index = {}
        for v in self.volumes:
            v.image = self
            for k in v.samples:
                self.index.setdefault(k, []).append(v)

    def close(self):
        for p in self.parts:
            p.fh.close()
