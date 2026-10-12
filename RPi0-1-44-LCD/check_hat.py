#!/usr/bin/env python3
"""On-device colour and key check for the Seengreat 1.44-inch HAT."""

from __future__ import annotations

import argparse
import time

from hardware import Buttons, Display


def main() -> None:
    parser = argparse.ArgumentParser(description="Sprawdz ekran i klawisze K1-K4")
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument("--x-offset", type=int, default=2)
    parser.add_argument("--y-offset", type=int, default=3)
    parser.add_argument("--rgb-panel", action="store_true")
    args = parser.parse_args()

    from PIL import Image, ImageDraw, ImageFont

    display = Display(rotation=args.rotation, x_offset=args.x_offset,
                      y_offset=args.y_offset, bgr=not args.rgb_panel)
    try:
        buttons = Buttons()
    except Exception:
        display.close()
        raise
    last = "Nacisnij K1-K4"
    try:
        while True:
            image = Image.new("RGB", (128, 128), "black")
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 63, 48), fill="red")
            draw.rectangle((64, 0, 127, 48), fill="green")
            draw.rectangle((0, 49, 63, 97), fill="blue")
            draw.rectangle((64, 49, 127, 97), fill="white")
            font = ImageFont.load_default()
            draw.text((4, 103), last[:22], font=font, fill="white")
            display.show(image)
            while True:
                event = buttons.poll()
                if event:
                    last = {"up": "K1: GORA", "down": "K2: DOL",
                            "select": "K3: WYBOR", "back": "K4: KONIEC"}[event]
                    print(last, flush=True)
                    break
                time.sleep(0.03)
            if event == "back":
                break
    finally:
        buttons.close()
        display.close()


if __name__ == "__main__":
    main()
