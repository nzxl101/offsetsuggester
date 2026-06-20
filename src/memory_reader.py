import ctypes
import re
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import pymem
from pymem.pattern import pattern_scan_all

STILL_ACTIVE = 259
KERNEL32 = ctypes.windll.kernel32


class GameState:
    play = 2


class BanchoStatus:
    playing = 2


def _compile_pattern(mask: str, pattern_bytes: bytes) -> bytes:
    result = bytearray()
    for i, b in enumerate(pattern_bytes):
        if mask[i:i + 1] == '?':
            result.append(ord('.'))
        else:
            result.extend(re.escape(bytes([b])))
    return bytes(result)


PATTERNS: dict[str, tuple[str, int]] = {
    "statusPtr": (
        _compile_pattern("xxxxxx", b"\x48\x83\xF8\x04\x73\x1E"),
        -4,
    ),
    "baseAddr": (
        _compile_pattern("xxxxxx", b"\xF8\x01\x74\x04\x83\x65"),
        0,
    ),
    "rulesetsAddr": (
        _compile_pattern("xxx????xx", b"\x7D\x15\xA1\x00\x00\x00\x00\x85\xC0"),
        0,
    ),
    "configurationAddr": (
        _compile_pattern(
            "xxxxxx????xxxxx????xxx?xxx",
            b"\x8D\x45\xEC\x50\x8B\x0D\x00\x00\x00\x00\x8B\xD7\x39\x09\xE8\x00\x00\x00\x00\x85\xC0\x74\x00\x8B\x4D\xEC",
        ),
        6,
    ),
    "userProfilePtr": (
        _compile_pattern("xx????x????xxxxx", b"\xFF\x15\x00\x00\x00\x00\xA1\x00\x00\x00\x00\x8B\x48\x54\x33\xD2"),
        7,
    ),
}


def _read_i32(pm: pymem.Pymem, addr: int) -> int:
    return struct.unpack("<i", pm.read_bytes(addr, 4))[0]


def _read_f64(pm: pymem.Pymem, addr: int) -> float:
    return struct.unpack("<d", pm.read_bytes(addr, 8))[0]


def _read_sharp_string(pm: pymem.Pymem, addr: int) -> str:
    if addr == 0:
        return ""
    length = _read_i32(pm, addr + 4)
    if length <= 0 or length > 1024:
        return ""
    raw = pm.read_bytes(addr + 8, length * 2)
    return raw.decode("utf-16-le", errors="replace")


@dataclass
class GameData:
    status: int = 0
    bancho_status: int = 0
    universal_offset: int = 0
    hit_errors: list[int] = field(default_factory=list)
    profile_id: int = -1
    connected: bool = False


class MemoryReader:
    PROCESS_NAME = "osu!.exe"
    POLL_INTERVAL = 1.0 / 30

    def __init__(self):
        self._pm: Optional[pymem.Pymem] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._data = GameData()
        self._addrs: dict[str, int] = {}
        self._config_offset_pos: Optional[int] = None
        self._last_known_offset: Optional[int] = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def latest(self) -> GameData:
        with self._lock:
            return self._data

    def _scan_patterns(self) -> None:
        self._addrs.clear()
        for name, (pattern, offset) in PATTERNS.items():
            try:
                found = pattern_scan_all(self._pm.process_handle, pattern)
                if found is None:
                    continue
                self._addrs[name] = found + offset
            except Exception:
                continue

    def _attach(self) -> bool:
        for attempt in range(10):
            try:
                self._pm = pymem.Pymem(self.PROCESS_NAME)
                self._scan_patterns()
                self._config_offset_pos = None
                self._last_known_offset = None
                if self._addrs:
                    print(f"  [reader] Attached, found {len(self._addrs)} patterns")
                    return True
                self._pm = None
            except pymem.exception.ProcessNotFound:
                self._pm = None
            except Exception as e:
                print(f"  [reader] Attach error: {e}")
                self._pm = None
            time.sleep(1)
        return False

    def _rescan_missing_patterns(self) -> None:
        found_count = len(self._addrs)
        if found_count >= len(PATTERNS):
            return
        for name, (pattern, offset) in PATTERNS.items():
            if name in self._addrs:
                continue
            try:
                found = pattern_scan_all(self._pm.process_handle, pattern)
                if found is not None:
                    self._addrs[name] = found + offset
            except Exception:
                pass
        if len(self._addrs) > found_count:
            print(f"  [reader] Rescanned: now {len(self._addrs)} patterns")

    def _read_config_offsets(self, config_ptr: int) -> list[int]:
        try:
            entries_ptr = _read_i32(self._pm, config_ptr + 8)
            if entries_ptr == 0:
                return []
            count = _read_i32(self._pm, config_ptr + 0x1c)
            if count <= 0 or count > 4096:
                return []
            positions: list[int] = []
            for i in range(count):
                entry_addr = entries_ptr + 8 + 16 * i
                key_ptr = _read_i32(self._pm, entry_addr)
                if key_ptr == 0:
                    continue
                key = _read_sharp_string(self._pm, key_ptr)
                if key and "Offset" in key:
                    positions.append(i)
            return positions
        except Exception:
            return []

    def _read_config_value(self, config_ptr: int, position: int) -> Optional[float]:
        try:
            entries_ptr = _read_i32(self._pm, config_ptr + 8)
            if entries_ptr == 0:
                return None
            entry_addr = entries_ptr + 8 + 16 * position
            bindable = _read_i32(self._pm, entry_addr + 4)
            if bindable == 0:
                return None
            return _read_f64(self._pm, bindable + 4)
        except Exception:
            return None

    def _update(self) -> None:
        try:
            pm = self._pm
            if pm is None:
                return

            self._rescan_missing_patterns()
            addrs = self._addrs
            status_ptr = addrs.get("statusPtr", 0)
            rulesets_addr = addrs.get("rulesetsAddr", 0)
            config_addr = addrs.get("configurationAddr", 0)
            user_prof_ptr = addrs.get("userProfilePtr", 0)
            base_addr = addrs.get("baseAddr", 0)

            status = 0
            if status_ptr:
                try:
                    raw = pm.read_bytes(status_ptr, 4)
                    status_addr = struct.unpack("<I", raw)[0]
                    if status_addr:
                        status = _read_i32(pm, status_addr)
                except Exception as e:
                    print(f"  [reader] status read error: {e}")

            profile_id = -1
            bancho_status = -1
            if user_prof_ptr:
                try:
                    profile_base_ptr = _read_i32(pm, user_prof_ptr)
                    if profile_base_ptr:
                        profile_base = _read_i32(pm, profile_base_ptr)
                        if profile_base:
                            profile_id = _read_i32(pm, profile_base + 0x70)
                            bancho_status = _read_i32(pm, profile_base + 0x8C)
                except Exception:
                    pass

            universal_offset = 0
            if config_addr:
                try:
                    static_ptr = _read_i32(pm, config_addr)
                    if static_ptr:
                        config_obj = _read_i32(pm, static_ptr)
                        if config_obj:
                            if self._config_offset_pos is None:
                                positions = self._read_config_offsets(config_obj)
                                if positions:
                                    self._config_offset_pos = positions[0]
                            if self._config_offset_pos is not None:
                                val = self._read_config_value(
                                    config_obj, self._config_offset_pos
                                )
                                if val is not None:
                                    universal_offset = int(val)
                                    self._last_known_offset = universal_offset
                except Exception:
                    pass

            if universal_offset == 0 and self._last_known_offset is not None:
                universal_offset = self._last_known_offset

            hit_errors: list[int] = []
            if rulesets_addr and base_addr:
                try:
                    ruleset_base = _read_i32(pm, rulesets_addr - 0xB)
                    if ruleset_base:
                        ruleset_addr2 = _read_i32(pm, ruleset_base + 4)
                        if ruleset_addr2:
                            gameplay_base = _read_i32(pm, ruleset_addr2 + 0x64)
                            if gameplay_base:
                                score_base = _read_i32(pm, gameplay_base + 0x38)
                                if score_base:
                                    hit_base = _read_i32(pm, score_base + 0x38)
                                    if hit_base:
                                        items = _read_i32(pm, hit_base + 4)
                                        # List<int>: _items at +4, _size at +8, _version at +0xC (AutoLayout)
                                        # Also try SequentialLayout: _items +4, _size +8, _version +0xC
                                        size = _read_i32(pm, hit_base + 8)
                                        if size <= 0 or size > 50000:
                                            size = _read_i32(pm, hit_base + 0xC)
                                        if items and size > 0 and size < 50000:
                                            for i in range(size):
                                                err = _read_i32(
                                                    pm, items + 8 + 4 * i
                                                )
                                                if err < -10000 or err > 10000:
                                                    break
                                                if len(hit_errors) >= size:
                                                    break
                                                hit_errors.append(err)
                except Exception:
                    pass

            with self._lock:
                self._data = GameData(
                    status=status,
                    bancho_status=bancho_status,
                    universal_offset=universal_offset,
                    hit_errors=hit_errors,
                    profile_id=profile_id,
                    connected=True,
                )
        except Exception:
            pass

    def _is_process_alive(self) -> bool:
        try:
            code = ctypes.c_ulong()
            if KERNEL32.GetExitCodeProcess(self._pm.process_handle, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        except Exception:
            return False

    def _poll_loop(self) -> None:
        while self._running:
            if self._pm is None and not self._attach():
                with self._lock:
                    self._data = GameData()
                time.sleep(1)
                continue

            if not self._is_process_alive():
                print("  [reader] Process died, re-attaching...")
                self._pm = None
                with self._lock:
                    self._data = GameData()
                continue

            self._update()
            time.sleep(self.POLL_INTERVAL)
