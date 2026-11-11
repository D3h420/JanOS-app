"""Small, fast 320x170 UI renderer for the JanOS controller."""

from __future__ import annotations

from pathlib import Path


WIDTH = 320
HEIGHT = 170
BG = (5, 10, 15)
PANEL = (13, 24, 34)
CYAN = (66, 211, 234)
GREEN = (98, 232, 158)
AMBER = (250, 185, 72)
RED = (244, 95, 95)
TEXT = (226, 238, 244)
DIM = (125, 151, 164)


class Renderer:
    def __init__(self) -> None:
        from PIL import ImageFont

        candidates = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/System/Library/Fonts/Menlo.ttc",
        )
        font_path = next((item for item in candidates if Path(item).exists()), None)
        self.small = ImageFont.truetype(font_path, 10) if font_path else ImageFont.load_default()
        self.medium = ImageFont.truetype(font_path, 12) if font_path else ImageFont.load_default()
        self.large = ImageFont.truetype(font_path, 24) if font_path else ImageFont.load_default()

    @staticmethod
    def _field(state, name: str, default):
        return getattr(state, name, default)

    @staticmethod
    def _clip(draw, text: object, font, width: int) -> str:
        value = str(text)
        if draw.textbbox((0, 0), value, font=font)[2] <= width:
            return value
        while value and draw.textbbox((0, 0), value + "…", font=font)[2] > width:
            value = value[:-1]
        return value + "…"

    def draw(self, state, *, bright: bool = False):
        from PIL import Image, ImageDraw

        image = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(image)
        accent_name = self._field(state, "accent", "cyan")
        accent = {"green": GREEN, "amber": AMBER, "red": RED}.get(accent_name, CYAN)
        if bright:
            accent = tuple(min(255, channel + 28) for channel in accent)
        for y in range(0, HEIGHT, 6):
            draw.line((0, y, WIDTH, y), fill=(7, 15, 22))

        title = self._field(state, "title", "JanOS")
        connected = bool(self._field(state, "connected", False))
        firmware = self._field(state, "firmware_version", "")
        draw.rectangle((0, 0, WIDTH - 1, 25), fill=PANEL)
        draw.text((7, 5), self._clip(draw, str(title).upper(), self.medium, 205), font=self.medium, fill=accent)
        badge = ("● " if connected else "○ ") + (str(firmware) if firmware else ("UART" if connected else "OFFLINE"))
        draw.text((224, 6), self._clip(draw, badge, self.small, 90), font=self.small, fill=GREEN if connected else AMBER)
        draw.line((0, 25, WIDTH - 1, 25), fill=accent)

        screen = self._field(state, "screen", "list")
        rows = list(self._field(state, "rows", []))
        selected = int(self._field(state, "selected", 0))
        scroll = int(self._field(state, "scroll", 0))
        if screen == "splash":
            draw.text((16, 39), "JanOS", font=self.large, fill=CYAN)
            draw.text((16, 70), "CONTROLLER", font=self.large, fill=GREEN)
            draw.line((16, 103, 255, 103), fill=AMBER, width=2)
            draw.text((17, 111), "PROJECTZERO / MONSTER C5", font=self.medium, fill=TEXT)
            draw.text((17, 130), "ONE CORE / NATIVE CARDPUTER UI", font=self.small, fill=DIM)
        elif screen in {"menu", "list"}:
            first = max(scroll, max(0, selected - 4))
            for visible_index, row in enumerate(rows[first:first + 5]):
                index = first + visible_index
                y = 32 + visible_index * 22
                active = index == selected
                if active:
                    draw.rounded_rectangle((5, y - 2, 314, y + 18), radius=3, fill=(19, 50, 60), outline=accent)
                    draw.text((9, y), ">", font=self.medium, fill=AMBER)
                draw.text((24, y), self._clip(draw, row, self.medium, 284), font=self.medium, fill=TEXT if active else DIM)
            if len(rows) > 5:
                draw.text((281, 132), f"{selected + 1}/{len(rows)}", font=self.small, fill=DIM)
        else:
            visible = rows[scroll:scroll + 7]
            for index, row in enumerate(visible):
                line = str(row)
                color = RED if line.lower().startswith(("error", "failed", "[!]")) else TEXT
                if line.lower().startswith(("ok", "done", "[+]")):
                    color = GREEN
                draw.text((7, 32 + index * 15), self._clip(draw, line, self.small, 305), font=self.small, fill=color)
            input_text = self._field(state, "input_text", "")
            if input_text:
                draw.rectangle((5, 123, 314, 143), fill=(10, 29, 38), outline=CYAN)
                draw.text((9, 128), self._clip(draw, "> " + str(input_text), self.small, 298), font=self.small, fill=TEXT)

        draw.rectangle((0, 146, WIDTH - 1, HEIGHT - 1), fill=PANEL)
        draw.line((0, 146, WIDTH - 1, 146), fill=(36, 76, 88))
        hint = self._field(state, "hint", "ENTER select  ESC back")
        status = self._field(state, "status", "")
        draw.text((7, 152), self._clip(draw, hint, self.small, 235), font=self.small, fill=DIM)
        if status:
            draw.text((245, 152), self._clip(draw, status, self.small, 68), font=self.small, fill=AMBER)
        if self._field(state, "simulated", False):
            draw.rectangle((263, 127, 315, 143), fill=(77, 48, 13), outline=AMBER)
            draw.text((269, 130), "DEMO", font=self.small, fill=AMBER)
        return image

