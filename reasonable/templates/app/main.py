"""__APP_TITLE__ — приложение, созданное в Reasonable Engine.

Запуск:  python main.py
Это готовый пример красивого десктопного приложения с сохранением данных и
встроенным ИИ-ассистентом. Меняйте код или попросите агента доработать его.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

import pygame

from reasonable.runtime import (
    AIChatPanel,
    AIConfig,
    Button,
    Entry,
    HStack,
    Icon,
    IconButton,
    ImageWidget,
    Label,
    Panel,
    ProgressBar,
    ScrollView,
    Spacer,
    Theme,
    UIApp,
    VStack,
    Widget,
    draw_icon,
    draw_rounded_rect,
    ellipsis,
    get_font,
    with_alpha,
)

APP_NAME = __APP_NAME_REPR__


def window_settings() -> tuple[tuple[int, int], bool, bool]:
    """Read window preferences from project.json with safe defaults."""
    data = {}
    try:
        data = json.loads((PROJECT_DIR / "project.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    window = data.get("window") if isinstance(data, dict) else {}
    window = window if isinstance(window, dict) else {}
    try:
        width = max(320, int(window.get("width") or __WINDOW_WIDTH__))
        height = max(240, int(window.get("height") or __WINDOW_HEIGHT__))
    except (TypeError, ValueError):
        width, height = __WINDOW_WIDTH__, __WINDOW_HEIGHT__
    resizable = bool(window.get("resizable", __WINDOW_RESIZABLE__))
    fullscreen = str(window.get("mode") or "windowed").lower() == "fullscreen"
    if not window.get("mode"):
        fullscreen = __WINDOW_FULLSCREEN__
    return (width, height), resizable, fullscreen


WINDOW_SIZE, WINDOW_RESIZABLE, WINDOW_FULLSCREEN = window_settings()
DATA_FILE = PROJECT_DIR / "data.json"

# The runtime theme is already graphite with one warm accent. A generated app
# only adjusts shape and density; it does not introduce a second palette.
THEME = Theme()
THEME.radius = 20
THEME.radius_sm = 13


def load_data() -> dict:
    default = {
        "tasks": [
            {"id": 1, "title": "Придумать идею проекта", "done": True},
            {"id": 2, "title": "Собрать первый прототип", "done": False},
            {"id": 3, "title": "Попросить ИИ-ассистента улучшить интерфейс", "done": False},
        ],
        "streak": 3,
    }
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return default


def save_data(data: dict) -> None:
    try:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


class TaskRow(Widget):
    def __init__(self, task: dict, on_toggle, on_delete, **kwargs) -> None:
        super().__init__(height=66, **kwargs)
        self.task = task
        self.on_toggle = on_toggle
        self.on_delete = on_delete
        self._hover_delete = False
        self._font = get_font(15, bold=False)
        self._title_font = get_font(15, bold=True)

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (max_width, 66)

    def _checkbox(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x + 16, self.rect.centery - 12, 24, 24)

    def _delete(self) -> pygame.Rect:
        return pygame.Rect(self.rect.right - 48, self.rect.centery - 16, 32, 32)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            self._hover_delete = self._delete().collidepoint(event.pos)
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.rect.collidepoint(event.pos):
            if self._checkbox().inflate(16, 16).collidepoint(event.pos):
                self.on_toggle(self.task)
                return True
            if self._delete().collidepoint(event.pos):
                self.on_delete(self.task)
                return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        done = bool(self.task.get("done"))
        bg = with_alpha(self.theme.text, 10) if self.hovered else self.theme.panel_alt
        draw_rounded_rect(surface, self.rect, bg, 16, border=with_alpha(self.theme.border, 170))
        box = self._checkbox()
        if done:
            draw_rounded_rect(surface, box, self.theme.accent, 8)
            draw_icon(surface, "check", box.inflate(-6, -6), self.theme.on_accent, 2)
        else:
            draw_rounded_rect(surface, box, with_alpha(self.theme.text, 12), 8, border=self.theme.border)
        color_value = self.theme.muted if done else self.theme.text
        text = ellipsis(self.task.get("title", ""), self._title_font, max(40, self.rect.width - 140))
        image = self._title_font.render(text, True, color_value)
        surface.blit(image, (self.rect.x + 56, self.rect.centery - image.get_height() // 2))
        if done:
            y = self.rect.centery
            pygame.draw.line(surface, self.theme.muted, (self.rect.x + 56, y), (self.rect.x + 56 + image.get_width(), y), 1)
        if self.hovered or self._hover_delete:
            draw_icon(surface, "close" if not self._hover_delete else "stop", self._delete().inflate(-8, -8), self.theme.danger if self._hover_delete else self.theme.faint, 2)


class PlannerApp(UIApp):
    def __init__(self) -> None:
        super().__init__(
            APP_NAME,
            WINDOW_SIZE,
            theme=THEME,
            splash=True,
            splash_accent="#D97757",
            resizable=WINDOW_RESIZABLE,
            fullscreen=WINDOW_FULLSCREEN,
        )
        self.data = load_data()
        self.filter = "all"
        self.tasks: list[dict] = list(self.data.get("tasks", []))
        self.next_id = max([int(task.get("id", 0)) for task in self.tasks] or [0]) + 1
        self.task_rows: list[TaskRow] = []
        self.ai_panel: AIChatPanel | None = None
        self.main_title: Label | None = None
        self.counter_label: Label | None = None
        self.progress: ProgressBar | None = None
        self.streak_label: Label | None = None
        self.empty_label: Label | None = None

    # ------------------------------------------------------------------
    def build_ui(self):
        root = HStack(spacing=0, padding=0)
        sidebar = self.build_sidebar()
        main = self.build_main()
        right = self.build_assistant()
        root.add(sidebar, main, right)
        return root

    def build_sidebar(self) -> Panel:
        side = Panel(padding=24, spacing=18, background=(18, 20, 25), border=None, radius=0, shadow=False, width=250)
        brand = HStack(spacing=10, align_y="center")
        logo = ImageWidget(PROJECT_DIR / "assets" / "icon.png", width=44, height=44, radius=12)
        brand.add(logo, VStack(spacing=0, align_x="left").add(Label("REASONABLE", size=12, bold=True, color_value=THEME.accent), Label(APP_NAME, size=15, bold=True)))
        side.add(brand)
        side.add(Widget(height=8))
        side.add(Label("ПРОСТРАНСТВО", size=10, bold=True, color_value=THEME.faint))
        self.filter = "all"
        self.filter_buttons: dict[str, Button] = {}
        for key, text, icon in (("all", "Все задачи", "home"), ("active", "В работе", "spark"), ("done", "Готово", "check")):
            button = Button(text, on_click=lambda k=key: self.set_filter(k), variant="ghost" if key != "all" else "secondary", icon=icon, height=44)
            self.filter_buttons[key] = button
            side.add(button)
        side.add(Widget(height=10))
        stat_panel = Panel(padding=16, spacing=6, background=THEME.panel_alt, radius=16, shadow=False)
        stat_panel.add(Label("ПРОГРЕСС ДНЯ", size=10, bold=True, color_value=THEME.faint))
        self.progress = ProgressBar(0, height=8, color_value=THEME.accent)
        stat_panel.add(self.progress)
        self.counter_label = Label("0 из 0 задач", size=12, color_value=THEME.muted)
        stat_panel.add(self.counter_label)
        side.add(stat_panel)
        side.add(Spacer())
        streak = Panel(padding=14, spacing=4, background=with_alpha(THEME.accent, 22), border=with_alpha(THEME.accent, 50), radius=14, shadow=False)
        self.streak_label = Label(f"Серия: {self.data.get('streak', 0)} дня подряд", size=12, bold=True, color_value=THEME.accent)
        streak.add(self.streak_label)
        side.add(streak)
        side.add(Label("Создано в Reasonable Engine", size=10, color_value=THEME.faint))
        return side

    def build_main(self) -> Panel:
        main = Panel(padding=30, spacing=16, background=(15, 17, 21), border=None, radius=0, shadow=False, expand_x=True)
        header = HStack(spacing=12, align_y="center")
        titles = VStack(spacing=2, align_x="left")
        self.main_title = Label("Планы на сегодня", size=32, bold=True, display=True)
        titles.add(self.main_title)
        titles.add(Label(time.strftime("%A, %d %B").capitalize(), size=13, color_value=THEME.muted))
        header.add(titles, Spacer(), IconButton("plus", self.focus_entry, size=44, variant="primary"))
        main.add(header)
        entry_row = HStack(spacing=10, align_y="center")
        self.entry = Entry("Что нужно сделать?", on_submit=lambda _value=None: self.add_task())
        self.entry.expand_x = True
        add_button = Button("Добавить", self.add_task, icon="plus", height=48)
        entry_row.add(self.entry, add_button)
        main.add(entry_row)
        self.empty_label = Label("Здесь пока пусто. Добавьте задачу или попросите ИИ составить план.", size=14, color_value=THEME.faint, align="center")
        self.empty_label.visible = False
        main.add(self.empty_label)
        self.list_stack = VStack(spacing=10)
        self.scroll = ScrollView(self.list_stack, expand_y=True)
        main.add(self.scroll)
        self.refresh_tasks()
        return main

    def build_assistant(self) -> Panel:
        wrapper = Panel(padding=0, spacing=0, background=(19, 21, 26), border=None, radius=0, shadow=False, width=370)
        config = AIConfig.load(APP_NAME, PROJECT_DIR)
        config.system_prompt = (
            "Ты — ИИ-ассистент внутри приложения-планировщика, созданного в Reasonable Engine. "
            "Помогай пользователю планировать день, формулировать задачи и разбивать большие цели на шаги. "
            "Отвечай по-русски, кратко и практично. При необходимости предлагай список задач."
        )
        config.title = "Помощник"
        self.ai_panel = AIChatPanel(
            config,
            app_name=APP_NAME,
            greeting="Привет! Помогу спланировать день и разбить большие задачи на маленькие шаги. С чего начнём?",
            padding=18,
            spacing=12,
        )
        self.ai_panel.expand_y = True
        self.ai_panel.expand_x = True
        wrapper.add(self.ai_panel)
        return wrapper

    # ------------------------------------------------------------------
    def focus_entry(self) -> None:
        self.entry.focus()

    def add_task(self) -> None:
        title = self.entry.value.strip()
        if not title:
            return
        self.tasks.insert(0, {"id": self.next_id, "title": title, "done": False})
        self.next_id += 1
        self.entry.set_value("")
        self.persist()
        self.refresh_tasks()

    def toggle_task(self, task: dict) -> None:
        task["done"] = not bool(task.get("done"))
        self.persist()
        self.refresh_tasks()

    def delete_task(self, task: dict) -> None:
        self.tasks = [item for item in self.tasks if item.get("id") != task.get("id")]
        self.persist()
        self.refresh_tasks()

    def set_filter(self, key: str) -> None:
        self.filter = key
        for name, button in getattr(self, "filter_buttons", {}).items():
            button.variant = "secondary" if name == key else "ghost"
        self.refresh_tasks()

    def visible_tasks(self) -> list[dict]:
        if self.filter == "active":
            return [task for task in self.tasks if not task.get("done")]
        if self.filter == "done":
            return [task for task in self.tasks if task.get("done")]
        return list(self.tasks)

    def refresh_tasks(self) -> None:
        self.task_rows.clear()
        self.list_stack.clear()
        for task in self.visible_tasks():
            row = TaskRow(task, self.toggle_task, self.delete_task)
            self.task_rows.append(row)
            self.list_stack.add(row)
        done_count = sum(1 for task in self.tasks if task.get("done"))
        total = len(self.tasks)
        percent = (done_count / total * 100) if total else 0
        if self.progress:
            self.progress.set_value(percent)
        if self.counter_label:
            self.counter_label.set_text(f"{done_count} из {total} задач")
        if self.empty_label:
            self.empty_label.visible = not self.visible_tasks()
        if self.main_title:
            self.main_title.set_text({"all": "Планы на сегодня", "active": "В работе", "done": "Готовые задачи"}[self.filter])

    def persist(self) -> None:
        self.data["tasks"] = self.tasks
        save_data(self.data)

    def on_update(self, dt: float) -> None:
        super().on_update(dt)
        if self.root is not None and self.root.rect.width < 1100:
            # keep the transcript usable on narrow windows and phones
            for child in self.root.children:
                if child is self.ai_panel.parent:
                    child.visible = self.root.rect.width >= 980
            self.root.arrange()


def main() -> None:
    PlannerApp().run()


if __name__ == "__main__":
    main()
