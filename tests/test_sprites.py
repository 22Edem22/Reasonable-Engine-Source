import tempfile
import unittest
from pathlib import Path

from PIL import Image

from reasonable.ai.sprites import generate_background, generate_icon, generate_sprite


class SpriteTests(unittest.TestCase):
    def test_procedural_sprite_is_transparent_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "star.png"
            result = generate_sprite(
                "золотая звезда с мягким свечением",
                target,
                style="flat",
                size=128,
                image_config={"provider": "procedural"},
                seed=7,
            )
            self.assertTrue(target.is_file())
            self.assertEqual(result["provider"], "procedural")
            self.assertEqual(result["seed"], 7)
            with Image.open(target) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.size, (128, 128))
                alpha = image.getchannel("A")
                bbox = alpha.getbbox()
                self.assertIsNotNone(bbox)
                self.assertGreater(bbox[2] - bbox[0], 20)
                self.assertGreater(bbox[3] - bbox[1], 20)
                self.assertEqual(alpha.getpixel((0, 0)), 0)

    def test_seed_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.png"
            second = Path(tmp) / "b.png"
            result_a = generate_sprite("синий кристалл", first, size=64, image_config={"provider": "procedural"})
            result_b = generate_sprite("синий кристалл", second, size=64, image_config={"provider": "procedural"})
            self.assertEqual(result_a["seed"], result_b["seed"])
            self.assertEqual(first.read_bytes(), second.read_bytes())

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

    def test_procedural_icon(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "icon.png"
            generate_icon("иконка приложения", target, size=128, image_config={"provider": "procedural"})
            with Image.open(target) as image:
                self.assertEqual(image.size, (128, 128))


if __name__ == "__main__":
    unittest.main()
