"""APPLaunch entry point and desktop simulator for JanOS Cardputer Zero."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path


def _prepare_source_path() -> Path:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    state_home = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    os.environ.setdefault("JANOS_CARDPUTER_STATE_DIR", str(state_home / "janos-cardputer"))
    return root


def _editing(controller) -> bool:
    state = controller.view()
    return bool(getattr(state, "editing", False) or getattr(state, "input_text", ""))


def run_device(controller) -> int:
    from .framebuffer import Framebuffer
    from .keyboard import Keyboard
    from .render import Renderer

    display = Framebuffer(os.environ.get("APPLAUNCH_LINUX_FBDEV_DEVICE", "/dev/fb0"))
    try:
        keyboard = Keyboard()
    except Exception:
        display.close()
        raise
    renderer = Renderer()
    running = True

    def stop(_signum, _frame) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    last_draw = 0.0
    try:
        while running and not controller.quit_requested:
            for key, character in keyboard.events(editing=_editing(controller)):
                controller.handle(key, character)
            changed = controller.tick()
            now = time.monotonic()
            if changed or now - last_draw >= 1.0:
                display.show(renderer.draw(controller.view(), bright=bool(getattr(controller, "theme_bright", False))))
                last_draw = now
            time.sleep(0.035)
    finally:
        controller.close()
        keyboard.close()
        display.close()
    return 0


def run_desktop(controller, *, snapshot: Path | None = None) -> int:
    import tkinter as tk
    from PIL import ImageTk
    from .render import Renderer

    renderer = Renderer()
    root = tk.Tk()
    root.title("JanOS / Cardputer Zero [SIMULATED]")
    root.resizable(False, False)
    label = tk.Label(root, bg="black")
    label.pack()
    image_ref = None

    def key_event(event) -> None:
        mapping = {
            "Up": "UP", "Down": "DOWN", "Left": "LEFT", "Right": "RIGHT",
            "Return": "ENTER", "Escape": "ESC", "Home": "HOME",
            "Prior": "PAGEUP", "Next": "PAGEDOWN", "BackSpace": "BACKSPACE",
            "Delete": "DELETE", "Tab": "TAB",
        }
        key = mapping.get(event.keysym)
        if not key and not _editing(controller):
            key = {"f": "UP", "x": "DOWN", "z": "LEFT", "c": "RIGHT"}.get(event.char.lower())
        if key:
            controller.handle(key, "")
        elif event.char and event.char.isprintable():
            controller.handle("TEXT", event.char)

    def draw_loop() -> None:
        nonlocal image_ref
        changed = controller.tick()
        if changed:
            image = renderer.draw(controller.view(), bright=bool(getattr(controller, "theme_bright", False)))
            if snapshot:
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                image.save(snapshot)
            image_ref = ImageTk.PhotoImage(image.resize((960, 510)))
            label.configure(image=image_ref)
        if controller.quit_requested:
            root.destroy()
        else:
            root.after(45, draw_loop)

    root.bind("<KeyPress>", key_event)
    root.protocol("WM_DELETE_WINDOW", lambda: controller.handle("HOME", ""))
    root.after(10, draw_loop)
    root.mainloop()
    controller.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JanOS controller for M5Stack Cardputer Zero")
    parser.add_argument("--dev", action="store_true", help="run the labelled desktop simulator")
    parser.add_argument("--snapshot", type=Path, help="write the latest simulator frame to PNG")
    parser.add_argument("--device", help="MonsterC5 UART device (auto-detected when omitted)")
    args = parser.parse_args(argv)
    _prepare_source_path()
    from .controller import Controller

    controller = Controller(device=args.device, demo=args.dev)
    try:
        return run_desktop(controller, snapshot=args.snapshot) if args.dev else run_device(controller)
    except Exception as error:
        print(f"JanOS Cardputer Zero startup error: {error}", file=sys.stderr)
        try:
            controller.close()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

