"""Draws u110.ico / u110_icon.png: a U-110 style front (charcoal face, backlit LCD, PCM card in the slot).
Run once with Pillow installed; the app itself only needs the generated files."""
import io, struct
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FACE, FACE_HI, EDGE = (40, 42, 46), (62, 65, 70), (18, 19, 21)
LCD_A, LCD_B, LCD_TXT = (190, 206, 70), (150, 170, 40), (30, 42, 14)
CARD, CARD_SH, RED = (205, 208, 212), (150, 153, 158), (214, 52, 40)


def font(size, name='ariblk.ttf'):
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def master(S=256):
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = S * 0.12
    # unit face with a soft top highlight
    d.rounded_rectangle((S * .03, S * .06, S * .97, S * .94), r, fill=EDGE)
    d.rounded_rectangle((S * .05, S * .08, S * .95, S * .92), r * .85, fill=FACE)
    d.rounded_rectangle((S * .05, S * .08, S * .95, S * .30), r * .85, fill=FACE_HI)
    d.rectangle((S * .05, S * .22, S * .95, S * .30), fill=FACE)
    # backlit LCD with vertical gradient
    x0, y0, x1, y1 = S * .12, S * .17, S * .88, S * .50
    d.rounded_rectangle((x0 - S * .02, y0 - S * .02, x1 + S * .02, y1 + S * .02), S * .03, fill=EDGE)
    for i in range(int(y1 - y0)):
        t = i / (y1 - y0)
        c = tuple(int(LCD_A[k] * (1 - t) + LCD_B[k] * t) for k in range(3))
        d.line((x0, y0 + i, x1, y0 + i), fill=c)
    f = font(int(S * .20))
    tw = d.textlength('U-110', font=f)
    d.text(((S - tw) / 2, y0 + (y1 - y0) * .12), 'U-110', font=f, fill=LCD_TXT)
    # red LED
    d.ellipse((S * .80, S * .58, S * .87, S * .65), fill=RED)
    # card slot with a PCM card sticking out
    d.rounded_rectangle((S * .14, S * .74, S * .70, S * .80), S * .015, fill=EDGE)
    d.rectangle((S * .17, S * .59, S * .67, S * .77), fill=CARD_SH)
    d.rectangle((S * .17, S * .58, S * .66, S * .76), fill=CARD)
    d.rectangle((S * .17, S * .58, S * .66, S * .63), fill=RED)
    fl = font(int(S * .075), 'arialbd.ttf')
    d.text((S * .20, S * .645), 'PCM', font=fl, fill=(60, 62, 66))
    return im


def small(S):
    """16/24 px: no text, just face, LCD bar, red card stripe"""
    im = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 1, S - 1, S - 2), max(2, S // 6), fill=FACE, outline=EDGE)
    d.rectangle((2, 3, S - 3, S // 2), fill=LCD_A)
    d.rectangle((3, S // 2 - 1, S - 4, S // 2), fill=LCD_B)
    d.line((4, S * 5 // 16, S - 5, S * 5 // 16), fill=LCD_TXT)
    d.rectangle((3, S * 5 // 8, S * 5 // 8, S - 4), fill=CARD)
    d.rectangle((3, S * 5 // 8, S * 5 // 8, S * 5 // 8 + max(1, S // 10)), fill=RED)
    d.point((S - 4, S * 5 // 8), fill=RED)
    return im


def write_ico(images, path):
    """ICO with PNG-compressed entries (Vista+)"""
    blobs = []
    for im in images:
        b = io.BytesIO(); im.save(b, 'PNG'); blobs.append(b.getvalue())
    head = struct.pack('<HHH', 0, 1, len(images))
    off = 6 + 16 * len(images)
    dirs = b''
    for im, blob in zip(images, blobs):
        w, h = im.size
        dirs += struct.pack('<BBBBHHII', w % 256, h % 256, 0, 0, 1, 32, len(blob), off)
        off += len(blob)
    with open(path, 'wb') as f:
        f.write(head + dirs + b''.join(blobs))


if __name__ == '__main__':
    m = master(256)
    m.save('u110_icon.png')
    imgs = [small(16), small(24)] + [m.resize((s, s), Image.LANCZOS) for s in (32, 48, 64, 128)] + [m]
    write_ico(imgs, 'u110.ico')
    sheet = Image.new('RGBA', (640, 270), (230, 230, 230, 255))
    x = 5
    for im in imgs:
        sheet.alpha_composite(im, (x, 5)); x += im.size[0] + 8
    sheet.save('icon_preview.png')
    print('wrote u110.ico, u110_icon.png')
