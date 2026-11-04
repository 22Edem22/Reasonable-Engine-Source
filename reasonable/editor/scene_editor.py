"""Visual scene editor: a canvas with draggable objects, an object list and an
inspector.

The page is intentionally close to the scene view of desktop engines: a
toolbar with creation tools, a viewport with grid/snap/zoom, a hierarchy on the
left and object properties on the right. Everything is stored in
``scenes/main.json`` through :mod:`reasonable.core.scene`, so the runtime can
reuse the same data.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from reasonable.core.i18n import t
from reasonable.core.scene import (
    GRID_STEP,
    create_scene,
    delete_scene,
    duplicate_scene,
    ensure_scene,
    list_scenes,
    load_scene,
    new_object,
    rename_scene,
    save_scene,
    template_objects,
)

from . import theme

HANDLE = 7
MIN_SIZE = 8.0
ZOOM_MIN = 0.1
ZOOM_MAX = 8.0

_KIND_ICONS = {
    "rect": "square",
    "circle": "circle",
    "text": "text",
    "image": "image",
    "panel": "layers",
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class SceneSettingsDialog(QDialog):
    """Name, canvas size, background and grid of one scene."""

    def __init__(self, scene: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("scene.settings_title"))
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(9)

        self.name_edit = QLineEdit(str(scene.get("name") or ""))
        form.addRow(t("scene.field_name"), self.name_edit)

        size = scene.get("size") or [960, 540]
        self.width_spin = QSpinBox()
        self.width_spin.setRange(160, 7680)
        self.width_spin.setValue(int(size[0]))
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox()
        self.height_spin.setRange(120, 4320)
        self.height_spin.setValue(int(size[1]))
        self.height_spin.setSuffix(" px")
        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(self.width_spin)
        size_row.addWidget(self.height_spin)
        form.addRow(t("scene.field_size"), size_row)

        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(4, 256)
        self.grid_spin.setValue(int(scene.get("grid") or GRID_STEP))
        form.addRow(t("scene.field_grid"), self.grid_spin)

        self.color_button = QPushButton()
        self.color_button.setFixedHeight(26)
        self.color_button.clicked.connect(self._pick_color)
        form.addRow(t("scene.bg_color"), self.color_button)
        self._color = QColor(str(scene.get("background") or "#141821"))
        self._refresh_color()

        layout.addLayout(form)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(t("common.save"))
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(t("common.cancel"))
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _refresh_color(self) -> None:
        color = self._color.name()
        luminance = 0.299 * self._color.red() + 0.587 * self._color.green() + 0.114 * self._color.blue()
        foreground = "#1B1D21" if luminance > 150 else "#F0F2F5"
        self.color_button.setText(color.upper())
        self.color_button.setStyleSheet(
            f"background: {color}; color: {foreground};"
            "border: 1px solid #4A4E55; border-radius: 3px;"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, t("scene.bg_color"))
        if chosen.isValid():
            self._color = chosen
            self._refresh_color()

    def values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "size": [self.width_spin.value(), self.height_spin.value()],
            "grid": self.grid_spin.value(),
            "background": self._color.name(),
        }


class SceneViewport(QWidget):
    """Canvas that renders the scene and edits objects with the mouse."""

    selection_changed = Signal(str)
    scene_changed = Signal()
    zoom_changed = Signal(int)
    tool_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(420, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.scene: dict = {"objects": [], "size": [960, 540], "grid": GRID_STEP, "background": "#141821"}
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.selected_id = ""
        self.tool = "select"
        self.snap = True
        self.show_grid = True

        self._drag: dict | None = None
        self._panning = False
        self._space_down = False
        self._fitted = False
        self._user_adjusted = False
        self._images: dict[str, QPixmap] = {}

    # -- geometry -----------------------------------------------------
    def scene_size(self) -> QSize:
        width, height = self.scene.get("size") or [960, 540]
        return QSize(int(width), int(height))

    def to_scene(self, point: QPointF) -> QPointF:
        return (point - self.pan) / max(0.001, self.zoom)

    def to_widget(self, point) -> QPointF:
        return QPointF(point[0], point[1]) * self.zoom + self.pan

    def fit_view(self) -> None:
        size = self.scene_size()
        margin = 28
        available_w = max(60, self.width() - margin * 2)
        available_h = max(60, self.height() - margin * 2)
        self.zoom = _clamp(
            min(available_w / max(1, size.width()), available_h / max(1, size.height())),
            ZOOM_MIN,
            ZOOM_MAX,
        )
        self.pan = QPointF(
            (self.width() - size.width() * self.zoom) / 2,
            (self.height() - size.height() * self.zoom) / 2,
        )
        self._fitted = True
        self._user_adjusted = False
        self.zoom_changed.emit(int(round(self.zoom * 100)))
        self.update()

    def reset_zoom(self) -> None:
        self.fit_view()

    def set_scene(self, scene: dict) -> None:
        self.scene = scene
        self._fitted = False
        self.selected_id = ""
        self.fit_view()

    # -- objects ------------------------------------------------------
    def objects(self) -> list[dict]:
        indexed = [
            (index, item)
            for index, item in enumerate(self.scene.get("objects") or [])
            if isinstance(item, dict)
        ]
        indexed.sort(key=lambda pair: (int(pair[1].get("z", 0)), pair[0]))
        return [item for _index, item in indexed]

    def find(self, object_id: str) -> dict | None:
        for item in self.scene.get("objects") or []:
            if isinstance(item, dict) and item.get("id") == object_id:
                return item
        return None

    def select(self, object_id: str) -> None:
        if object_id == self.selected_id:
            return
        self.selected_id = object_id or ""
        self.selection_changed.emit(self.selected_id)
        self.update()

    def _notify_changed(self) -> None:
        self.update()
        self.scene_changed.emit()

    # -- painting -----------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#16181C"))

        size = self.scene_size()
        canvas = QRectF(self.pan.x(), self.pan.y(), size.width() * self.zoom, size.height() * self.zoom)

        # The canvas itself sits on a slightly darker plate with a hairline.
        painter.fillRect(canvas, QColor(self.scene.get("background") or "#141821"))
        if self.show_grid:
            self._draw_grid(painter, canvas)

        painter.save()
        painter.setClipRect(canvas.adjusted(-1, -1, 1, 1))
        for item in self.objects():
            self._draw_object(painter, item)
        painter.restore()

        painter.setPen(QPen(QColor("#3A3D43"), 1))
        painter.drawRect(canvas)

        selected = self.find(self.selected_id) if self.selected_id else None
        if selected is not None:
            self._draw_selection(painter, selected)
        elif not (self.scene.get("objects") or []):
            painter.setPen(QColor("#6C727B"))
            font = QFont(self.font())
            font.setPointSizeF(9.0)
            painter.setFont(font)
            painter.drawText(
                canvas.adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                t("scene.empty_hint"),
            )
        drag = self._drag
        if drag is not None and drag.get("mode") == "create":
            start = drag["start"]
            current = drag["current"]
            preview = QRectF(self.to_widget((start.x(), start.y())), self.to_widget((current.x(), current.y()))).normalized()
            painter.setBrush(QColor(217, 119, 87, 38))
            painter.setPen(QPen(QColor("#D97757"), 1, Qt.PenStyle.DashLine))
            painter.drawRect(preview)
        painter.end()

    def _draw_grid(self, painter: QPainter, canvas: QRectF) -> None:
        step = max(4, int(self.scene.get("grid") or GRID_STEP))
        spacing = step * self.zoom
        while spacing < 7 and step < 4096:
            step *= 2
            spacing = step * self.zoom
        if spacing < 4:
            return
        painter.save()
        painter.setClipRect(canvas)
        minor = QPen(QColor("#24272C"), 1)
        painter.setPen(minor)
        x = 0
        index = 0
        while x <= canvas.width() + 0.5:
            line_x = canvas.left() + x
            if index % 4:
                painter.drawLine(QPointF(line_x, canvas.top()), QPointF(line_x, canvas.bottom()))
            x += spacing
            index += 1
        y = 0
        index = 0
        while y <= canvas.height() + 0.5:
            line_y = canvas.top() + y
            if index % 4:
                painter.drawLine(QPointF(canvas.left(), line_y), QPointF(canvas.right(), line_y))
            y += spacing
            index += 1
        # Every fourth line is brighter and marks the design grid.
        painter.setPen(QPen(QColor("#2C3036"), 1))
        x = 0
        index = 0
        while x <= canvas.width() + 0.5:
            if index % 4 == 0:
                line_x = canvas.left() + x
                painter.drawLine(QPointF(line_x, canvas.top()), QPointF(line_x, canvas.bottom()))
            x += spacing
            index += 1
        y = 0
        index = 0
        while y <= canvas.height() + 0.5:
            if index % 4 == 0:
                line_y = canvas.top() + y
                painter.drawLine(QPointF(canvas.left(), line_y), QPointF(canvas.right(), line_y))
            y += spacing
            index += 1
        painter.restore()

    def _object_rect(self, item: dict) -> QRectF:
        return QRectF(
            float(item.get("x", 0)),
            float(item.get("y", 0)),
            max(1.0, float(item.get("w", 32))),
            max(1.0, float(item.get("h", 32))),
        )

    def _draw_object(self, painter: QPainter, item: dict) -> None:
        rect = self._object_rect(item)
        center = rect.center()
        is_marker = bool(item.get("marker"))
        painter.save()
        painter.setOpacity(
            0.8 if is_marker else (1.0 if item.get("visible", True) else 0.35)
        )
        painter.translate(self.to_widget((center.x(), center.y())))
        painter.rotate(float(item.get("rotation", 0) or 0))
        painter.scale(self.zoom, self.zoom)
        local = QRectF(-rect.width() / 2, -rect.height() / 2, rect.width(), rect.height())
        kind = str(item.get("kind") or "rect")
        color = QColor(str(item.get("color") or "#D97757"))

        if is_marker:
            # Spawn markers are hidden in the game but should be obvious here.
            marker_color = QColor("#7FA3C7")
            painter.setPen(
                QPen(marker_color, max(1.0, 1.6 / max(0.01, self.zoom)), Qt.PenStyle.DashLine)
            )
            painter.setBrush(QColor(127, 163, 199, 30))
            painter.drawRect(local)
            painter.drawLine(local.left(), 0, local.right(), 0)
            painter.drawLine(0, local.top(), 0, local.bottom())
            painter.setBrush(marker_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(0, 0), max(2.0, 4.0 / max(0.01, self.zoom)), max(2.0, 4.0 / max(0.01, self.zoom)))
            painter.restore()
            return

        if kind == "circle":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(local)
        elif kind == "panel":
            radius = max(0.0, float(item.get("radius", 14) or 0))
            painter.setPen(QPen(QColor("#34373C"), max(0.5, 1.0 / max(0.01, self.zoom))))
            painter.setBrush(color)
            painter.drawRoundedRect(local, radius, radius)
        elif kind == "text":
            font = QFont(self.font())
            font.setPixelSize(max(6, int(local.height() * 0.62)))
            font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(local, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(item.get("text") or ""))
        elif kind == "image":
            pixmap = self._image(item.get("asset"))
            if pixmap is None or pixmap.isNull():
                painter.setPen(QPen(QColor("#4A4E55"), 1, Qt.PenStyle.DashLine))
                painter.setBrush(QColor(255, 255, 255, 8))
                painter.drawRect(local)
                painter.setPen(QColor("#767B84"))
                painter.drawText(local, Qt.AlignmentFlag.AlignCenter, "?")
            else:
                painter.drawPixmap(local, pixmap, QRectF(pixmap.rect()))
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRect(local)
        painter.restore()

    def _image(self, asset) -> QPixmap | None:
        path = str(asset or "").strip()
        if not path:
            return None
        root = getattr(self, "project_root", None)
        target = Path(path)
        if not target.is_absolute() and root is not None:
            target = Path(root) / target
        key = str(target)
        cached = self._images.get(key)
        if cached is not None:
            return cached
        pixmap = QPixmap(key) if target.exists() else QPixmap()
        self._images[key] = pixmap
        return pixmap if not pixmap.isNull() else None

    def _draw_selection(self, painter: QPainter, item: dict) -> None:
        rect = self._object_rect(item)
        center = rect.center()
        painter.save()
        painter.translate(self.to_widget((center.x(), center.y())))
        painter.rotate(float(item.get("rotation", 0) or 0))
        painter.scale(self.zoom, self.zoom)
        local = QRectF(-rect.width() / 2, -rect.height() / 2, rect.width(), rect.height())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(theme.COLORS["accent"]), max(1.0, 1.0 / self.zoom)))
        painter.drawRect(local)
        painter.restore()

        # Handles stay a constant screen size regardless of zoom.
        for point in self._handle_points(item):
            painter.setPen(QPen(QColor("#1E1F22"), 1))
            painter.setBrush(QColor("#E9EBEE"))
            painter.drawRect(QRectF(point.x() - HANDLE / 2, point.y() - HANDLE / 2, HANDLE, HANDLE))

    def _handle_points(self, item: dict) -> list[QPointF]:
        rect = self._object_rect(item)
        center = rect.center()
        corners = []
        for x, y in (
            (rect.left(), rect.top()),
            (rect.center().x(), rect.top()),
            (rect.right(), rect.top()),
            (rect.right(), rect.center().y()),
            (rect.right(), rect.bottom()),
            (rect.center().x(), rect.bottom()),
            (rect.left(), rect.bottom()),
            (rect.left(), rect.center().y()),
        ):
            angle = math.radians(float(item.get("rotation", 0) or 0))
            dx, dy = x - center.x(), y - center.y()
            rx = dx * math.cos(angle) - dy * math.sin(angle) + center.x()
            ry = dx * math.sin(angle) + dy * math.cos(angle) + center.y()
            corners.append(self.to_widget((rx, ry)))
        return corners

    _HANDLE_NAMES = ("nw", "n", "ne", "e", "se", "s", "sw", "w")

    def _hit_handle(self, pos: QPointF) -> str | None:
        item = self.find(self.selected_id) if self.selected_id else None
        if item is None:
            return None
        for name, point in zip(self._HANDLE_NAMES, self._handle_points(item)):
            if QRectF(point.x() - HANDLE, point.y() - HANDLE, HANDLE * 2, HANDLE * 2).contains(pos):
                return name
        return None

    def _hit_object(self, pos: QPointF) -> dict | None:
        scene_point = self.to_scene(pos)
        for item in reversed(self.objects()):
            rect = self._object_rect(item)
            center = rect.center()
            angle = math.radians(float(item.get("rotation", 0) or 0))
            dx, dy = scene_point.x() - center.x(), scene_point.y() - center.y()
            lx = dx * math.cos(angle) + dy * math.sin(angle) + center.x()
            ly = -dx * math.sin(angle) + dy * math.cos(angle) + center.y()
            if rect.contains(QPointF(lx, ly)):
                return item
        return None

    # -- interaction ---------------------------------------------------
    def _snap_value(self, value: float) -> float:
        if not self.snap:
            return value
        step = max(1, int(self.scene.get("grid") or GRID_STEP))
        return round(value / step) * step

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and self._space_down
        ):
            self._panning = True
            self._drag = {"mode": "pan", "origin": pos, "pan": QPointF(self.pan)}
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()

        handle = self._hit_handle(pos)
        if handle:
            item = self.find(self.selected_id)
            self._drag = {
                "mode": "resize",
                "handle": handle,
                "item": item,
                "start": self.to_scene(pos),
                "rect": self._object_rect(item),
            }
            return

        hit = self._hit_object(pos)
        if hit is not None:
            self.select(str(hit.get("id", "")))
            self._drag = {
                "mode": "move",
                "item": hit,
                "start": self.to_scene(pos),
                "x": float(hit.get("x", 0)),
                "y": float(hit.get("y", 0)),
            }
            return

        if self.tool in {"rect", "circle", "text", "panel"}:
            point = self.to_scene(pos)
            self._drag = {
                "mode": "create",
                "kind": self.tool,
                "start": point,
                "current": point,
            }
            self.update()
            return

        self.select("")

    def _create_at(self, point: QPointF) -> None:
        kind = self.tool
        sizes = {
            "rect": (96.0, 64.0),
            "circle": (64.0, 64.0),
            "text": (180.0, 32.0),
            "panel": (240.0, 150.0),
        }
        width, height = sizes.get(kind, (96.0, 64.0))
        x = self._snap_value(point.x() - width / 2)
        y = self._snap_value(point.y() - height / 2)
        self.add_object(kind, x=x, y=y, w=width, h=height)

    def _finish_create(self, drag: dict) -> None:
        kind = str(drag.get("kind") or self.tool)
        start = drag["start"]
        current = drag["current"]
        width = abs(current.x() - start.x())
        height = abs(current.y() - start.y())
        if width < 8 or height < 8:
            self.tool = kind
            self._create_at(start)
            return
        x = self._snap_value(min(start.x(), current.x()))
        y = self._snap_value(min(start.y(), current.y()))
        if self.snap:
            width = self._snap_value(width)
            height = self._snap_value(height)
        self.add_object(
            kind,
            x=x,
            y=y,
            w=max(MIN_SIZE, width),
            h=max(MIN_SIZE, height),
        )

    def add_object(self, kind: str, **kwargs) -> dict:
        objects = self.scene.setdefault("objects", [])
        index = len(objects) + 1
        item = new_object(kind, index=index, **kwargs)
        objects.append(item)
        self.selected_id = str(item["id"])
        self.selection_changed.emit(self.selected_id)
        self.scene_changed.emit()
        self.update()
        self.setFocus()
        return item

    def duplicate_selected(self) -> None:
        item = self.find(self.selected_id) if self.selected_id else None
        if item is None:
            return
        clone = dict(item)
        clone["id"] = f"obj-{uuid.uuid4().hex[:10]}"
        clone["name"] = f"{item.get('name', '')} 2"
        clone["x"] = float(item.get("x", 0)) + 16
        clone["y"] = float(item.get("y", 0)) + 16
        self.scene.setdefault("objects", []).append(clone)
        self.selected_id = clone["id"]
        self.selection_changed.emit(self.selected_id)
        self.scene_changed.emit()
        self.update()

    def delete_selected(self) -> None:
        item = self.find(self.selected_id) if self.selected_id else None
        if item is None:
            return
        self.scene.get("objects", []).remove(item)
        self.selected_id = ""
        self.selection_changed.emit("")
        self.scene_changed.emit()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        drag = self._drag
        if drag is None:
            if self._hit_handle(pos):
                self.setCursor(Qt.CursorShape.SizeFDiagCursor)
            elif self._hit_object(pos):
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if drag["mode"] == "pan":
            self.pan = drag["pan"] + (pos - drag["origin"])
            self._user_adjusted = True
            self.update()
            return
        if drag["mode"] == "create":
            drag["current"] = self.to_scene(pos)
            self.update()
            return

        item = drag.get("item")
        if item is None:
            return
        current = self.to_scene(pos)
        if drag["mode"] == "move":
            start = drag["start"]
            x = drag["x"] + (current.x() - start.x())
            y = drag["y"] + (current.y() - start.y())
            item["x"] = self._snap_value(x)
            item["y"] = self._snap_value(y)
            self.update()
            return

        if drag["mode"] == "resize":
            self._resize(item, drag, current)

    def _resize(self, item: dict, drag: dict, current: QPointF) -> None:
        rect: QRectF = drag["rect"]
        handle = drag["handle"]
        left, top, right, bottom = rect.left(), rect.top(), rect.right(), rect.bottom()
        if "w" in handle:
            left = min(self._snap_value(current.x()), right - MIN_SIZE)
        if "e" in handle:
            right = max(self._snap_value(current.x()), left + MIN_SIZE)
        if "n" in handle:
            top = min(self._snap_value(current.y()), bottom - MIN_SIZE)
        if "s" in handle:
            bottom = max(self._snap_value(current.y()), top + MIN_SIZE)
        item["x"] = left
        item["y"] = top
        item["w"] = max(MIN_SIZE, right - left)
        item["h"] = max(MIN_SIZE, bottom - top)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._panning:
            self._panning = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if self._drag is not None:
            mode = self._drag.get("mode")
            drag = self._drag
            self._drag = None
            if mode == "create":
                self._finish_create(drag)
            if mode in {"move", "resize"}:
                self.scene_changed.emit()
                self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if not delta:
            return
        before = self.to_scene(event.position())
        self.zoom = _clamp(self.zoom * (1.1 ** (delta / 120)), ZOOM_MIN, ZOOM_MAX)
        self.pan = event.position() - before * self.zoom
        self._user_adjusted = True
        self.zoom_changed.emit(int(round(self.zoom * 100)))
        self.update()
        event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        point = self.to_scene(QPointF(event.pos()))
        menu = QMenu(self)
        for kind, key in (
            ("panel", "scene.tool_panel"),
            ("rect", "scene.tool_rect"),
            ("circle", "scene.tool_circle"),
            ("text", "scene.tool_text"),
        ):
            action = QAction(t(key), menu)
            action.triggered.connect(
                lambda checked=False, value=kind: self._create_kind_at(value, point)
            )
            menu.addAction(action)
        menu.addSeparator()
        item = self.find(self.selected_id) if self.selected_id else None
        duplicate = QAction(t("scene.tool_duplicate"), menu)
        duplicate.setEnabled(item is not None)
        duplicate.triggered.connect(self.duplicate_selected)
        menu.addAction(duplicate)
        remove = QAction(t("scene.tool_delete"), menu)
        remove.setEnabled(item is not None)
        remove.triggered.connect(self.delete_selected)
        menu.addAction(remove)
        front = QAction(t("scene.bring_front"), menu)
        front.setEnabled(item is not None)
        front.triggered.connect(lambda: self._change_layer(1))
        menu.addAction(front)
        back = QAction(t("scene.send_back"), menu)
        back.setEnabled(item is not None)
        back.triggered.connect(lambda: self._change_layer(-1))
        menu.addAction(back)
        menu.addSeparator()
        reset = QAction(t("scene.reset_view"), menu)
        reset.triggered.connect(self.fit_view)
        menu.addAction(reset)
        menu.exec(event.globalPos())

    def _create_kind_at(self, kind: str, point: QPointF) -> None:
        previous = self.tool
        self.tool = kind
        self._create_at(point)
        self.tool = previous

    def _change_layer(self, direction: int) -> None:
        item = self.find(self.selected_id) if self.selected_id else None
        if item is None:
            return
        levels = [int(other.get("z", 0)) for other in self.scene.get("objects") or [] if isinstance(other, dict)]
        if direction > 0:
            item["z"] = max(levels or [0]) + 1
        else:
            item["z"] = min(levels or [0]) - 1
        self.scene_changed.emit()
        self.update()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        tool_keys = {
            Qt.Key.Key_V: "select",
            Qt.Key.Key_R: "rect",
            Qt.Key.Key_O: "circle",
            Qt.Key.Key_T: "text",
            Qt.Key.Key_P: "panel",
        }
        if key in tool_keys:
            self.tool = tool_keys[key]
            self.tool_changed.emit(self.tool)
            self.setCursor(
                Qt.CursorShape.CrossCursor
                if self.tool != "select"
                else Qt.CursorShape.ArrowCursor
            )
            return
        if key == Qt.Key.Key_Space:
            self._space_down = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            return
        if key == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.duplicate_selected()
            return
        if key == Qt.Key.Key_Escape:
            self.tool = "select"
            self.select("")
            return
        if key == Qt.Key.Key_0:
            self.fit_view()
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        item = self.find(self.selected_id) if self.selected_id else None
        if item is not None and key in (
            Qt.Key.Key_Left,
            Qt.Key.Key_Right,
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
        ):
            if key == Qt.Key.Key_Left:
                item["x"] = float(item.get("x", 0)) - step
            elif key == Qt.Key.Key_Right:
                item["x"] = float(item.get("x", 0)) + step
            elif key == Qt.Key.Key_Up:
                item["y"] = float(item.get("y", 0)) - step
            else:
                item["y"] = float(item.get("y", 0)) + step
            self.scene_changed.emit()
            self.update()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_down = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().keyReleaseEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._user_adjusted:
            self.fit_view()


class SceneEditorPage(QWidget):
    """Scene editor page with multiple scenes, toolbar, hierarchy and inspector."""

    status_message = Signal(str)
    run_requested = Signal()

    def __init__(self, project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        window = getattr(project, "window", None) or {}
        self.default_size = (
            int(window.get("width") or 960),
            int(window.get("height") or 540),
        )
        # Existing projects that were created before the scene editor existed
        # still get a usable starter scene instead of an empty canvas.
        # Real projects receive a readable starter level; bare fixtures and
        # app projects start with an empty canvas and the onboarding panel.
        has_history = bool(project.manifest.get("engine_version"))
        if has_history and project.project_type == "game":
            starter_template = "level"
        elif has_history and project.project_type == "app":
            starter_template = "app"
        else:
            starter_template = "empty"
        ensure_scene(
            project.root,
            project_type=project.project_type,
            size=self.default_size,
            template=starter_template,
        )
        scenes = list_scenes(project.root)
        self.scene_name = scenes[0]["id"] if scenes else "main"
        self.scene = load_scene(project.root, self.scene_name, size=self.default_size)
        # Older builds could save an empty scenes/main.json for a real game.
        # Fill that one blank starter scene once, without touching scenes the
        # user has actually created (those have a template marker).
        if (
            has_history
            and self.scene_name == "main"
            and not self.scene.get("objects")
            and not self.scene.get("template")
        ):
            starter = "level" if project.project_type == "game" else "app"
            self.scene["objects"] = template_objects(starter, self.scene["size"])
            self.scene["template"] = starter
            save_scene(project.root, self.scene, "main")
        self._syncing = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self.save_now)
        self._save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self.save_now)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)
        root.addWidget(self._build_scene_bar())
        root.addWidget(self._build_toolbar())

        body = QHBoxLayout()
        body.setSpacing(8)
        body.addWidget(self._build_hierarchy())
        body.addWidget(self._build_viewport(), 1)
        body.addWidget(self._build_inspector())
        root.addLayout(body, 1)
        root.addWidget(self._build_footer())

        self.viewport.set_scene(self.scene)
        self.viewport.project_root = project.root
        self.viewport.selection_changed.connect(self._on_selection)
        self.viewport.scene_changed.connect(self._on_scene_changed)
        self.viewport.tool_changed.connect(self._on_viewport_tool)
        self._refresh_scene_tabs(self.scene_name)
        self._refresh_list(select="")
        self._load_inspector(None)
        self._refresh_empty_panel()

        QTimer.singleShot(0, self.viewport.fit_view)

    # -- scene tabs ----------------------------------------------------
    def _build_scene_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(34)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 3, 8, 3)
        row.setSpacing(6)

        label = QLabel(t("scene.scenes"))
        label.setObjectName("dim")
        label.setFont(theme.section_font())
        row.addWidget(label)

        self.scene_tabs = QTabBar()
        self.scene_tabs.setDrawBase(False)
        self.scene_tabs.setExpanding(False)
        self.scene_tabs.setMovable(False)
        self.scene_tabs.setUsesScrollButtons(True)
        self.scene_tabs.setStyleSheet(
            "QTabBar::tab { background: #232529; color: #B8BDC5; padding: 4px 12px;"
            " border: 1px solid #34373C; border-bottom: none;"
            " border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }"
            "QTabBar::tab:hover { color: #F0F2F5; background: #2A2D32; }"
            "QTabBar::tab:selected { background: #2E3137; color: #F0F2F5;"
            " border-color: #D97757; }"
        )
        self.scene_tabs.currentChanged.connect(self._tab_switched)
        row.addWidget(self.scene_tabs, 1)

        add = QPushButton()
        add.setObjectName("ghost")
        add.setFixedSize(26, 26)
        add.setIcon(theme.icon("plus", 13))
        add.setToolTip(t("scene.new_scene"))
        add.setMenu(self._new_scene_menu())
        row.addWidget(add)

        manage = QPushButton()
        manage.setObjectName("ghost")
        manage.setFixedSize(26, 26)
        manage.setIcon(theme.icon("dots", 14))
        manage.setToolTip(t("scene.manage"))
        manage.setMenu(self._manage_scene_menu())
        row.addWidget(manage)

        row.addSpacing(6)
        run = QPushButton(t("scene.run"))
        run.setObjectName("teal")
        run.setIcon(theme.icon("play", 13, "#1B110D"))
        run.setToolTip(t("scene.run_tip"))
        run.clicked.connect(self.run_requested)
        row.addWidget(run)
        return bar

    def _new_scene_menu(self) -> QMenu:
        menu = QMenu(self)
        for template, key in (
            ("level", "scene.new_level"),
            ("menu", "scene.new_menu"),
            ("empty", "scene.new_empty"),
        ):
            action = QAction(t(key), menu)
            action.triggered.connect(lambda checked=False, value=template: self._create_scene(value))
            menu.addAction(action)
        menu.addSeparator()
        duplicate = QAction(t("scene.duplicate"), menu)
        duplicate.triggered.connect(self._duplicate_scene)
        menu.addAction(duplicate)
        return menu

    def _marker_menu(self) -> QMenu:
        menu = QMenu(self)
        for role, key in (
            ("player", "scene.add_player"),
            ("star", "scene.add_star"),
            ("slime", "scene.add_slime"),
        ):
            action = QAction(t(key), menu)
            action.triggered.connect(
                lambda checked=False, value=role, label=key: self._add_marker(value, t(label))
            )
            menu.addAction(action)
        return menu

    def _manage_scene_menu(self) -> QMenu:
        menu = QMenu(self)
        rename = QAction(t("scene.rename"), menu)
        rename.triggered.connect(self._rename_scene)
        menu.addAction(rename)
        duplicate = QAction(t("scene.duplicate"), menu)
        duplicate.triggered.connect(self._duplicate_scene)
        menu.addAction(duplicate)
        menu.addSeparator()
        settings = QAction(t("scene.settings"), menu)
        settings.triggered.connect(self._scene_settings)
        menu.addAction(settings)
        menu.addSeparator()
        remove = QAction(t("scene.delete"), menu)
        remove.triggered.connect(self._delete_scene)
        menu.addAction(remove)
        return menu

    def _scene_title(self) -> str:
        return str(self.scene.get("name") or self.scene_name)

    def _refresh_scene_tabs(self, select: str | None = None) -> None:
        if not hasattr(self, "scene_tabs"):
            return
        self.scenes = list_scenes(self.project.root)
        self.scene_tabs.blockSignals(True)
        while self.scene_tabs.count():
            self.scene_tabs.removeTab(0)
        target = 0
        for index, summary in enumerate(self.scenes):
            self.scene_tabs.addTab(summary["title"])
            self.scene_tabs.setTabData(index, summary["id"])
            self.scene_tabs.setTabToolTip(
                index,
                f"{summary['title']}  ·  scenes/{summary['id']}.json",
            )
            if summary["id"] == (select or self.scene_name):
                target = index
        self.scene_tabs.setCurrentIndex(max(0, target))
        self.scene_tabs.blockSignals(False)

    def _tab_switched(self, index: int) -> None:
        scene_id = self.scene_tabs.tabData(index)
        if scene_id and str(scene_id) != self.scene_name:
            self._open_scene(str(scene_id))

    def _open_scene(self, scene_id: str) -> None:
        if scene_id == self.scene_name:
            return
        self.save_now()
        self.scene_name = scene_id
        self.scene = load_scene(self.project.root, scene_id, size=self.default_size)
        self.viewport.set_scene(self.scene)
        self.viewport.selected_id = ""
        self._refresh_list(select="")
        self._load_inspector(None)
        self._refresh_scene_tabs(scene_id)
        self._refresh_empty_panel()
        QTimer.singleShot(0, self.viewport.fit_view)
        self.status_message.emit(t("scene.opened", title=self._scene_title()))

    def _create_scene(self, template: str) -> None:
        default = t("scene.new_default_name", index=len(self.scenes) + 1)
        title, ok = QInputDialog.getText(
            self,
            t("scene.new_scene"),
            t("scene.new_prompt"),
            text=default,
        )
        if not ok or not str(title).strip():
            return
        self.save_now()
        size = self.viewport.scene_size()
        created = create_scene(
            self.project.root,
            str(title).strip(),
            size=(size.width(), size.height()) or self.default_size,
            template=template,
        )
        self.scene_name = str(created["id"])
        self.scene = load_scene(self.project.root, self.scene_name, size=self.default_size)
        self.viewport.set_scene(self.scene)
        self.viewport.selected_id = ""
        self._refresh_scene_tabs(self.scene_name)
        self._refresh_list(select="")
        self._load_inspector(None)
        self._refresh_empty_panel()
        QTimer.singleShot(0, self.viewport.fit_view)
        self.status_message.emit(t("scene.created", title=self._scene_title()))

    def _rename_scene(self) -> None:
        title, ok = QInputDialog.getText(
            self,
            t("scene.rename"),
            t("scene.new_prompt"),
            text=self._scene_title(),
        )
        if not ok or not str(title).strip():
            return
        self.save_now()
        if rename_scene(self.project.root, self.scene_name, str(title).strip()):
            self.scene["name"] = str(title).strip()
            self._refresh_scene_tabs(self.scene_name)
            self.status_message.emit(t("scene.renamed", title=self._scene_title()))

    def _duplicate_scene(self) -> None:
        self.save_now()
        created = duplicate_scene(self.project.root, self.scene_name)
        if created is None:
            return
        self.scene_name = str(created["id"])
        self.scene = load_scene(self.project.root, self.scene_name, size=self.default_size)
        self.viewport.set_scene(self.scene)
        self.viewport.selected_id = ""
        self._refresh_scene_tabs(self.scene_name)
        self._refresh_list(select="")
        self._load_inspector(None)
        self._refresh_empty_panel()
        QTimer.singleShot(0, self.viewport.fit_view)
        self.status_message.emit(t("scene.created", title=self._scene_title()))

    def _delete_scene(self) -> None:
        if len(self.scenes) <= 1:
            QMessageBox.information(
                self,
                t("scene.delete"),
                t("scene.delete_last"),
            )
            return
        answer = QMessageBox.question(
            self,
            t("scene.delete"),
            t("scene.delete_text", title=self._scene_title()),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_scene(self.project.root, self.scene_name)
        remaining = list_scenes(self.project.root)
        self.scene_name = remaining[0]["id"] if remaining else "main"
        self.scene = load_scene(self.project.root, self.scene_name, size=self.default_size)
        self.viewport.set_scene(self.scene)
        self.viewport.selected_id = ""
        self._refresh_scene_tabs(self.scene_name)
        self._refresh_list(select="")
        self._load_inspector(None)
        self._refresh_empty_panel()
        QTimer.singleShot(0, self.viewport.fit_view)
        self.status_message.emit(t("scene.deleted", title=self._scene_title()))

    def _scene_settings(self) -> None:
        dialog = SceneSettingsDialog(self.scene, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if not values["name"]:
            values["name"] = self._scene_title()
        self.scene["name"] = values["name"]
        self.scene["size"] = values["size"]
        self.scene["grid"] = values["grid"]
        self.scene["background"] = values["background"]
        self.save_now()
        self._refresh_scene_tabs(self.scene_name)
        self.viewport.fit_view()
        self.status_message.emit(t("scene.settings_saved", title=self._scene_title()))

    def _refresh_empty_panel(self) -> None:
        if not hasattr(self, "empty_panel"):
            return
        self.empty_panel.setVisible(not (self.viewport.scene.get("objects") or []))

    # -- construction --------------------------------------------------
    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(38)
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(2)

        self.tool_buttons: dict[str, QPushButton] = {}
        for name, icon_name, label, shortcut in (
            ("select", "pointer", "scene.tool_select", "V"),
            ("rect", "square", "scene.tool_rect", "R"),
            ("circle", "circle", "scene.tool_circle", "O"),
            ("text", "text", "scene.tool_text", "T"),
            ("panel", "layers", "scene.tool_panel", "P"),
            ("image", "image", "scene.tool_image", "I"),
        ):
            button = QPushButton()
            button.setObjectName("ghost")
            button.setCheckable(name != "image")
            button.setFixedSize(28, 28)
            button.setIcon(theme.icon(icon_name, 15))
            button.setToolTip(f"{t(label)}  ({shortcut})")
            button.clicked.connect(lambda checked=False, tool=name: self._pick_tool(tool))
            row.addWidget(button)
            self.tool_buttons[name] = button
        self.tool_buttons["select"].setChecked(True)

        row.addSpacing(8)
        self.snap_check = QCheckBox(t("scene.snap"))
        self.snap_check.setChecked(True)
        self.snap_check.toggled.connect(self._toggle_snap)
        row.addWidget(self.snap_check)
        self.grid_check = QCheckBox(t("scene.grid"))
        self.grid_check.setChecked(True)
        self.grid_check.toggled.connect(self._toggle_grid)
        row.addWidget(self.grid_check)

        row.addStretch(1)
        markers = QPushButton()
        markers.setObjectName("ghost")
        markers.setFixedSize(28, 28)
        markers.setIcon(theme.icon("move", 15))
        markers.setToolTip(t("scene.markers"))
        markers.setMenu(self._marker_menu())
        row.addWidget(markers)
        duplicate = QPushButton()
        duplicate.setObjectName("ghost")
        duplicate.setFixedSize(28, 28)
        duplicate.setIcon(theme.icon("layers", 15))
        duplicate.setToolTip(t("scene.tool_duplicate"))
        duplicate.clicked.connect(self.viewport_duplicate)
        row.addWidget(duplicate)
        remove = QPushButton()
        remove.setObjectName("ghost")
        remove.setFixedSize(28, 28)
        remove.setIcon(theme.icon("trash", 15))
        remove.setToolTip(t("scene.tool_delete"))
        remove.clicked.connect(self.viewport_delete)
        row.addWidget(remove)

        row.addSpacing(8)
        zoom_out = QPushButton()
        zoom_out.setObjectName("ghost")
        zoom_out.setFixedSize(28, 28)
        zoom_out.setIcon(theme.icon("zoom-out", 15))
        zoom_out.setToolTip(t("scene.zoom_out"))
        zoom_out.clicked.connect(lambda: self._zoom_step(1 / 1.2))
        row.addWidget(zoom_out)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("dim")
        self.zoom_label.setFixedWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.zoom_label)
        zoom_in = QPushButton()
        zoom_in.setObjectName("ghost")
        zoom_in.setFixedSize(28, 28)
        zoom_in.setIcon(theme.icon("zoom-in", 15))
        zoom_in.setToolTip(t("scene.zoom_in"))
        zoom_in.clicked.connect(lambda: self._zoom_step(1.2))
        row.addWidget(zoom_in)
        reset = QPushButton()
        reset.setObjectName("ghost")
        reset.setFixedSize(28, 28)
        reset.setIcon(theme.icon("refresh", 15))
        reset.setToolTip(t("scene.reset_view"))
        reset.clicked.connect(lambda: self.viewport.fit_view())
        row.addWidget(reset)

        save = QPushButton(t("scene.save").split(" (")[0])
        save.setObjectName("ghost")
        save.setIcon(theme.icon("save", 14))
        save.setToolTip(t("scene.save"))
        save.clicked.connect(self.save_now)
        row.addWidget(save)
        return bar

    def _build_hierarchy(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        frame.setFixedWidth(196)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        head = QHBoxLayout()
        caption = QLabel(t("scene.objects"))
        caption.setObjectName("dim")
        caption.setFont(theme.section_font())
        head.addWidget(caption)
        head.addStretch(1)
        for icon_name, kind in (("square", "rect"), ("circle", "circle"), ("text", "text")):
            add = QPushButton()
            add.setObjectName("ghost")
            add.setFixedSize(22, 22)
            add.setIcon(theme.icon(icon_name, 13))
            add.setToolTip(t(f"scene.tool_{kind}"))
            add.clicked.connect(lambda checked=False, k=kind: self._quick_add(k))
            head.addWidget(add)
        layout.addLayout(head)

        self.list = QListWidget()
        self.list.setIconSize(QSize(14, 14))
        self.list.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.currentItemChanged.connect(self._list_selected)
        layout.addWidget(self.list, 1)
        return frame

    def _build_viewport(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)

        self.empty_panel = QFrame()
        self.empty_panel.setObjectName("cardSoft")
        empty = QVBoxLayout(self.empty_panel)
        empty.setContentsMargins(14, 10, 14, 10)
        empty.setSpacing(7)
        empty_title = QLabel(t("scene.empty_title"))
        empty_title.setFont(theme.ui_font(10, 600))
        empty_title.setStyleSheet("color: #E7E9EC; background: transparent; border: none;")
        empty.addWidget(empty_title)
        hint = QLabel(t("scene.empty_text"))
        hint.setWordWrap(True)
        hint.setObjectName("dim")
        hint.setFont(theme.ui_font(8))
        empty.addWidget(hint)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        for key, kind in (
            ("scene.add_platform", "rect"),
            ("scene.add_circle", "circle"),
            ("scene.add_text", "text"),
        ):
            button = QPushButton(t(key))
            button.setObjectName("ghost")
            button.clicked.connect(lambda checked=False, value=kind: self._quick_add(value))
            buttons.addWidget(button)
        marker = QPushButton(t("scene.add_player"))
        marker.setObjectName("teal")
        marker.setToolTip(t("scene.add_player_tip"))
        marker.setVisible(self.project.project_type == "game")
        marker.clicked.connect(
            lambda: self._add_marker("player", t("scene.add_player"))
        )
        buttons.addWidget(marker)
        buttons.addStretch(1)
        empty.addLayout(buttons)
        self.empty_panel.hide()
        layout.addWidget(self.empty_panel)

        self.viewport = SceneViewport()
        layout.addWidget(self.viewport, 1)
        self.viewport.zoom_changed.connect(self._update_zoom)
        return frame

    def _build_inspector(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(224)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QFrame()
        host.setObjectName("card")
        scroll.setWidget(host)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(7)

        caption = QLabel(t("scene.inspector"))
        caption.setObjectName("dim")
        caption.setFont(theme.section_font())
        layout.addWidget(caption)

        self.empty_label = QLabel(t("scene.no_selection"))
        self.empty_label.setObjectName("dim")
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("padding: 16px 0;")
        layout.addWidget(self.empty_label)

        self.form = QWidget()
        form = QVBoxLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.name_edit = QLineEdit()
        self.name_edit.editingFinished.connect(self._apply_fields)
        form.addLayout(self._field(t("scene.field_name"), self.name_edit))

        x_row = QHBoxLayout()
        x_row.setSpacing(5)
        self.x_spin = self._spin()
        self.y_spin = self._spin()
        self.x_spin.setPrefix("X ")
        self.y_spin.setPrefix("Y ")
        x_row.addWidget(self.x_spin)
        x_row.addWidget(self.y_spin)
        form.addLayout(self._field(t("scene.field_position"), x_row))

        size_row = QHBoxLayout()
        size_row.setSpacing(5)
        self.w_spin = self._spin(minimum=MIN_SIZE)
        self.h_spin = self._spin(minimum=MIN_SIZE)
        self.w_spin.setPrefix("W ")
        self.h_spin.setPrefix("H ")
        size_row.addWidget(self.w_spin)
        size_row.addWidget(self.h_spin)
        form.addLayout(self._field(t("scene.field_size"), size_row))

        rot_row = QHBoxLayout()
        rot_row.setSpacing(5)
        self.rotation_spin = self._spin(minimum=-360, maximum=360)
        self.rotation_spin.setSuffix("°")
        self.z_spin = QSpinBox()
        self.z_spin.setRange(-999, 999)
        self.z_spin.setMinimumWidth(56)
        self.z_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.z_spin.valueChanged.connect(self._apply_fields)
        rot_row.addWidget(self.rotation_spin)
        rot_row.addWidget(self.z_spin)
        form.addLayout(self._field(t("scene.field_rotation"), rot_row))

        self.radius_spin = self._spin(minimum=0, maximum=300)
        self.radius_spin.setSuffix(" px")
        self.radius_label = self._field_label(t("scene.field_radius"))
        form.addWidget(self.radius_label)
        form.addWidget(self.radius_spin)

        self.text_edit = QLineEdit()
        self.text_edit.editingFinished.connect(self._apply_fields)
        self.text_label = self._field_label(t("scene.field_text"))
        form.addWidget(self.text_label)
        form.addWidget(self.text_edit)

        self.asset_row_host = QWidget()
        asset_row = QHBoxLayout(self.asset_row_host)
        asset_row.setContentsMargins(0, 0, 0, 0)
        asset_row.setSpacing(5)
        self.asset_edit = QLineEdit()
        self.asset_edit.setReadOnly(True)
        self.asset_button = QPushButton(t("scene.pick_asset"))
        self.asset_button.setObjectName("ghost")
        self.asset_button.clicked.connect(self._pick_asset)
        asset_row.addWidget(self.asset_edit, 1)
        asset_row.addWidget(self.asset_button)
        self.asset_label = self._field_label(t("scene.field_asset"))
        form.addWidget(self.asset_label)
        form.addWidget(self.asset_row_host)

        self.color_button = QPushButton()
        self.color_button.setFixedHeight(24)
        self.color_button.clicked.connect(self._pick_color)
        form.addLayout(self._field(t("scene.field_color"), self.color_button))

        self.visible_check = QCheckBox(t("scene.field_visible"))
        self.visible_check.toggled.connect(self._apply_fields)
        form.addWidget(self.visible_check)

        layout.addWidget(self.form)
        layout.addStretch(1)
        return scroll

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("dim")
        label.setFont(theme.ui_font(8))
        return label

    def _field(self, label_text: str, widget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(2)
        box.addWidget(self._field_label(label_text))
        if isinstance(widget, (QHBoxLayout, QVBoxLayout)):
            box.addLayout(widget)
        else:
            box.addWidget(widget)
        return box

    def _spin(self, *, minimum: float = -100000, maximum: float = 100000) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setMinimumWidth(56)
        spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        spin.setKeyboardTracking(False)
        spin.valueChanged.connect(self._apply_fields)
        return spin

    def _build_footer(self) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(2, 0, 2, 0)
        hint = QLabel(t("scene.footer_hint"))
        hint.setObjectName("dim")
        hint.setFont(theme.ui_font(8))
        line.addWidget(hint)
        line.addStretch(1)
        self.save_state = QLabel(t("scene.save_hint"))
        self.save_state.setObjectName("dim")
        self.save_state.setFont(theme.ui_font(8))
        line.addWidget(self.save_state)
        return row

    # -- tools ---------------------------------------------------------
    def _on_viewport_tool(self, tool: str) -> None:
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool and name != "image")

    def _pick_tool(self, tool: str) -> None:
        if tool == "image":
            self._add_image()
            self._set_tool("select")
            return
        self._set_tool(tool)

    def _set_tool(self, tool: str) -> None:
        self.viewport.tool = tool
        for name, button in self.tool_buttons.items():
            button.setChecked(name == tool and name != "image")
        if tool in {"rect", "circle", "text", "panel"}:
            self.viewport.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport.setCursor(Qt.CursorShape.ArrowCursor)
        self.viewport.setFocus()

    def _quick_add(self, kind: str) -> None:
        size = self.viewport.scene_size()
        width, height = {
            "rect": (96, 64),
            "circle": (64, 64),
            "text": (180, 32),
            "panel": (240, 150),
        }.get(kind, (96, 64))
        # Stagger repeated clicks so new objects do not stack exactly.
        offset = (len(self.viewport.scene.get("objects") or []) % 6) * 24
        self.viewport.add_object(
            kind,
            x=size.width() / 2 - width / 2 + offset,
            y=size.height() / 2 - height / 2 + offset,
            w=width,
            h=height,
        )
        self.status_message.emit(t("scene.added"))

    def _add_marker(self, role: str, name: str) -> None:
        """Add a hidden spawn marker used by the sample game."""
        size = self.viewport.scene_size()
        marker_size = {"star": 32, "slime": 44}.get(role, 56)
        item = self.viewport.add_object(
            "rect",
            x=size.width() / 2 - marker_size / 2,
            y=size.height() / 2 - marker_size / 2,
            w=marker_size,
            h=marker_size,
            color="#7FA3C7",
            name=name,
        )
        item["visible"] = False
        item["marker"] = True
        item["role"] = role
        self._on_scene_changed()
        self.status_message.emit(t("scene.added"))

    def _add_image(self) -> None:
        start = str(self.project.root)
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("scene.tool_image"),
            start,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not path:
            return
        try:
            relative = str(Path(path).resolve().relative_to(self.project.root.resolve())).replace("\\", "/")
        except ValueError:
            relative = path
        pixmap = QPixmap(path)
        width = min(240, max(32, pixmap.width() if not pixmap.isNull() else 64))
        height = min(240, max(32, pixmap.height() if not pixmap.isNull() else 64))
        size = self.viewport.scene_size()
        self.viewport.add_object(
            "image",
            x=size.width() / 2 - width / 2,
            y=size.height() / 2 - height / 2,
            w=width,
            h=height,
            asset=relative,
        )
        self.status_message.emit(t("scene.added"))

    def _toggle_snap(self, checked: bool) -> None:
        self.viewport.snap = bool(checked)

    def _toggle_grid(self, checked: bool) -> None:
        self.viewport.show_grid = bool(checked)
        self.viewport.update()

    def viewport_duplicate(self) -> None:
        self.viewport.duplicate_selected()

    def viewport_delete(self) -> None:
        self.viewport.delete_selected()

    def _update_zoom(self, percent: int) -> None:
        self.zoom_label.setText(f"{percent}%")

    def _zoom_step(self, factor: float) -> None:
        viewport = self.viewport
        before = viewport.to_scene(QPointF(viewport.rect().center()))
        viewport.zoom = _clamp(viewport.zoom * factor, ZOOM_MIN, ZOOM_MAX)
        viewport.pan = QPointF(viewport.rect().center()) - before * viewport.zoom
        viewport._user_adjusted = True
        viewport.zoom_changed.emit(int(round(viewport.zoom * 100)))
        viewport.update()

    # -- selection / list ---------------------------------------------
    def _on_selection(self, object_id: str) -> None:
        self._select_row(object_id)
        self._load_inspector(self.viewport.find(object_id) if object_id else None)

    def _select_row(self, object_id: str) -> None:
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == object_id:
                self.list.setCurrentItem(item)
                break
        else:
            self.list.setCurrentItem(None)
        self.list.blockSignals(False)

    def _list_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if self._syncing or current is None:
            return
        self.viewport.select(str(current.data(Qt.ItemDataRole.UserRole) or ""))

    def _refresh_list(self, select: str | None = None) -> None:
        self._syncing = True
        self.list.clear()
        for item in self.viewport.objects():
            row = QListWidgetItem(str(item.get("name") or ""))
            row.setData(Qt.ItemDataRole.UserRole, str(item.get("id") or ""))
            icon = (
                "move"
                if item.get("marker")
                else _KIND_ICONS.get(str(item.get("kind") or "rect"), "square")
            )
            row.setIcon(theme.icon(icon, 13))
            row.setToolTip(
                f"{item.get('name') or ''}\n{t('scene.marker_tip')}"
                if item.get("marker")
                else str(item.get("name") or "")
            )
            if not item.get("visible", True):
                row.setForeground(QColor(theme.COLORS["dim"]))
            self.list.addItem(row)
        self._syncing = False
        target = select if select is not None else self.viewport.selected_id
        self._select_row(target)

    def _on_scene_changed(self) -> None:
        self._refresh_list()
        self._refresh_empty_panel()
        self._schedule_save()

    # -- inspector -----------------------------------------------------
    def _load_inspector(self, item: dict | None) -> None:
        self._syncing = True
        try:
            self.form.setVisible(item is not None)
            self.empty_label.setVisible(item is None)
            if item is None:
                return
            self.name_edit.setText(str(item.get("name") or ""))
            self.x_spin.setValue(float(item.get("x", 0)))
            self.y_spin.setValue(float(item.get("y", 0)))
            self.w_spin.setValue(float(item.get("w", 32)))
            self.h_spin.setValue(float(item.get("h", 32)))
            self.rotation_spin.setValue(float(item.get("rotation", 0)))
            self.z_spin.setValue(int(item.get("z", 0)))
            self.visible_check.setChecked(bool(item.get("visible", True)))
            kind = str(item.get("kind") or "rect")
            self.radius_label.setVisible(kind == "panel")
            self.radius_spin.setVisible(kind == "panel")
            self.radius_spin.setValue(float(item.get("radius", 14) if kind == "panel" else 0))
            self.text_label.setVisible(kind == "text")
            self.text_edit.setVisible(kind == "text")
            self.text_edit.setText(str(item.get("text") or ""))
            self.asset_label.setVisible(kind == "image")
            self.asset_row_host.setVisible(kind == "image")
            self.asset_edit.setText(str(item.get("asset") or ""))
            color = QColor(str(item.get("color") or "#D97757"))
            luminance = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
            foreground = "#1B1D21" if luminance > 150 else "#F0F2F5"
            self.color_button.setStyleSheet(
                f"background: {color.name()}; color: {foreground};"
                "border: 1px solid #4A4E55; border-radius: 3px;"
            )
            self.color_button.setText(color.name().upper())
        finally:
            self._syncing = False

    def _apply_fields(self, *_args) -> None:
        if self._syncing:
            return
        item = self.viewport.find(self.viewport.selected_id) if self.viewport.selected_id else None
        if item is None:
            return
        item["name"] = self.name_edit.text().strip() or str(item.get("name") or "")
        item["x"] = self.x_spin.value()
        item["y"] = self.y_spin.value()
        item["w"] = max(MIN_SIZE, self.w_spin.value())
        item["h"] = max(MIN_SIZE, self.h_spin.value())
        item["rotation"] = self.rotation_spin.value()
        item["z"] = self.z_spin.value()
        item["visible"] = self.visible_check.isChecked()
        if item.get("kind") == "panel":
            item["radius"] = max(0.0, self.radius_spin.value())
        if item.get("kind") == "text":
            item["text"] = self.text_edit.text()
        self.viewport.update()
        self._refresh_list()
        self._schedule_save()

    def _pick_color(self) -> None:
        item = self.viewport.find(self.viewport.selected_id) if self.viewport.selected_id else None
        if item is None:
            return
        current = QColor(str(item.get("color") or "#D97757"))
        chosen = QColorDialog.getColor(current, self, t("scene.field_color"))
        if not chosen.isValid():
            return
        item["color"] = chosen.name()
        self._load_inspector(item)
        self.viewport.update()
        self._schedule_save()

    def _pick_asset(self) -> None:
        item = self.viewport.find(self.viewport.selected_id) if self.viewport.selected_id else None
        if item is None:
            return
        start = str(self.project.root)
        path, _ = QFileDialog.getOpenFileName(
            self,
            t("scene.pick_asset"),
            start,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not path:
            return
        try:
            relative = str(Path(path).resolve().relative_to(self.project.root.resolve())).replace("\\", "/")
        except ValueError:
            relative = path
        item["asset"] = relative
        self.viewport._images.clear()
        self._load_inspector(item)
        self.viewport.update()
        self._schedule_save()

    # -- persistence ---------------------------------------------------
    def _schedule_save(self) -> None:
        self.save_state.setText(t("scene.dirty"))
        self._save_timer.start(600)

    def save_now(self) -> None:
        self._save_timer.stop()
        self.scene["objects"] = [
            item for item in (self.scene.get("objects") or []) if isinstance(item, dict)
        ]
        try:
            path = save_scene(self.project.root, self.scene, self.scene_name)
        except Exception as exc:  # pragma: no cover - disk errors
            self.status_message.emit(t("scene.save_failed", error=exc))
            return
        self.save_state.setText(t("scene.save_hint"))
        self.status_message.emit(t("scene.saved", path=self.project.rel(path)))

    def shutdown(self) -> None:
        if self._save_timer.isActive():
            self.save_now()

    def flush(self) -> None:
        """Save pending edits without reporting when nothing changed."""
        if self._save_timer.isActive():
            self.save_now()
