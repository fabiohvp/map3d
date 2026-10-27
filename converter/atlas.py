"""Sprite atlas generation with shelf packing and RGB5_A1 encoding."""
import struct
import numpy as np
from typing import List, Dict, Tuple, Optional


class SpriteInfo:
    __slots__ = ('orig_id', 'td_height', 'orig_w', 'orig_h', 'crop_x', 'crop_y',
                 'w', 'h', 'ox', 'oy', 'page', 'ax', 'ay', 'pixels')

    def __init__(self, orig_id: int, td_height: int, orig_w: int, orig_h: int,
                 crop_x: int, crop_y: int, w: int, h: int, ox: int, oy: int,
                 pixels: np.ndarray):
        self.orig_id = orig_id
        self.td_height = td_height
        self.orig_w = orig_w
        self.orig_h = orig_h
        self.crop_x = crop_x
        self.crop_y = crop_y
        self.w = w
        self.h = h
        self.ox = ox
        self.oy = oy
        self.pixels = pixels
        self.page = 0
        self.ax = 0
        self.ay = 0


class AtlasBuilder:
    """Packs sprites into 4096x4096 RGB5_A1 atlas pages."""

    PAGE_SIZE = 4096
    GUTTER = 2

    def __init__(self):
        self.sprites: List[SpriteInfo] = []

    def add_sprite(self, orig_id: int, td_height: int, orig_w: int, orig_h: int,
                   raw_555_pixels: np.ndarray) -> Optional[int]:
        """
        raw_555_pixels: 2D array of shape (orig_h, orig_w) with 0 = transparent.
        Returns sprite index in atlas, or None if sprite is completely empty.
        """
        # Find opaque bounding box
        nz_y, nz_x = np.nonzero(raw_555_pixels)
        if len(nz_y) == 0:
            # Completely empty sprite
            s = SpriteInfo(orig_id, td_height, orig_w, orig_h, 0, 0, 0, 0, 0, 0, np.zeros((0, 0), dtype=np.uint16))
            idx = len(self.sprites)
            self.sprites.append(s)
            return idx

        min_y, max_y = int(nz_y.min()), int(nz_y.max())
        min_x, max_x = int(nz_x.min()), int(nz_x.max())
        w = max_x - min_x + 1
        h = max_y - min_y + 1

        cropped = raw_555_pixels[min_y:max_y + 1, min_x:max_x + 1]

        # Anchor is base-center of original art: (orig_w // 2, orig_h)
        ox = min_x - (orig_w // 2)
        oy = min_y - orig_h

        s = SpriteInfo(orig_id, td_height, orig_w, orig_h, min_x, min_y, w, h, ox, oy, cropped)
        idx = len(self.sprites)
        self.sprites.append(s)
        return idx

    def pack(self) -> Tuple[List[np.ndarray], bytes]:
        """
        Packs all sprites into 4096x4096 pages.
        Returns (pages_raw_bytes, sprites_bin_bytes).
        """
        # Sort non-empty sprites by descending height for shelf packing
        non_empty = [s for s in self.sprites if s.w > 0 and s.h > 0]
        # Keep track of original sprite index
        sorted_sprites = sorted(non_empty, key=lambda s: (s.h, s.w), reverse=True)

        pages: List[np.ndarray] = []  # uint16 arrays of (4096, 4096)
        pages.append(np.zeros((self.PAGE_SIZE, self.PAGE_SIZE), dtype=np.uint16))

        current_page = 0
        current_x = self.GUTTER
        current_y = self.GUTTER
        shelf_height = 0

        for s in sorted_sprites:
            alloc_w = s.w + self.GUTTER
            alloc_h = s.h + self.GUTTER

            # Check if fits in current shelf
            if current_x + alloc_w > self.PAGE_SIZE:
                # Move to next shelf
                current_x = self.GUTTER
                current_y += shelf_height
                shelf_height = 0

            # Check if fits on current page
            if current_y + alloc_h > self.PAGE_SIZE:
                # Move to next page
                pages.append(np.zeros((self.PAGE_SIZE, self.PAGE_SIZE), dtype=np.uint16))
                current_page += 1
                current_x = self.GUTTER
                current_y = self.GUTTER
                shelf_height = 0

            # Assign coordinates
            s.page = current_page
            s.ax = current_x
            s.ay = current_y

            # Convert pixels to RGB5_A1: ((c & 0x7FFF) << 1) | 1 if c != 0 else 0
            px = s.pixels
            opaque_mask = px != 0
            conv = np.zeros_like(px, dtype=np.uint16)
            conv[opaque_mask] = ((px[opaque_mask] & 0x7FFF) << 1) | 1

            # Blit to atlas page
            pages[current_page][s.ay:s.ay + s.h, s.ax:s.ax + s.w] = conv

            current_x += alloc_w
            if alloc_h > shelf_height:
                shelf_height = alloc_h

        # Build sprites.bin: Header 'SPR1' + count + count * 16 bytes
        # struct: u16 ax, ay, w, h; i16 ox, oy; u8 page, u8 tdHeight; u16 origId
        spr_entries = []
        for s in self.sprites:
            entry = struct.pack('<HHHHhhBBH',
                                s.ax, s.ay, s.w, s.h,
                                s.ox, s.oy,
                                s.page, s.td_height,
                                s.orig_id)
            spr_entries.append(entry)

        count = len(self.sprites)
        header = struct.pack('<4sI', b'SPR1', count)
        sprites_bin = header + b''.join(spr_entries)

        # Convert page arrays to bytes
        page_bytes = [p.tobytes() for p in pages]
        return page_bytes, sprites_bin
