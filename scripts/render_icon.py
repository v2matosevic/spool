"""Render the Spool mark to the PNG icon files.

The mark is plain geometry in a 64-unit box and matches the inline SVG in
templates/index.html: a tangerine tile, an ink disc with a hub hole, and a
band of tape leaving the disc along its bottom tangent. build_desktop.py derives icon.ico/.icns from
.ade/logo.png, so run this before a desktop build after changing the mark.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ORANGE = (255, 122, 47, 255)
INK = (20, 17, 14, 255)
CX, CY, R = 28, 32, 19
HUB = 4.2
BAND = (28, 44, 55, 51)
TILE_RADIUS = 14


def render(size, margin=0.0):
    big = size * 8
    unit = big * (1 - 2 * margin) / 64
    off = big * margin
    s = lambda value: off + value * unit
    image = Image.new('RGBA', (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([s(0), s(0), s(64), s(64)], radius=TILE_RADIUS * unit, fill=ORANGE)
    draw.ellipse([s(CX - R), s(CY - R), s(CX + R), s(CY + R)], fill=INK)
    draw.rectangle([s(BAND[0]), s(BAND[1]), s(BAND[2]), s(BAND[3])], fill=INK)
    draw.ellipse([s(CX - HUB), s(CY - HUB), s(CX + HUB), s(CY + HUB)], fill=ORANGE)
    return image.resize((size, size), Image.LANCZOS)


if __name__ == '__main__':
    desktop_mark = render(1024, margin=0.04)
    desktop_mark.save(ROOT / '.ade' / 'logo.png')
    desktop_mark.save(ROOT / 'static' / 'spool.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    render(256).save(ROOT / 'static' / 'logo.png')
