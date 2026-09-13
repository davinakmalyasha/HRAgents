"""Generate the PWA icon set with the standard library only.

Draws the HRAgents mark (dark rounded square + white H) at 4x supersampling,
then downsamples for smooth edges. Run once and commit the PNGs; rerun after
any brand change: ``uv run python web/scripts/make-icons.py``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

PUBLIC_DIR = Path(__file__).resolve().parents[1] / "public"

INK = (0x21, 0x25, 0x29)
PAPER = (0xFF, 0xFF, 0xFF)
SUPERSAMPLE = 4


def rounded_rect(x: float, y: float, size: float, radius: float) -> bool:
    """True when (x, y) sits inside the [0, size]^2 box with rounded corners."""
    inner = radius
    cx = min(max(x, inner), size - inner)
    cy = min(max(y, inner), size - inner)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def h_mark(x: float, y: float, size: float, pad: float) -> bool:
    """True when (x, y) sits on the H glyph."""
    left, top = pad, pad
    right, bottom = size - pad, size - pad
    bar = (right - left) * 0.22
    mid = (top + bottom) / 2
    cross = (bottom - top) * 0.09
    in_left = left <= x <= left + bar and top <= y <= bottom
    in_right = right - bar <= x <= right and top <= y <= bottom
    in_cross = left <= x <= right and mid - cross <= y <= mid + cross
    return in_left or in_right or in_cross


def render(size: int, *, pad_frac: float) -> list[bytes]:
    pad = size * pad_frac
    radius = size * 0.22
    rows: list[bytes] = []
    for row in range(size):
        scanline = bytearray()
        for col in range(size):
            red = green = blue = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = (col * SUPERSAMPLE + sx + 0.5) / SUPERSAMPLE
                    y = (row * SUPERSAMPLE + sy + 0.5) / SUPERSAMPLE
                    on_mark = rounded_rect(x, y, size, radius) and h_mark(x, y, size, pad)
                    pixel = PAPER if on_mark else INK
                    red += pixel[0]
                    green += pixel[1]
                    blue += pixel[2]
            samples = SUPERSAMPLE * SUPERSAMPLE
            scanline += bytes((red // samples, green // samples, blue // samples))
        rows.append(bytes(scanline))
    return rows


def write_png(path: Path, size: int, rows: list[bytes]) -> None:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    targets = [
        ("pwa-192x192.png", 192, 0.20),
        ("pwa-512x512.png", 512, 0.20),
        ("pwa-maskable-512x512.png", 512, 0.30),
        ("apple-touch-icon.png", 180, 0.20),
    ]
    for name, size, pad_frac in targets:
        write_png(PUBLIC_DIR / name, size, render(size, pad_frac=pad_frac))
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
