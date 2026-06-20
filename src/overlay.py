from __future__ import annotations

import ctypes
from typing import Optional

import glfw
import OpenGL.GL as gl
from slimgui import imgui
from slimgui.integrations.glfw import GlfwRenderer

from src.calculator import OffsetCalculator, get_offset_color
from src.memory_reader import GameData

WINDOW_WIDTH = 440
WINDOW_HEIGHT = 180
RESIZE_GRAB_SIZE = 16

WS_EX_TOPMOST = 0x8
WS_EX_TOOLWINDOW = 0x80
GWL_EXSTYLE = -20

SetWindowLong = ctypes.windll.user32.SetWindowLongW
GetWindowLong = ctypes.windll.user32.GetWindowLongW

SWP_NOSIZE = 0x1
SWP_NOMOVE = 0x2
SWP_NOZORDER = 0x4
SWP_SHOWWINDOW = 0x40
HWND_TOPMOST = -1

SetWindowPos = ctypes.windll.user32.SetWindowPos

_BG = (0.11, 0.11, 0.12, 1.0)
_BG_DARK = (0.07, 0.07, 0.08, 1.0)

def _rgba(r: int, g: int, b: int, a: int) -> tuple[float, float, float, float]:
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


class OffsetOverlay:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._window: Optional[int] = None
        self._impl: Optional[GlfwRenderer] = None
        self._calc: Optional[OffsetCalculator] = None
        self._running = False
        self._window_width = WINDOW_WIDTH
        self._window_height = WINDOW_HEIGHT
        self._dragging = False
        self._drag_off_x = 0
        self._drag_off_y = 0
        self._resizing = False

    @property
    def running(self) -> bool:
        return self._running and not glfw.window_should_close(self._window)

    def setup(self, calc: OffsetCalculator) -> None:
        self._calc = calc
        imgui.create_context()
        imgui.get_io().ini_filename = None

        glfw.init()
        glfw.window_hint(glfw.DECORATED, False)
        glfw.window_hint(glfw.FLOATING, True)
        glfw.window_hint(glfw.RESIZABLE, True)
        glfw.window_hint(glfw.SAMPLES, 4)

        monitor = glfw.get_primary_monitor()
        mode = glfw.get_video_mode(monitor)
        wx = mode.size.width - WINDOW_WIDTH - 20
        wy = 20

        self._window = glfw.create_window(
            WINDOW_WIDTH, WINDOW_HEIGHT, "Offset Suggester", None, None
        )
        if self._window is None:
            raise RuntimeError("Failed to create GLFW window")

        glfw.set_window_pos(self._window, wx, wy)
        glfw.make_context_current(self._window)
        glfw.set_window_size_callback(self._window, self._on_resize)

        hwnd = glfw.get_win32_window(self._window)
        ex_style = GetWindowLong(hwnd, GWL_EXSTYLE)
        ex_style |= WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        SetWindowLong(hwnd, GWL_EXSTYLE, ex_style)
        SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW,
        )

        print(f"Window created: {WINDOW_WIDTH}x{WINDOW_HEIGHT} at ({wx}, {wy})")

        self._impl = GlfwRenderer(self._window)
        self._running = True

    def _on_resize(self, window: int, w: int, h: int) -> None:
        self._window_width = w
        self._window_height = h

    def render(self, data: Optional[GameData]) -> None:
        glfw.poll_events()
        self._impl.new_frame()

        imgui.new_frame()

        if self._calc:
            self._calc.update_warning()

        imgui.push_style_var(imgui.StyleVar.WINDOW_ROUNDING, 0)
        imgui.push_style_var(imgui.StyleVar.WINDOW_PADDING, (16, 12))

        imgui.push_style_color(imgui.Col.WINDOW_BG, _BG)
        imgui.push_style_color(imgui.Col.TITLE_BG, _BG_DARK)
        imgui.push_style_color(imgui.Col.TITLE_BG_ACTIVE, _BG_DARK)
        imgui.push_style_color(imgui.Col.TITLE_BG_COLLAPSED, _BG_DARK)

        imgui.set_next_window_pos((0, 0))
        imgui.set_next_window_size(
            (self._window_width, self._window_height)
        )

        flags = (
            imgui.WindowFlags.NO_RESIZE
            | imgui.WindowFlags.NO_SCROLLBAR
            | imgui.WindowFlags.NO_BRING_TO_FRONT_ON_FOCUS
            | imgui.WindowFlags.NO_FOCUS_ON_APPEARING
        )

        imgui.begin("Offset Suggester", closable=False, flags=flags)

        self._handle_window_ops()

        if data and data.connected:
            self._draw_card()
        else:
            self._draw_disconnected()

        imgui.end()

        imgui.pop_style_color(4)
        imgui.pop_style_var(2)

        imgui.render()
        gl.glClearColor(*_BG_DARK)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        self._impl.render(imgui.get_draw_data())
        glfw.swap_buffers(self._window)

    def _handle_window_ops(self) -> None:
        mx, my = imgui.get_mouse_pos()
        ww, wh = self._window_width, self._window_height

        in_resize = (
            mx >= ww - RESIZE_GRAB_SIZE and my >= wh - RESIZE_GRAB_SIZE
        )
        in_titlebar = (
            imgui.is_item_hovered() and my < 28
        )

        if in_resize and imgui.is_mouse_clicked(0):
            self._resizing = True
        elif in_titlebar and imgui.is_mouse_clicked(0):
            self._dragging = True
            cx, cy = glfw.get_cursor_pos(self._window)
            self._drag_off_x = int(cx)
            self._drag_off_y = int(cy)

        if self._dragging and imgui.is_mouse_down(0):
            cx, cy = glfw.get_cursor_pos(self._window)
            wx, wy = glfw.get_window_pos(self._window)
            glfw.set_window_pos(
                self._window,
                int(wx + cx - self._drag_off_x),
                int(wy + cy - self._drag_off_y),
            )
        elif self._dragging and not imgui.is_mouse_down(0):
            self._dragging = False

        if self._resizing and imgui.is_mouse_down(0):
            nw = max(200, int(mx) + RESIZE_GRAB_SIZE)
            nh = max(150, int(my) + RESIZE_GRAB_SIZE)
            glfw.set_window_size(self._window, int(nw), int(nh))
        elif self._resizing and not imgui.is_mouse_down(0):
            self._resizing = False

        if in_resize:
            imgui.set_mouse_cursor(imgui.MouseCursor.RESIZE_NWSE)
        elif in_titlebar:
            imgui.set_mouse_cursor(imgui.MouseCursor.ARROW)

    def _draw_card(self) -> None:
        calc = self._calc
        if calc is None:
            return

        imgui.push_style_var(imgui.StyleVar.ITEM_SPACING, (0, 4))

        # self._draw_header()
        self._draw_suggested(calc)
        imgui.separator()
        self._draw_stats(calc)
        self._draw_reset_button(calc)
        self._draw_warning(calc)

        imgui.pop_style_var()

    def _draw_suggested(self, calc: OffsetCalculator) -> None:
        imgui.spacing()

        label = "Suggested  UNIVERSAL  Offset"
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 255, 255, 191))
        imgui.text(label)
        imgui.pop_style_color()

        if calc.settings.suggested_offset_enable:
            diff = calc.suggested_offset - (calc.client_universal_offset or 0)
            if calc.settings.suggested_offset_color_enable:
                r, g, b = get_offset_color(diff)
                color = (r / 255.0, g / 255.0, b / 255.0, 1.0)
            else:
                color = (1.0, 1.0, 1.0, 1.0)
        else:
            color = (1.0, 1.0, 1.0, 0.25)

        imgui.push_style_color(imgui.Col.TEXT, color)
        imgui.text(f"{calc.suggested_offset}")
        imgui.pop_style_color()

        imgui.same_line()
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 255, 255, 153))
        imgui.text("ms")
        imgui.pop_style_color()

    def _draw_stats(self, calc: OffsetCalculator) -> None:
        imgui.spacing()

        col1 = imgui.get_cursor_pos_x()
        imgui.begin_group()

        label_current = "Current  UNIVERSAL  Offset"
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 255, 255, 153))
        imgui.text(label_current)
        imgui.pop_style_color()

        opacity = 1.0 if calc.settings.current_offset_enable else 0.25
        imgui.push_style_color(imgui.Col.TEXT, (1.0, 1.0, 1.0, opacity))
        imgui.text(f"{calc.current_offset}  ms")
        imgui.pop_style_color()

        imgui.end_group()

        available = self._window_width - 32
        right_x = col1 + (available / 2)

        imgui.same_line()
        imgui.set_cursor_pos_x(right_x)

        imgui.begin_group()

        label_last = "Last Map's  LOCAL  Offset"
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 255, 255, 153))
        imgui.text(label_last)
        imgui.pop_style_color()

        opacity = 1.0 if calc.settings.last_map_offset_enable else 0.25
        imgui.push_style_color(imgui.Col.TEXT, (1.0, 1.0, 1.0, opacity))
        imgui.text(f"{calc.last_map_offset}  ms")
        imgui.pop_style_color()

        imgui.end_group()

    def _draw_reset_button(self, calc: OffsetCalculator) -> None:
        imgui.spacing()

        imgui.push_style_color(imgui.Col.BUTTON, _rgba(255, 255, 255, 20))
        imgui.push_style_color(imgui.Col.BUTTON_HOVERED, _rgba(255, 100, 100, 60))
        imgui.push_style_color(imgui.Col.BUTTON_ACTIVE, _rgba(255, 100, 100, 40))
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 180, 180, 200))
        if imgui.button("Reset Data"):
            calc.clear_data()
        imgui.pop_style_color(4)

    def _draw_warning(self, calc: OffsetCalculator) -> None:
        opacity = calc.get_warning_opacity()
        if opacity > 0 and calc.warning_text:
            imgui.spacing()
            imgui.push_style_color(
                imgui.Col.TEXT, (1.0, 196 / 255, 186 / 255, opacity)
            )
            imgui.text(calc.warning_text)
            imgui.pop_style_color()

    def _draw_disconnected(self) -> None:
        imgui.push_style_color(imgui.Col.TEXT, _rgba(255, 255, 255, 127))
        imgui.text("Waiting for osu!...")
        imgui.pop_style_color()

    def close(self) -> None:
        self._running = False
        if self._impl:
            self._impl.shutdown()
        if self._window:
            glfw.destroy_window(self._window)
        glfw.terminate()
