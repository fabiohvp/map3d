"""Generates TRN1 (terrain) and STA1 (statics) chunks."""
import struct
import numpy as np
from typing import Dict, List, Tuple, Set, Optional
from .formats import (
    FLAG_BACKGROUND, FLAG_SURFACE, FLAG_WALL, FLAG_ROOF,
    FLAG_FOLIAGE, FLAG_TRANSLUCENT, FLAG_WINDOW, FLAG_PARTIAL_HUE,
    FLAG_LIGHT, FLAG_ANIMATION, FLAG_DOOR, FLAG_WET
)
from .materials import VOID_IDS

NODRAW_IDS = {0x0001, 0x21BC, 0x63D3} | set(range(0x2198, 0x21A5))


class ChunkGenerator:
    """Processes a 64x64 chunk for terrain and statics."""

    def __init__(self, cx: int, cy: int,
                 global_tid: np.ndarray, global_z: np.ndarray,
                 land_to_mat: Dict[int, int],
                 static_items_by_block: Dict[int, np.ndarray],
                 tiledata_statics: list,
                 sprite_id_to_index: Dict[int, int],
                 water_id_to_kind: Dict[int, int],
                 blocks_w: int, blocks_h: int):
        self.cx = cx
        self.cy = cy
        self.global_tid = global_tid
        self.global_z = global_z
        self.land_to_mat = land_to_mat
        self.static_items_by_block = static_items_by_block
        self.tiledata_statics = tiledata_statics
        self.sprite_id_to_index = sprite_id_to_index
        self.water_id_to_kind = water_id_to_kind
        self.blocks_w = blocks_w
        self.blocks_h = blocks_h

        self.map_w = global_tid.shape[1]
        self.map_h = global_tid.shape[0]

    def build_terrain_and_statics(self) -> Tuple[Optional[bytes], Optional[bytes], int, int]:
        """
        Builds (trn_bytes, sta_bytes, z_min, z_max).
        Returns (None, None, 0, 0) if the chunk is 100% void and has no statics.
        """
        # Tile coordinates for this chunk
        x0 = self.cx * 64
        y0 = self.cy * 64
        x1 = min(x0 + 64, self.map_w)
        y1 = min(y0 + 64, self.map_h)

        # Slice 64x64 tiles (pad with void/edge if at map boundary)
        chunk_tids = np.full((64, 64), 0x0244, dtype=np.uint16)
        chunk_z = np.zeros((64, 64), dtype=np.int8)

        actual_w = x1 - x0
        actual_h = y1 - y0
        if actual_w > 0 and actual_h > 0:
            chunk_tids[:actual_h, :actual_w] = self.global_tid[y0:y1, x0:x1]
            chunk_z[:actual_h, :actual_w] = self.global_z[y0:y1, x0:x1]

        # Check pure void
        is_all_void = np.isin(chunk_tids[:actual_h, :actual_w], list(VOID_IDS)).all()

        # Water arrays for terrain
        water_z = np.full(4096, -128, dtype=np.int8)
        water_kind = np.zeros(4096, dtype=np.uint8)
        has_water = False

        # --- Process Statics ---
        raw_instances = []
        tie_counter = 0

        # Iterate over the 8x8 blocks belonging to this chunk
        bx0 = self.cx * 8
        by0 = self.cy * 8
        for by in range(by0, min(by0 + 8, self.blocks_h)):
            for bx in range(bx0, min(bx0 + 8, self.blocks_w)):
                block_idx = bx * self.blocks_h + by
                if block_idx not in self.static_items_by_block:
                    continue
                block_items = self.static_items_by_block[block_idx]
                for item in block_items:
                    s_id = int(item['id'])
                    s_x = int(item['x']) + (bx - bx0) * 8
                    s_y = int(item['y']) + (by - by0) * 8
                    s_z = int(item['z'])
                    s_hue = int(item['hue'])

                    if s_x >= 64 or s_y >= 64 or s_x < 0 or s_y < 0:
                        continue

                    # Filter NoDraw
                    if s_id in NODRAW_IDS:
                        continue
                    td = self.tiledata_statics[s_id] if s_id < len(self.tiledata_statics) else None
                    if td and td.name.lower() == 'nodraw':
                        continue

                    # Check flat water candidate
                    if td and (td.flags & FLAG_WET) and td.height == 0 and s_id in self.water_id_to_kind:
                        tile_idx = s_y * 64 + s_x
                        if water_z[tile_idx] == -128 or s_z > water_z[tile_idx]:
                            water_z[tile_idx] = s_z
                            water_kind[tile_idx] = self.water_id_to_kind[s_id]
                            has_water = True
                            continue  # Extracted into water layer

                    raw_instances.append((s_id, s_x, s_y, s_z, s_hue, tie_counter))
                    tie_counter += 1

        if is_all_void and len(raw_instances) == 0 and not has_water:
            return None, None, 0, 0

        # Deduplicate statics (same id, x, y, z)
        seen_keys = set()
        dedup_instances = []
        for s_id, s_x, s_y, s_z, s_hue, tie in raw_instances:
            key = (s_id, s_x, s_y, s_z)
            if key not in seen_keys:
                seen_keys.add(key)
                dedup_instances.append((s_id, s_x, s_y, s_z, s_hue, tie))

        # Classify statics (opaque vs translucent)
        opaque_list = []
        transl_list = []

        for s_id, s_x, s_y, s_z, s_hue, tie in dedup_instances:
            td = self.tiledata_statics[s_id] if s_id < len(self.tiledata_statics) else None
            td_flags = td.flags if td else 0
            td_height = td.height if td else 0

            is_bg = bool(td_flags & FLAG_BACKGROUND)
            is_surface = bool(td_flags & FLAG_SURFACE)
            is_wall = bool(td_flags & FLAG_WALL)
            is_roof = bool(td_flags & FLAG_ROOF)
            is_foliage = bool(td_flags & FLAG_FOLIAGE)
            is_transl = bool(td_flags & FLAG_TRANSLUCENT)
            is_window = bool(td_flags & FLAG_WINDOW)
            is_phue = bool(td_flags & FLAG_PARTIAL_HUE)
            is_light = bool(td_flags & FLAG_LIGHT)
            is_anim = bool(td_flags & FLAG_ANIMATION)
            is_door = bool(td_flags & FLAG_DOOR)

            # Compact flags (12 bits)
            inst_flags = (
                (1 if is_bg else 0) |
                ((1 if is_surface else 0) << 1) |
                ((1 if is_wall else 0) << 2) |
                ((1 if is_roof else 0) << 3) |
                ((1 if is_foliage else 0) << 4) |
                ((1 if is_transl else 0) << 5) |
                ((1 if is_window else 0) << 6) |
                ((1 if is_phue else 0) << 7) |
                ((1 if is_light else 0) << 8) |
                ((1 if is_anim else 0) << 9) |
                ((1 if is_door else 0) << 10)
            )

            # Priority Z
            prio_z = s_z - (1 if is_bg else 0) + (1 if td_height > 0 else 0)
            sort_key = (s_x + s_y, prio_z, tie)

            # Sprite index
            spr_idx = self.sprite_id_to_index.get(s_id, 0)
            # Hue (0x3FFF applied, 1-based if non-zero)
            h = (s_hue & 0x3FFF) if s_hue else 0

            # Encode word A: bits 0-5 x, 6-11 y, 12-19 z+128, 20-31 flags
            z_clamped = max(-128, min(127, s_z)) + 128
            word_a = (s_x & 0x3F) | ((s_y & 0x3F) << 6) | ((z_clamped & 0xFF) << 12) | ((inst_flags & 0xFFF) << 20)
            # Encode word B: bits 0-15 spriteIndex, 16-31 hue
            word_b = (spr_idx & 0xFFFF) | ((h & 0xFFFF) << 16)

            entry = (sort_key, word_a, word_b, is_anim, is_light)
            if is_transl:
                transl_list.append(entry)
            else:
                opaque_list.append(entry)

        # Sort both lists
        opaque_list.sort(key=lambda e: e[0])
        transl_list.sort(key=lambda e: e[0])

        all_instances = opaque_list + transl_list
        count = len(all_instances)
        n_opaque = len(opaque_list)
        n_transl = len(transl_list)

        words_a = []
        words_b = []
        anim_indices = []
        light_indices = []

        for idx, (_, wa, wb, is_anim, is_light) in enumerate(all_instances):
            words_a.append(wa)
            words_b.append(wb)
            if is_anim:
                anim_indices.append(idx)
            if is_light:
                light_indices.append(idx)

        # Build STA1 binary
        sta_header = struct.pack('<4sHHIIIIII',
                                 b'STA1',
                                 self.cx, self.cy,
                                 count,
                                 n_opaque,
                                 n_transl,
                                 len(anim_indices),
                                 len(light_indices),
                                 0)  # reserved
        sta_data_a = struct.pack(f'<{count}I', *words_a) if count else b''
        sta_data_b = struct.pack(f'<{count}I', *words_b) if count else b''
        sta_anim = struct.pack(f'<{len(anim_indices)}H', *anim_indices) if anim_indices else b''
        sta_light = struct.pack(f'<{len(light_indices)}H', *light_indices) if light_indices else b''

        # Align to 4 bytes
        sta_extra = sta_anim + sta_light
        if len(sta_extra) % 4 != 0:
            sta_extra += b'\0' * (4 - (len(sta_extra) % 4))

        sta_bytes = sta_header + sta_data_a + sta_data_b + sta_extra

        # --- Process Terrain (TRN1) ---
        # 65x65 height grid (vertices: 0..64)
        x_pad_end = min(x0 + 65, self.map_w)
        y_pad_end = min(y0 + 65, self.map_h)
        grid_65 = np.zeros((65, 65), dtype=np.int8)

        # Fill available region
        avail_w = x_pad_end - x0
        avail_h = y_pad_end - y0
        grid_65[:avail_h, :avail_w] = self.global_z[y0:y_pad_end, x0:x_pad_end]

        # Pad remaining border if at edge of map
        if avail_w < 65:
            grid_65[:, avail_w:] = grid_65[:, avail_w - 1:avail_w]
        if avail_h < 65:
            grid_65[avail_h:, :] = grid_65[avail_h - 1:avail_h, :]

        z_min = int(grid_65.min())
        z_max = int(grid_65.max())

        all_flat = (z_min == z_max)
        has_void = np.isin(chunk_tids, list(VOID_IDS)).any()

        # Flags: bit0 hasWater, bit1 allFlat, bit2 hasVoid, bit3 hasDiag
        flags = (1 if has_water else 0) | ((1 if all_flat else 0) << 1) | ((1 if has_void else 0) << 2)

        # Material 64x64
        materials_64 = np.zeros((64, 64), dtype=np.uint16)
        for y in range(64):
            for x in range(64):
                tid = int(chunk_tids[y, x])
                materials_64[y, x] = self.land_to_mat.get(tid, 0)

        # Header: u32 'TRN1', u16 cx, cy, i8 zMin, zMax, u16 flags, u32 reserved
        trn_header = struct.pack('<4sHHbbHI',
                                 b'TRN1',
                                 self.cx, self.cy,
                                 z_min, z_max,
                                 flags,
                                 0)
        trn_mat = materials_64.tobytes()

        if all_flat:
            # 1 byte + 3 bytes pad
            trn_height = struct.pack('<b3x', z_min)
        else:
            # 65*65 bytes + 3 bytes pad
            trn_height = grid_65.tobytes() + b'\0\0\0'

        trn_bytes = trn_header + trn_mat + trn_height

        if has_water:
            trn_bytes += water_z.tobytes() + water_kind.tobytes()

        return trn_bytes, sta_bytes, z_min, z_max
