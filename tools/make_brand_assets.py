"""Generate Reasonable Engine brand assets without external design files."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reasonable" / "assets" / "brand"
FONT = ROOT / "reasonable" / "assets" / "fonts" / "Unbounded-Variable.ttf"
SIZE = 1024


def gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size)
    pixels = image.load()
    for y in range(height):
        t = y / max(1, height - 1)
        for x in range(width):
            # diagonal interpolation adds a little life
            tt = max(0.0, min(1.0, t * 0.82 + (x / max(1, width - 1)) * 0.18))
            pixels[x, y] = (
                int(top[0] + (bottom[0] - top[0]) * tt),
                int(top[1] + (bottom[1] - top[1]) * tt),
                int(top[2] + (bottom[2] - top[2]) * tt),
                255,
            )
    return image


def star_points(cx: float, cy: float, outer: float, inner: float, points: int = 8, rotation: float = 0.0):
    result = []
    for i in range(points * 2):
        angle = rotation - math.pi / 2 + i * math.pi / points
        radius = outer if i % 2 == 0 else inner
        result.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return result


def make_logo() -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    margin = 46
    radius = 232
    # outer glow
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle(
        (margin - 12, margin - 12, SIZE - margin + 12, SIZE - margin + 12),
        radius=radius + 12,
        fill=(255, 107, 74, 40),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(38))
    canvas.alpha_composite(glow)

    background = gradient((SIZE, SIZE), (9, 14, 24), (18, 29, 47)).convert("RGBA")
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, SIZE - margin, SIZE - margin), radius=radius, fill=255
    )
    canvas.paste(background, (0, 0), mask)

    draw = ImageDraw.Draw(canvas)
    # subtle dot grid
    dot = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dot)
    for y in range(100, SIZE - 80, 38):
        for x in range(100, SIZE - 80, 38):
            dd.ellipse((x, y, x + 2, y + 2), fill=(150, 178, 220, 18))
    canvas.alpha_composite(dot)

    cx = cy = SIZE / 2
    # colored rim (draw two arcs, then mask)
    rim = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    rd.rounded_rectangle(
        (margin, margin, SIZE - margin, SIZE - margin),
        radius=radius,
        outline=(53, 214, 196, 160),
        width=4,
    )
    rd.arc((margin + 40, margin + 40, SIZE - margin - 40, SIZE - margin - 40), 120, 300, fill=(255, 107, 74, 130), width=3)
    canvas.alpha_composite(rim)

    # orbital rings
    for r, color, width, start, end in (
        (300, (255, 107, 74, 148), 3, -40, 155),
        (300, (53, 214, 196, 120), 3, 160, 310),
        (360, (160, 188, 225, 36), 2, 30, 330),
    ):
        layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ImageDraw.Draw(layer).arc((cx - r, cy - r, cx + r, cy + r), start, end, fill=color, width=width)
        canvas.alpha_composite(layer)

    # star glow
    star_glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    sd = ImageDraw.Draw(star_glow)
    sd.ellipse((cx - 170, cy - 170, cx + 170, cy + 170), fill=(255, 107, 74, 44))
    sd.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), fill=(255, 200, 87, 50))
    star_glow = star_glow.filter(ImageFilter.GaussianBlur(42))
    canvas.alpha_composite(star_glow)

    # center disc
    disc = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(disc).ellipse((cx - 236, cy - 236, cx + 236, cy + 236), fill=(10, 16, 27, 155))
    disc = disc.filter(ImageFilter.GaussianBlur(30))
    canvas.alpha_composite(disc)

    # 8-point star, orange body + warm core
    draw = ImageDraw.Draw(canvas)
    draw.polygon(star_points(cx, cy, 250, 62, 8, -0.1), fill=(255, 107, 74, 255))
    draw.polygon(star_points(cx, cy, 166, 44, 8, -0.1), fill=(255, 165, 100, 255))
    draw.polygon(star_points(cx, cy, 104, 26, 8, -0.1), fill=(255, 232, 190, 255))
    draw.ellipse((cx - 20, cy - 20, cx + 20, cy + 20), fill=(255, 255, 255, 255))

    # orbit dot
    dot_x = cx + math.cos(math.radians(-36)) * 360
    dot_y = cy + math.sin(math.radians(-36)) * 360
    for r, alpha in ((18, 20), (11, 50), (7, 230)):
        draw.ellipse((dot_x - r, dot_y - r, dot_x + r, dot_y + r), fill=(53, 214, 196, alpha))

    # top-left highlight
    shine = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    ImageDraw.Draw(shine).arc((margin + 30, margin + 30, SIZE - margin - 30, SIZE - margin - 30), 190, 265, fill=(255, 255, 255, 35), width=3)
    canvas.alpha_composite(shine)
    return canvas


def make_wordmark(logo: Image.Image) -> Image.Image:
    width, height = 1800, 420
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    mark = logo.resize((300, 300), Image.LANCZOS)
    image.alpha_composite(mark, (20, 60))
    draw = ImageDraw.Draw(image)
    font_big = ImageFont.truetype(str(FONT), 126)
    font_small = ImageFont.truetype(str(FONT), 38)
    draw.text((370, 106), "REASONABLE", font=font_big, fill=(244, 247, 251, 255))
    draw.text((378, 260), "ENGINE", font=font_small, fill=(255, 200, 87, 255))
    return image


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    logo = make_logo()
    logo.resize((512, 512), Image.LANCZOS).save(OUT / "logo_512.png")
    logo.resize((256, 256), Image.LANCZOS).save(OUT / "logo_256.png")
    logo.save(OUT / "logo.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    make_wordmark(logo).save(OUT / "wordmark.png")
    print(f"Brand assets written to {OUT}")


if __name__ == "__main__":
    main()
