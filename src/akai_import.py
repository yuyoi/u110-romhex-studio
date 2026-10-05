"""Akai programs -> Studio tones: pick a velocity layer, mix stereo pairs, keep loops and tuning, write WAVs.

An Akai keygroup (key range, up to 4 velocity zones with a sample each) becomes one U-110 zone (key range + sample).
The U-110 tone has no velocity layers in this tool, so one layer is chosen per keygroup (the one covering `vel`).
Zones that sound together at that velocity (stereo L/R pairs) are mixed to mono when they line up, else the
first one is used. More than 12 keygroups in a program (drum kits) are split over several tones.
"""
import os
import re

import numpy as np

import akai
import u110build as B

LOOPING = {0, 1}                     # sample header loop mode: 0 in release, 1 until release (2 none, 3 play to end)
PB_LOOPING = {1, 2}                  # keygroup playback: 0 as sample, 1 loop in release, 2 loop until release, 3 none, 4 to end


def safe(s):
    return re.sub(r'[^A-Za-z0-9_+-]+', '_', s.strip()).strip('_') or 'x'


def pick_zones(kg, vol, vel):
    """the zones of a keygroup that sound at velocity vel (only those whose sample exists on the disk)"""
    zs = [z for z in kg['zones'] if vol.owner(z['sample']) is not None]
    if not zs:
        return []
    hit = [z for z in zs if z['lovel'] <= vel <= z['hivel']]
    if hit:
        return hit
    mid = lambda z: abs((z['lovel'] + z['hivel']) / 2 - vel)
    return [min(zs, key=mid)]


class Importer:
    def __init__(self, out_dir, vel=100, mix_stereo=True):
        self.out_dir, self.vel, self.mix_stereo = out_dir, vel, mix_stereo
        self.written = {}                    # (vol key, sample names, tune) -> zone template
        self.cache = {}                      # (vol key, name) -> decoded sample
        self.report = []

    def sample(self, vol, name):
        owner = vol.owner(name) or vol
        k = (id(owner), name)
        if k not in self.cache:
            self.cache[k] = owner.sample(name)
        return self.cache[k]

    def make_zone(self, vol, kg, zs):
        """-> zone dict (without 'hi') or None"""
        samples = [(z, self.sample(vol, z['sample'])) for z in zs]
        samples = [(z, s) for z, s in samples if s is not None]
        if not samples:
            return None
        z0, s0 = samples[0]
        used = [(z0, s0)]
        if len(samples) > 1 and self.mix_stereo:
            for z, s in samples[1:]:
                same = (s['rate'] == s0['rate'] and s['root'] == s0['root'] and abs(len(s['pcm']) - len(s0['pcm'])) <= 1
                        and s['loop'] == s0['loop'])
                if same:
                    used.append((z, s))
                else:
                    self.report.append('  keygroup %d-%d: layers %s / %s do not line up, used %s only' % (
                        kg['lo'], kg['hi'], z0['sample'], z['sample'], z0['sample']))
                    break
        tune = kg['tune'] + z0['tune'] + s0['cents']
        semis = int(round(tune / 100))
        cents = tune - 100 * semis
        key = (id(vol), tuple(z['sample'] for z, _ in used), cents)
        if key not in self.written:
            n = min(len(s['pcm']) for _, s in used)
            x = sum(s['pcm'][:n].astype(np.float64) for _, s in used) / len(used)
            rate = int(round(s0['base_rate'] * 2 ** (cents / 1200)))   # the sampler plays at 44.1 / 22.05 kHz, tuned by `tune`
            sub = os.path.join(self.out_dir, safe(vol.name))
            os.makedirs(sub, exist_ok=True)
            base = safe('_'.join(z['sample'] for z, _ in used)[:40])
            fn = os.path.join(sub, '%s%s.wav' % (base, '' if not cents else '_%+dc' % cents))
            i = 1
            while fn in self.written.values():       # two different samples that clean up to the same name
                fn = os.path.join(sub, '%s_%d.wav' % (base, i))
                i += 1
            import soundfile as sf
            sf.write(fn, np.clip(np.round(x), -32768, 32767).astype(np.int16), rate, subtype='PCM_16')
            self.written[key] = fn
        fn = self.written[key]
        n = min(len(s['pcm']) for _, s in used)
        st = int(min(s0['start'], n - 2))
        en = int(min(max(s0['end'] + 1, st + 8), n))
        zone = dict(path=fn, root=int(max(0, min(127, s0['root'] - semis))), hi=127, loop='off', start=st, end=en,
                    loop_start=0, xfade_ms=0)
        playback = z0['playback']
        looping = (playback in PB_LOOPING) if playback else (s0['loop_mode'] in LOOPING)
        if looping and s0['loop']:
            ls, le = s0['loop']
            ls = max(ls, st)
            if le > ls + 8:
                zone.update(loop='loop', loop_start=ls, end=min(n, le + 1))
        return zone

    def program(self, vol, f, max_zones=B.MAX_ZONES):
        """-> [tone dict, ...] for one program file"""
        pr = vol.program(f)
        if not pr or not pr['keygroups']:
            self.report.append('%s: no keygroups, skipped' % f['name'])
            return []
        zones = []
        seen = set()
        for kg in sorted(pr['keygroups'], key=lambda k: (k['lo'], k['hi'])):
            if kg['hi'] in seen or kg['hi'] < kg['lo']:
                continue
            zs = pick_zones(kg, vol, self.vel)
            if not zs:
                self.report.append('  keygroup %d-%d: sample not found on the disk, dropped' % (kg['lo'], kg['hi']))
                continue
            z = self.make_zone(vol, kg, zs)
            if z is None:
                continue
            z['hi'] = kg['hi']
            seen.add(kg['hi'])
            zones.append(z)
        if not zones:
            return []
        zones[-1]['hi'] = 127
        chunks = [zones[i:i + max_zones] for i in range(0, len(zones), max_zones)]
        tones = []
        base = B.clean_name(pr['name'] or f['name'], 12).strip() or 'AKAI'
        for i, ch in enumerate(chunks):
            ch[-1]['hi'] = 127 if i == len(chunks) - 1 else ch[-1]['hi']
            name = base[:10] if len(chunks) == 1 else (base[:8] + ' ' + str(i + 1))[:10]
            tones.append(dict(name=name, zones=ch))
        if len(chunks) > 1:
            self.report.append('%s: %d keygroups -> %d tones (a tone holds %d zones)' % (base, len(zones), len(chunks), max_zones))
        return tones


def import_programs(items, out_dir, vel=100, mix_stereo=True):
    """items: [(Volume, program file dict)] -> (tones, report lines)"""
    imp = Importer(out_dir, vel, mix_stereo)
    tones = []
    for vol, f in items:
        tones += imp.program(vol, f)
    return tones, imp.report
