import tempfile
import unittest
from pathlib import Path

from PIL import Image

from reasonable.ai.drawing import DrawingError, draw_sprite
from reasonable.ai.sprites import generate_background, generate_sprite


class SpriteTests(unittest.TestCase):
    def test_draw_shapes_sprite_is_transparent_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "heart.png"
            result = draw_sprite(
                target,
                size=128,
                shapes=[
                    {"type": "ellipse", "center": [36, 40], "radius": [22, 22], "fill": "#E63946"},
                    {"type": "ellipse", "center": [64, 40], "radius": [22, 22], "fill": "#E63946"},
                    {"type": "polygon", "points": [[16, 44], [84, 44], [50, 88]], "fill": "#E63946"},
                    {"type": "polygon", "points": [[30, 28], [40, 20], [47, 34]], "fill": "#FF8FA3", "opacity": 0.7},
                ],
            )
            self.assertTrue(target.is_file())
            self.assertEqual(result["provider"], "draw")
            with Image.open(target) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (128, 128))
                alpha = image.getchannel("A")
                bbox = alpha.getbbox()
                self.assertIsNotNone(bbox)
                self.assertGreater(bbox[2] - bbox[0], 20)
                self.assertGreater(bbox[3] - bbox[1], 20)
                self.assertEqual(alpha.getpixel((0, 0)), 0)

    def test_draw_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.png"
            second = Path(tmp) / "b.png"
            shapes = [
                {"type": "rounded_rect", "box": [20, 20, 80, 80], "radius": 12, "fill": "#3F86FF"},
                {"type": "circle", "center": [50, 50], "radius": 10, "fill": "#FFD447"},
            ]
            draw_sprite(first, shapes=shapes, size=64)
            draw_sprite(second, shapes=shapes, size=64)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_pixel_grid_uses_palette(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pixel.png"
            result = draw_sprite(
                target,
                mode="pixels",
                size=64,
                pixels=[
                    "..XX..",
                    ".XOOX.",
                    "XOOOOX",
                    ".XOOX.",
                    "..XX..",
                ],
                palette={"X": "#3A2418", "O": "#FF6B4A"},
            )
            self.assertEqual(result["mode"], "pixels")
            with Image.open(target) as image:
                self.assertEqual(image.mode, "RGBA")
                colors = {color for _count, color in image.convert("RGB").getcolors(maxcolors=100000)}
                self.assertIn((255, 107, 74), colors)
                self.assertIn((58, 36, 24), colors)

    def test_gradient_fill_and_outline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "orb.png"
            result = draw_sprite(
                target,
                size=96,
                shapes=[
                    {
                        "type": "circle",
                        "center": [50, 50],
                        "radius": 35,
                        "fill": {"type": "radial", "from": "#FFF3B0", "to": "#C2410C", "radius": 45},
                        "outline": "#2B1608",
                        "outline_width": 2,
                    }
                ],
            )
            self.assertEqual(result["mode"], "shapes")
            with Image.open(target) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertIsNotNone(image.getchannel("A").getbbox())

    def test_invalid_drawing_description_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bad.png"
            with self.assertRaises(DrawingError):
                draw_sprite(target, shapes=[{"type": "triangle", "points": [[0, 0], [1, 1], [2, 2]]}])
            with self.assertRaises(DrawingError):
                draw_sprite(target, mode="pixels", pixels=["XX", "X"], palette={"X": "#000000"})
            self.assertFalse(target.exists())

    def test_generate_sprite_requires_an_external_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "star.png"
            with self.assertRaises(RuntimeError) as raised:
                generate_sprite("золотая звезда", target, image_config={"provider": "procedural"})
            self.assertIn("draw_sprite", str(raised.exception))
            self.assertFalse(target.exists())

    def test_procedural_background_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "forest.png"
            result = generate_background(
                "ночной лес со светлячками",
                target,
                width=320,
                height=240,
                image_config={"provider": "procedural"},
                seed=11,
            )
            self.assertTrue(target.is_file())
            self.assertEqual(result["provider"], "procedural")
            with Image.open(target) as image:
                self.assertEqual(image.size, (320, 240))
                self.assertIn(image.mode, {"RGB", "RGBA"})


if __name__ == "__main__":
    unittest.main()
