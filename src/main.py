import sys
import time

from src.calculator import OffsetCalculator
from src.memory_reader import MemoryReader
from src.overlay import OffsetOverlay


class Settings:
    current_offset_enable = True
    suggested_offset_enable = True
    suggested_offset_color_enable = True
    reset_suggestion_on_universal_offset_change = False
    last_map_offset_enable = True
    realtime_offset_calculation = False
    warning_text_display_time = 2000


def main() -> None:
    config = Settings()

    reader = MemoryReader()
    calc = OffsetCalculator(config)

    overlay = OffsetOverlay(config)
    try:
        overlay.setup(calc)
    except Exception as e:
        print(f"Failed to create overlay: {e}")
        sys.exit(1)

    def shutdown():
        overlay.close()
        reader.stop()

    try:
        import signal
        signal.signal(signal.SIGINT, lambda s, f: shutdown())
    except (ValueError, AttributeError):
        pass

    reader.start()

    print("Offset Suggester started")

    while overlay.running:
        data = reader.latest()
        if data.connected:
            calc.update(data)
        overlay.render(data)
        time.sleep(1.0 / 60)

    shutdown()


if __name__ == "__main__":
    main()
