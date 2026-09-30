"""U110 RomHex Studio - build Roland SN-U110 style PCM cards from WAV files.

Tones (left) hold up to 12 key zones; each zone is a WAV with root note, key range and loop.
Waveform: drag the S (start), L (loop start) and E (end) markers, wheel = zoom, Shift+wheel = pan,
double-click = set start, then end (alternating), right-click = fit. Keyboard: click a key to hear it the way the U-110 will play it.
Build writes a burn-ready .bin (connector order) for your EPROM / flash programmer.
"""
import os, sys, threading, queue, traceback
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import u110build as B
import u110card as UC
import u110wave as WV
import u110prog as UP

APP = 'U110 RomHex Studio'
EXT = '.u110proj'
# hardware look: charcoal panel, backlit yellow-green LCD, red keys, amber selection
PANEL, PANEL_HI, RECESS, EDGE = '#1d2228', '#2a3038', '#12161a', '#0a0c0e'   # U-110 front: blue-black
TEXT, DIM, SILK = '#eef1f3', '#8a96a0', '#ffffff'
RED, AMBER, BLUE = '#c8322a', '#6ec8e8', '#6ec8e8'   # logo light blue is the accent
LCD_A, LCD_B, LCD_CELL, LCD_INK = '#94ec44', '#5cc41c', '#80da32', '#10280a'   # backlit U-110 LCD green
WAVE_BG, WAVE_FG, WAVE_FILL, LOOP_BG, OUT_BG, GRID = '#0c0f0d', '#8fe05a', '#2b5a20', '#172a19', '#17181b', '#161d17'
MARK = {'start': '#5aa9ff', 'loop_start': AMBER, 'end': RED}
ZONE_COLS = ['#4f7fc0', '#c07a3f', '#4fae6a', '#9a5fc0', '#b8a53a', '#3fa6b0']


def res(name):
    """bundled file (works from source and from the PyInstaller exe)"""
    return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), name)


def apply_theme(root):
    st = ttk.Style(root)
    st.theme_use('clam')
    root.configure(bg=PANEL)
    st.configure('.', background=PANEL, foreground=TEXT, fieldbackground=RECESS, bordercolor=EDGE,
                 lightcolor=PANEL_HI, darkcolor=EDGE, troughcolor=RECESS, focuscolor=AMBER,
                 selectbackground=AMBER, selectforeground='#111', insertcolor=TEXT, arrowcolor=TEXT,
                 font=('Segoe UI', 9))
    st.configure('TLabelframe', background=PANEL, bordercolor='#46494e')
    st.configure('TLabelframe.Label', background=PANEL, foreground=SILK, font=('Arial', 8, 'bold'))
    st.configure('TButton', background='#3a3f46', foreground=TEXT, bordercolor=EDGE, lightcolor='#50565e',
                 darkcolor='#1a1d21', padding=(9, 3), font=('Arial', 9, 'bold'))
    st.map('TButton', background=[('pressed', '#23272c'), ('active', '#474d55')])
    st.configure('Build.TButton', background='#3a4048', foreground=BLUE, font=('Bahnschrift', 13, 'bold'),
                 padding=(20, 10), lightcolor='#4d545d', darkcolor='#16191d', bordercolor=BLUE)
    st.map('Build.TButton', background=[('pressed', '#23272c'), ('active', '#454c55')])
    st.configure('Treeview', background=RECESS, fieldbackground=RECESS, foreground=TEXT, rowheight=21, bordercolor=EDGE)
    st.map('Treeview', background=[('selected', '#2f6f8a')], foreground=[('selected', '#ffffff')])
    st.configure('Treeview.Heading', background=PANEL_HI, foreground=SILK, font=('Segoe UI', 8, 'bold'), relief='flat')
    st.map('Treeview.Heading', background=[('active', '#44474c')])
    for w in ('TEntry', 'TSpinbox', 'TCombobox'):
        st.configure(w, fieldbackground=RECESS, foreground=TEXT, background='#4a4d53', arrowcolor=TEXT)
    st.map('TCombobox', fieldbackground=[('readonly', RECESS)], foreground=[('readonly', TEXT)],
           selectbackground=[('readonly', RECESS)], selectforeground=[('readonly', TEXT)])
    root.option_add('*TCombobox*Listbox.background', RECESS)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', AMBER)
    root.option_add('*TCombobox*Listbox.selectForeground', '#111')
    st.configure('TCheckbutton', background=PANEL, foreground=TEXT, indicatorbackground=RECESS, indicatorforeground=AMBER)
    st.map('TCheckbutton', background=[('active', PANEL)])
    st.configure('TRadiobutton', background=PANEL, foreground=TEXT, indicatorbackground=RECESS, indicatorforeground=AMBER)
    st.map('TRadiobutton', background=[('active', PANEL)])
    st.configure('Horizontal.TProgressbar', background=AMBER, troughcolor=RECESS, bordercolor=EDGE, lightcolor=AMBER, darkcolor=AMBER)
    st.configure('TScrollbar', background='#4a4d53', troughcolor=RECESS, arrowcolor=TEXT)
    st.configure('Dim.TLabel', foreground=DIM)
    st.configure('Silk.TLabel', foreground=SILK, font=('Arial', 8, 'bold'))
    st.configure('Title.TLabel', foreground=BLUE, font=('Bahnschrift SemiLight SemiConde', 30))
    st.configure('Sub.TLabel', foreground=BLUE, font=('Bahnschrift', 10))
    st.configure('Status.TFrame', background=RECESS)
    st.configure('Status.TLabel', background=RECESS, foreground=DIM)


def dark_titlebar(win):
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        v = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (Win11 / older Win10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v)) == 0:
                break
    except Exception:
        pass


# ============================================================ LCD + LED meter
class LCD(tk.Canvas):
    """backlit dot-matrix style display, 2 rows"""
    CW, CH = 11, 20

    def __init__(self, master, cols=40):
        self.cols = cols
        super().__init__(master, width=cols * self.CW + 26, height=2 * self.CH + 22, bg=PANEL, highlightthickness=0)
        self.lines = ['', '']
        self.text_ids = []
        self.draw_glass()

    def draw_glass(self):
        W, H = int(self['width']), int(self['height'])
        self.create_rectangle(0, 0, W, H, fill=EDGE, outline='#0b0b0c')
        x0, y0, x1, y1 = 6, 6, W - 6, H - 6
        n = y1 - y0
        a = [int(LCD_A[i:i + 2], 16) for i in (1, 3, 5)]
        b = [int(LCD_B[i:i + 2], 16) for i in (1, 3, 5)]
        for i in range(n):
            t = abs(i / n - 0.35) * 1.3
            c = '#%02x%02x%02x' % tuple(int(a[k] * (1 - t) + b[k] * t) for k in range(3))
            self.create_line(x0, y0 + i, x1, y0 + i, fill=c)
        for r in range(2):
            for c in range(self.cols):
                cx, cy = 13 + c * self.CW, 11 + r * self.CH
                self.create_rectangle(cx, cy, cx + self.CW - 2, cy + self.CH - 3, fill=LCD_CELL, outline='')

    def set(self, l1, l2):
        lines = [l1[:self.cols].ljust(self.cols), l2[:self.cols].ljust(self.cols)]
        if lines == self.lines:
            return
        self.lines = lines
        for i in self.text_ids:
            self.delete(i)
        self.text_ids = []
        for r, s in enumerate(lines):
            for c, ch in enumerate(s):
                if ch != ' ':
                    self.text_ids.append(self.create_text(13 + c * self.CW + (self.CW - 2) / 2, 11 + r * self.CH + (self.CH - 3) / 2,
                                                          text=ch, fill=LCD_INK, font=('Consolas', 12, 'bold')))


class LEDMeter(tk.Canvas):
    def __init__(self, master, segs=26):
        self.segs = segs
        super().__init__(master, width=segs * 8 + 4, height=18, bg=PANEL, highlightthickness=0)
        self.set(0)

    def set(self, frac, over=False):
        self.delete('all')
        lit = int(round(frac * self.segs))
        for i in range(self.segs):
            p = i / self.segs
            on = over or i < lit
            col = ('#ff3b30' if over or p >= 0.9 else '#f0b12a' if p >= 0.7 else '#6fd13a') if on else \
                  ('#3a1e1c' if p >= 0.9 else '#3a3218' if p >= 0.7 else '#1f3319')
            self.create_rectangle(2 + i * 8, 2, 2 + i * 8 + 6, 16, fill=col, outline='')


def new_project():
    return dict(card_name='MY CARD 01', card_no=13, rate='auto', tones=[])


def simulate(d, ls, mode, step, seconds):
    """play decoded data d the way the chip does: resample by step, follow the loop"""
    L = len(d)
    if L < 2:
        return np.zeros(1)
    pos = np.arange(int(32000 * seconds)) * step
    if mode == 'off' or ls is None or ls >= L - 2:
        pos = pos[pos < L - 1]
    elif mode in ('loop', 'mode3'):  # mode3 is undocumented: previewed as a forward loop
        pos = np.where(pos < L - 1, pos, ls + np.mod(pos - ls, (L - 1 - ls)))
    else:
        per = 2 * (L - 1 - ls)
        q = np.mod(pos - ls, per)
        q = np.where(q <= L - 1 - ls, q, per - q)
        pos = np.where(pos < L - 1, pos, ls + q)
    i = np.floor(pos).astype(int)
    f = pos - i
    return d[i] * (1 - f) + d[np.minimum(i + 1, L - 1)] * f


# ============================================================ waveform
class WaveView(tk.Canvas):
    def __init__(self, master, app):
        super().__init__(master, bg=WAVE_BG, height=230, highlightthickness=0)
        self.app, self.z, self.x, self.sr = app, None, None, 1
        self.v0 = self.v1 = 0
        self.drag = None
        self.bind('<Configure>', lambda e: self.redraw())
        self.bind('<ButtonPress-1>', self.on_press)
        self.bind('<B1-Motion>', self.on_drag)
        self.bind('<ButtonRelease-1>', self.on_release)
        self.bind('<MouseWheel>', self.on_wheel)
        self.bind('<Double-Button-1>', self.on_double)
        self.bind('<Button-3>', lambda e: self.fit())
        self.next_set = 'start'

    def on_double(self, ev):
        """double-click: place start, next double-click places end, alternating (loop start is dragged)"""
        if self.x is None:
            return
        self.drag = None
        z, f = self.z, self.snap(max(0, min(len(self.x), self.px2f(ev.x))))
        gap = int(self.sr * 0.002)
        if self.next_set == 'start':
            z['start'] = max(0, min(f, z['end'] - gap))
            self.next_set = 'end'
        else:
            z['end'] = min(len(self.x), max(f, z['start'] + gap))
            self.next_set = 'start'
        if z['loop'] != 'off':
            z['loop_start'] = min(max(z['loop_start'], z['start'] + 1), z['end'] - gap)
        self.redraw()
        self.app.status('Double-click again to set the %s' % self.next_set.upper())
        self.app.show_zone_numbers()
        self.app.zone_changed()

    def set_zone(self, z):
        self.next_set = 'start'
        self.z = z
        if z is None:
            self.x = None
        else:
            self.x, self.sr = self.app.cache.get(z['path'])
            self.v0, self.v1 = 0, len(self.x)
        self.redraw()

    def fit(self):
        if self.x is not None:
            self.v0, self.v1 = 0, len(self.x)
            self.redraw()

    def f2px(self, f):
        return (f - self.v0) * self.winfo_width() / max(1, self.v1 - self.v0)

    def px2f(self, px):
        return int(self.v0 + px * (self.v1 - self.v0) / max(1, self.winfo_width()))

    def markers(self):
        m = ['start', 'end']
        if self.z and self.z['loop'] != 'off':
            m.insert(1, 'loop_start')
        return m

    def redraw(self):
        self.delete('all')
        W, H = self.winfo_width(), self.winfo_height()
        for i in range(1, 10):
            self.create_line(W * i / 10, 0, W * i / 10, H, fill=GRID)
        for f in (0.25, 0.75):
            self.create_line(0, H * f, W, H * f, fill=GRID)
        if self.x is None:
            self.create_text(W / 2, H / 2, text='SELECT A ZONE  -  OR ADD WAVS TO A TONE', fill='#4d6b45', font=('Consolas', 12, 'bold'))
            return
        z, mid, amp = self.z, H / 2, H / 2 - 16
        s, e = self.f2px(z['start']), self.f2px(z['end'])
        self.create_rectangle(0, 0, s, H, fill=OUT_BG, width=0, stipple='gray50')
        self.create_rectangle(e, 0, W, H, fill=OUT_BG, width=0, stipple='gray50')
        if z['loop'] != 'off':
            self.create_rectangle(self.f2px(z['loop_start']), 0, e, H, fill=LOOP_BG, width=0)
        self.create_line(0, mid, W, mid, fill='#24302a')
        seg = self.x[self.v0:self.v1]
        n = len(seg)
        scale = amp / max(1e-9, float(np.max(np.abs(self.x))))
        if W < 4:
            return  # not laid out yet
        if n > W * 2:
            edges = np.linspace(0, n, W + 1).astype(int)[:-1]
            mx, mn = np.maximum.reduceat(seg, edges), np.minimum.reduceat(seg, edges)
            top = [(i, mid - mx[i] * scale) for i in range(len(edges))]
            bot = [(i, mid - mn[i] * scale + 1) for i in range(len(edges) - 1, -1, -1)]
            poly = [c for p in top + bot for c in p]
            self.create_polygon(*poly, fill=WAVE_FILL, outline='')
            self.create_line(*[c for p in top for c in p], fill=WAVE_FG)
            self.create_line(*[c for p in bot for c in p], fill=WAVE_FG)
        elif n > 1:
            xs = (np.arange(n)) * W / max(1, n - 1)
            pts = np.column_stack([xs, mid - seg * scale]).ravel().tolist()
            self.create_line(*pts, fill=WAVE_FG, width=2)
        for m in self.markers():
            px = self.f2px(z[m])
            self.create_line(px, 0, px, H, fill=MARK[m], width=2)
            self.create_polygon(px - 1, 0, px + 17, 0, px + 17, 12, px + 9, 17, px - 1, 17, fill=MARK[m], outline='')
            self.create_text(px + 8, 8, text={'start': 'S', 'loop_start': 'L', 'end': 'E'}[m], fill='#111', font=('Segoe UI', 8, 'bold'))
        t0, t1 = self.v0 / self.sr, self.v1 / self.sr
        self.create_text(4, H - 4, anchor='sw', text='%.3fs' % t0, fill='#5f7a58', font=('Consolas', 9))
        self.create_text(W - 4, H - 4, anchor='se', text='%.3fs' % t1, fill='#5f7a58', font=('Consolas', 9))

    def on_press(self, ev):
        if self.x is None:
            return
        best = min(self.markers(), key=lambda m: abs(self.f2px(self.z[m]) - ev.x))
        self.drag = best if abs(self.f2px(self.z[best]) - ev.x) < 10 else None

    def snap(self, f):
        if not self.app.snap.get():
            return f
        w = int(self.sr * 0.005)
        a, b = max(1, f - w), min(len(self.x) - 1, f + w)
        seg = self.x[a - 1:b]
        zc = np.nonzero((seg[:-1] < 0) & (seg[1:] >= 0))[0]
        return int(a + zc[np.argmin(np.abs(zc + a - f))]) if len(zc) else f

    def on_drag(self, ev):
        if not self.drag:
            return
        z, f = self.z, self.snap(max(0, min(len(self.x), self.px2f(ev.x))))
        gap = int(self.sr * 0.002)
        if self.drag == 'start':
            f = min(f, (z['loop_start'] if z['loop'] != 'off' else z['end']) - gap)
        elif self.drag == 'loop_start':
            f = max(z['start'] + 1, min(f, z['end'] - gap))
        else:
            f = max(f, (z['loop_start'] if z['loop'] != 'off' else z['start']) + gap)
        z[self.drag] = max(0, min(len(self.x), f))
        if z['loop_start'] < z['start']:
            z['loop_start'] = z['start']
        self.redraw()
        self.app.show_zone_numbers()

    def on_release(self, ev):
        if self.drag:
            self.drag = None
            self.app.zone_changed()

    def on_wheel(self, ev):
        if self.x is None:
            return
        span = self.v1 - self.v0
        if ev.state & 0x1:  # shift: pan
            d = int(span * 0.15) * (-1 if ev.delta > 0 else 1)
            d = max(-self.v0, min(len(self.x) - self.v1, d))
            self.v0 += d; self.v1 += d
        else:
            c = self.px2f(ev.x)
            k = 0.8 if ev.delta > 0 else 1.25
            ns = max(64, min(len(self.x), int(span * k)))
            self.v0 = max(0, min(len(self.x) - ns, int(c - (c - self.v0) * ns / span)))
            self.v1 = self.v0 + ns
        self.redraw()


# ============================================================ keyboard
class KeyView(tk.Canvas):
    def __init__(self, master, app):
        super().__init__(master, height=104, bg=PANEL, highlightthickness=0)
        self.app = app
        self.lit = None
        self.bind('<Configure>', lambda e: self.redraw())
        self.bind('<ButtonPress-1>', self.on_click)
        self.hit = []

    def light(self, note):
        self.lit = note
        self.redraw()
        self.after(450, lambda: (setattr(self, 'lit', None), self.redraw()) if self.lit == note else None)

    @staticmethod
    def is_black(n):
        return n % 12 in (1, 3, 6, 8, 10)

    def geom(self):
        W = self.winfo_width()
        whites = [n for n in range(128) if not self.is_black(n)]
        ww = W / len(whites)
        wx = {n: i * ww for i, n in enumerate(whites)}
        g = {}
        for n in range(128):
            if self.is_black(n):
                x = wx[n - 1] + ww * 0.65
                g[n] = (x, x + ww * 0.7, True)
            else:
                g[n] = (wx[n], wx[n] + ww, False)
        return g

    def redraw(self):
        self.delete('all')
        g = self.geom()
        top, H = 26, self.winfo_height()
        W = self.winfo_width()
        self.hit = []
        self.create_rectangle(0, top - 3, W, top, fill=RED, outline='')  # felt strip (Roland red, as on the cards)
        for n in range(128):
            x0, x1, blk = g[n]
            if not blk:
                lit = n == self.lit
                self.create_rectangle(x0, top, x1, H, fill=AMBER if lit else '#ecebe5', outline='#6d6f73')
                self.create_rectangle(x0 + 1, H - 6, x1 - 1, H - 1, fill='#d8a02a' if lit else '#cfcec6', outline='')
                if n % 12 == 0:
                    self.create_text((x0 + x1) / 2, H - 13, text=B.note_name(n), font=('Segoe UI', 6), fill='#6d6f73')
        for n in range(128):
            x0, x1, blk = g[n]
            if blk:
                bh = top + (H - top) * 0.62
                self.create_rectangle(x0, top, x1, bh, fill=AMBER if n == self.lit else '#1b1c1e', outline='#0d0d0e')
                self.create_line(x0 + 2, bh - 3, x1 - 2, bh - 3, fill='#3d3f44')
        tone = self.app.cur_tone()
        if tone:
            lo = 0
            zsel = self.app.cur_zone()
            for i, z in enumerate(sorted(tone['zones'], key=lambda z: z['hi'])):
                hi = z['hi']
                x0, x1 = g[lo][0], g[hi][1]
                col = ZONE_COLS[i % len(ZONE_COLS)]
                sel = z is zsel
                self.create_rectangle(x0 + 1, 3, x1 - 1, 19, fill=col, outline=AMBER if sel else PANEL, width=2 if sel else 1)
                self.create_text((x0 + x1) / 2, 11, text=B.note_name(z['root']), fill='white', font=('Segoe UI', 7, 'bold'))
                rx0, rx1, _ = g[z['root']]
                self.create_oval((rx0 + rx1) / 2 - 3, H - 26, (rx0 + rx1) / 2 + 3, H - 20, fill=col, outline='')
                lo = hi + 1

    def on_click(self, ev):
        g = self.geom()
        top, H = 26, self.winfo_height()
        note = None
        for n in range(128):  # black keys first (they sit on top)
            x0, x1, blk = g[n]
            if blk and x0 <= ev.x <= x1 and ev.y <= top + (H - top) * 0.62:
                note = n
        if note is None:
            for n in range(128):
                x0, x1, blk = g[n]
                if not blk and x0 <= ev.x < x1:
                    note = n
        if note is not None:
            self.light(note)
            self.app.play_note(note)


# ============================================================ app
class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry('1320x880')
        self.minsize(1100, 740)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('U110RomHexStudio')  # own taskbar icon
        except Exception:
            pass
        try:
            self.iconbitmap(default=res('u110.ico'))
        except tk.TclError:
            pass
        apply_theme(self)
        dark_titlebar(self)
        self.cache = B.AudioCache()
        self.proj, self.path, self.dirty = new_project(), None, False
        self.k = 0
        self.prev_cache = {}
        self._loading = False
        self.q = queue.Queue()
        self.snap = tk.BooleanVar(value=True)
        self.hold = tk.DoubleVar(value=3.0)
        self.build_menu()
        self.build_ui()
        self.refresh_all()
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.after(100, self.poll)

    # ---------------------------------------------------------------- layout
    def build_menu(self):
        mb = tk.Menu(self)
        f = tk.Menu(mb, tearoff=0)
        f.add_command(label='New', accelerator='Ctrl+N', command=self.cmd_new)
        f.add_command(label='Open Project...', accelerator='Ctrl+O', command=self.cmd_open)
        f.add_command(label='Save', accelerator='Ctrl+S', command=self.cmd_save)
        f.add_command(label='Save As...', command=lambda: self.cmd_save(True))
        f.add_separator()
        f.add_command(label='Import Roland / own card .bin...', command=self.cmd_import)
        f.add_separator()
        f.add_command(label='Build Card .bin...', accelerator='Ctrl+B', command=self.cmd_build)
        f.add_command(label='Build and Burn to Programmer', accelerator='Ctrl+Shift+B', command=self.cmd_build_burn)
        f.add_command(label='Send .bin to Programmer...', command=self.cmd_burn_file)
        f.add_separator()
        f.add_command(label='Exit', command=self.on_close)
        mb.add_cascade(label='File', menu=f)
        t = tk.Menu(mb, tearoff=0)
        t.add_command(label='Add Tone', command=self.tone_add)
        t.add_command(label='Wavetable...', accelerator='Ctrl+W', command=self.wavetable)
        t.add_command(label='Duplicate Tone', command=self.tone_dup)
        t.add_command(label='Delete Tone', command=self.tone_del)
        t.add_command(label='Move Up', command=lambda: self.tone_move(-1))
        t.add_command(label='Move Down', command=lambda: self.tone_move(1))
        mb.add_cascade(label='Tone', menu=t)
        z = tk.Menu(mb, tearoff=0)
        z.add_command(label='Add WAVs...', accelerator='Ctrl+I', command=self.zone_add)
        z.add_command(label='Remove Zone', accelerator='Del', command=self.zone_del)
        z.add_command(label='Auto-map Key Ranges', command=self.zone_automap)
        z.add_command(label='Auto Loop', command=self.zone_autoloop)
        mb.add_cascade(label='Zone', menu=z)
        h = tk.Menu(mb, tearoff=0)
        h.add_command(label='How it works', command=self.cmd_help)
        mb.add_cascade(label='Help', menu=h)
        self.config(menu=mb)
        for key, fn in (('<Control-n>', self.cmd_new), ('<Control-o>', self.cmd_open), ('<Control-s>', self.cmd_save),
                        ('<Control-b>', self.cmd_build), ('<Control-i>', self.zone_add),
                        ('<Control-w>', self.wavetable), ('<Control-B>', self.cmd_build_burn)):
            self.bind(key, lambda e, fn=fn: fn())

    def build_ui(self):
        # header: name plate, LCD, memory LEDs, BUILD key -- like the unit's front panel
        head = ttk.Frame(self, padding=(12, 10, 12, 4))
        head.pack(fill='x')
        plate = ttk.Frame(head)
        plate.pack(side='left', padx=(0, 16))
        ttk.Label(plate, text='U-110', style='Title.TLabel').pack(anchor='w')
        ttk.Label(plate, text='ROMHEX STUDIO', style='Sub.TLabel').pack(anchor='w')
        self.lcd = LCD(head, cols=40)
        self.lcd.pack(side='left')
        mf = ttk.Frame(head)
        mf.pack(side='left', padx=16)
        ttk.Label(mf, text='MEMORY', style='Silk.TLabel').pack(anchor='w')
        self.meter = LEDMeter(mf)
        self.meter.pack(anchor='w', pady=(2, 2))
        self.v_mem = tk.StringVar()
        ttk.Label(mf, textvariable=self.v_mem, style='Dim.TLabel').pack(anchor='w')
        bf0 = ttk.Frame(head)
        bf0.pack(side='right')
        ttk.Label(bf0, text='WRITE CARD', style='Silk.TLabel').pack()
        ttk.Button(bf0, text='BUILD', style='Build.TButton', command=self.cmd_build).pack(pady=(2, 0))

        top = ttk.Frame(self, padding=(12, 2, 12, 6))
        top.pack(fill='x')
        ttk.Label(top, text='CARD NAME', style='Silk.TLabel').pack(side='left')
        self.v_card = tk.StringVar()
        vcmd = (self.register(lambda s: len(s) <= 16), '%P')
        e = ttk.Entry(top, textvariable=self.v_card, width=18, validate='key', validatecommand=vcmd)
        e.pack(side='left', padx=(6, 16))
        self.v_card.trace_add('write', lambda *a: (self.set_proj('card_name', self.v_card.get()), self.update_lcd()))
        ttk.Label(top, text='CARD #', style='Silk.TLabel').pack(side='left')
        ttk.Label(top, text='13').pack(side='left', padx=(6, 16))
        ttk.Label(top, text='SAMPLE RATE', style='Silk.TLabel').pack(side='left')
        self.rate_vals = ['Auto (best that fits)'] + ['%d Hz%s' % (B.rate_for(k), '  (native)' if k == 0 else '  (-%d st)' % k) for k in range(25)]
        self.v_rate = tk.StringVar(value=self.rate_vals[0])
        cb = ttk.Combobox(top, textvariable=self.v_rate, values=self.rate_vals, width=20, state='readonly')
        cb.pack(side='left', padx=(6, 16))
        cb.bind('<<ComboboxSelected>>', lambda e: self.set_proj('rate', 'auto' if cb.current() == 0 else cb.current() - 1))

        main = ttk.PanedWindow(self, orient='horizontal')
        main.pack(fill='both', expand=True, padx=8, pady=(0, 4))

        # tones
        lf = ttk.Labelframe(main, text=' TONES ', padding=6)
        main.add(lf, weight=1)
        self.tt = ttk.Treeview(lf, columns=('n', 'name', 'z'), show='headings', selectmode='browse', height=20)
        for c, t, w in (('n', '#', 34), ('name', 'Name', 120), ('z', 'Zones', 50)):
            self.tt.heading(c, text=t); self.tt.column(c, width=w, anchor='w' if c == 'name' else 'center')
        self.tt.pack(fill='both', expand=True)
        self.tt.bind('<<TreeviewSelect>>', lambda e: self.on_tone_select())
        bf = ttk.Frame(lf); bf.pack(fill='x', pady=(4, 0))
        for txt, fn in (('+ Tone', self.tone_add), ('Dup', self.tone_dup), ('Delete', self.tone_del),
                        ('▲', lambda: self.tone_move(-1)), ('▼', lambda: self.tone_move(1))):
            ttk.Button(bf, text=txt, width=6 if len(txt) > 1 else 3, command=fn).pack(side='left', padx=1)
        nf = ttk.Frame(lf); nf.pack(fill='x', pady=(6, 0))
        ttk.Label(nf, text='TONE NAME', style='Silk.TLabel').pack(side='left')
        self.v_tname = tk.StringVar()
        vcmd10 = (self.register(lambda s: len(s) <= 10), '%P')
        ttk.Entry(nf, textvariable=self.v_tname, width=12, validate='key', validatecommand=vcmd10).pack(side='left', padx=4)
        self.v_tname.trace_add('write', lambda *a: self.on_tname())
        cf = ttk.Frame(lf); cf.pack(fill='x', pady=(8, 0))
        ttk.Label(cf, text='CHARACTER', style='Silk.TLabel').pack(side='left')
        self.char_keys = list(B.CHARACTERS)
        self.v_char = tk.StringVar(value=B.CHARACTERS['studio'][0])
        cc = ttk.Combobox(cf, textvariable=self.v_char, values=[B.CHARACTERS[k][0] for k in self.char_keys], width=10, state='readonly')
        cc.pack(side='left', padx=4)
        cc.bind('<<ComboboxSelected>>', lambda e: self.on_char())
        af = ttk.Frame(lf); af.pack(fill='x', pady=(4, 0))
        ttk.Label(af, text='AMOUNT', style='Silk.TLabel').pack(side='left')
        self.v_amt = tk.IntVar(value=50)
        ttk.Scale(af, from_=0, to=100, variable=self.v_amt, command=lambda v: None).pack(side='left', fill='x', expand=True, padx=4)
        self.v_amt.trace_add('write', lambda *a: self.after_idle(self.on_char))
        self.v_chardesc = tk.StringVar()
        ttk.Label(lf, textvariable=self.v_chardesc, style='Dim.TLabel', wraplength=260).pack(anchor='w', pady=(2, 0))
        self.v_tcount = tk.StringVar()
        ttk.Label(lf, textvariable=self.v_tcount, style='Dim.TLabel').pack(anchor='w', pady=(4, 0))

        # right side
        right = ttk.Frame(main)
        main.add(right, weight=4)
        zf = ttk.Labelframe(right, text=' ZONES  (max 12 per tone) ', padding=6)
        zf.pack(fill='x')
        self.zt = ttk.Treeview(zf, columns=('file', 'root', 'keys', 'loop', 'len'), show='headings', selectmode='browse', height=6)
        for c, t, w in (('file', 'File', 300), ('root', 'Root', 60), ('keys', 'Keys', 90), ('loop', 'Loop', 80), ('len', 'Length', 70)):
            self.zt.heading(c, text=t); self.zt.column(c, width=w, anchor='w' if c == 'file' else 'center')
        self.zt.pack(fill='x')
        self.zt.bind('<<TreeviewSelect>>', lambda e: self.on_zone_select())
        self.zt.bind('<Delete>', lambda e: self.zone_del())
        zb = ttk.Frame(zf); zb.pack(fill='x', pady=(4, 0))
        for txt, fn in (('Add WAVs...', self.zone_add), ('Remove', self.zone_del), ('Auto-map keys', self.zone_automap),
                        ('Auto loop', self.zone_autoloop)):
            ttk.Button(zb, text=txt, command=fn).pack(side='left', padx=1)

        ed = ttk.Frame(zf); ed.pack(fill='x', pady=(6, 0))
        self.v_root, self.v_hi, self.v_xf = tk.IntVar(), tk.IntVar(), tk.IntVar()
        self.v_loop = tk.StringVar()
        ttk.Label(ed, text='ROOT', style='Silk.TLabel').pack(side='left')
        ttk.Spinbox(ed, from_=0, to=127, textvariable=self.v_root, width=5, command=self.on_edit).pack(side='left', padx=(2, 0))
        self.v_rootname = tk.StringVar()
        ttk.Label(ed, textvariable=self.v_rootname, width=5).pack(side='left', padx=(2, 10))
        ttk.Label(ed, text='TOP KEY', style='Silk.TLabel').pack(side='left')
        ttk.Spinbox(ed, from_=0, to=127, textvariable=self.v_hi, width=5, command=self.on_edit).pack(side='left', padx=(2, 0))
        self.v_hiname = tk.StringVar()
        ttk.Label(ed, textvariable=self.v_hiname, width=5).pack(side='left', padx=(2, 10))
        ttk.Label(ed, text='LOOP', style='Silk.TLabel').pack(side='left')
        lc = ttk.Combobox(ed, textvariable=self.v_loop, values=['off', 'loop', 'pingpong', 'mode3'], width=9, state='readonly')
        lc.pack(side='left', padx=(2, 10))
        lc.bind('<<ComboboxSelected>>', lambda e: self.on_edit())
        ttk.Label(ed, text='CROSSFADE MS', style='Silk.TLabel').pack(side='left')
        ttk.Spinbox(ed, from_=0, to=500, textvariable=self.v_xf, width=5, command=self.on_edit).pack(side='left', padx=(2, 10))
        ttk.Checkbutton(ed, text='Snap to zero crossing', variable=self.snap).pack(side='left', padx=(0, 10))
        for v in (self.v_root, self.v_hi, self.v_xf):
            v.trace_add('write', lambda *a: self.after_idle(self.on_edit))
        self.v_nums = tk.StringVar()
        ttk.Label(zf, textvariable=self.v_nums, style='Dim.TLabel').pack(anchor='w', pady=(4, 0))

        wf = ttk.Labelframe(right, text=' WAVE   drag S / L / E  ·  wheel zoom  ·  shift+wheel pan  ·  double-click = start / end  ·  right-click fit ', padding=6)
        wf.pack(fill='both', expand=True, pady=(6, 0))
        self.wave = WaveView(wf, self)
        self.wave.pack(fill='both', expand=True)

        pf = ttk.Frame(right); pf.pack(fill='x', pady=(6, 2))
        ttk.Button(pf, text='▶ Original', command=self.play_original).pack(side='left', padx=1)
        ttk.Button(pf, text='▶ As U-110 (root)', command=lambda: self.play_note(None)).pack(side='left', padx=1)
        ttk.Button(pf, text='■ Stop', command=self.stop).pack(side='left', padx=1)
        ttk.Label(pf, text='   PREVIEW s', style='Silk.TLabel').pack(side='left')
        ttk.Spinbox(pf, from_=0.5, to=20, increment=0.5, textvariable=self.hold, width=5).pack(side='left', padx=4)
        ttk.Label(pf, text='   click a key to hear it exactly as the U-110 plays it', style='Dim.TLabel').pack(side='left')
        self.keys = KeyView(right, self)
        self.keys.pack(fill='x', pady=(2, 0))

        sb = ttk.Frame(self, padding=(10, 3), style='Status.TFrame'); sb.pack(fill='x', side='bottom')
        self.v_status = tk.StringVar(value='Ready')
        ttk.Label(sb, textvariable=self.v_status, style='Status.TLabel').pack(side='left')
        self.prog = ttk.Progressbar(sb, length=180, maximum=100)
        self.prog.pack(side='right')

    # ---------------------------------------------------------------- helpers
    def status(self, s):
        self.v_status.set(s)

    def mark(self):
        self.dirty = True
        self.title('%s - %s%s' % (APP, os.path.basename(self.path) if self.path else 'untitled', ' *'))

    def set_proj(self, key, val):
        if self._loading:
            return
        self.proj[key] = val
        self.mark()
        if key == 'rate':
            self.update_memory()

    def cur_tone(self):
        s = self.tt.selection()
        return self.proj['tones'][int(s[0])] if s else None

    def cur_zone(self):
        t, s = self.cur_tone(), self.zt.selection()
        return t['zones'][int(s[0])] if (t and s and int(s[0]) < len(t['zones'])) else None

    def refresh_all(self, tone_i=None, zone_i=None):
        self._loading = True
        self.v_card.set(self.proj.get('card_name', ''))
        r = self.proj.get('rate', 'auto')
        self.v_rate.set(self.rate_vals[0 if r == 'auto' else int(r) + 1])
        self._loading = False
        self.tt.delete(*self.tt.get_children())
        for i, t in enumerate(self.proj['tones']):
            self.tt.insert('', 'end', iid=str(i), values=(i + 1, t['name'], len(t['zones'])))
        self.v_tcount.set('%d / %d tones' % (len(self.proj['tones']), B.MAX_TONES))
        if self.proj['tones']:
            ti = min(tone_i if tone_i is not None else 0, len(self.proj['tones']) - 1)
            self.tt.selection_set(str(ti)); self.tt.see(str(ti))
            self.on_tone_select(zone_i)
        else:
            self.on_tone_select()
        self.title('%s - %s%s' % (APP, os.path.basename(self.path) if self.path else 'untitled', ' *' if self.dirty else ''))
        self.update_memory()

    def on_tone_select(self, zone_i=None):
        t = self.cur_tone()
        self._loading = True
        self.v_tname.set(t['name'] if t else '')
        ck = t.get('character', 'studio') if t else 'studio'
        self.v_char.set(B.CHARACTERS[ck][0]); self.v_amt.set(int(t.get('amount', 50)) if t else 50)
        self.v_chardesc.set(B.CHARACTERS[ck][1])
        self._loading = False
        self.refresh_zones(zone_i)

    def refresh_zones(self, zone_i=None):
        self.zt.delete(*self.zt.get_children())
        t = self.cur_tone()
        if t:
            t['zones'].sort(key=lambda z: z['hi'])
            lo = 0
            for i, z in enumerate(t['zones']):
                x, sr = self.cache.get(z['path'])
                self.zt.insert('', 'end', iid=str(i), values=(
                    os.path.basename(z['path']), B.note_name(z['root']),
                    '%s-%s' % (B.note_name(lo), B.note_name(z['hi'])), z['loop'], '%.2fs' % ((z['end'] - z['start']) / sr)))
                lo = z['hi'] + 1
            if t['zones']:
                zi = min(zone_i if zone_i is not None else 0, len(t['zones']) - 1)
                self.zt.selection_set(str(zi))
        self.on_zone_select()

    def on_zone_select(self):
        z = self.cur_zone()
        self._loading = True
        if z:
            self.v_root.set(z['root']); self.v_hi.set(z['hi']); self.v_loop.set(z['loop']); self.v_xf.set(z.get('xfade_ms', 0))
        self._loading = False
        self.label_notes()
        self.wave.set_zone(z)
        self.show_zone_numbers()
        self.keys.redraw()
        self.update_lcd()

    def label_notes(self):
        try:
            self.v_rootname.set(B.note_name(self.v_root.get())); self.v_hiname.set(B.note_name(self.v_hi.get()))
        except (tk.TclError, ValueError):
            pass

    def show_zone_numbers(self):
        z = self.cur_zone()
        if not z:
            self.v_nums.set(''); return
        x, sr = self.cache.get(z['path'])
        s = 'start %.3fs   end %.3fs   length %.3fs   source %d Hz' % (z['start'] / sr, z['end'] / sr, (z['end'] - z['start']) / sr, sr)
        if z['loop'] != 'off':
            s += '   loop %.3fs (%.3fs long)' % (z['loop_start'] / sr, (z['end'] - z['loop_start']) / sr)
        self.v_nums.set(s)

    def on_edit(self):
        if self._loading:
            return
        z = self.cur_zone()
        if not z:
            return
        try:
            root, hi, xf = int(self.v_root.get()), int(self.v_hi.get()), int(self.v_xf.get())
        except (tk.TclError, ValueError):
            return
        root, hi = max(0, min(127, root)), max(0, min(127, hi))
        loop = self.v_loop.get() or 'off'
        if (root, hi, loop, xf) == (z['root'], z['hi'], z['loop'], z.get('xfade_ms', 0)):
            return
        if loop != 'off' and z['loop'] == 'off' and z['loop_start'] <= z['start']:
            z['loop_start'] = z['start'] + (z['end'] - z['start']) // 2
        z.update(root=root, hi=hi, loop=loop, xfade_ms=max(0, xf))
        self.label_notes()
        self.zone_changed(resort=True)

    def zone_changed(self, resort=False):
        self.mark()
        t, z = self.cur_tone(), self.cur_zone()
        if resort and t and z:
            t['zones'].sort(key=lambda q: q['hi'])
            self.refresh_zones(t['zones'].index(z))
        else:
            self.refresh_zone_row()
            self.wave.redraw()
            self.keys.redraw()
        self.update_memory()

    def refresh_zone_row(self):
        t = self.cur_tone()
        if not t:
            return
        lo = 0
        for i, z in enumerate(t['zones']):
            x, sr = self.cache.get(z['path'])
            self.zt.item(str(i), values=(os.path.basename(z['path']), B.note_name(z['root']),
                                         '%s-%s' % (B.note_name(lo), B.note_name(z['hi'])), z['loop'], '%.2fs' % ((z['end'] - z['start']) / sr)))
            lo = z['hi'] + 1

    def on_tname(self):
        t = self.cur_tone()
        if self._loading or not t:
            return
        t['name'] = self.v_tname.get()
        i = self.proj['tones'].index(t)
        self.tt.item(str(i), values=(i + 1, t['name'], len(t['zones'])))
        self.mark()
        self.update_lcd()

    def on_char(self):
        t = self.cur_tone()
        if self._loading or not t:
            return
        try:
            ck = self.char_keys[[B.CHARACTERS[k][0] for k in self.char_keys].index(self.v_char.get())]
            amt = int(float(self.v_amt.get()))
        except (ValueError, tk.TclError):
            return
        if (ck, amt) == (t.get('character', 'studio'), int(t.get('amount', 50))):
            return
        t['character'], t['amount'] = ck, amt
        self.v_chardesc.set(B.CHARACTERS[ck][1])
        self.mark()
        self.update_memory()

    def update_memory(self):
        try:
            k, used, fits = B.plan(self.proj, self.cache)
        except Exception as e:
            self.v_mem.set('error: %s' % e); return
        self.k, self.used, self.fits = k, used, fits
        cap = B.capacity()
        self.meter.set(min(1.0, used / cap), over=not fits)
        self.v_mem.set('%d / %d KB   %d Hz%s' % (used // 1024, cap // 1024, B.rate_for(k), '' if fits else '   TOO BIG'))
        self.update_lcd()

    def update_lcd(self):
        """row 1: card + memory, row 2: selected tone / zone (40 columns)"""
        used, cap = getattr(self, 'used', 0), B.capacity()
        name = (self.proj.get('card_name') or '').upper()[:16]
        pct = 'FULL!' if not getattr(self, 'fits', True) else '%3d%%' % min(100, round(100 * used / cap))
        l1 = '%-16s MEM %s %5dHZ' % (name, pct, round(B.rate_for(getattr(self, 'k', 0))))
        t, z = self.cur_tone(), self.cur_zone()
        if not self.proj['tones']:
            l2 = 'NO TONES - PRESS + TONE, THEN ADD WAVS'
        elif not t:
            l2 = '%d TONES' % len(self.proj['tones'])
        else:
            ti = self.proj['tones'].index(t) + 1
            if z:
                zi = t['zones'].index(z) + 1
                lp = {'off': '1SHOT', 'loop': 'LOOP', 'pingpong': 'PPONG', 'mode3': 'MODE3'}[z['loop']] + ' ' + B.CHARACTERS[t.get('character', 'studio')][0][:5]
                l2 = 'T%03d %-10s Z%02d/%02d %-4s %s' % (ti, t['name'].upper()[:10], zi, len(t['zones']), B.note_name(z['root']), lp)
            else:
                l2 = 'T%03d %-10s NO ZONES - ADD WAVS' % (ti, t['name'].upper()[:10])
        self.lcd.set(l1, l2)

    # ---------------------------------------------------------------- tones
    def tone_add(self, name=None, zones=None):
        if len(self.proj['tones']) >= B.MAX_TONES:
            messagebox.showwarning(APP, 'A card holds %d tones.' % B.MAX_TONES); return
        t = self.cur_tone()
        i = self.proj['tones'].index(t) + 1 if t else len(self.proj['tones'])
        self.proj['tones'].insert(i, dict(name=name or 'TONE %d' % (len(self.proj['tones']) + 1), zones=zones or []))
        self.mark(); self.refresh_all(i)
        return i

    def tone_dup(self):
        t = self.cur_tone()
        if t:
            import copy
            self.tone_add((t['name'][:8] + ' 2')[:10], copy.deepcopy(t['zones']))

    def tone_del(self):
        t = self.cur_tone()
        if t and messagebox.askyesno(APP, 'Delete tone "%s"?' % t['name']):
            i = self.proj['tones'].index(t)
            del self.proj['tones'][i]
            self.mark(); self.refresh_all(max(0, i - 1))

    def tone_move(self, d):
        t = self.cur_tone()
        if not t:
            return
        i = self.proj['tones'].index(t)
        j = i + d
        if 0 <= j < len(self.proj['tones']):
            L = self.proj['tones']; L[i], L[j] = L[j], L[i]
            self.mark(); self.refresh_all(j)

    def wave_dir(self):
        d = os.path.join(os.path.dirname(self.path), 'wavetables') if self.path else \
            os.path.join(os.path.expanduser('~'), 'Documents', 'U110 RomHex Studio', 'wavetables')
        os.makedirs(d, exist_ok=True)
        return d

    def wave_lib(self):
        """bundled AKWF library: {category: [(name, index)]}, waves array"""
        if not hasattr(self, '_wlib'):
            try:
                z = np.load(res(os.path.join('wavetables', 'akwf.npz')))
                cats = {}
                for i, (c, n) in enumerate(zip(z['cats'], z['names'])):
                    cats.setdefault(str(c), []).append((str(n), i))
                self._wlib = (cats, z['waves'])
            except Exception:
                self._wlib = ({}, None)
        return self._wlib

    def wavetable(self):
        """single-cycle waves -> looped wave tones, or one scan-morph tone through them"""
        w = tk.Toplevel(self); w.title('Wavetable'); w.configure(bg=PANEL); w.transient(self); w.resizable(False, False)
        try:
            dark_titlebar(w)
        except Exception:
            pass
        cats, waves = self.wave_lib()
        SHAPES = 'Built-in shapes'
        catnames = [SHAPES] + sorted(cats, key=lambda c: (not c[:4].isdigit(), c.lower()))
        items, picked = [], []                          # items: (label, kind, ref) of the browser; picked: same, ordered

        def cycle(it):
            _, k, r = it
            if k == 'shape':
                return WV.shape(r)
            if k == 'akwf':
                return waves[r].astype(np.float64) / 32767
            return WV.load_cycle(r)

        lbopt = dict(bg=RECESS, fg=TEXT, selectbackground=AMBER, selectforeground='#111', highlightthickness=0,
                     relief='flat', exportselection=False, width=26, height=16)
        f = ttk.Frame(w, padding=10); f.pack(fill='both')
        ttk.Label(f, text='LIBRARY  (click = listen, double-click = add)', style='Silk.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(f, text='SELECTED  (scan uses this order)', style='Silk.TLabel').grid(row=0, column=2, sticky='w')
        cat = tk.StringVar(value=SHAPES)
        cb = ttk.Combobox(f, textvariable=cat, values=catnames, state='readonly', width=24)
        cb.grid(row=1, column=0, sticky='w', pady=(4, 2))
        lb = tk.Listbox(f, selectmode='extended', **lbopt); lb.grid(row=2, column=0, sticky='nsew')
        sb = tk.Listbox(f, selectmode='browse', **lbopt); sb.grid(row=2, column=2, sticky='nsew', rowspan=1)

        def fill(*_):
            items.clear(); lb.delete(0, 'end')
            c = cat.get()
            if c == SHAPES:
                items.extend((n, 'shape', n) for n in WV.SHAPES)
            else:
                items.extend((n, 'akwf', i) for n, i in cats.get(c, []))
            for it in items:
                lb.insert('end', it[0])

        def refill_sel():
            sb.delete(0, 'end')
            for it in picked:
                sb.insert('end', it[0])
            upd()

        def add(*_):
            for i in lb.curselection():
                picked.append(items[i])
            refill_sel()

        def add_files():
            fs = filedialog.askopenfilenames(parent=w, title='Single-cycle WAVs', filetypes=[('Audio', '*.wav *.aif *.aiff *.flac')])
            picked.extend((os.path.splitext(os.path.basename(x))[0], 'file', x) for x in fs)
            refill_sel()

        def remove():
            for i in reversed(sb.curselection()):
                del picked[i]
            refill_sel()

        def move(d):
            sel = sb.curselection()
            if sel and 0 <= sel[0] + d < len(picked):
                i = sel[0]; picked[i], picked[i + d] = picked[i + d], picked[i]; refill_sel(); sb.selection_set(i + d)

        def listen(*_):
            sel = lb.curselection()
            if sel:
                c = cycle(items[sel[-1]])
                H = WV._harmonics(c)
                n, k = WV._fit(48)
                y = WV._norm(WV._render(H, n, k, WV.freq(48))[0])
                reps = int(0.6 * WV.SR / n) + 1
                y = np.tile(y, reps) * np.minimum(1, np.linspace(8, 0, n * reps))
                self._play(y * 0.7, WV.SR)

        cb.bind('<<ComboboxSelected>>', fill); lb.bind('<<ListboxSelect>>', listen); lb.bind('<Double-Button-1>', add)
        mid = ttk.Frame(f); mid.grid(row=2, column=1, padx=8)
        ttk.Button(mid, text='Add >', command=add).pack(fill='x')
        ttk.Button(mid, text='< Remove', command=remove).pack(fill='x', pady=(4, 12))
        ttk.Button(mid, text='Up', command=lambda: move(-1)).pack(fill='x')
        ttk.Button(mid, text='Down', command=lambda: move(1)).pack(fill='x', pady=(2, 12))
        ttk.Button(mid, text='WAV files...', command=add_files).pack(fill='x')

        mode = tk.StringVar(value='tones'); secs = tk.StringVar(value='0.75'); lp = tk.StringVar(value='hold last wave')
        name = tk.StringVar(value='')
        mf = ttk.Labelframe(f, text=' MODE ', padding=6); mf.grid(row=3, column=0, columnspan=3, sticky='ew', pady=(8, 0))
        ttk.Radiobutton(mf, text='One looped tone per selected wave', variable=mode, value='tones').grid(row=0, column=0, columnspan=4, sticky='w')
        ttk.Radiobutton(mf, text='Scan morph: one tone sweeping through the selected waves', variable=mode, value='scan').grid(row=1, column=0, columnspan=4, sticky='w')
        ttk.Label(mf, text='sweep s').grid(row=2, column=0, sticky='w', padx=(18, 4))
        ttk.Spinbox(mf, from_=0.2, to=2.0, increment=0.05, textvariable=secs, width=6).grid(row=2, column=1, sticky='w')
        ttk.Combobox(mf, textvariable=lp, values=['hold last wave', 'ping-pong sweep'], state='readonly', width=15).grid(row=2, column=2, padx=6)
        steps = tk.StringVar(value='smooth'); zn = tk.StringVar(value='3  C1-B8'); lo = tk.BooleanVar(value=False)
        ttk.Label(mf, text='steps').grid(row=3, column=0, sticky='w', padx=(18, 4), pady=(4, 0))
        ttk.Combobox(mf, textvariable=steps, values=['smooth', '2', '3', '4', '6', '8', '12', '16', '24', '32'], state='readonly', width=7).grid(row=3, column=1, sticky='w', pady=(4, 0))
        ttk.Label(mf, text='few steps = glitch columns', style='Dim.TLabel').grid(row=3, column=2, columnspan=2, sticky='w', padx=6, pady=(4, 0))
        ttk.Label(mf, text='zones').grid(row=4, column=0, sticky='w', padx=(18, 4), pady=(4, 0))
        ttk.Combobox(mf, textvariable=zn, values=['3  C1-B8', '2  C1-B5', '1  up to B4'], state='readonly', width=11).grid(row=4, column=1, columnspan=2, sticky='w', pady=(4, 0))
        ttk.Checkbutton(mf, text='lo-rate 16 kHz (half memory, grittier)', variable=lo).grid(row=5, column=0, columnspan=4, sticky='w', padx=(18, 0), pady=(4, 0))
        nf = ttk.Frame(f); nf.grid(row=4, column=0, columnspan=3, sticky='w', pady=(8, 0))
        ttk.Label(nf, text='name').pack(side='left')
        ttk.Entry(nf, textvariable=name, width=12).pack(side='left', padx=6)
        info = ttk.Label(f, text='', style='Dim.TLabel'); info.grid(row=5, column=0, columnspan=3, sticky='w', pady=(6, 0))

        def upd(*_):
            n = len(picked)
            try:
                sv = float(secs.get())
            except ValueError:
                sv = 0.75
            if mode.get() == 'tones':
                info.config(text='%d tone(s), ~4 KB each (4 zones C1-C7, band-limited)' % n)
            else:
                kb = WV.scan_kb(sv, int(zn.get()[0]), lo.get())
                info.config(text='1 tone sweeping %d waves: %d KB = %d%% of the card' % (n, kb, round(kb * 1024 * 100 / 507891)))
        for v in (mode, secs, zn, lo):
            v.trace_add('write', upd)

        def safe(t):
            return ''.join(ch for ch in t if ch.isalnum() or ch in '_-')[:24] or 'wave'

        def make():
            if not picked:
                messagebox.showinfo(APP, 'Add at least one wave to SELECTED.', parent=w); return
            scan = mode.get() == 'scan'
            if scan and len(picked) < 2:
                messagebox.showinfo(APP, 'Scan morph needs 2 or more waves.', parent=w); return
            if not scan and len(self.proj['tones']) + len(picked) > B.MAX_TONES:
                messagebox.showwarning(APP, 'A card holds %d tones.' % B.MAX_TONES, parent=w); return
            try:
                cyc = [cycle(it) for it in picked]
                out = self.wave_dir()
                nm = name.get().strip().upper()
                if scan:
                    self.tone_add((nm or 'SCAN ' + picked[0][0].upper())[:10],
                                  WV.scan_tone(cyc, out, 'scan_' + '_'.join(safe(it[0])[:6] for it in picked)[:40],
                                               min(2.0, max(0.2, float(secs.get()))),
                                               'last' if lp.get().startswith('hold') else 'pingpong',
                                               zones=int(zn.get()[0]), steps=0 if steps.get() == 'smooth' else int(steps.get()),
                                               lo_rate=lo.get()))
                else:
                    for it, c in zip(picked, cyc):
                        t = nm if nm and len(picked) == 1 else ('WT ' + it[0].upper())
                        self.tone_add(t[:10], WV.wave_tone(c, out, 'wt_' + safe(it[0])))
            except Exception as e:
                messagebox.showerror(APP, 'Wavetable failed:\n%s' % e, parent=w); return
            self.status('Wave files written to %s' % out)
            w.destroy()

        bb = ttk.Frame(f); bb.grid(row=6, column=0, columnspan=3, sticky='e', pady=(10, 0))
        ttk.Button(bb, text='Cancel', command=w.destroy).pack(side='right')
        ttk.Button(bb, text='Create', command=make).pack(side='right', padx=6)
        fill(); upd()
        w.grab_set()
        w._t = dict(cat=cat, fill=fill, lb=lb, add=add, mode=mode, make=make, picked=picked, steps=steps, zn=zn, lo=lo, secs=secs, info=info)   # for the self-test
        return w

    # ---------------------------------------------------------------- zones
    def zone_add(self):
        files = filedialog.askopenfilenames(title='Add WAV files', filetypes=[('Audio', '*.wav *.aif *.aiff *.flac'), ('All', '*.*')])
        if not files:
            return
        files = list(files)
        as_tones = False
        if len(files) > 1:
            r = messagebox.askyesnocancel(APP, '%d files.\n\nYes = one multisampled tone (key zones)\nNo = one tone per file (drums, FX)' % len(files))
            if r is None:
                return
            as_tones = not r
        try:
            zones = [B.new_zone(f, self.cache) for f in files]
        except Exception as e:
            messagebox.showerror(APP, 'Could not read file:\n%s' % e); return
        if as_tones:
            for f, z in zip(files, zones):
                z['hi'] = 127
                self.tone_add(os.path.splitext(os.path.basename(f))[0][:10].upper(), [z])
            return
        t = self.cur_tone()
        if t is None:
            self.tone_add(os.path.splitext(os.path.basename(files[0]))[0][:10].upper()); t = self.cur_tone()
        if len(t['zones']) + len(zones) > B.MAX_ZONES:
            messagebox.showwarning(APP, 'A tone holds %d zones; this would make %d.' % (B.MAX_ZONES, len(t['zones']) + len(zones))); return
        t['zones'] += zones
        B.auto_map(t['zones'])
        self.mark()
        self.refresh_all(self.proj['tones'].index(t), t['zones'].index(zones[0]))

    def zone_del(self):
        t, z = self.cur_tone(), self.cur_zone()
        if z:
            i = t['zones'].index(z)
            t['zones'].remove(z)
            if t['zones']:
                t['zones'][-1]['hi'] = 127
            self.mark(); self.refresh_all(self.proj['tones'].index(t), max(0, i - 1))

    def zone_automap(self):
        t = self.cur_tone()
        if t and t['zones']:
            B.auto_map(t['zones']); self.mark(); self.refresh_all(self.proj['tones'].index(t))

    def zone_autoloop(self):
        z = self.cur_zone()
        if z:
            if B.auto_loop(z, self.cache):
                self.status('Auto loop: %.3fs long, %d ms crossfade' % ((z['end'] - z['loop_start']) / self.cache.get(z['path'])[1], z['xfade_ms']))
                self.on_zone_select(); self.zone_changed()
            else:
                self.status('Auto loop: no good loop found (sample too short?)')

    # ---------------------------------------------------------------- audio preview
    def stop(self):
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def play_original(self):
        z = self.cur_zone()
        if not z:
            return
        x, sr = self.cache.get(z['path'])
        seg = x[z['start']:z['end']]
        ls = z['loop_start'] - z['start'] if z['loop'] != 'off' else None
        out = simulate(seg, ls, z['loop'], 1.0, self.hold.get() * 32000 / sr)
        self._play(out, sr)

    def play_note(self, note):
        t = self.cur_tone()
        if not t or not t['zones']:
            return
        z = self.cur_zone() if note is None else next((q for q in sorted(t['zones'], key=lambda q: q['hi']) if note <= q['hi']), t['zones'][-1])
        if note is None:
            note = z['root']
        elif z is not self.cur_zone():
            self.zt.selection_set(str(t['zones'].index(z)))
        self.status('Rendering %s as the U-110 plays it...' % B.note_name(note))
        z['char'], z['amt'] = t.get('character', 'studio'), int(t.get('amount', 50))
        threading.Thread(target=self._preview_worker, args=(z, note, self.k, self.hold.get()), daemon=True).start()

    def _preview_worker(self, z, note, k, hold):
        try:
            kz = B.zone_k(z, self.cache, k)
            key = (B.akey(z), kz)
            if key not in self.prev_cache:
                y, ls = B.render_zone(z, self.cache, kz)
                enc = B.encode_zone(y, ls, z['loop'], B.PEAK / (np.max(np.abs(y)) or 1), hq=z.get('char') == 'crystal')
                self.prev_cache[key] = (UC.decode(enc) / 2048.0, (ls + B.LEAD) if ls is not None else None)
            d, ls = self.prev_cache[key]
            step = 2 ** ((note - (z['root'] + kz)) / 12)
            out = simulate(d, ls, z['loop'], step, hold)
            self.q.put(('play', out, 32000, 'Playing %s  (zone root %s, stored at %d Hz)' % (B.note_name(note), B.note_name(z['root']), B.rate_for(kz))))
        except Exception as e:
            self.q.put(('status', 'Preview failed: %s' % e))

    def _play(self, out, sr):
        try:
            import sounddevice as sd
            sd.stop()
            sd.play((np.asarray(out) * 0.8).astype(np.float32), int(sr))
        except Exception as e:
            self.status('Audio output failed: %s' % e)

    # ---------------------------------------------------------------- files
    def confirm_discard(self):
        if not self.dirty:
            return True
        r = messagebox.askyesnocancel(APP, 'Save changes to the current project?')
        if r is None:
            return False
        return self.cmd_save() if r else True

    def cmd_new(self):
        if self.confirm_discard():
            self.proj, self.path, self.dirty = new_project(), None, False
            self.refresh_all()

    def cmd_open(self):
        if not self.confirm_discard():
            return
        p = filedialog.askopenfilename(filetypes=[('U-110 project', '*' + EXT)])
        if p:
            try:
                self.proj, self.path, self.dirty = B.load_project(p), p, False
            except Exception as e:
                messagebox.showerror(APP, 'Could not open:\n%s' % e); return
            self.refresh_all()

    def cmd_save(self, as_=False):
        p = self.path
        if as_ or not p:
            p = filedialog.asksaveasfilename(defaultextension=EXT, filetypes=[('U-110 project', '*' + EXT)],
                                             initialfile=(self.proj.get('card_name') or 'card').strip() + EXT)
            if not p:
                return False
        B.save_project(self.proj, p)
        self.path, self.dirty = p, False
        self.refresh_all(*self._sel())
        self.status('Saved %s' % p)
        return True

    def _sel(self):
        t, z = self.cur_tone(), self.cur_zone()
        return (self.proj['tones'].index(t) if t else None, t['zones'].index(z) if (t and z) else None)

    def cmd_import(self):
        if not self.confirm_discard():
            return
        p = filedialog.askopenfilename(title='Import card image', filetypes=[('Card image', '*.bin *.BIN'), ('All', '*.*')])
        if not p:
            return
        out = os.path.splitext(p)[0] + '_wavs'
        try:
            proj, order = B.import_card(p, out)
        except Exception as e:
            messagebox.showerror(APP, 'Import failed:\n%s' % e); return
        self.proj, self.path, self.dirty = proj, None, True
        self.refresh_all()
        self.status('Imported %d tones (%s order); samples extracted to %s' % (len(proj['tones']), order, out))

    def cmd_build(self):
        if not any(t['zones'] for t in self.proj['tones']):
            messagebox.showinfo(APP, 'Add some tones with WAVs first.'); return
        name = (self.proj.get('card_name') or 'card').strip().replace(' ', '_')
        p = filedialog.asksaveasfilename(title='Save burn-ready card image', defaultextension='.bin',
                                         initialfile=name + '_BURN.bin', filetypes=[('Card image', '*.bin')])
        if not p:
            return
        self.status('Building...')
        self.prog['value'] = 0
        threading.Thread(target=self._build_worker, args=(p,), daemon=True).start()

    def _build_worker(self, p):
        try:
            conn, card, rep = B.build(self.proj, self.cache, progress=lambda i, n: self.q.put(('prog', 100 * i / n)))
            with open(p, 'wb') as f:
                f.write(conn)
            with open(os.path.splitext(p)[0] + '_report.txt', 'w') as f:
                f.write('\n'.join(rep) + '\n')
            self.q.put(('built', p, rep))
        except Exception as e:
            traceback.print_exc()
            self.q.put(('error', 'Build failed:\n%s' % e))

    def confirm_burn(self, what=None):
        return messagebox.askyesno(APP, 'Erase the chip in the SST programmer and burn %s?\n\n'
                                        'The chip must be OUT of the synth. Everything on it is replaced.\n\n'
                                        'When it is done, unplug the chip from the programmer before you put it in the synth.' % (what or 'this card'))

    def cmd_build_burn(self):
        if not any(t['zones'] for t in self.proj['tones']):
            messagebox.showinfo(APP, 'Add some tones with WAVs first.'); return
        if not self.confirm_burn('"%s"' % (self.proj.get('card_name') or 'this card')):
            return
        self.status('Building...'); self.prog['value'] = 0
        threading.Thread(target=self._burn_worker, args=(None, None), daemon=True).start()

    def cmd_burn_file(self):
        p = filedialog.askopenfilename(title='Card image to send to the programmer', filetypes=[('Card image', '*.bin')])
        if not p:
            return
        try:
            data = open(p, 'rb').read()
        except OSError as e:
            messagebox.showerror(APP, 'Cannot read file:\n%s' % e); return
        if len(data) != 512 * 1024:
            messagebox.showerror(APP, 'A card image must be exactly 512 KB (this file is %d bytes).' % len(data)); return
        if not self.confirm_burn(os.path.basename(p)):
            return
        self.status('Sending to programmer...'); self.prog['value'] = 0
        threading.Thread(target=self._burn_worker, args=(data, os.path.basename(p)), daemon=True).start()

    def _burn_worker(self, data, name):
        try:
            info = None
            if data is None:                                    # build first (the first 20% of the bar)
                conn, card, rep = B.build(self.proj, self.cache, progress=lambda i, n: self.q.put(('prog', 20 * i / n)))
                data, name = bytes(conn), (self.proj.get('card_name') or 'card').strip().replace(' ', '_') + '.bin'
                info = '%s: %s' % ((self.proj.get('card_name') or 'card').strip(), ', '.join(t['name'] for t in self.proj['tones']))

            def say(f, text):
                self.q.put(('prog', 20 + 80 * f)); self.q.put(('status', text))
            msg = UP.burn_image(data, name, say, info=info)
            self.q.put(('burned', msg))
        except UP.ProgrammerError as e:
            self.q.put(('error', 'Programmer: %s' % e))
        except Exception as e:
            traceback.print_exc()
            self.q.put(('error', 'Burn failed:\n%s' % e))

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == 'play':
                    self._play(m[1], m[2]); self.status(m[3])
                elif m[0] == 'status':
                    self.status(m[1])
                elif m[0] == 'prog':
                    self.prog['value'] = m[1]
                elif m[0] == 'built':
                    self.prog['value'] = 100
                    self.status('Built %s' % m[1])
                    messagebox.showinfo(APP, 'Burn-ready card written:\n%s\n\n%s\n\nBurn it as-is (no byte swap) to a 512 KB chip, e.g. SST39SF040.' % (m[1], '\n'.join(m[2])))
                elif m[0] == 'burned':
                    self.prog['value'] = 100
                    self.status('Burned')
                    messagebox.showinfo(APP, 'Burn finished.\n\n%s\n\nThe programmer does not read the chip back: verify it in your chip programmer, or try the card in the synth.' % m[1])
                elif m[0] == 'error':
                    self.prog['value'] = 0
                    self.status('Failed')
                    messagebox.showerror(APP, m[1])
        except queue.Empty:
            pass
        self.after(80, self.poll)

    def cmd_help(self):
        messagebox.showinfo(APP, __doc__ + '\nCard: 512 KB, up to 128 tones, 12 zones per tone, one sample max 2 s at 32 kHz '
                            '(longer ones get a lower rate automatically). Output is in connector order for a '
                            'straight-wired adapter (chip pin Ak = slot pin Ak).')

    def on_close(self):
        if self.confirm_discard():
            self.stop()
            self.destroy()


def selftest(project_path):
    """open a project, click through everything, build, close"""
    app = Studio()
    app.proj, app.path = B.load_project(project_path), project_path
    app.refresh_all(0, 0)
    app.update()
    app.wave.on_wheel(type('E', (), {'x': 300, 'delta': 120, 'state': 0})())
    app.keys.redraw(); app.update()
    z = app.cur_zone()
    log = ['selected zone %s root %d loop %s' % (os.path.basename(z['path']), z['root'], z['loop'])]
    app._preview_worker(z, z['root'] + 12, app.k, 0.5)
    log.append('preview: ' + str(app.q.get()[-1]))
    conn, card, rep = B.build(app.proj, app.cache)
    log += rep
    app.destroy()
    with open(project_path + '.selftest.txt', 'w') as f:
        f.write('\n'.join(log) + '\n')
    print('\n'.join(log))


if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--selftest':
        selftest(sys.argv[2])
    else:
        Studio().mainloop()
