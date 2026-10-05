"""Roland S-760/S-770 patches -> Studio tones (same idea as akai_import).

A patch maps keys to partials, a partial points at up to 4 samples. The tone gets one zone per run of keys that share a
partial; the first valid sample slot of the partial is used. Roots, loop points and fine tune come from the sample.
The key map starts at a base key that is not stored where we can read it, so zone borders come from the sample root keys
(halfway between neighbouring roots, like Auto-map), which is also how the originals are laid out.
"""
import os
import re
import struct

import numpy as np

import roland
import u110build as B

KEY0 = 21                                     # the patch key map starts at A0


def safe(s):
    return re.sub(r'[^A-Za-z0-9_+-]+', '_', s.strip()).strip('_') or 'x'


def groups(disc):
    """[(tag, [(slot, name)])] patches grouped by their 3-letter tag (GTR, BS, KIK ...)"""
    out = {}
    for slot, nm in disc.entries(0x42):
        tag = nm.split(':', 1)[0].strip() if ':' in nm[:5] else '---'
        out.setdefault(tag or '---', []).append((slot, nm))
    return sorted(out.items())


class Importer:
    def __init__(self, disc, out_dir):
        self.disc, self.out_dir = disc, out_dir
        self.partial_by_name = {}
        for slot, nm in disc.entries(0x43):
            self.partial_by_name.setdefault(nm, slot)
        self.samples = {}                    # slot -> (decoded dict or None, wav path)
        self.report = []

    def sample(self, slot):
        if slot not in self.samples:
            s = self.disc.sample(slot) if slot < roland.DIR[0x44][1] else None
            fn = None
            if s is not None:
                import soundfile as sf
                sub = os.path.join(self.out_dir, safe(self.disc.volume.split(':', 1)[-1]))
                os.makedirs(sub, exist_ok=True)
                fn = os.path.join(sub, '%04d_%s.wav' % (slot, safe(s['name'])[:30]))
                rate = int(round(s['rate'] * 2 ** (s['fine'] / 1200.0)))
                sf.write(fn, s['pcm'], rate, subtype='PCM_16')
            self.samples[slot] = (s, fn)
        return self.samples[slot]

    def partial_sample(self, pslot):
        """first valid sample slot of a partial -> (sample dict, wav path) or (None, None)"""
        pr = self.disc.param(0x43, pslot)
        for i in range(4):
            s = struct.unpack('<H', pr[16 + 16 * i:18 + 16 * i])[0]
            if s != 0xFFFF and s < roland.DIR[0x44][1]:
                got = self.sample(s)
                if got[0] is not None:
                    return got
        return None, None

    def runs(self, rec, name):
        """[(first idx, last idx, partial slot)] from the patch's key map (key = idx + 21), or the same-named partial"""
        umap = struct.unpack('<96H', rec[0x100:0x1C0])
        runs = []
        for k, v in enumerate(umap):
            if v == 0xFFFF or v >= roland.DIR[0x43][1]:
                continue
            if runs and runs[-1][2] == v and runs[-1][1] == k - 1:
                runs[-1][1] = k
            else:
                runs.append([k, k, v])
        if runs:
            return runs
        p = self.partial_by_name.get(name)
        return [[0, 95, p]] if p is not None else []

    def patch(self, slot, name, max_zones=B.MAX_ZONES):
        rec = self.disc.param(0x42, slot)
        zs = []                                   # (first idx, last idx, sample dict, wav path)
        for lo, hi, ps in self.runs(rec, name):
            s, fn = self.partial_sample(ps)
            if s is None:
                continue
            if zs and zs[-1][3] == fn:            # neighbouring runs on the same sample merge
                zs[-1] = (zs[-1][0], hi, s, fn)
            else:
                zs.append((lo, hi, s, fn))
        if not zs:
            self.report.append('%s: no usable sample, skipped' % name)
            return []
        zones = []
        for i, (lo, hi, s, fn) in enumerate(zs):
            n = len(s['pcm'])
            z = dict(path=fn, root=int(max(0, min(127, s['root']))), hi=127, loop='off', start=0, end=n, loop_start=0, xfade_ms=0)
            if s['loop']:
                ls, le = s['loop']
                z.update(loop='loop', loop_start=ls, end=min(n, le + 1))
            zones.append(z)
        for i in range(len(zones) - 1):                # a zone ends at the last key its run covers
            zones[i]['hi'] = int(max(0, min(126, KEY0 + zs[i][1])))
            if i and zones[i]['hi'] <= zones[i - 1]['hi']:
                zones[i]['hi'] = min(126, zones[i - 1]['hi'] + 1)
        chunks = [zones[i:i + max_zones] for i in range(0, len(zones), max_zones)]
        tones = []
        nm = B.clean_name(name.split(':', 1)[-1].strip(), 10).strip() or 'ROLAND'
        for i, ch in enumerate(chunks):
            ch[-1]['hi'] = 127
            tones.append(dict(name=nm if len(chunks) == 1 else (nm[:8] + ' ' + str(i + 1))[:10], zones=ch))
        if len(chunks) > 1:
            self.report.append('%s: %d zones -> %d tones' % (nm, len(zones), len(chunks)))
        return tones


def import_patches(disc, items, out_dir):
    """items: [(slot, name)] -> (tones, report)"""
    imp = Importer(disc, out_dir)
    tones = []
    for slot, nm in items:
        tones += imp.patch(slot, nm)
    return tones, imp.report
