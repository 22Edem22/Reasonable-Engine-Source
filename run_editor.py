"""Launch the Reasonable Engine editor from the repository root.

The ``--self-test`` flag is used by the Windows EXE builder. It verifies that
the frozen application can find its bundled assets, templates, documentation
and engine source, then creates a real project to exercise ``vendor_engine``.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
import warnings
from pathlib import Path

# pygame may pull in the deprecated pkg_resources module; keep that specific
# harmless warning out of the user's console.
warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API.*",
    category=UserWarning,
)


def _self_test() -> int:
    """Create a project and verify everything a frozen editor needs."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report_path = Path(
        os.environ.get("REASONABLE_SELF_TEST_REPORT")
        or (Path(tempfile.gettempdir()) / "reasonable-editor-self-test.json")
    )
    home = Path(tempfile.mkdtemp(prefix="reasonable-self-test-"))
    os.environ["REASONABLE_HOME"] = str(home)
    checks: list[dict] = []
    error = ""
    app = None
    window = None

    def log(message: str) -> None:
        if sys.stdout is not None:
            try:
                print(message, flush=True)
            except Exception:
                pass

    def check(name: str, condition: bool, detail: str = "") -> bool:
        checks.append({"name": name, "ok": bool(condition), "detail": str(detail)})
        log(("OK   " if condition else "FAIL ") + name + (f" — {detail}" if detail else ""))
        return bool(condition)

    try:
        from reasonable.version import VERSION

        log(f"Reasonable Engine {VERSION} self-test")
        log(f"Frozen: {bool(getattr(sys, 'frozen', False))} · executable: {sys.executable}")

        from reasonable.core.paths import (
            BRAND_DIR,
            DOCS_DIR,
            ENGINE_ROOT,
            FONT_DIR,
            TEMPLATES_DIR,
        )

        resources = {
            "README.md": ENGINE_ROOT / "README.md",
            "brand logo": BRAND_DIR / "logo_256.png",
            "brand icon": BRAND_DIR / "logo.ico",
            "Inter font": FONT_DIR / "Inter-Variable.ttf",
            "game template": TEMPLATES_DIR / "game" / "main.py",
            "app template": TEMPLATES_DIR / "app" / "main.py",
            "external-agent docs": DOCS_DIR / "EXTERNAL_AGENTS.md",
            "architecture docs": DOCS_DIR / "ARCHITECTURE.md",
        }
        for name, path in resources.items():
            check(f"resource: {name}", path.is_file(), str(path))

        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        from reasonable.editor import theme

        theme.apply_theme(app)
        from reasonable.editor.main_window import MainWindow

        window = MainWindow()
        check("editor window constructs", window is not None, "offscreen PySide6")
        window.close()
        window.deleteLater()
        window = None
        app.processEvents()

        from reasonable.core.project import Project, default_manifest

        from reasonable.core.paths import (
            bundled_python,
            default_projects_dir,
            install_root,
            player_executable,
            project_launch_command,
        )

        if getattr(sys, "frozen", False):
            check("player executable present", player_executable() is not None, str(player_executable()))
            # A standalone EXE build has no runtime folder; the installer adds
            # it. Verify the bundled interpreter only where it should exist.
            if (install_root() / "runtime").is_dir():
                check("bundled python present", bundled_python() is not None, str(bundled_python()))
        projects_dir = default_projects_dir()
        check(
            "default projects folder inside install",
            not getattr(sys, "frozen", False) or projects_dir.parent == install_root(),
            str(projects_dir),
        )

        project_root = home / "projects" / "self-test"
        project = Project.create(
            project_root,
            default_manifest(
                "Self test",
                project_type="game",
                mode="external",
                goal="Проверка упакованного редактора",
                notes="Материалы проверки EXE.",
                width=960,
                height=540,
                window_mode="fullscreen",
                resizable=False,
                orientation="landscape",
            ),
        )
        check("project/main.py", project.entry.is_file(), str(project.entry))
        check("project/project.json", (project.root / "project.json").is_file())
        check("project/agent guide", (project.root / "AGENT_GUIDE.md").is_file())
        check("project/agent skills", (project.root / "skills").is_dir())
        check("project/re.bat", (project.root / "re.bat").is_file())
        check("project/vendored engine", project.has_vendored_engine(), str(project.root / "_engine"))
        for relative in (
            "runtime/app",
            "ai/agent",
            "core/project",
            "core/scaffold",
        ):
            python_file = project.root / "_engine" / "reasonable" / f"{relative}.py"
            bytecode_file = project.root / "_engine" / "reasonable" / f"{relative}.pyc"
            check(
                f"vendored: {relative}",
                python_file.is_file() or bytecode_file.is_file(),
                str(bytecode_file if bytecode_file.is_file() else python_file),
            )
        check("vendored editor omitted", not (project.root / "_engine" / "reasonable" / "editor").exists())
        vendored_source = list((project.root / "_engine" / "reasonable").rglob("*.py"))
        check(
            "vendored source protected in frozen build",
            not getattr(sys, "frozen", False) or not vendored_source,
            f"{len(vendored_source)} .py files",
        )
        check("window fullscreen", project.window_mode == "fullscreen", project.window_mode)
        check("window resizable", not project.resizable, str(project.resizable))
        check("project notes", project.notes == "Материалы проверки EXE.", project.notes)

        compile(project.entry.read_text(encoding="utf-8"), str(project.entry), "exec")
        check("project source compiles", True)
        launch = project_launch_command(project.entry)
        check("project launch command", bool(launch), " ".join(launch))
        if getattr(sys, "frozen", False):
            check(
                "project launch is not the editor",
                Path(launch[0]).resolve() != Path(sys.executable).resolve(),
                launch[0],
            )
        issues = project.validate()
        errors = [issue.message for issue in issues if issue.level == "error"]
        check("project validates", not errors, "; ".join(errors))

        from reasonable.core.convert import convert_project

        converted_result = convert_project(
            project,
            "android",
            name="Self test Android",
            output=home / "converted",
            orientation="portrait",
        )
        converted = Project.load(converted_result["path"])
        check("conversion creates project", converted.root.is_dir(), str(converted.root))
        check("conversion platform", converted.platform == "android", converted.platform)
        check("conversion orientation", converted.orientation == "portrait", converted.orientation)
        check(
            "conversion portrait window",
            converted.window["width"] < converted.window["height"],
            f"{converted.window['width']}x{converted.window['height']}",
        )
        check("conversion agent pack", (converted.root / "AGENT_GUIDE.md").is_file())
        check("conversion report", (converted.root / "CONVERSION.md").is_file())
        check("conversion vendored engine", converted.has_vendored_engine())
        check("source project untouched", project.platform == "windows", project.platform)
    except Exception:
        error = traceback.format_exc()
        log(error)
    finally:
        ok = bool(checks) and all(item["ok"] for item in checks) and not error
        report = {
            "ok": ok,
            "version": _version_safe(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "executable": sys.executable,
            "engine_root": str(_engine_root_safe()),
            "checks": checks,
            "error": error,
        }
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            log(f"Report: {report_path}")
        except OSError as exc:
            log(f"Не удалось записать отчёт self-test: {exc}")
            ok = False
        if window is not None:
            try:
                window.close()
                window.deleteLater()
            except Exception:
                pass
        if app is not None:
            try:
                app.processEvents()
            except Exception:
                pass
        import shutil

        shutil.rmtree(home, ignore_errors=True)
        log("SELF-TEST OK" if ok else "SELF-TEST FAILED")
    return 0 if ok else 1


def _version_safe() -> str:
    try:
        from reasonable.version import VERSION

        return VERSION
    except Exception:
        return "unknown"


def _engine_root_safe() -> str:
    try:
        from reasonable.core.paths import ENGINE_ROOT

        return str(ENGINE_ROOT)
    except Exception:
        return ""


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        return _self_test()
    try:
        from reasonable.editor import main as editor_main
    except ImportError as exc:
        print(
            "Reasonable Engine: редактор не запущен.\n"
            f"Причина: {exc}\n\n"
            "Установите зависимости:\n"
            "  python -m pip install -r requirements.txt\n",
            file=sys.stderr,
        )
        return 1
    return editor_main()


if __name__ == "__main__":
    raise SystemExit(main())
