"""__APP_TITLE__ — приложение, созданное в Reasonable Engine.

Запуск:  python main.py

Готовый планировщик: несколько представлений, приоритеты, теги, поиск,
статистика за неделю, серия дней, отмена удаления и встроенный ИИ-помощник.
Все данные лежат в data.json рядом с проектом — их видно и можно перенести.

Горячие клавиши:
  Ctrl+N — новая задача      Ctrl+F — поиск
  Ctrl+1…4 — представления   Enter — добавить задачу
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller build: project files (project.json, data.json) sit next to
    # the executable; bundled data lives inside the PyInstaller bundle.
    PROJECT_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(__file__).resolve().parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = PROJECT_DIR
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR, BUNDLE_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


def _project_file(relative: str) -> Path:
    """Locate a project file in both source and frozen (exe) modes."""
    candidate = PROJECT_DIR / relative
    if candidate.exists():
        return candidate
    return BUNDLE_DIR / relative


# Importing the package installs the engine's warning filters before pygame
# pulls in deprecated pkg_resources on some builds.
import reasonable  # noqa: F401,E402

import pygame  # noqa: E402

try:
    from reasonable.core.i18n import tr as _tr
except Exception:  # exported builds may run without the bundled core package
    def _tr(en: str, ru: str, **values) -> str:
        return en

from reasonable.runtime import (
    AIChatPanel,
    AIConfig,
    Badge,
    Button,
    Divider,
    Entry,
    HStack,
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
        data = json.loads(_project_file("project.json").read_text(encoding="utf-8"))
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

PRIORITIES = ("Низкий", "Обычный", "Важный")
PRIORITY_COLORS = ((154, 161, 171), (127, 163, 199), (217, 119, 87))
TAG_COLORS = {
    "Работа": (127, 163, 199),
    "Личное": (141, 184, 160),
    "Дом": (201, 173, 115),
    "Идея": (176, 148, 201),
    "Учёба": (201, 138, 144),
}
TAG_CHOICES = ("Личное", "Работа", "Дом", "Идея", "Учёба")
FILTERS = (
    ("today", "Сегодня", "home"),
    ("active", "В работе", "spark"),
    ("high", "Важные", "bolt"),
    ("done", "Готово", "check"),
)
SORTS = ("Важные", "Новые", "Алфавит")
WEEKDAYS = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _today() -> str:
    return date.today().isoformat()


def _format_date() -> str:
    today = date.today()
    return f"{WEEKDAYS[today.weekday()]}, {today.day} {MONTHS[today.month - 1]}"


def _new_task(task_id: int, title: str, *, priority: int = 1, tag: str = "Личное", done: bool = False) -> dict:
    return {
        "id": task_id,
        "title": title,
        "done": bool(done),
        "priority": max(0, min(2, int(priority))),
        "tag": tag if tag else "Личное",
        "created": _today(),
        "completed_on": _today() if done else "",
        "focus": False,
    }


def default_data() -> dict:
    tasks = [
        _new_task(1, "Придумать идею проекта", priority=1, tag="Идея", done=True),
        _new_task(2, "Собрать первый прототип", priority=2, tag="Работа"),
        _new_task(3, "Попросить ИИ-помощника улучшить интерфейс", priority=1, tag="Идея"),
        _new_task(4, "Проверить результат и записать выводы", priority=0, tag="Учёба"),
    ]
    done_today = sum(1 for task in tasks if task.get("done"))
    return {
        "version": 2,
        "tasks": tasks,
        "history": {_today(): done_today} if done_today else {},
        "last_day": _today(),
        "filter": "today",
        "sort": 0,
    }


def normalise_data(raw: dict) -> dict:
    """Bring old data.json files (only id/title/done) to the current shape."""
    data = default_data()
    if not isinstance(raw, dict):
        return data
    tasks = raw.get("tasks")
    if not isinstance(tasks, list):
        tasks = []
    cleaned: list[dict] = []
    for index, item in enumerate(tasks, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            task_id = int(item.get("id") or index)
        except (TypeError, ValueError):
            task_id = index
        try:
            priority = int(item.get("priority", 1))
        except (TypeError, ValueError):
            priority = 1
        cleaned.append(
            {
                "id": task_id,
                "title": title[:400],
                "done": bool(item.get("done")),
                "priority": max(0, min(2, priority)),
                "tag": str(item.get("tag") or "Личное")[:40],
                "created": str(item.get("created") or _today()),
                "completed_on": str(item.get("completed_on") or ""),
                "focus": bool(item.get("focus")),
            }
        )
    data["tasks"] = cleaned
    data["history"] = {}
    history = raw.get("history")
    if isinstance(history, dict):
        data["history"] = {
            str(key): max(0, int(value))
            for key, value in history.items()
            if isinstance(value, (int, float))
        }
    if raw.get("filter") in {key for key, _label, _icon in FILTERS}:
        data["filter"] = raw["filter"]
    try:
        data["sort"] = max(0, min(len(SORTS) - 1, int(raw.get("sort", 0))))
    except (TypeError, ValueError):
        data["sort"] = 0
    data["last_day"] = str(raw.get("last_day") or _today())
    return data


def load_data() -> dict:
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    return normalise_data(raw)


def save_data(data: dict) -> None:
    try:
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def compute_streak(history: dict) -> int:
    """Consecutive days with at least one completed task, ending today/yesterday."""
    streak = 0
    cursor = date.today()
    if not history.get(cursor.isoformat()):
        cursor -= timedelta(days=1)
    while history.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ---------------------------------------------------------------------------
# Custom widgets
# ---------------------------------------------------------------------------
class TaskRow(Widget):
    """A dense task card with priority, tag, pin and delete controls."""

    def __init__(self, task: dict, on_toggle, on_delete, on_priority, on_pin, **kwargs) -> None:
        super().__init__(height=78, **kwargs)
        self.task = task
        self.on_toggle = on_toggle
        self.on_delete = on_delete
        self.on_priority = on_priority
        self.on_pin = on_pin
        self.hover_zone = ""
        self._title_font = get_font(15, bold=True)
        self._body_font = get_font(11)

    def measure(self, max_width: int, max_height: int) -> tuple[int, int]:
        return (max_width, 78)

    def _checkbox(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x + 16, self.rect.centery - 13, 26, 26)

    def _priority(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x + 58, self.rect.y + 13, 78, 22)

    def _tag(self) -> pygame.Rect:
        return pygame.Rect(self.rect.x + 144, self.rect.y + 13, 76, 22)

    def _pin(self) -> pygame.Rect:
        return pygame.Rect(self.rect.right - 78, self.rect.centery - 15, 30, 30)

    def _delete(self) -> pygame.Rect:
        return pygame.Rect(self.rect.right - 42, self.rect.centery - 15, 30, 30)

    def handle_event(self, event: pygame.event.Event) -> bool:
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
            self.hover_zone = ""
            if self.hovered:
                if self._delete().collidepoint(event.pos):
                    self.hover_zone = "delete"
                elif self._pin().collidepoint(event.pos):
                    self.hover_zone = "pin"
                elif self._priority().collidepoint(event.pos):
                    self.hover_zone = "priority"
            return False
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1 and self.rect.collidepoint(event.pos):
            if self._checkbox().inflate(18, 18).collidepoint(event.pos):
                self.on_toggle(self.task)
                return True
            if self._delete().collidepoint(event.pos):
                self.on_delete(self.task)
                return True
            if self._pin().collidepoint(event.pos):
                self.on_pin(self.task)
                return True
            if self._priority().collidepoint(event.pos):
                self.on_priority(self.task)
                return True
        return False

    def draw(self, surface: pygame.Surface) -> None:
        done = bool(self.task.get("done"))
        focused = bool(self.task.get("focus"))
        background = with_alpha(self.theme.text, 12) if self.hovered else self.theme.panel_alt
        border = with_alpha(self.theme.border, 190)
        if focused:
            border = with_alpha(self.theme.accent, 150)
        draw_rounded_rect(surface, self.rect, background, 16, border=border)

        box = self._checkbox()
        if done:
            draw_rounded_rect(surface, box, self.theme.success, 9)
            draw_icon(surface, "check", box.inflate(-7, -7), self.theme.on_accent, 2)
        else:
            draw_rounded_rect(surface, box, with_alpha(self.theme.text, 10), 9, border=self.theme.border)

        priority = int(self.task.get("priority", 1))
        priority_color = PRIORITY_COLORS[priority]
        chip = self._priority()
        draw_rounded_rect(surface, chip, with_alpha(priority_color, 34), 11, border=with_alpha(priority_color, 110))
        priority_text = get_font(10, bold=True).render(PRIORITIES[priority].upper(), True, priority_color)
        surface.blit(priority_text, priority_text.get_rect(center=chip.center))

        tag = str(self.task.get("tag") or "Личное")
        tag_color = TAG_COLORS.get(tag, (154, 161, 171))
        tag_rect = self._tag()
        tag_rect.width = max(tag_rect.width, self._body_font.size(tag)[0] + 20)
        draw_rounded_rect(surface, tag_rect, with_alpha(tag_color, 22), 11)
        tag_text = self._body_font.render(tag, True, tag_color)
        surface.blit(tag_text, tag_text.get_rect(center=tag_rect.center))

        color_value = self.theme.muted if done else self.theme.text
        title = ellipsis(str(self.task.get("title") or ""), self._title_font, max(60, self.rect.width - 196))
        image = self._title_font.render(title, True, color_value)
        title_y = self.rect.y + 38
        surface.blit(image, (self.rect.x + 58, title_y))
        if done:
            surface.fill(
                with_alpha(self.theme.muted, 140),
                pygame.Rect(self.rect.x + 58, title_y + image.get_height() // 2, image.get_width(), 1),
            )

        created = str(self.task.get("created") or "")
        if created and created != _today():
            small = self._body_font.render(created, True, self.theme.faint)
            surface.blit(
                small,
                small.get_rect(topright=(self._pin().x - 8, self.rect.y + 16)),
            )

        pin_color = self.theme.accent if focused else self.theme.faint
        if focused or self.hover_zone == "pin" or self.hovered:
            draw_icon(
                surface,
                "spark",
                self._pin().inflate(-6, -6),
                pin_color if focused else with_alpha(pin_color, 170 if self.hover_zone == "pin" else 90),
                2,
            )
        if self.hovered or self.hover_zone == "delete":
            draw_icon(
                surface,
                "close",
                self._delete().inflate(-7, -7),
                self.theme.danger if self.hover_zone == "delete" else with_alpha(self.theme.faint, 190),
                2,
            )


class WeekChart(Widget):
    """Seven small bars showing how many tasks were completed each day."""

    def __init__(self, history: dict, **kwargs) -> None:
        super().__init__(height=86, **kwargs)
        self.history = history

    def set_history(self, history: dict) -> None:
        self.history = history

    def draw(self, surface: pygame.Surface) -> None:
        start = date.today() - timedelta(days=6)
        values = []
        for offset in range(7):
            day = start + timedelta(days=offset)
            values.append(int(self.history.get(day.isoformat(), 0)))
        peak = max(1, max(values))
        inner = self.rect.inflate(-4, -8)
        gap = 7
        bar_width = max(8, (inner.width - gap * 6) // 7)
        baseline = inner.bottom - 18
        for index, value in enumerate(values):
            x = inner.x + index * (bar_width + gap)
            height = int((baseline - inner.y) * (value / peak)) if value else 3
            color = self.theme.accent if index == 6 else with_alpha(self.theme.accent_2, 190)
            draw_rounded_rect(
                surface,
                pygame.Rect(x, baseline - height, bar_width, max(3, height)),
                color,
                4,
            )
            label = get_font(9, bold=True).render(WEEKDAYS[index], True, self.theme.faint)
            surface.blit(label, label.get_rect(center=(x + bar_width // 2, self.rect.bottom - 7)))
            if value:
                count = get_font(9, bold=True).render(str(value), True, self.theme.muted)
                surface.blit(count, count.get_rect(center=(x + bar_width // 2, baseline - height - 9)))


class StatRow(Widget):
    def __init__(self, label: str, value: str, color_value=None, **kwargs) -> None:
        super().__init__(height=26, **kwargs)
        self.label = label
        self.value = value
        self.color_value = color_value

    def set_value(self, value: str) -> None:
        self.value = value

    def draw(self, surface: pygame.Surface) -> None:
        left = get_font(12).render(self.label, True, self.theme.muted)
        right = get_font(13, bold=True).render(self.value, True, self.color_value or self.theme.text)
        surface.blit(left, (self.rect.x, self.rect.centery - left.get_height() // 2))
        surface.blit(right, right.get_rect(midright=(self.rect.right, self.rect.centery)))


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
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
        self.filter = self.data.get("filter", "today")
        self.sort_mode = int(self.data.get("sort", 0))
        self.tasks: list[dict] = list(self.data.get("tasks", []))
        self.next_id = max([int(task.get("id", 0)) for task in self.tasks] or [0]) + 1
        self.priority = 1
        self.tag_index = 0
        self.query = ""
        self.last_deleted: tuple[dict, int] | None = None
        self.toast = ""
        self.toast_timer = 0.0
        self.task_rows: list[TaskRow] = []
        self.ai_panel: AIChatPanel | None = None
        self.week_chart: WeekChart | None = None
        self.stat_rows: dict[str, StatRow] = {}
        self.nav_buttons: dict[str, Button] = {}
        self.main_title: Label | None = None
        self.greeting: Label | None = None
        self.counter_label: Label | None = None
        self.progress: ProgressBar | None = None
        self.streak_label: Label | None = None
        self.empty_label: Label | None = None
        self.status_label: Label | None = None
        self.undo_button: Button | None = None
        self.priority_button: Button | None = None
        self.sort_button: Button | None = None
        self.ai_button: IconButton | None = None
        self.ai_back_button: Button | None = None
        self.right_panel: Panel | None = None
        self.sidebar: Panel | None = None
        self.main_panel: Panel | None = None
        self._compact = False
        self.ai_overlay = False

    # ------------------------------------------------------------------
    def build_ui(self):
        root = HStack(spacing=0, padding=0)
        self.sidebar = self.build_sidebar()
        self.main_panel = self.build_main()
        self.right_panel = self.build_right_panel()
        root.add(self.sidebar, self.main_panel, self.right_panel)
        return root

    def _greeting_text(self) -> str:
        hour = datetime.now().hour
        if hour < 6:
            return "Доброй ночи"
        if hour < 12:
            return "Доброе утро"
        if hour < 18:
            return "Добрый день"
        return "Добрый вечер"

    def build_sidebar(self) -> Panel:
        side = Panel(padding=22, spacing=14, background=(18, 20, 25), border=None, radius=0, shadow=False, width=240)
        brand = HStack(spacing=10, align_y="center")
        logo = ImageWidget(_project_file("assets/icon.png"), width=44, height=44, radius=12)
        brand.add(
            logo,
            VStack(spacing=0, align_x="left").add(
                Label("REASONABLE", size=12, bold=True, color_value=THEME.accent),
                Label(APP_NAME, size=15, bold=True),
            ),
        )
        side.add(brand)
        side.add(Widget(height=4))
        side.add(Label("ПРОСТРАНСТВО", size=10, bold=True, color_value=THEME.faint))
        for key, label, icon in FILTERS:
            button = Button(label, on_click=lambda k=key: self.set_filter(k), variant="ghost", icon=icon, height=44)
            self.nav_buttons[key] = button
            side.add(button)

        side.add(Widget(height=6))
        stat_panel = Panel(padding=16, spacing=9, background=THEME.panel_alt, radius=16, shadow=False)
        stat_panel.add(Label("ПРОГРЕСС ДНЯ", size=10, bold=True, color_value=THEME.faint))
        self.progress = ProgressBar(0, height=8, color_value=THEME.accent)
        stat_panel.add(self.progress)
        self.counter_label = Label("0 из 0 задач", size=12, color_value=THEME.muted)
        stat_panel.add(self.counter_label)
        side.add(stat_panel)

        self.streak_panel = Panel(
            padding=14,
            spacing=4,
            background=with_alpha(THEME.accent, 22),
            border=with_alpha(THEME.accent, 50),
            radius=14,
            shadow=False,
        )
        self.streak_label = Label("Серия: 0 дней", size=12, bold=True, color_value=THEME.accent)
        self.streak_panel.add(self.streak_label)
        self.streak_hint = Label("Отмечайте задачи каждый день", size=10, color_value=with_alpha(THEME.accent, 190))
        self.streak_panel.add(self.streak_hint)
        side.add(self.streak_panel)

        side.add(Spacer())
        side.add(Divider())
        side.add(Label("Ctrl+N — новая задача", size=10, color_value=THEME.faint))
        side.add(Label("Ctrl+F — поиск", size=10, color_value=THEME.faint))
        side.add(Label("Ctrl+1…4 — разделы", size=10, color_value=THEME.faint))
        side.add(Label("Создано в Reasonable Engine", size=10, color_value=THEME.faint))
        return side

    def build_main(self) -> Panel:
        main = Panel(padding=28, spacing=14, background=(15, 17, 21), border=None, radius=0, shadow=False, expand_x=True)
        header = HStack(spacing=12, align_y="center")
        titles = VStack(spacing=2, align_x="left")
        self.greeting = Label(self._greeting_text(), size=12, bold=True, color_value=THEME.accent)
        titles.add(self.greeting)
        self.main_title = Label("Планы на сегодня", size=30, bold=True, display=True)
        titles.add(self.main_title)
        self.status_label = Label(
            _format_date(),
            size=12,
            color_value=THEME.muted,
        )
        titles.add(self.status_label)
        header.add(titles, Spacer())
        self.undo_button = IconButton("refresh", self.undo_delete, size=40, variant="secondary")
        self.undo_button.visible = False
        header.add(self.undo_button)
        self.ai_button = IconButton("chat", self.toggle_ai, size=44, variant="secondary")
        self.ai_button.visible = False
        header.add(self.ai_button)
        header.add(IconButton("plus", self.focus_entry, size=44, variant="primary"))
        main.add(header)

        entry_row = HStack(spacing=9, align_y="center")
        self.entry = Entry("Что нужно сделать?", on_submit=lambda _value=None: self.add_task())
        self.entry.expand_x = True
        entry_row.add(self.entry)
        self.priority_button = Button("ОБЫЧНЫЙ", self.cycle_priority, variant="secondary", height=48, width=120)
        entry_row.add(self.priority_button)
        entry_row.add(Button("Добавить", self.add_task, icon="plus", height=48))
        main.add(entry_row)

        tools = HStack(spacing=9, align_y="center")
        self.search = Entry("Поиск по задачам…", on_change=self.set_query)
        self.search.expand_x = True
        tools.add(self.search)
        self.tag_button = Button("ТЕГ: ЛИЧНОЕ", self.cycle_tag, variant="ghost", height=40, width=132)
        tools.add(self.tag_button)
        self.sort_button = Button("СОРТ: ВАЖНЫЕ", self.cycle_sort, variant="ghost", height=40, width=150)
        tools.add(self.sort_button)
        main.add(tools)

        self.empty_label = Label(
            "Здесь пока пусто. Добавьте задачу или попросите ИИ составить план.",
            size=14,
            color_value=THEME.faint,
            align="center",
        )
        self.empty_label.visible = False
        main.add(self.empty_label)

        self.list_stack = VStack(spacing=9)
        self.scroll = ScrollView(self.list_stack, expand_y=True)
        main.add(self.scroll)
        self.refresh_tasks()
        return main

    def build_right_panel(self) -> Panel:
        wrapper = Panel(padding=0, spacing=0, background=(19, 21, 26), border=None, radius=0, shadow=False, width=356)
        self.ai_back_button = Button(
            "Назад к задачам",
            self.toggle_ai,
            variant="ghost",
            icon="back",
            height=40,
        )
        self.ai_back_button.visible = False
        wrapper.add(self.ai_back_button)
        stats = Panel(padding=18, spacing=10, background=(19, 21, 26), border=None, radius=0, shadow=False)
        head = HStack(spacing=8, align_y="center")
        head.add(Label("СТАТИСТИКА", size=10, bold=True, color_value=THEME.faint), Spacer())
        self.week_badge = Badge("7 дней", size=10)
        head.add(self.week_badge)
        stats.add(head)
        self.week_chart = WeekChart(self.data.get("history", {}))
        stats.add(self.week_chart)
        for key, label in (
            ("done_today", "Выполнено сегодня"),
            ("active", "Осталось"),
            ("important", "Важных"),
            ("streak", "Серия дней"),
            ("total", "Всего задач"),
        ):
            row = StatRow(label, "0")
            self.stat_rows[key] = row
            stats.add(row)
        wrapper.add(stats)

        config = AIConfig.load(APP_NAME, PROJECT_DIR)
        titles = ", ".join(str(task.get("title")) for task in self.tasks[:10] if not task.get("done"))
        # AI-facing material is English-only; the "user's language" rule makes
        # the assistant answer in the language the end user types in.
        config.system_prompt = (
            "You are the AI assistant inside a task planner built with Reasonable Engine. "
            "Help the user plan the day, phrase clear tasks and break big goals into steps. "
            "Reply in the language the user writes in, briefly and practically. "
            "When useful, offer a short numbered task list the user can copy. "
            f"Current open tasks: {titles or 'none yet'}."
        )
        config.title = _tr("Assistant", "Помощник")
        self.ai_panel = AIChatPanel(
            config,
            app_name=APP_NAME,
            greeting=_tr(
                "Hi! I will help you plan the day and break big tasks into small steps. Where do we start?",
                "Привет! Помогу спланировать день и разбить большие задачи на маленькие шаги. С чего начнём?",
            ),
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

    def focus_search(self) -> None:
        self.search.focus()

    def toggle_ai(self) -> None:
        """On narrow screens the assistant and stats open as a full-page view."""
        self.ai_overlay = not self.ai_overlay
        if self.ai_overlay and self.ai_panel is not None:
            self.ai_panel.visible = True
        self.on_update(0.0)

    def show_toast(self, text: str) -> None:
        self.toast = text
        self.toast_timer = 3.0
        if self.status_label is not None:
            self.status_label.set_text(text)

    def add_task(self) -> None:
        title = self.entry.value.strip()
        if not title:
            self.focus_entry()
            return
        task = _new_task(
            self.next_id,
            title,
            priority=self.priority,
            tag=TAG_CHOICES[self.tag_index],
        )
        self.next_id += 1
        self.tasks.insert(0, task)
        self.entry.set_value("")
        self.persist()
        self.show_toast(f"Добавлено: {title[:60]}")
        self.refresh_tasks()

    def toggle_task(self, task: dict) -> None:
        task["done"] = not bool(task.get("done"))
        history = self.data.setdefault("history", {})
        today = _today()
        if task["done"]:
            task["completed_on"] = today
            history[today] = int(history.get(today, 0)) + 1
        else:
            if task.get("completed_on") == today:
                history[today] = max(0, int(history.get(today, 0)) - 1)
            task["completed_on"] = ""
        self.persist()
        self.refresh_tasks()

    def delete_task(self, task: dict) -> None:
        try:
            index = self.tasks.index(task)
        except ValueError:
            return
        self.last_deleted = (dict(task), index)
        self.tasks.pop(index)
        self.persist()
        self.show_toast("Задача удалена — можно вернуть")
        self.refresh_tasks()

    def undo_delete(self) -> None:
        if not self.last_deleted:
            return
        task, index = self.last_deleted
        self.tasks.insert(max(0, min(index, len(self.tasks))), task)
        self.last_deleted = None
        self.persist()
        self.show_toast("Задача восстановлена")
        self.refresh_tasks()

    def cycle_priority(self) -> None:
        self.priority = (self.priority + 1) % len(PRIORITIES)
        if self.priority_button is not None:
            self.priority_button.set_text(PRIORITIES[self.priority].upper())
            self.priority_button.variant = "primary" if self.priority == 2 else "secondary"

    def cycle_tag(self) -> None:
        self.tag_index = (self.tag_index + 1) % len(TAG_CHOICES)
        if hasattr(self, "tag_button") and self.tag_button is not None:
            self.tag_button.set_text("ТЕГ: " + TAG_CHOICES[self.tag_index].upper())

    def cycle_sort(self) -> None:
        self.sort_mode = (self.sort_mode + 1) % len(SORTS)
        if self.sort_button is not None:
            self.sort_button.set_text("СОРТ: " + SORTS[self.sort_mode].upper())
        self.persist()
        self.refresh_tasks()

    def set_query(self, value: str) -> None:
        self.query = str(value or "").strip().lower()
        self.refresh_tasks()

    def set_filter(self, key: str) -> None:
        self.filter = key
        for name, button in self.nav_buttons.items():
            button.variant = "secondary" if name == key else "ghost"
        self.persist()
        self.refresh_tasks()

    def visible_tasks(self) -> list[dict]:
        tasks = list(self.tasks)
        if self.filter == "active":
            tasks = [task for task in tasks if not task.get("done")]
        elif self.filter == "high":
            tasks = [task for task in tasks if not task.get("done") and int(task.get("priority", 1)) == 2]
        elif self.filter == "done":
            tasks = [task for task in tasks if task.get("done")]
        if self.query:
            tasks = [
                task
                for task in tasks
                if self.query in str(task.get("title", "")).lower()
                or self.query in str(task.get("tag", "")).lower()
            ]
        if self.sort_mode == 0:
            tasks.sort(key=lambda task: (-int(task.get("priority", 1)), bool(task.get("done")), str(task.get("created", ""))))
        elif self.sort_mode == 1:
            tasks.sort(key=lambda task: (str(task.get("created", "")), int(task.get("id", 0))), reverse=True)
        else:
            tasks.sort(key=lambda task: str(task.get("title", "")).lower())
        return tasks

    def refresh_tasks(self) -> None:
        self.task_rows.clear()
        self.list_stack.clear()
        visible = self.visible_tasks()
        for task in visible:
            row = TaskRow(task, self.toggle_task, self.delete_task, self.cycle_task_priority, self.toggle_focus)
            self.task_rows.append(row)
            self.list_stack.add(row)

        done_count = sum(1 for task in self.tasks if task.get("done"))
        total = len(self.tasks)
        active = total - done_count
        important = sum(
            1
            for task in self.tasks
            if not task.get("done") and int(task.get("priority", 1)) == 2
        )
        history = self.data.setdefault("history", {})
        streak = compute_streak(history)
        percent = (done_count / total * 100) if total else 0

        if self.progress:
            self.progress.set_value(percent)
        if self.counter_label:
            self.counter_label.set_text(f"{done_count} из {total} задач")
        if self.streak_label:
            self.streak_label.set_text(f"Серия: {streak} {self._days_word(streak)}")
        if self.streak_hint:
            self.streak_hint.set_text(
                "Так держать! Продолжайте завтра" if streak > 1 else "Отмечайте задачи каждый день"
            )
        if self.week_chart:
            self.week_chart.set_history(history)
        stats = {
            "done_today": str(int(history.get(_today(), 0))),
            "active": str(active),
            "important": str(important),
            "streak": str(streak),
            "total": str(total),
        }
        for key, row in self.stat_rows.items():
            row.set_value(stats.get(key, "0"))
        if "important" in self.stat_rows:
            self.stat_rows["important"].color_value = THEME.accent
        if "streak" in self.stat_rows:
            self.stat_rows["streak"].color_value = THEME.accent_3

        titles = {
            "today": "Планы на сегодня",
            "active": "В работе",
            "high": "Важные задачи",
            "done": "Готовые задачи",
        }
        if self.main_title:
            self.main_title.set_text(titles.get(self.filter, "Планы"))
        if self.empty_label:
            self.empty_label.visible = not visible
            if not visible:
                if self.query:
                    self.empty_label.set_text("Ничего не найдено. Попробуйте другой запрос.")
                elif self.filter == "done":
                    self.empty_label.set_text("Пока нет выполненных задач — начните с одной небольшой.")
                elif self.filter == "high":
                    self.empty_label.set_text("Важных задач нет. Так и продолжайте!")
                else:
                    self.empty_label.set_text("Здесь пока пусто. Добавьте задачу или попросите ИИ составить план.")

        counts = {
            "today": total,
            "active": active,
            "high": important,
            "done": done_count,
        }
        for key, label, _icon in FILTERS:
            button = self.nav_buttons.get(key)
            if button is not None:
                button.set_text(f"{label}   {counts.get(key, 0)}")
        if self.undo_button is not None:
            self.undo_button.visible = self.last_deleted is not None
        if self.root is not None:
            self.root.layout(pygame.Rect(0, 0, *self.size))

    @staticmethod
    def _days_word(count: int) -> str:
        if count % 10 == 1 and count % 100 != 11:
            return "день"
        if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
            return "дня"
        return "дней"

    def cycle_task_priority(self, task: dict) -> None:
        task["priority"] = (int(task.get("priority", 1)) + 1) % len(PRIORITIES)
        self.persist()
        self.refresh_tasks()

    def toggle_focus(self, task: dict) -> None:
        task["focus"] = not bool(task.get("focus"))
        self.persist()
        self.refresh_tasks()

    def persist(self) -> None:
        self.data["tasks"] = self.tasks
        self.data["filter"] = self.filter
        self.data["sort"] = self.sort_mode
        self.data["last_day"] = _today()
        save_data(self.data)

    # ------------------------------------------------------------------
    def on_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and self._compact and self.ai_overlay:
                self.toggle_ai()
                return
            ctrl = bool(getattr(event, "mod", 0) & pygame.KMOD_CTRL)
            if ctrl and event.key == pygame.K_n:
                self.focus_entry()
                return
            if ctrl and event.key == pygame.K_f:
                self.focus_search()
                return
            if ctrl and pygame.K_1 <= event.key <= pygame.K_4:
                self.set_filter(FILTERS[event.key - pygame.K_1][0])
                return
        super().on_event(event)

    def on_update(self, dt: float) -> None:
        if self.toast_timer > 0:
            self.toast_timer = max(0.0, self.toast_timer - dt)
            if self.toast_timer <= 0 and self.status_label is not None:
                self.status_label.set_text(_format_date())
        compact = self.size[0] < 1040
        overlay = compact and self.ai_overlay
        sidebar_width = 204 if self.size[0] < 900 else 240
        right_width = 356
        self._compact = compact
        if self.sidebar is not None:
            self.sidebar.width = sidebar_width
            self.sidebar.visible = not overlay
        if self.main_panel is not None:
            self.main_panel.visible = not overlay
        if self.right_panel is not None:
            self.right_panel.visible = not compact or overlay
            self.right_panel.width = self.size[0] if overlay else right_width
        if self.ai_panel is not None:
            self.ai_panel.visible = True
        if self.ai_back_button is not None:
            self.ai_back_button.visible = overlay
        if self.ai_button is not None:
            self.ai_button.visible = compact and not overlay
        if self.main_panel is not None:
            # HStack gives a widget with ``width`` exactly that width and
            # distributes the remaining space between expanding children.
            # Pinning the middle column prevents long toolbars from pushing
            # the assistant panel off-screen on smaller windows.
            self.main_panel.expand_x = False
            self.main_panel.width = max(
                340,
                self.size[0] - sidebar_width - (right_width if not compact else 0),
            )
        if hasattr(self, "tag_button") and self.tag_button is not None:
            self.tag_button.visible = self.size[0] >= 900
        if self.sort_button is not None:
            self.sort_button.visible = self.size[0] >= 900
        super().on_update(dt)


def main() -> None:
    PlannerApp().run()


if __name__ == "__main__":
    main()
