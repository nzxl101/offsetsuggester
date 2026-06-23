import math
import time
from typing import Optional

from src.memory_reader import BanchoStatus, GameData, GameState


def calculate_median(values: list[int]) -> int:
    if len(values) == 0:
        return 0
    if len(values) == 1:
        return values[0]
    sorted_vals = sorted(values)
    center = len(sorted_vals) // 2
    if len(sorted_vals) % 2 == 0:
        return round((sorted_vals[center - 1] + sorted_vals[center]) / 2)
    return sorted_vals[center]


def calculate_average(values: list[int]) -> Optional[int]:
    if len(values) == 0:
        return None
    if len(values) == 1:
        return values[0]
    avg = sum(values) / len(values)
    if math.isnan(avg):
        return None
    return round(avg)


def get_offset_color(diff: int, max_diff: int = 15) -> tuple[int, int, int]:
    distance = min(abs(diff), max_diff)
    t = distance / max_diff
    r = round(255 * t)
    g = round(255 * (1 - t))
    return (r, g, 0)


class OffsetCalculator:
    def __init__(self, settings) -> None:
        self.settings = settings

        self.client_universal_offset: Optional[int] = None
        self.global_offsets: list[int] = []
        self.hit_errors: list[int] = []
        self.was_playing = False

        self.suggested_offset: int = 0
        self.current_offset: int = 0
        self.last_map_offset: int = 0
        self.warning_text: str = ""
        self.warning_visible: bool = False
        self.warning_timer: float = 0.0

    def update(self, data: GameData) -> None:
        if not data.connected:
            return

        is_playing = self._is_playing(data)
        current_errors = data.hit_errors

        if self.client_universal_offset is None:
            self.client_universal_offset = data.universal_offset
            self.current_offset = data.universal_offset
        elif data.universal_offset != self.client_universal_offset:
            self._on_universal_offset_changed(data.universal_offset)

        if is_playing:
            if not self.was_playing:
                self.hit_errors = []
                self.was_playing = True
                return

            if len(current_errors) >= len(self.hit_errors):
                if len(current_errors) == len(self.hit_errors):
                    self.was_playing = True
                    return

                self.hit_errors = current_errors

                if self.settings.realtime_offset_calculation:
                    self.last_map_offset = calculate_median(self.hit_errors)

                self.was_playing = True
                return

            self._on_map_finish()
            self.hit_errors = current_errors
            self.was_playing = True
            return

        if self.was_playing and not is_playing:
            self._on_map_finish()

        self.client_universal_offset = data.universal_offset
        self.current_offset = data.universal_offset
        if not is_playing:
            self.was_playing = False

    def _is_playing(self, data: GameData) -> bool:
        if data.profile_id == -1:
            return data.status == GameState.play
        return data.bancho_status == BanchoStatus.playing and data.profile_id != -1

    def _on_universal_offset_changed(self, new_offset: int) -> None:
        self.client_universal_offset = new_offset
        self.current_offset = new_offset

        if self.settings.reset_suggestion_on_universal_offset_change:
            self.global_offsets = []
            self.suggested_offset = new_offset

        if self.settings.warning_text_display_time > 0:
            self._show_warning(f"Universal offset updated to {new_offset} ms")

    def clear_data(self) -> None:
        self.global_offsets = []
        self.hit_errors = []
        self.suggested_offset = self.client_universal_offset or 0
        self.last_map_offset = 0

    def _on_map_finish(self) -> None:
        if len(self.hit_errors) == 0:
            return

        if len(self.hit_errors) <= 50:
            self.hit_errors = []
            self._show_warning("Not enough hits!")
            return

        last_map_offset = calculate_median(self.hit_errors)
        self.hit_errors = []
        self.global_offsets.append(last_map_offset)
        self.last_map_offset = last_map_offset

        self._update_suggested_offset()

        if self.settings.warning_text_display_time > 0:
            self._show_warning(f"Suggested offset updated to {self.suggested_offset} ms")

    def _update_suggested_offset(self) -> None:
        offset = self.client_universal_offset
        if offset is None:
            self.suggested_offset = 0
            return

        if len(self.global_offsets) == 1:
            offset -= self.global_offsets[0]
        elif len(self.global_offsets) > 1:
            avg = calculate_average(self.global_offsets)
            if avg is not None:
                offset -= avg

        self.suggested_offset = offset

    def _show_warning(self, text: str) -> None:
        if not text:
            return
        self.warning_text = text
        self.warning_visible = True
        self.warning_timer = time.time()

    def update_warning(self) -> None:
        if not self.warning_visible:
            return
        elapsed = (time.time() - self.warning_timer) * 1000
        display_time = self.settings.warning_text_display_time
        if elapsed > display_time + 250:
            self.warning_text = ""
            self.warning_visible = False

    def get_warning_opacity(self) -> float:
        if not self.warning_visible:
            return 0.0
        elapsed = (time.time() - self.warning_timer) * 1000
        display_time = self.settings.warning_text_display_time
        if elapsed < display_time:
            return 0.6
        fade = (elapsed - display_time) / 250.0
        return max(0.0, 0.6 * (1.0 - fade))
