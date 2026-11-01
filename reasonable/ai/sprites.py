"""Sprite and background generation.

Two independent paths:

* remote image models: any OpenAI-compatible /images/generations endpoint;
* a procedural offline generator that produces coherent pixel-art/flat sprites.

Remote results are chroma-keyed, trimmed and packed into PNGs with alpha. If the
network fails, the procedural path keeps the agent productive and the tool result
clearly reports that a fallback was used.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from reasonable.core.paths import ensure_app_dirs


STYLE_PROMPTS = {
    "pixel": (
        "crisp 2D pixel-art game sprite, 64x64 pixel grid aesthetic, clean dark outlines, "
        "limited harmonious palette, readable silhouette"
    ),
    "flat": (
        "modern flat vector 2D game sprite, subtle gradients, clean dark outline, polished "
        "mobile-game art direction, soft rim light, readable silhouette"
    ),
    "painterly": (
        "stylized painterly 2D game sprite, soft brush texture, vivid rim light, clean "
        "silhouette, premium indie game art"
    ),
    "icon": (
        "polished app icon, bold simple silhouette, subtle gradient, premium dark UI style, "
        "centered, no text"
    ),
}


def _hash_seed(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:12], 16)


def _stable_seed(prompt: str, style: str, seed: int | None) -> int:
    return int(seed) if seed is not None else _hash_seed(prompt + "|" + style) % 2_000_000_000


def _safe_asset_name(name: str, fallback: str = "sprite") -> str:
    safe = "".join(ch for ch in name.lower() if ch.isalnum() or ch in "-_")
    return (safe or fallback)[:60]


# ---------------------------------------------------------------------------
# Remote image providers
# ---------------------------------------------------------------------------


def _remote_prompt(prompt: str, style: str, kind: str) -> str:
    style_text = STYLE_PROMPTS.get(style, STYLE_PROMPTS["flat"])
    if kind == "background":
        return (
            f"Atmospheric 2D game background: {prompt}. Wide composition, depth, layered "
            "foreground/midground/background, no characters, no text, no watermark, no UI. "
            "Premium indie game art, coherent lighting."
        )
    if kind == "icon":
        return (
            f"App icon for a program: {prompt}. Bold simple symbol, centered, strong silhouette, "
            "premium dark navy and coral color palette, subtle glow, flat vector style, no text, "
            "no letters, no watermark, square composition."
        )
    return (
        f"Single 2D game asset: {prompt}. {style_text}. One object only, centered, full subject "
        "visible, strong readable silhouette, harmonious saturated palette, professional game "
        "art, clean edges. Isolated on a solid pure magenta background (#FF00FF). No shadow on "
        "the background, no text, no watermark, no border, no extra objects."
    )


def _http_image(url: str, headers: dict[str, str] | None = None, timeout: int = 120) -> Image.Image:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ReasonableEngine/0.1 (image generation)",
            "Accept": "image/png,image/jpeg,image/webp,*/*",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Сервер изображений вернул HTTP {error.code}: {body[:240]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Нет соединения с сервером изображений: {error.reason}") from error
    except TimeoutError as error:
        raise RuntimeError("Сервер изображений не ответил вовремя.") from error
    try:
        return Image.open(io.BytesIO(data))
    except Exception as error:
        raise RuntimeError("Сервер вернул не изображение. Проверьте endpoint.") from error


def _openai_image(prompt: str, config: dict[str, Any], *, size: tuple[int, int], kind: str) -> Image.Image:
    base = (config.get("base_url") or "").rstrip("/")
    if not base:
        raise RuntimeError("Не задан Base URL сервера изображений.")
    if not base.endswith("/images/generations"):
        if base.endswith("/v1"):
            url = base + "/images/generations"
        else:
            url = base + "/v1/images/generations" if not base.endswith("/images/generations") else base
    else:
        url = base
    # Most OpenAI-compatible servers accept this subset.
    request_size = "1024x1024"
    payload = {
        "model": config.get("model") or "gpt-image-1",
        "prompt": prompt,
        "n": 1,
        "size": request_size,
    }
    if "gpt-image" not in payload["model"] and "dall-e" not in payload["model"]:
        payload["response_format"] = "b64_json"
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Сервер изображений вернул HTTP {error.code}: {body[:240]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"Нет соединения с сервером изображений: {error.reason}") from error
    items = data.get("data") or []
    if not items:
        raise RuntimeError("Сервер изображений вернул пустой ответ.")
    item = items[0]
    if item.get("b64_json"):
        try:
            return Image.open(io.BytesIO(base64.b64decode(item["b64_json"])))
        except Exception as error:
            raise RuntimeError("Не удалось декодировать base64 изображение.") from error
    if item.get("url"):
        return _http_image(item["url"], headers={"Authorization": headers.get("Authorization", "")} if headers.get("Authorization") else None)
    raise RuntimeError("В ответе сервера изображений нет url или b64_json.")


# ---------------------------------------------------------------------------
# Chroma key / packing
# ---------------------------------------------------------------------------


def _chroma_key(image: Image.Image) -> Image.Image:
    image = image.convert("RGBA")
    alpha_channel = image.getchannel("A")
    if alpha_channel.getextrema()[0] < 250:
        # The model already generated transparency.
        return image
    rgb = image.convert("RGB")
    width, height = rgb.size
    # Use the median of the corner patches as the background colour.
    key_r, key_g, key_b = 255, 0, 255
    patches = []
    step = max(2, min(width, height) // 28)
    for x in range(0, min(width, step * 3), step):
        for y in range(0, min(height, step * 3), step):
            patches.append(rgb.getpixel((x, y)))
            patches.append(rgb.getpixel((width - 1 - x, y)))
            patches.append(rgb.getpixel((x, height - 1 - y)))
            patches.append(rgb.getpixel((width - 1 - x, height - 1 - y)))
    if patches:
        patches.sort(key=lambda p: p[0] + p[1] + p[2])
        middle = patches[len(patches) // 2]
        key_r, key_g, key_b = middle

    def near_key(r: int, g: int, b: int) -> tuple[bool, int]:
        distance = math.sqrt((r - key_r) ** 2 + (g - key_g) ** 2 + (b - key_b) ** 2)
        # A slight magenta bias avoids deleting complementary cold details.
        magenta_bias = (r > g + 28 and b > g + 28)
        threshold = 72 if magenta_bias else 48
        if distance <= threshold:
            return True, 0
        if distance < threshold * 1.9:
            return False, int(255 * (distance - threshold) / (threshold * 0.9))
        return False, 255

    pixels = list(rgb.getdata())
    out = []
    removed = 0
    for r, g, b in pixels:
        hidden, a = near_key(r, g, b)
        if hidden:
            removed += 1
            out.append((0, 0, 0, 0))
        else:
            out.append((r, g, b, a))
    if removed < width * height * 0.01:
        # Background detection failed; keep the image intact rather than hollowing it.
        return image
    result = Image.new("RGBA", image.size)
    result.putdata(out)
    # Soften the matte edge a touch to remove fringes.
    alpha = result.getchannel("A").filter(ImageFilter.GaussianBlur(0.6))
    result.putalpha(alpha)
    bbox = result.getbbox()
    if bbox:
        pad = 10
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(width, bbox[2] + pad), min(height, bbox[3] + pad))
        result = result.crop(bbox)
    return result


def _fit_canvas(image: Image.Image, size: int, margin: int = 8) -> Image.Image:
    image = image.convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    max_dim = max(1, size - margin * 2)
    scale = min(max_dim / max(1, image.width), max_dim / max(1, image.height))
    if scale <= 0:
        scale = 1.0
    new_size = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
    image = image.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    return canvas


# ---------------------------------------------------------------------------
# Procedural art
# ---------------------------------------------------------------------------


def _hsv(h: float, s: float, v: float) -> tuple[int, int, int]:
    import colorsys

    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return int(r * 255), int(g * 255), int(b * 255)


COLOR_WORDS = {
    "красн": 0.005,
    "red": 0.005,
    "оранж": 0.06,
    "orange": 0.06,
    "жёлт": 0.135,
    "желт": 0.135,
    "yellow": 0.135,
    "золот": 0.12,
    "gold": 0.12,
    "зелён": 0.33,
    "зелен": 0.33,
    "green": 0.33,
    "бирюз": 0.49,
    "turquoise": 0.49,
    "cyan": 0.5,
    "голуб": 0.55,
    "blue": 0.6,
    "син": 0.64,
    "фиолет": 0.77,
    "purple": 0.77,
    "violet": 0.8,
    "розов": 0.92,
    "pink": 0.92,
    "magenta": 0.9,
    "корич": 0.07,
    "brown": 0.07,
    "white": 0.6,
    "бел": 0.6,
}

SUBJECT_HUES = {
    "slime": 0.33,
    "tree": 0.32,
    "star": 0.13,
    "coin": 0.12,
    "crystal": 0.58,
    "orb": 0.77,
    "potion": 0.88,
    "robot": 0.64,
    "ship": 0.56,
    "rock": 0.08,
}


def _palette_for(prompt: str, style: str, seed: int) -> dict[str, tuple[int, int, int]]:
    rng = random.Random(seed)
    lower = prompt.lower()
    hue = None
    for word, value in COLOR_WORDS.items():
        if word in lower:
            hue = (value + rng.uniform(-0.018, 0.018)) % 1.0
            break
    if hue is None:
        for word, value in SUBJECT_HUES.items():
            if word in lower:
                hue = value
                break
    if hue is None:
        hue = rng.random()
    saturation = rng.uniform(0.58, 0.82)
    base = _hsv(hue, saturation, 0.94)
    light = _hsv(hue, saturation * 0.72, 1.0)
    dark = _hsv(hue, saturation * 0.9, 0.54)
    deep = _hsv(hue, saturation * 0.7, 0.24)
    accent = _hsv(hue + rng.choice((0.42, 0.5, 0.58)), 0.82, 1.0)
    warm = _hsv(hue + 0.07, 0.9, 1.0)
    return {
        "base": base,
        "light": light,
        "dark": dark,
        "deep": deep,
        "accent": accent,
        "warm": warm,
        "white": (246, 249, 255),
        "outline": _hsv(hue, 0.55, 0.13),
    }


def _vertical_gradient(size: tuple[int, int], top, bottom) -> Image.Image:
    width, height = size
    grad = Image.new("RGBA", size)
    pixels = grad.load()
    for y in range(height):
        t = y / max(1, height - 1)
        c = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
            255,
        )
        for x in range(width):
            pixels[x, y] = c
    return grad


def _shape_gradient(image: Image.Image, points_or_bbox, palette, vertical=True) -> None:
    mask = Image.new("L", image.size, 0)
    md = ImageDraw.Draw(mask)
    if isinstance(points_or_bbox, (tuple, list)) and len(points_or_bbox) > 2 and isinstance(points_or_bbox[0], (tuple, list)):
        md.polygon(points_or_bbox, fill=255)
    else:
        md.ellipse(points_or_bbox, fill=255)
    grad = _vertical_gradient(image.size, palette["light"], palette["dark"]) if vertical else None
    if grad:
        image.paste(grad, (0, 0), mask)


def _star(draw: ImageDraw.ImageDraw, cx: float, cy: float, outer: float, inner: float, points: int, fill) -> None:
    coords = []
    for index in range(points * 2):
        angle = -math.pi / 2 + index * math.pi / points
        radius = outer if index % 2 == 0 else inner
        coords.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    draw.polygon(coords, fill=fill)


def _draw_subject(kind: str, image: Image.Image, palette, rng: random.Random, *, pixel: bool, object_name: str) -> None:
    draw = ImageDraw.Draw(image)
    W, H = image.size
    outline = palette["outline"]
    ow = max(2, W // 120) if not pixel else max(1, W // 80)
    if pixel:
        ow = max(1, W // 64)
    cx, cy = W // 2, int(H * 0.52)
    # ground shadow
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((int(W * 0.24), int(H * 0.82), int(W * 0.76), int(H * 0.9)), fill=(0, 0, 0, 55))
    shadow = shadow.filter(ImageFilter.GaussianBlur(max(2, W // 80)))
    image.alpha_composite(shadow)

    if kind in {"star", "coin"}:
        if kind == "coin":
            bbox = (int(W * 0.2), int(H * 0.2), int(W * 0.8), int(H * 0.8))
            draw.ellipse(bbox, fill=palette["outline"])
            inner = (bbox[0] + ow * 3, bbox[1] + ow * 3, bbox[2] - ow * 3, bbox[3] - ow * 3)
            _shape_gradient(image, inner, palette)
            draw.ellipse(inner, outline=palette["outline"], width=ow)
            draw.ellipse((inner[0] + W * 0.1, inner[1] + W * 0.08, inner[0] + W * 0.28, inner[1] + W * 0.2), fill=(255, 255, 255, 150))
            _star(draw, cx, cy, W * 0.19, W * 0.07, 4, palette["warm"])
            _star(draw, cx, cy, W * 0.12, W * 0.035, 4, (255, 255, 255))
        else:
            _star(draw, cx, cy, W * 0.38, W * 0.14, 8, palette["outline"])
            _star(draw, cx, cy, W * 0.35, W * 0.12, 8, palette["base"])
            _star(draw, cx, cy - W * 0.01, W * 0.25, W * 0.08, 8, palette["light"])
            _star(draw, cx, cy, W * 0.09, W * 0.025, 4, (255, 255, 255))
            draw.ellipse((cx - W * 0.035, cy - W * 0.035, cx + W * 0.035, cy + W * 0.035), fill=palette["warm"])
        return
    if kind == "crystal":
        points = [(cx, int(H * 0.12)), (int(W * 0.76), int(H * 0.38)), (int(W * 0.64), int(H * 0.84)), (int(W * 0.36), int(H * 0.84)), (int(W * 0.24), int(H * 0.38))]
        draw.polygon(points, fill=palette["outline"])
        inner = [(cx, int(H * 0.16)), (int(W * 0.72), int(H * 0.4)), (int(W * 0.61), int(H * 0.8)), (int(W * 0.39), int(H * 0.8)), (int(W * 0.28), int(H * 0.4))]
        draw.polygon(inner, fill=palette["base"])
        draw.polygon([(cx, int(H * 0.16)), (int(W * 0.72), int(H * 0.4)), (cx, int(H * 0.55))], fill=palette["light"])
        draw.polygon([(cx, int(H * 0.55)), (int(W * 0.61), int(H * 0.8)), (int(W * 0.39), int(H * 0.8))], fill=palette["dark"])
        draw.line([(cx, int(H * 0.18)), (cx, int(H * 0.78))], fill=(255, 255, 255, 120), width=max(1, W // 200))
        for sx, sy, r in ((0.2, 0.24, 0.018), (0.82, 0.7, 0.012), (0.76, 0.2, 0.01)):
            _star(draw, int(W * sx), int(H * sy), W * r * 2, W * r * 0.6, 4, (255, 255, 255, 220))
        return
    if kind == "tree":
        draw.rounded_rectangle((int(W * 0.43), int(H * 0.52), int(W * 0.57), int(H * 0.86)), radius=int(W * 0.03), fill=palette["deep"], outline=palette["outline"], width=ow)
        for x, y, r, c in ((0.5, 0.34, 0.25, "dark"), (0.36, 0.42, 0.19, "base"), (0.64, 0.42, 0.19, "base"), (0.5, 0.46, 0.28, "base"), (0.5, 0.3, 0.18, "light")):
            bbox = (int(W * (x - r)), int(H * (y - r * 1.1)), int(W * (x + r)), int(H * (y + r * 1.1)))
            draw.ellipse(bbox, fill=palette[c], outline=palette["outline"], width=ow)
        for _ in range(7):
            x = rng.uniform(W * 0.28, W * 0.72)
            y = rng.uniform(H * 0.2, H * 0.52)
            draw.ellipse((x - W * 0.02, y - W * 0.02, x + W * 0.02, y + W * 0.02), fill=palette["accent"])
        return
    if kind == "rock":
        points = [(cx, int(H * 0.28)), (int(W * 0.8), int(H * 0.47)), (int(W * 0.72), int(H * 0.82)), (int(W * 0.3), int(H * 0.86)), (int(W * 0.18), int(H * 0.55))]
        draw.polygon(points, fill=palette["outline"])
        inner = [(cx, int(H * 0.32)), (int(W * 0.76), int(H * 0.49)), (int(W * 0.68), int(H * 0.78)), (int(W * 0.33), int(H * 0.81)), (int(W * 0.23), int(H * 0.56))]
        draw.polygon(inner, fill=palette["base"])
        draw.polygon([(cx, int(H * 0.32)), (int(W * 0.76), int(H * 0.49)), (int(W * 0.56), int(H * 0.58))], fill=palette["light"])
        for _ in range(3):
            x1, y1 = rng.uniform(W * 0.3, W * 0.65), rng.uniform(H * 0.4, H * 0.7)
            draw.line((x1, y1, x1 + W * 0.08, y1 + H * 0.03), fill=palette["deep"], width=max(1, W // 150))
        return
    if kind == "slime":
        bbox = (int(W * 0.16), int(H * 0.34), int(W * 0.84), int(H * 0.86))
        draw.ellipse(bbox, fill=palette["outline"])
        inner = (bbox[0] + ow * 3, bbox[1] + ow * 3, bbox[2] - ow * 3, bbox[3] - ow * 3)
        draw.ellipse(inner, fill=palette["base"])
        draw.ellipse((inner[0] + W * 0.06, inner[1] + H * 0.02, inner[0] + W * 0.36, inner[1] + H * 0.2), fill=palette["light"])
        _draw_face(draw, cx, int(H * 0.55), W, palette, ow)
        return
    if kind == "robot":
        # antenna
        draw.line((cx, int(H * 0.12), cx, int(H * 0.3)), fill=palette["outline"], width=max(2, W // 120))
        draw.ellipse((cx - W * 0.035, int(H * 0.08), cx + W * 0.035, int(H * 0.15)), fill=palette["accent"], outline=palette["outline"], width=ow)
        # head
        head = (int(W * 0.29), int(H * 0.25), int(W * 0.71), int(H * 0.53))
        draw.rounded_rectangle(head, radius=int(W * 0.09), fill=palette["outline"])
        inner_head = (head[0] + ow * 3, head[1] + ow * 3, head[2] - ow * 3, head[3] - ow * 3)
        draw.rounded_rectangle(inner_head, radius=int(W * 0.07), fill=palette["light"])
        visor = (int(W * 0.36), int(H * 0.32), int(W * 0.64), int(H * 0.4))
        draw.rounded_rectangle(visor, radius=int(W * 0.025), fill=palette["deep"])
        draw.ellipse((int(W * 0.41), int(H * 0.34), int(W * 0.46), int(H * 0.38)), fill=palette["accent"])
        draw.ellipse((int(W * 0.54), int(H * 0.34), int(W * 0.59), int(H * 0.38)), fill=palette["accent"])
        # body
        body = (int(W * 0.31), int(H * 0.55), int(W * 0.69), int(H * 0.83))
        draw.rounded_rectangle(body, radius=int(W * 0.08), fill=palette["outline"])
        inner_body = (body[0] + ow * 3, body[1] + ow * 3, body[2] - ow * 3, body[3] - ow * 3)
        draw.rounded_rectangle(inner_body, radius=int(W * 0.06), fill=palette["base"])
        draw.rounded_rectangle((int(W * 0.44), int(H * 0.61), int(W * 0.56), int(H * 0.72)), radius=int(W * 0.03), fill=palette["accent"], outline=palette["outline"], width=ow)
        draw.rectangle((int(W * 0.36), int(H * 0.75), int(W * 0.64), int(H * 0.78)), fill=palette["deep"])
        return
    if kind == "orb":
        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((int(W * 0.18), int(H * 0.18), int(W * 0.82), int(H * 0.82)), fill=(*palette["accent"], 80))
        glow = glow.filter(ImageFilter.GaussianBlur(W // 20))
        image.alpha_composite(glow)
        bbox = (int(W * 0.25), int(H * 0.25), int(W * 0.75), int(H * 0.75))
        _shape_gradient(image, bbox, palette)
        draw.ellipse(bbox, outline=palette["outline"], width=ow)
        draw.ellipse((int(W * 0.31), int(H * 0.29), int(W * 0.48), int(H * 0.44)), fill=(255, 255, 255, 180))
        draw.arc((int(W * 0.28), int(H * 0.3), int(W * 0.72), int(H * 0.7)), 200, 340, fill=palette["accent"], width=max(2, W // 80))
        return
    if kind == "ship":
        points = [(cx, int(H * 0.14)), (int(W * 0.82), int(H * 0.74)), (cx, int(H * 0.62)), (int(W * 0.18), int(H * 0.74))]
        draw.polygon(points, fill=palette["outline"])
        inner = [(cx, int(H * 0.19)), (int(W * 0.76), int(H * 0.7)), (cx, int(H * 0.58)), (int(W * 0.24), int(H * 0.7))]
        draw.polygon(inner, fill=palette["base"])
        draw.polygon([(cx, int(H * 0.19)), (cx, int(H * 0.58)), (int(W * 0.24), int(H * 0.7))], fill=palette["light"])
        pygame = None  # noqa - keeps the block self-contained
        draw.ellipse((cx - W * 0.08, int(H * 0.52), cx + W * 0.08, int(H * 0.65)), fill=palette["accent"], outline=palette["outline"], width=ow)
        draw.ellipse((cx - W * 0.04, int(H * 0.55), cx + W * 0.04, int(H * 0.61)), fill=(255, 255, 255, 200))
        return
    if kind == "potion":
        draw.rounded_rectangle((int(W * 0.42), int(H * 0.14), int(W * 0.58), int(H * 0.3)), radius=int(W * 0.03), fill=palette["deep"], outline=palette["outline"], width=ow)
        draw.rectangle((int(W * 0.46), int(H * 0.27), int(W * 0.54), int(H * 0.35)), fill=palette["light"], outline=palette["outline"], width=ow)
        body = (int(W * 0.26), int(H * 0.34), int(W * 0.74), int(H * 0.84))
        draw.ellipse(body, fill=palette["outline"])
        inner = (body[0] + ow * 3, body[1] + ow * 3, body[2] - ow * 3, body[3] - ow * 3)
        _shape_gradient(image, inner, palette)
        draw.ellipse(inner, outline=palette["outline"], width=ow)
        draw.ellipse((int(W * 0.32), int(H * 0.47), int(W * 0.7), int(H * 0.78)), fill=palette["accent"])
        draw.arc((int(W * 0.36), int(H * 0.49), int(W * 0.66), int(H * 0.72)), 200, 340, fill=(255, 255, 255, 140), width=max(1, W // 130))
        draw.ellipse((int(W * 0.36), int(H * 0.42), int(W * 0.46), int(H * 0.49)), fill=(255, 255, 255, 180))
        _star(draw, int(W * 0.2), int(H * 0.26), W * 0.035, W * 0.01, 4, palette["warm"])
        return

    # generic creature / hero
    _draw_creature(draw, image, palette, rng, pixel=pixel, kind=kind, outline=outline, ow=ow)


def _draw_face(draw, cx, cy, W, palette, ow):
    eye_dx = W * 0.115
    eye_y = cy
    for dx in (-eye_dx, eye_dx):
        draw.ellipse((cx + dx - W * 0.065, eye_y - W * 0.075, cx + dx + W * 0.065, eye_y + W * 0.075), fill=palette["white"], outline=palette["outline"], width=ow)
        draw.ellipse((cx + dx - W * 0.026, eye_y - W * 0.032, cx + dx + W * 0.026, eye_y + W * 0.032), fill=palette["outline"])
        draw.ellipse((cx + dx - W * 0.012, eye_y - W * 0.04, cx + dx + W * 0.008, eye_y - W * 0.018), fill=(255, 255, 255))
    draw.arc((cx - W * 0.09, eye_y + W * 0.06, cx + W * 0.09, eye_y + W * 0.15), 20, 160, fill=palette["outline"], width=ow)


def _draw_creature(draw, image, palette, rng, *, pixel: bool, kind: str, outline, ow):
    W, H = image.size
    cx = W // 2
    # feet
    for dx in (-0.16, 0.16):
        foot = (cx + W * dx - W * 0.09, int(H * 0.78), cx + W * dx + W * 0.09, int(H * 0.89))
        draw.ellipse(foot, fill=palette["outline"])
        inner = (foot[0] + ow * 2, foot[1] + ow * 2, foot[2] - ow * 2, foot[3] - ow * 2)
        draw.ellipse(inner, fill=palette["dark"])
    # body capsule
    body = (int(W * 0.27), int(H * 0.44), int(W * 0.73), int(H * 0.83))
    draw.ellipse(body, fill=palette["outline"])
    inner_body = (body[0] + ow * 3, body[1] + ow * 3, body[2] - ow * 3, body[3] - ow * 3)
    _shape_gradient(image, inner_body, palette)
    draw.ellipse(inner_body, outline=palette["outline"], width=ow)
    # arms
    for dx in (-1, 1):
        arm = (cx + dx * W * 0.26 - W * 0.07, int(H * 0.5), cx + dx * W * 0.26 + W * 0.07, int(H * 0.64))
        draw.ellipse(arm, fill=palette["dark"], outline=palette["outline"], width=ow)
    # chest emblem
    _star(draw, cx, int(H * 0.64), W * 0.06, W * 0.022, 4, palette["accent"])
    # head
    head_r = W * 0.22
    head = (cx - head_r, int(H * 0.18), cx + head_r, int(H * 0.18) + head_r * 2)
    draw.ellipse(head, fill=palette["outline"])
    inner_head = (head[0] + ow * 3, head[1] + ow * 3, head[2] - ow * 3, head[3] - ow * 3)
    draw.ellipse(inner_head, fill=palette["light"])
    draw.ellipse((inner_head[0] + W * 0.03, inner_head[1] + H * 0.02, inner_head[0] + W * 0.16, inner_head[1] + H * 0.12), fill=(255, 255, 255, 80))
    _draw_face(draw, cx, int(H * 0.37), W, palette, ow)
    # ears / horns
    if rng.random() < 0.55:
        for dx in (-1, 1):
            points = [(cx + dx * W * 0.12, int(H * 0.2)), (cx + dx * W * 0.27, int(H * 0.06)), (cx + dx * W * 0.31, int(H * 0.23))]
            draw.polygon(points, fill=palette["dark"], outline=palette["outline"])
    if kind in {"hero", "character", "knight", "wizard"}:
        draw.arc((cx - W * 0.24, int(H * 0.12), cx + W * 0.24, int(H * 0.3)), 190, 350, fill=palette["accent"], width=max(2, W // 100))
        draw.line((cx + W * 0.14, int(H * 0.52), int(W * 0.79), int(H * 0.25)), fill=palette["white"], width=max(2, W // 120))
        draw.line((int(W * 0.79), int(H * 0.25), int(W * 0.82), int(H * 0.33)), fill=palette["accent"], width=max(3, W // 90))


def _draw_procedural_pixel(prompt: str, subject: str, size: int, palette, rng, kind: str) -> Image.Image:
    base = 64
    image = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    # background shadow
    draw.ellipse((12, 54, 52, 61), fill=(0, 0, 0, 45))
    outline = palette["outline"]
    if kind in {"star", "coin"}:
        _star(draw, 32, 32, 25, 10, 8, outline)
        _star(draw, 32, 32, 22, 8, 8, palette["base"])
        _star(draw, 32, 30, 12, 4, 4, (255, 255, 255))
    elif kind == "slime":
        draw.ellipse((9, 23, 55, 56), fill=outline)
        draw.ellipse((12, 26, 52, 53), fill=palette["base"])
        draw.ellipse((17, 27, 31, 35), fill=palette["light"])
        for ex in (24, 40):
            draw.rectangle((ex - 4, 37, ex + 3, 44), fill=(255, 255, 255))
            draw.rectangle((ex - 1, 39, ex + 1, 42), fill=outline)
    elif kind == "orb":
        draw.ellipse((9, 9, 55, 55), fill=outline)
        draw.ellipse((12, 12, 52, 52), fill=palette["base"])
        draw.ellipse((17, 17, 32, 30), fill=(255, 255, 255, 190))
        draw.arc((14, 14, 50, 50), 200, 340, fill=palette["accent"], width=2)
    else:
        draw.ellipse((12, 42, 52, 57), fill=palette["dark"])
        draw.ellipse((17, 26, 47, 51), fill=outline)
        draw.ellipse((19, 28, 45, 49), fill=palette["base"])
        draw.ellipse((18, 14, 46, 40), fill=outline)
        draw.ellipse((20, 16, 44, 38), fill=palette["light"])
        for ex in (27, 37):
            draw.rectangle((ex - 3, 24, ex + 2, 29), fill=(255, 255, 255))
            draw.rectangle((ex - 1, 26, ex + 1, 28), fill=outline)
        draw.rectangle((29, 31, 35, 32), fill=outline)
        draw.rectangle((23, 43, 41, 47), fill=palette["accent"])
        if rng.random() < 0.5:
            draw.polygon([(20, 16), (32, 7), (44, 16)], fill=palette["dark"])
    # reduce to a limited palette with a proper outline pass
    return image.resize((size, size), Image.Resampling.NEAREST)


def procedural_sprite(prompt: str, *, style: str = "flat", size: int = 256, seed: int | None = None) -> tuple[Image.Image, dict]:
    seed = _stable_seed(prompt, style, seed)
    rng = random.Random(seed)
    palette = _palette_for(prompt, style, seed)
    lower = prompt.lower()
    kind = "creature"
    for candidate in ("slime", "robot", "star", "coin", "crystal", "tree", "rock", "potion", "ship", "orb"):
        if candidate in lower:
            kind = candidate
            break
    if any(word in lower for word in ("hero", "knight", "wizard", "character", "girl", "boy", "warrior", "mage", "enemy")):
        kind = "creature"
    work_size = 640
    image = Image.new("RGBA", (work_size, work_size), (0, 0, 0, 0))
    _draw_subject(kind, image, palette, rng, pixel=False, object_name=prompt)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    if style == "pixel":
        image = _draw_procedural_pixel(prompt, prompt, size, palette, rng, kind)
    meta = {
        "subject": kind,
        "palette": {key: "#%02x%02x%02x" % value if isinstance(value, tuple) and len(value) >= 3 else value for key, value in palette.items() if key in {"base", "light", "dark", "accent", "warm"}},
        "seed": seed,
    }
    return image, meta


def procedural_background(prompt: str, *, width: int = 1280, height: int = 720, seed: int | None = None) -> tuple[Image.Image, dict]:
    seed = _stable_seed(prompt, "background", seed)
    rng = random.Random(seed)
    lower = prompt.lower()
    if any(word in lower for word in ("space", "star", "cosmic", "galaxy", "night")):
        top, bottom = (7, 10, 24), (22, 20, 52)
    elif any(word in lower for word in ("desert", "sun", "dune", "warm")):
        top, bottom = (43, 31, 50), (120, 65, 58)
    elif any(word in lower for word in ("forest", "jungle", "green")):
        top, bottom = (8, 24, 27), (28, 57, 47)
    elif any(word in lower for word in ("city", "cyber", "neon", "night city")):
        top, bottom = (10, 12, 28), (31, 22, 47)
    else:
        top, bottom = (12, 18, 34), (40, 51, 76)
    scale = 2
    W, H = width * scale, height * scale
    image = _vertical_gradient((W, H), top, bottom)
    draw = ImageDraw.Draw(image, "RGBA")
    # stars
    for _ in range(rng.randint(70, 150)):
        x, y = rng.uniform(0, W), rng.uniform(0, H * 0.65)
        r = rng.choice((1, 1, 1, 2))
        draw.ellipse((x, y, x + r * scale, y + r * scale), fill=(230, 240, 255, rng.randint(60, 200)))
    # sun/moon
    if any(word in lower for word in ("sun", "sunset", "moon", "space", "night")):
        mx, my = rng.uniform(W * 0.62, W * 0.82), rng.uniform(H * 0.16, H * 0.3)
        mr = rng.uniform(W * 0.035, W * 0.07)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gd.ellipse((mx - mr * 3, my - mr * 3, mx + mr * 3, my + mr * 3), fill=(255, 170, 100, 50))
        glow = glow.filter(ImageFilter.GaussianBlur(W // 45))
        image.alpha_composite(glow)
        draw.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(255, 223, 170, 220))
    # mountains / hills / dunes
    layers = 4
    for layer in range(layers):
        if any(word in lower for word in ("desert", "dune")):
            base_y = H * (0.58 + layer * 0.09)
            points = [(0, H)]
            for x in range(0, W + W // 12, W // 12):
                y = base_y + math.sin(x / W * (4 + layer * 2) + layer) * H * 0.025
                points.append((x, y))
            points += [(W, H)]
            color = (max(0, 55 - layer * 8), max(0, 42 - layer * 6), 45, 255)
        else:
            base_y = H * (0.56 + layer * 0.095)
            points = [(0, H)]
            for x in range(0, W + W // 10, W // 10):
                y = base_y - abs(math.sin(x / W * (6 + layer) + layer * 2.1)) * H * (0.09 + layer * 0.015)
                points.append((x, y))
            points += [(W, H)]
            shade = 38 - layer * 5
            color = (max(4, shade - 8), max(8, shade + 4), max(14, shade + 16), 255)
        draw.polygon(points, fill=color)
    # fog line
    fog = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fog)
    fd.rectangle((0, int(H * 0.52), W, int(H * 0.75)), fill=(180, 200, 230, 18))
    fog = fog.filter(ImageFilter.GaussianBlur(W // 50))
    image.alpha_composite(fog)
    # neon grid for cyber/city
    if any(word in lower for word in ("cyber", "neon", "city")):
        grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(grid)
        horizon = int(H * 0.62)
        for i in range(-12, 13):
            gd.line((W // 2 + i * W * 0.035, H, W // 2 + i * W * 0.11, horizon), fill=(53, 214, 196, 35), width=2)
        for i in range(1, 9):
            y = horizon + (H - horizon) * ((i / 8) ** 1.7)
            gd.line((0, y, W, y), fill=(255, 107, 74, 24), width=2)
        grid = grid.filter(ImageFilter.GaussianBlur(0.5))
        image.alpha_composite(grid)
    image = image.resize((width, height), Image.Resampling.LANCZOS)
    return image, {"seed": seed}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _ensure_output(path: Path) -> Path:
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def generate_sprite(
    prompt: str,
    output_path: str | Path,
    *,
    style: str = "flat",
    size: int = 256,
    image_config: dict[str, Any] | None = None,
    seed: int | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    prompt = prompt.strip()
    if not prompt:
        raise ValueError("Пустой промпт для спрайта.")
    style = style if style in STYLE_PROMPTS else "flat"
    size = max(64, min(1024, int(size)))
    config = image_config or {}
    output = _ensure_output(Path(output_path))
    seed_value = _stable_seed(prompt, style, seed)
    result = {
        "prompt": prompt,
        "style": style,
        "size": size,
        "seed": seed_value,
        "provider": config.get("provider", "procedural"),
        "fallback": False,
    }
    provider = config.get("provider", "procedural")
    remote_error = None
    if provider == "openai":
        remote_prompt = _remote_prompt(prompt, style, "sprite")
        try:
            image = _openai_image(remote_prompt, config, size=(size, size), kind="sprite")
            image = image.convert("RGBA")
            image = _chroma_key(image)
            image = _fit_canvas(image, size)
            image.save(output, "PNG")
            result.update({"path": str(output), "provider": provider, "message": "Спрайт сгенерирован ИИ-моделью."})
            return result
        except Exception as exc:
            remote_error = str(exc)
            if not allow_fallback:
                raise
    image, meta = procedural_sprite(prompt, style=style, size=size, seed=seed_value)
    image.save(output, "PNG")
    result.update(
        {
            "path": str(output),
            "fallback": bool(remote_error) or provider == "procedural",
            "provider": "procedural",
            "message": (
                "Использован офлайн-генератор спрайтов."
                if not remote_error
                else f"Сервер изображений недоступен ({remote_error[:200]}). Использован офлайн-генератор."
            ),
            "procedural_meta": meta,
        }
    )
    return result


def generate_background(
    prompt: str,
    output_path: str | Path,
    *,
    width: int = 1280,
    height: int = 720,
    image_config: dict[str, Any] | None = None,
    seed: int | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    prompt = prompt.strip() or "atmospheric fantasy landscape"
    width = max(320, min(1920, int(width)))
    height = max(240, min(1080, int(height)))
    output = _ensure_output(Path(output_path))
    config = image_config or {}
    seed_value = _stable_seed(prompt, "background", seed)
    result = {
        "prompt": prompt,
        "width": width,
        "height": height,
        "seed": seed_value,
        "provider": config.get("provider", "procedural"),
        "fallback": False,
    }
    provider = config.get("provider", "procedural")
    remote_error = None
    if provider == "openai":
        remote_prompt = _remote_prompt(prompt, "flat", "background")
        try:
            image = _openai_image(remote_prompt, config, size=(width, height), kind="background")
            image = image.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
            image.save(output, "PNG")
            result.update({"path": str(output), "provider": provider, "message": "Фон сгенерирован ИИ-моделью."})
            return result
        except Exception as exc:
            remote_error = str(exc)
            if not allow_fallback:
                raise
    image, meta = procedural_background(prompt, width=width, height=height, seed=seed_value)
    image.save(output, "PNG")
    result.update(
        {
            "path": str(output),
            "fallback": bool(remote_error) or provider == "procedural",
            "provider": "procedural",
            "message": (
                "Использован офлайн-генератор фонов."
                if not remote_error
                else f"Сервер изображений недоступен ({remote_error[:200]}). Использован офлайн-генератор."
            ),
            "procedural_meta": meta,
        }
    )
    return result


def generate_icon(
    prompt: str,
    output_path: str | Path,
    *,
    style: str = "icon",
    size: int = 512,
    image_config: dict[str, Any] | None = None,
    seed: int | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    result = generate_sprite(
        prompt,
        output_path,
        style="icon",
        size=size,
        image_config=image_config,
        seed=seed,
        allow_fallback=allow_fallback,
    )
    return result
