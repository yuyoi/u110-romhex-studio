"""Wavetable tools: single-cycle waves -> looped, band-limited multisample tones.

The chip pitches a sample up by at most ~2 octaves, so a wave tone is stored at
several roots (C1, C3, C5, C7), each band-limited so its top key does not alias.
Each zone holds a whole number of cycles whose length lands within ~1 cent of the
root, plus one lead cycle so the loop point is clean (loop = last `k` cycles).

Scan morph renders a sweep through several waves over time, looping the last wave
(or ping-ponging the whole sweep).
"""
import os
import numpy as np

SR = 32000
ROOTS = (24, 48, 72, 96)          # C1 C3 C5 C7: each zone covers root .. root+23
SHAPES = ('sine', 'triangle', 'saw', 'square', 'pulse 25', 'pulse 12', 'supersaw', 'sync', 'organ', 'formant')


def freq(note):
    return 440.0 * 2 ** ((note - 69) / 12)


def shape(name, n=2048):
    """one cycle of a built-in shape, n samples"""
    t = np.arange(n) / n
    if name == 'sine':
        return np.sin(2 * np.pi * t)
    if name == 'triangle':
        return 1 - 4 * np.abs(t - 0.5)
    if name == 'saw':
        return 1 - 2 * t
    if name == 'square':
        return np.where(t < 0.5, 1.0, -1.0)
    if name.startswith('pulse'):
        w = int(name.split()[1]) / 100
        return np.where(t < w, 1.0, -1.0) - (2 * w - 1)
    if name == 'supersaw':
        return sum((1 - 2 * ((t * h) % 1)) / h ** 0.3 for h in (1, 2, 3)) / 2.2
    if name == 'sync':  # hard-sync saw, slave at 2.6x
        return 1 - 2 * ((t * 2.6) % 1)
    if name == 'organ':
        return sum(a * np.sin(2 * np.pi * h * t) for h, a in ((1, 1), (2, .7), (3, .5), (4, .35), (6, .25), (8, .2)))
    if name == 'formant':
        return np.sin(2 * np.pi * t) * np.exp(-3 * t) + 0.6 * np.sin(2 * np.pi * 7 * t) * np.exp(-6 * t)
    raise ValueError(name)


def load_cycle(path):
    """a single-cycle WAV (AKWF etc.): the whole file is one cycle"""
    import soundfile as sf
    x, _ = sf.read(path, dtype='float64', always_2d=True)
    return x.mean(axis=1)


def _harmonics(cycle):
    c = np.asarray(cycle, np.float64)
    c = c - c.mean()
    return np.fft.rfft(c) / len(c)


def _render(H, n, cycles, top_hz):
    """`cycles` periods in `n` samples, keeping only harmonics that stay under Nyquist at top_hz"""
    f0 = SR * cycles / n
    hmax = max(1, int(SR * 0.45 / top_hz))
    H = H[:hmax + 1].copy()
    k = np.arange(len(H))
    out = np.zeros(n)
    ph = 2 * np.pi * np.outer(np.arange(n) * cycles / n, k[1:])
    out = (np.cos(ph) * H[1:].real * 2 - np.sin(ph) * H[1:].imag * 2).sum(axis=1)
    return out, f0


def _fit(root, max_cycles=16):
    """whole cycles + length closest to the root pitch; returns (samples, cycles)"""
    per = SR / freq(root)
    best = None
    for c in range(1, max_cycles + 1):
        n = round(per * c)
        cents = abs(1200 * np.log2(per * c / n))
        if best is None or cents < best[0] - 0.05:
            best = (cents, n, c)
        if cents < 0.5:
            break
    return best[1], best[2]


def _norm(x):
    m = np.max(np.abs(x)) or 1
    return x / m * 0.95


def _write(path, x):
    import soundfile as sf
    sf.write(path, np.clip(x, -1, 1), SR, subtype='PCM_16')


def wave_tone(cycle, out_dir, name, roots=ROOTS):
    """one looped tone: a zone per root. returns zone dicts (loop = last cycle block)"""
    H = _harmonics(cycle)
    zones = []
    for r in roots:
        n, c = _fit(r)
        body, _ = _render(H, n, c, freq(r + 23))
        body = _norm(body)
        x = np.concatenate([body, body])          # lead block + loop block
        p = os.path.join(out_dir, '%s_%d.wav' % (name, r))
        _write(p, x)
        zones.append(dict(path=p, root=r, hi=r + 23, loop='loop', start=0, end=len(x), loop_start=n, xfade_ms=0))
    zones[-1]['hi'] = 127
    return zones


def scan_tone(cycles, out_dir, name, seconds=1.5, loop='last', roots=(24, 48, 72)):
    """morph through the waves over `seconds`; loop='last' holds the final wave, 'pingpong' sweeps back and forth"""
    Hs = [_harmonics(c) for c in cycles]
    L = max(len(h) for h in Hs)
    Hs = [np.pad(h, (0, L - len(h))) for h in Hs]
    zones = []
    for r in roots:
        n, c = _fit(r)
        top = freq(r + 23)
        steps = max(2, int(seconds * SR / n))        # blocks of `c` cycles across the sweep
        pos = np.linspace(0, len(Hs) - 1, steps)
        blocks = []
        for p in pos:
            i = min(int(p), len(Hs) - 2) if len(Hs) > 1 else 0
            f = p - i if len(Hs) > 1 else 0
            H = Hs[i] * (1 - f) + Hs[min(i + 1, len(Hs) - 1)] * f
            blocks.append(_render(H, n, c, top)[0])
        last = blocks[-1]
        x = np.concatenate(blocks + ([last] if loop == 'last' else []))
        x = _norm(x)
        p = os.path.join(out_dir, '%s_%d.wav' % (name, r))
        _write(p, x)
        if loop == 'last':
            z = dict(loop='loop', loop_start=len(x) - n)
        else:
            z = dict(loop='pingpong', loop_start=n)
        zones.append(dict(path=p, root=r, hi=r + 23, start=0, end=len(x), xfade_ms=0, **z))
    zones[-1]['hi'] = 127
    return zones
