"""Parsers for classic UO binary formats (TileData HS, RadarCol, Hues, TexMaps, Art)."""
import os
import struct
import numpy as np
from typing import Dict, List, Tuple, Optional, Set
from .uop import UopReader, hashlittle2

# Common flags
FLAG_BACKGROUND = 0x1
FLAG_TRANSPARENT = 0x4
FLAG_TRANSLUCENT = 0x8
FLAG_WALL = 0x10
FLAG_IMPASSABLE = 0x40
FLAG_WET = 0x80
FLAG_SURFACE = 0x200
FLAG_BRIDGE = 0x400
FLAG_WINDOW = 0x1000
FLAG_FOLIAGE = 0x20000
FLAG_PARTIAL_HUE = 0x40000
FLAG_LIGHT = 0x800000
FLAG_ANIMATION = 0x1000000
FLAG_ROOF = 0x10000000
FLAG_DOOR = 0x20000000


class LandEntry:
    __slots__ = ('flags', 'tex_id', 'name')
    def __init__(self, flags: int, tex_id: int, name: str):
        self.flags = flags
        self.tex_id = tex_id
        self.name = name


class StaticEntry:
    __slots__ = ('flags', 'height', 'animation', 'hue', 'name')
    def __init__(self, flags: int, height: int, animation: int, hue: int, name: str):
        self.flags = flags
        self.height = height
        self.animation = animation
        self.hue = hue
        self.name = name


class TileData:
    """Parses tiledata.mul (High Seas 64-bit flag format)."""

    def __init__(self, filepath: str):
        self.land: List[LandEntry] = []
        self.statics: List[StaticEntry] = []
        self._load(filepath)

    def _load(self, filepath: str):
        with open(filepath, 'rb') as f:
            data = f.read()

        off = 0
        # 512 land groups
        for _ in range(512):
            off += 4  # skip header
            for _ in range(32):
                flags, tex_id = struct.unpack_from('<QH', data, off)
                name_raw = data[off + 10:off + 30].split(b'\0')[0]
                name = name_raw.decode('latin1', errors='ignore')
                self.land.append(LandEntry(flags, tex_id, name))
                off += 30

        # static groups (up to end of file, ~2048 groups)
        while off + 4 <= len(data):
            off += 4  # skip header
            for _ in range(32):
                if off + 41 > len(data):
                    break
                flags = struct.unpack_from('<Q', data, off)[0]
                anim = struct.unpack_from('<H', data, off + 14)[0]
                hue = data[off + 17]
                height = data[off + 20]
                name_raw = data[off + 21:off + 41].split(b'\0')[0]
                name = name_raw.decode('latin1', errors='ignore')
                self.statics.append(StaticEntry(flags, height, anim, hue, name))
                off += 41


class RadarCol:
    """Reads radarcol.mul (u16 555 colors per item/land id)."""

    def __init__(self, filepath: str):
        self.colors = np.fromfile(filepath, dtype='<u2')

    def get_land_color(self, land_id: int) -> int:
        if 0 <= land_id < len(self.colors):
            return int(self.colors[land_id])
        return 0

    def get_static_color(self, static_id: int) -> int:
        idx = 0x4000 + static_id
        if 0 <= idx < len(self.colors):
            return int(self.colors[idx])
        return 0


class Hues:
    """Reads hues.mul (375 groups * 8 hues = 3000 hues, each 32 colors)."""

    def __init__(self, filepath: str):
        with open(filepath, 'rb') as f:
            data = f.read()
        self.hues_555: List[List[int]] = []  # 3000 hues, each 32 colors
        off = 0
        for _ in range(375):
            off += 4  # skip group header
            for _ in range(8):
                colors = list(struct.unpack_from('<32H', data, off))
                self.hues_555.append(colors)
                off += 88  # 32*2 + 2(tableStart) + 2(tableEnd) + 20(name)


class TexMaps:
    """Reads terrain textures from texidx.mul and texmaps.mul."""

    def __init__(self, idx_path: str, data_path: str):
        self.idx = np.fromfile(idx_path, dtype='<i4').reshape(-1, 3)
        self.data_file = open(data_path, 'rb')

    def get_texmap(self, tex_id: int) -> Optional[Tuple[int, bytes]]:
        """Returns (dimension, raw_bytes_555) where dimension is 64 or 128, or None."""
        if tex_id < 0 or tex_id >= len(self.idx):
            return None
        lookup, length, extra = self.idx[tex_id]
        if lookup < 0 or length <= 0:
            return None
        self.data_file.seek(lookup)
        data = self.data_file.read(length)
        dim = 128 if length == 32768 else 64
        return (dim, data)

    def close(self):
        if self.data_file:
            self.data_file.close()


class ArtArchive:
    """Reads land and static sprites from artLegacyMUL.uop."""

    def __init__(self, uop_path: str):
        self.uop = UopReader(uop_path)

    def read_land_art(self, land_id: int) -> Optional[np.ndarray]:
        """Returns 44x44 numpy array of uint16 (555 color) or None."""
        name = f"build/artlegacymul/{land_id:08d}.tga"
        raw = self.uop.read_entry(name)
        if not raw or len(raw) < 2048:
            return None

        pixels = np.zeros((44, 44), dtype=np.uint16)
        idx = 0
        for y in range(22):
            count = 2 * (y + 1)
            start_x = 21 - y
            for x in range(start_x, start_x + count):
                pixels[y, x] = struct.unpack_from('<H', raw, idx)[0]
                idx += 2
        for y in range(22, 44):
            count = 2 * (44 - y)
            start_x = y - 22
            for x in range(start_x, start_x + count):
                pixels[y, x] = struct.unpack_from('<H', raw, idx)[0]
                idx += 2
        return pixels

    def read_static_art(self, static_id: int) -> Optional[Tuple[int, int, np.ndarray]]:
        """
        Returns (width, height, pixels_array) where pixels_array is shape (height, width)
        of uint16 (555 color, 0 = transparent).
        """
        name = f"build/artlegacymul/{static_id + 0x4000:08d}.tga"
        raw = self.uop.read_entry(name)
        if not raw or len(raw) < 8:
            return None

        flag, width, height = struct.unpack_from('<IHH', raw, 0)
        if width <= 0 or height <= 0 or width > 1024 or height > 1024:
            return None

        lookups = struct.unpack_from(f'<{height}H', raw, 8)
        pixels = np.zeros((height, width), dtype=np.uint16)

        for y in range(height):
            off = 8 + 2 * height + 2 * lookups[y]
            while off + 4 <= len(raw):
                x_off, x_run = struct.unpack_from('<HH', raw, off)
                off += 4
                if x_off == 0 and x_run == 0:
                    break
                if off + 2 * x_run > len(raw):
                    break
                run_pixels = struct.unpack_from(f'<{x_run}H', raw, off)
                off += 2 * x_run
                end_x = min(x_off + x_run, width)
                actual_run = end_x - x_off
                if actual_run > 0:
                    pixels[y, x_off:end_x] = run_pixels[:actual_run]

        return (width, height, pixels)

    def close(self):
        self.uop.close()
