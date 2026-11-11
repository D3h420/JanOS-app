"""Linux RGB565 framebuffer output for the 320x170 Cardputer Zero LCD."""

from __future__ import annotations

import fcntl
import mmap
import os
import struct


FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602
WIDTH = 320
HEIGHT = 170


class Framebuffer:
    """Memory-mapped framebuffer with strict geometry validation."""

    def __init__(self, path: str = "/dev/fb0") -> None:
        self.fd = os.open(path, os.O_RDWR)
        try:
            variable = bytearray(160)
            fixed = bytearray(80)
            fcntl.ioctl(self.fd, FBIOGET_VSCREENINFO, variable)
            fcntl.ioctl(self.fd, FBIOGET_FSCREENINFO, fixed)
            self.width, self.height = struct.unpack_from("II", variable, 0)
            self.bits_per_pixel = struct.unpack_from("I", variable, 24)[0]
            memory_length = struct.unpack_from("I", fixed, 24)[0]
            self.stride = struct.unpack_from("I", fixed, 48)[0]
            if (self.width, self.height, self.bits_per_pixel) != (WIDTH, HEIGHT, 16):
                raise RuntimeError(
                    f"Expected {WIDTH}x{HEIGHT} RGB565 framebuffer, got "
                    f"{self.width}x{self.height}x{self.bits_per_pixel}"
                )
            if self.stride < self.width * 2 or memory_length < self.stride * self.height:
                raise RuntimeError("Framebuffer memory/stride is smaller than the visible frame")
            self.memory = mmap.mmap(
                self.fd,
                memory_length,
                mmap.MAP_SHARED,
                mmap.PROT_WRITE | mmap.PROT_READ,
            )
        except Exception:
            os.close(self.fd)
            raise

    @staticmethod
    def _rgb565(image) -> bytes:
        pixels = image.convert("RGB").tobytes()
        output = bytearray((len(pixels) // 3) * 2)
        target = 0
        for source in range(0, len(pixels), 3):
            red, green, blue = pixels[source:source + 3]
            value = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
            output[target] = value & 0xFF
            output[target + 1] = value >> 8
            target += 2
        return bytes(output)

    def show(self, image) -> None:
        if image.size != (self.width, self.height):
            raise ValueError(f"Expected {self.width}x{self.height} image, got {image.size}")
        frame = self._rgb565(image)
        row_bytes = self.width * 2
        if self.stride == row_bytes:
            self.memory.seek(0)
            self.memory.write(frame)
        else:
            for row in range(self.height):
                self.memory.seek(row * self.stride)
                start = row * row_bytes
                self.memory.write(frame[start:start + row_bytes])

    def close(self) -> None:
        self.memory.close()
        os.close(self.fd)

