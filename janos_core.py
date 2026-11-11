"""Platform-neutral JanOS protocol helpers shared by every frontend.

This module deliberately depends only on the Python standard library. The
terminal and Cardputer Zero applications both import it, so protocol changes
reach both interfaces after the next package build.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class NetworkRecord:
    index: str
    ssid: str
    vendor: str
    bssid: str
    channel: str
    auth: str
    rssi: str
    band: str = ""


def parse_network_line(line: str) -> NetworkRecord | None:
    """Parse the quoted JanOS scan CSV format."""
    if not line or not line.lstrip().startswith('"'):
        return None
    try:
        fields = next(csv.reader(io.StringIO(line), skipinitialspace=True))
    except (csv.Error, StopIteration):
        return None
    if len(fields) < 7 or not fields[0].strip().isdigit():
        return None
    return NetworkRecord(
        index=fields[0].strip(),
        ssid=fields[1].strip(),
        vendor=fields[2].strip(),
        bssid=fields[3].strip(),
        channel=fields[4].strip(),
        auth=fields[5].strip(),
        rssi=fields[6].strip(),
        band=fields[7].strip() if len(fields) > 7 else "",
    )


def parse_firmware_version(lines: Iterable[str]) -> str:
    for line in lines:
        match = re.search(
            r"(?:JanOS\s+version:|APP_MAIN START \(v)\s*([0-9][^ )]*)",
            line,
            re.I,
        )
        if match:
            return match.group(1)
    return "unknown"


def parse_help_commands(lines: Iterable[str], known: Iterable[str] = ()) -> set[str]:
    """Extract registered command names from ESP-IDF ``help`` output."""
    allowed = set(known)
    commands: set[str] = set()
    for line in lines:
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip().lower()
        first = re.match(r"([a-z][a-z0-9_]+)(?:\s|$)", clean)
        if first and (not allowed or first.group(1) in allowed):
            commands.add(first.group(1))
        if allowed:
            commands.update(
                token
                for token in re.findall(r"\b[a-z][a-z0-9_]+\b", clean)
                if token in allowed
            )
    return commands


def fs_path64(path: str) -> str:
    """Encode a relative FS/1 path exactly as JanOS expects."""
    if not path or path.startswith("/") or "\\" in path:
        raise ValueError("FS/1 path must be relative to /sdcard/lab")
    parts = path.split("/")
    if any(part in ("", ".", "..") or part.endswith((".", " ")) for part in parts):
        raise ValueError("Unsafe FS/1 path")
    return base64.b64encode(path.encode("cp437")).decode("ascii")


def make_ftb_frame(index: int, payload: bytes) -> bytes:
    return b"FTB\x01" + struct.pack(
        "<III", index, len(payload), zlib.crc32(payload) & 0xFFFFFFFF
    ) + payload


def make_ftb_finish(index: int) -> bytes:
    return b"FTB\x01" + struct.pack("<III", index, 0, 0)


def parse_ftb_header(frame: bytes) -> tuple[int, int, int]:
    if len(frame) != 16 or frame[:4] != b"FTB\x01":
        raise ValueError("Invalid FTB/1 header")
    return struct.unpack("<III", frame[4:16])


def validate_fta_frame(frame: bytes, index: int, offset: int) -> None:
    ack_index, status, committed = parse_fta_frame(frame)
    if status != 0x06 or ack_index != index or committed != offset:
        raise ValueError(
            f"Upload rejected (status=0x{status:02x}, index={ack_index}, offset={committed})"
        )


def parse_fta_frame(frame: bytes) -> tuple[int, int, int]:
    """Validate and decode one JanOS 32-byte framed transfer reply.

    The tuple contains ``(block_index, status, committed_offset)``.  Callers
    that implement retry-capable protocols can distinguish ACK, NAK and CAN;
    simple uploads can continue to use :func:`validate_fta_frame`.
    """
    if len(frame) != 32 or frame[:4] != b"FTA\x01":
        raise ValueError("Invalid FTA/1 ACK frame")
    if frame[9:12] != b"\0\0\0" or frame[24:32] != b"\0" * 8:
        raise ValueError("Invalid FTA/1 reserved fields")
    frame_crc = struct.unpack("<I", frame[20:24])[0]
    if zlib.crc32(frame[:20]) & 0xFFFFFFFF != frame_crc:
        raise ValueError("Invalid FTA/1 ACK CRC")
    return (
        struct.unpack("<I", frame[4:8])[0],
        frame[8],
        struct.unpack("<Q", frame[12:20])[0],
    )


def crc32_file(
    path: str | Path,
    *,
    limit: int | None = None,
    chunk_size: int = 256 * 1024,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[int, int]:
    """Return ``(bytes_read, crc32)`` without loading the file into RAM."""
    if limit is not None and limit < 0:
        raise ValueError("CRC limit must not be negative")
    total = 0
    checksum = 0
    with Path(path).open("rb") as source:
        while limit is None or total < limit:
            if cancelled and cancelled():
                raise InterruptedError("File operation cancelled")
            requested = chunk_size if limit is None else min(chunk_size, limit - total)
            if requested <= 0:
                break
            chunk = source.read(requested)
            if not chunk:
                break
            checksum = zlib.crc32(chunk, checksum)
            total += len(chunk)
    return total, checksum & 0xFFFFFFFF

