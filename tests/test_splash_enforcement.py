"""The splash is enforced by the runtime, not by project flags."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


class SplashEnforcementTests(unittest.TestCase):
    def test_splash_false_is_ignored(self) -> None:
        from reasonable.runtime import UIApp

        app = UIApp("Splash test", (320, 240), splash=False)
        self.assertTrue(app.splash)

    def test_splash_caption_uses_the_current_generation(self) -> None:
        from reasonable import VERSION_NAME
        from reasonable.branding import APP_NAME
        from reasonable.runtime.splash import SplashAnimator

        animator = SplashAnimator(320, 240)
        self.assertEqual(animator.caption, f"{APP_NAME.upper()} {VERSION_NAME}")
        self.assertFalse(animator.caption.endswith(" 1"))

    def test_play_splash_marks_the_process_and_cannot_be_skipped_by_flag(self) -> None:
        from reasonable.runtime import splash

        splash._SPLASH_PLAYED = False
        self.assertFalse(splash.splash_played())
        self.assertTrue(splash.play_splash((320, 240)))
        self.assertTrue(splash.splash_played())

    def test_app_run_always_calls_the_splash_even_with_false_flag(self) -> None:
        import reasonable.runtime.app as app_module

        calls: list[int] = []
        original_play = app_module.play_splash
        original_played = app_module.splash_played
        original_frames = os.environ.get("RE_FRAMES")
        app_module.play_splash = lambda *args, **kwargs: calls.append(1) or True
        app_module.splash_played = lambda: False
        os.environ["RE_FRAMES"] = "1"
        try:
            app = app_module.App("Splash test", (320, 240), splash=False)
            app.run()
        finally:
            app_module.play_splash = original_play
            app_module.splash_played = original_played
            if original_frames is None:
                os.environ.pop("RE_FRAMES", None)
            else:
                os.environ["RE_FRAMES"] = original_frames
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
