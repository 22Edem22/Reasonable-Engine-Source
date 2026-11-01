"""__APP_TITLE__ — программа с простым интерфейсом, созданная в Reasonable Engine.

Уровень «Простой»: обычное оконное приложение Windows на tkinter — без
игрового рендера, только понятные элементы управления и аккуратная тёмная тема
движка с фирменным акцентом.

Запуск:  python main.py
Перед открытием окна проигрывается заставка Reasonable Engine — она является
частью движка и всегда играет целиком.

Данные хранятся в data.json рядом с программой.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import ttk

if getattr(sys, "frozen", False):
    # PyInstaller build: project files sit next to the executable.
    PROJECT_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(__file__).resolve().parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = PROJECT_DIR
for _candidate in (PROJECT_DIR / "_engine", PROJECT_DIR, BUNDLE_DIR):
    if (_candidate / "reasonable").is_dir() and str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))

DATA_FILE = PROJECT_DIR / "data.json"

ACCENT = "#D97757"
BG = "#101216"
SURFACE = "#171A20"
SURFACE_2 = "#1B1E24"
BORDER = "#2C323B"
TEXT = "#E7E9EC"
TEXT_MUTED = "#9AA4B2"
TEXT_DIM = "#6F7680"
DANGER = "#C98A90"
DONE = "#8DB8A0"
FONT_MAIN = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")
FONT_SMALL = ("Segoe UI", 9)

APP_NAME = __APP_NAME_REPR__


# ---------------------------------------------------------------------------
# Заставка Reasonable Engine — до открытия tkinter-окна
# ---------------------------------------------------------------------------


def play_engine_splash() -> bool:
    """Play the mandatory Reasonable Engine intro. False — окно закрыли."""
    try:
        import pygame

        from reasonable.runtime.splash import play_splash
    except Exception:
        # Движок недоступен (запуск без папки _engine) — это нештатная
        # ситуация, но приложение всё же откроется.
        return True
    try:
        if not play_splash((920, 600)):
            pygame.quit()
            return False
    finally:
        # Отдаём дисплей tkinter'у: pygame больше не нужен.
        try:
            pygame.display.quit()
        except Exception:
            pass
        try:
            pygame.quit()
        except Exception:
            pass
    return True


# ---------------------------------------------------------------------------
# Хранение данных
# ---------------------------------------------------------------------------


def load_data() -> dict:
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"tasks": [], "next_id": 1}


def save_data(data: dict) -> None:
    """Атомарная запись: сначала во временный файл, затем замена."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(DATA_FILE.parent), prefix=".data-", suffix=".tmp", delete=False
        )
        try:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
        finally:
            handle.close()
        os.replace(handle.name, DATA_FILE)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Интерфейс
# ---------------------------------------------------------------------------


class TaskRow(tk.Frame):
    """Одна задача: флажок, текст, кнопка удаления."""

    def __init__(self, master, app: "SimpleApp", task: dict) -> None:
        super().__init__(master, bg=SURFACE, bd=0, highlightthickness=1, highlightbackground=BORDER)
        self.app = app
        self.task_id = int(task.get("id", 0))
        done = bool(task.get("done"))

        check_var = tk.BooleanVar(value=done)
        self.check = tk.Checkbutton(
            self,
            variable=check_var,
            command=lambda: app.toggle_task(self.task_id, check_var.get()),
            bg=SURFACE,
            activebackground=SURFACE,
            activeforeground=ACCENT,
            fg=TEXT_MUTED,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.check.pack(side="left", padx=(12, 6), pady=10)

        self.label = tk.Label(
            self,
            text=str(task.get("title", "")),
            bg=SURFACE,
            fg=TEXT if not done else TEXT_DIM,
            font=FONT_BOLD if not done else FONT_MAIN,
            anchor="w",
        )
        self.label.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if done:
            self.label.configure(fg=TEXT_DIM)

        delete = tk.Label(
            self,
            text="✕",
            bg=SURFACE,
            fg=TEXT_DIM,
            font=FONT_BOLD,
            cursor="hand2",
        )
        delete.pack(side="right", padx=(0, 12))
        delete.bind("<Button-1>", lambda _event: app.delete_task(self.task_id))
        for widget in (self.label, self):
            widget.bind("<Double-Button-1>", lambda _event: app.toggle_task(self.task_id, not done))


class SimpleApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("860x600")
        self.minsize(640, 430)
        self.configure(bg=BG)
        self._data = load_data()
        self._style()

        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=24, pady=(20, 6))
        self.header_title = tk.Label(
            header,
            text=APP_NAME,
            bg=BG,
            fg=TEXT,
            font=FONT_TITLE,
            anchor="w",
        )
        self.header_title.pack(anchor="w")
        tk.Label(
            header,
            text="Создано в Reasonable Engine",
            bg=BG,
            fg=TEXT_DIM,
            font=FONT_SMALL,
        ).pack(anchor="w")
        tk.Frame(header, bg=ACCENT, height=2, width=64).pack(anchor="w", pady=(8, 0))

        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=24, pady=(8, 4))
        self.entry = tk.Entry(
            form,
            bg=SURFACE_2,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            font=FONT_MAIN,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.entry.bind("<Return>", lambda _event: self.add_task())
        self.entry.bind("<KP_Enter>", lambda _event: self.add_task())
        self.entry.insert(0, "")
        add = tk.Button(
            form,
            text="＋  Добавить",
            command=self.add_task,
            bg=ACCENT,
            fg="#FFFFFF",
            activebackground="#C4633F",
            activeforeground="#FFFFFF",
            relief="flat",
            font=FONT_BOLD,
            cursor="hand2",
            padx=18,
            pady=7,
            bd=0,
        )
        add.pack(side="left", padx=(10, 0))

        list_holder = tk.Frame(self, bg=BG)
        list_holder.pack(fill="both", expand=True, padx=24, pady=(8, 4))
        self.canvas = tk.Canvas(list_holder, bg=BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_holder, orient="vertical", command=self.canvas.yview, width=10)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_host = tk.Frame(self.canvas, bg=BG)
        self.rows_window = self.canvas.create_window((0, 0), window=self.rows_host, anchor="nw")
        self.rows_host.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self.rows_window, width=event.width),
        )
        # Колесо мыши прокручивает список (Windows и macOS).
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        self.canvas.bind_all("<Button-4>", self._on_wheel)
        self.canvas.bind_all("<Button-5>", self._on_wheel)

        self.empty_label = tk.Label(
            self.rows_host,
            text="Пока ничего нет.\nДобавьте первую запись выше.",
            bg=BG,
            fg=TEXT_DIM,
            font=("Segoe UI", 11),
            justify="center",
        )

        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", padx=24, pady=(4, 18))
        self.counter = tk.Label(footer, text="", bg=BG, fg=TEXT_MUTED, font=FONT_SMALL)
        self.counter.pack(side="left")
        clear_done = tk.Button(
            footer,
            text="Удалить выполненные",
            command=self.remove_done,
            bg=SURFACE_2,
            fg=DANGER,
            activebackground=SURFACE,
            activeforeground=DANGER,
            relief="flat",
            font=FONT_SMALL,
            cursor="hand2",
            padx=12,
            pady=5,
            bd=0,
        )
        clear_done.pack(side="right")
        self.bind("<Escape>", lambda _event: self.lift())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.refresh_rows()
        # Headless verification runs (RE_FRAMES) open the window briefly and
        # close it automatically so agents can check the app without a screen.
        frames = os.environ.get("RE_FRAMES")
        if frames:
            try:
                self.after(max(80, int(frames) * 25), self._close)
            except (TypeError, ValueError):
                pass

    # -- стиль ------------------------------------------------------------
    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE_2, bordercolor=BORDER)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)

    # -- данные ------------------------------------------------------------
    def _persist(self) -> None:
        save_data(self._data)

    def _on_wheel(self, event) -> None:
        delta = -1 if getattr(event, "delta", 0) > 0 or event.num == 4 else 1
        self.canvas.yview_scroll(delta * 2, "units")

    # -- действия ----------------------------------------------------------
    def add_task(self) -> None:
        title = self.entry.get().strip()
        if not title:
            self.entry.focus_set()
            return
        tasks = self._data.setdefault("tasks", [])
        tasks.insert(0, {"id": int(self._data.get("next_id", 1)), "title": title, "done": False})
        self._data["next_id"] = int(self._data.get("next_id", 1)) + 1
        self.entry.delete(0, "end")
        self._persist()
        self.refresh_rows()
        self.entry.focus_set()

    def toggle_task(self, task_id: int, done: bool) -> None:
        for task in self._data.setdefault("tasks", []):
            if int(task.get("id", 0)) == task_id:
                task["done"] = bool(done)
        self._persist()
        self.refresh_rows()

    def delete_task(self, task_id: int) -> None:
        tasks = self._data.setdefault("tasks", [])
        self._data["tasks"] = [task for task in tasks if int(task.get("id", 0)) != task_id]
        self._persist()
        self.refresh_rows()

    def remove_done(self) -> None:
        tasks = self._data.setdefault("tasks", [])
        self._data["tasks"] = [task for task in tasks if not task.get("done")]
        self._persist()
        self.refresh_rows()

    # -- отрисовка ----------------------------------------------------------
    def refresh_rows(self) -> None:
        for child in self.rows_host.winfo_children():
            if child is self.empty_label:
                continue
            child.destroy()
        tasks = list(self._data.get("tasks", []))
        if not tasks:
            self.empty_label.pack(expand=True, fill="both", pady=(48, 24))
        else:
            self.empty_label.pack_forget()
            for task in tasks:
                TaskRow(self.rows_host, self, task).pack(fill="x", expand=True, pady=3)
        done = sum(1 for task in tasks if task.get("done"))
        self.counter.configure(text=f"Выполнено {done} из {len(tasks)}")

    def _close(self) -> None:
        self._persist()
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass
        self.destroy()


def main() -> None:
    if not play_engine_splash():
        return
    SimpleApp().mainloop()


if __name__ == "__main__":
    main()
