"""Tests for the scene document format, the runtime loader and the scene editor."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pygame

from reasonable.core.project import Project, default_manifest
from reasonable.core.scene import (
    create_scene,
    delete_scene,
    duplicate_scene,
    ensure_scene,
    list_scenes,
    load_scene,
    new_object,
    new_scene,
    normalize_scene,
    rename_scene,
    save_scene,
    scene_path,
)
from reasonable.runtime.scenes import build_scene_objects, load_scene_data, scene_background

try:
    from PySide6.QtWidgets import QApplication

    PYSIDE_AVAILABLE = True
except ImportError:  # pragma: no cover - editor is optional for headless CI
    PYSIDE_AVAILABLE = False


class SceneFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_scene_round_trip_keeps_objects(self) -> None:
        scene = new_scene((800, 600))
        scene["objects"].append(new_object("rect", index=1, x=10, y=20, w=80, h=40))
        scene["objects"].append(new_object("text", index=2, text="Привет", x=5, y=90))
        path = save_scene(self.root, scene)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.name, "scenes")

        loaded = load_scene(self.root)
        self.assertEqual(loaded["size"], [800, 600])
        self.assertEqual([item["kind"] for item in loaded["objects"]], ["rect", "text"])
        self.assertEqual(loaded["objects"][1]["text"], "Привет")
        self.assertEqual(loaded["objects"][0]["x"], 10.0)

    def test_missing_scene_returns_default(self) -> None:
        scene = load_scene(self.root, "missing", size=(640, 360))
        self.assertEqual(scene["objects"], [])
        self.assertEqual(scene["size"], [640, 360])

    def test_damaged_scene_is_repaired(self) -> None:
        path = scene_path(self.root, "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"objects": [{"kind": "nonsense"}, 5, {"kind": "rect", "w": -4}]}', encoding="utf-8")
        scene = load_scene(self.root, "broken")
        self.assertEqual(len(scene["objects"]), 2)
        self.assertTrue(all(item["kind"] in {"rect", "circle", "text", "image"} for item in scene["objects"]))
        self.assertGreater(scene["objects"][1]["w"], 0)

    def test_scene_name_is_sanitised(self) -> None:
        path = save_scene(self.root, new_scene(), "../../evil name")
        self.assertEqual(path.parent.name, "scenes")
        self.assertNotIn("..", path.name)

    def test_multiple_scenes_can_be_created_renamed_duplicated_deleted(self) -> None:
        level = create_scene(self.root, "Level One", template="level")
        boss = create_scene(self.root, "Boss Room", template="menu")
        self.assertEqual(level["id"], "level-one")
        self.assertGreater(len(level["scene"]["objects"]), 5)
        self.assertEqual([row["id"] for row in list_scenes(self.root)], ["boss-room", "level-one"])

        self.assertTrue(rename_scene(self.root, "boss-room", "Final Battle"))
        self.assertEqual(load_scene(self.root, "boss-room")["name"], "Final Battle")

        copy = duplicate_scene(self.root, "level-one", "Level One Copy")
        self.assertIsNotNone(copy)
        self.assertEqual(copy["title"], "Level One Copy")
        self.assertEqual(len(list_scenes(self.root)), 3)

        self.assertTrue(delete_scene(self.root, "boss-room"))
        self.assertEqual(len(list_scenes(self.root)), 2)

    def test_ensure_scene_creates_main_for_an_empty_project(self) -> None:
        created = ensure_scene(self.root, project_type="game", size=(800, 600))
        self.assertEqual(created["id"], "main")
        self.assertTrue((self.root / "scenes" / "main.json").is_file())
        self.assertEqual(load_scene(self.root, "main")["size"], [800, 600])


class RuntimeSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.display.set_mode((320, 240))

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_nodes_are_built_and_sorted_by_layer(self) -> None:
        data = {
            "background": "#101820",
            "objects": [
                {"id": "a", "name": "Top", "kind": "circle", "x": 10, "y": 10, "w": 40, "h": 40, "z": 5},
                {"id": "b", "name": "Bottom", "kind": "rect", "x": 0, "y": 0, "w": 20, "h": 20, "z": -1},
                {"id": "c", "name": "Caption", "kind": "text", "x": 4, "y": 50, "w": 200, "h": 30, "text": "Hi"},
                {"id": "d", "name": "Hidden", "kind": "rect", "x": 0, "y": 0, "visible": False},
            ],
        }
        nodes = build_scene_objects(data)
        self.assertEqual([node.name for node in nodes], ["Bottom", "Caption", "Hidden", "Top"])
        self.assertEqual([type(node).__name__ for node in nodes], ["Shape", "Text", "Shape", "Shape"])
        self.assertFalse(nodes[2].visible)
        self.assertEqual(scene_background(data)[:3], (16, 24, 32))

    def test_panel_objects_keep_their_corner_radius(self) -> None:
        nodes = build_scene_objects(
            {
                "objects": [
                    {
                        "kind": "panel",
                        "x": 10,
                        "y": 20,
                        "w": 200,
                        "h": 100,
                        "radius": 18,
                    }
                ]
            }
        )
        self.assertEqual(len(nodes), 1)
        self.assertEqual(type(nodes[0]).__name__, "Shape")
        self.assertEqual(nodes[0].shape, "rect")
        self.assertEqual(nodes[0].radius, 18)

    def test_missing_image_object_is_skipped(self) -> None:
        nodes = build_scene_objects(
            {"objects": [{"kind": "image", "asset": "assets/nope.png", "w": 20, "h": 20}]}
        )
        self.assertEqual(nodes, [])

    def test_invalid_file_returns_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_scene_data(path)["objects"], [])


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class SceneEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from reasonable.editor import theme

        cls.app = QApplication.instance() or QApplication([])
        theme.apply_theme(cls.app)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "scene-project"
        self.project = Project.create(root, default_manifest("Scene Test"), scaffold=False)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_add_move_and_save(self) -> None:
        from reasonable.editor.scene_editor import SceneEditorPage

        page = SceneEditorPage(self.project)
        try:
            page._quick_add("rect")
            self.assertEqual(len(page.scene["objects"]), 1)
            item = page.scene["objects"][0]
            self.assertEqual(item["kind"], "rect")
            self.assertEqual(page.list.count(), 1)

            page.x_spin.setValue(123)
            page.y_spin.setValue(45)
            page._apply_fields()
            self.assertEqual(item["x"], 123.0)
            self.assertEqual(item["y"], 45.0)

            page.viewport.duplicate_selected()
            self.assertEqual(len(page.scene["objects"]), 2)
            page.viewport.delete_selected()
            self.assertEqual(len(page.scene["objects"]), 1)

            page.save_now()
            loaded = load_scene(self.project.root)
            self.assertEqual(len(loaded["objects"]), 1)
            self.assertEqual(loaded["objects"][0]["x"], 123.0)
        finally:
            page.shutdown()
            page.deleteLater()
            self.app.processEvents()

    def test_empty_main_scene_of_a_real_game_is_filled_with_a_starter(self) -> None:
        from reasonable.editor.scene_editor import SceneEditorPage

        self.project.manifest["engine_version"] = "RE-2.02"
        self.project.save()
        save_scene(self.project.root, new_scene((1280, 720), "Main"), "main")
        page = SceneEditorPage(self.project)
        try:
            self.assertEqual(page.scene_name, "main")
            self.assertGreaterEqual(len(page.scene["objects"]), 10)
            self.assertEqual(page.scene.get("template"), "level")
        finally:
            page.shutdown()
            page.deleteLater()
            self.app.processEvents()

    def test_scene_tabs_switch_scenes_and_empty_state(self) -> None:
        from reasonable.editor.scene_editor import SceneEditorPage

        page = SceneEditorPage(self.project)
        try:
            self.assertEqual(page.scene_tabs.count(), 1)
            self.assertFalse(page.empty_panel.isHidden())
            create_scene(self.project.root, "Boss", template="level")
            create_scene(self.project.root, "Blank", template="empty")
            page._refresh_scene_tabs("main")
            self.assertEqual(page.scene_tabs.count(), 3)

            page._open_scene("blank")
            self.assertEqual(page.scene_name, "blank")
            self.assertEqual(page.scene["objects"], [])
            self.assertFalse(page.empty_panel.isHidden())

            page._open_scene("boss")
            self.assertEqual(len(page.scene["objects"]), 12)
            self.assertTrue(page.empty_panel.isHidden())
        finally:
            page.shutdown()
            page.deleteLater()
            self.app.processEvents()

    def test_drag_creation_uses_the_drawn_rectangle(self) -> None:
        from PySide6.QtCore import QPointF

        from reasonable.editor.scene_editor import SceneEditorPage

        page = SceneEditorPage(self.project)
        try:
            page.viewport.snap = True
            page.viewport._finish_create(
                {
                    "kind": "rect",
                    "start": QPointF(10, 20),
                    "current": QPointF(122, 94),
                }
            )
            self.assertEqual(len(page.scene["objects"]), 1)
            item = page.scene["objects"][0]
            self.assertEqual((item["x"], item["y"]), (0.0, 32.0))
            self.assertEqual((item["w"], item["h"]), (128.0, 64.0))
        finally:
            page.shutdown()
            page.deleteLater()
            self.app.processEvents()

    def test_snap_rounds_to_grid(self) -> None:
        from reasonable.editor.scene_editor import SceneEditorPage

        page = SceneEditorPage(self.project)
        try:
            page.viewport.snap = True
            self.assertEqual(page.viewport._snap_value(37), 32)
            page.viewport.snap = False
            self.assertEqual(page.viewport._snap_value(37), 37)
        finally:
            page.shutdown()
            page.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
