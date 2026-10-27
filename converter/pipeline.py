"""Conversion pipeline orchestrator."""
import os
import math
import struct
import base64
import json
import time
import numpy as np
from PIL import Image
from typing import Dict, List, Tuple, Set, Optional

from .uop import UopReader, hashlittle2
from .formats import (
    TileData, RadarCol, Hues, TexMaps, ArtArchive,
    FLAG_WET, FLAG_BACKGROUND
)
from .atlas import AtlasBuilder
from .materials import MaterialsBuilder
from .chunks import ChunkGenerator
from .compress import write_file_and_compressed
from . import enhanced

MAP_DIMS = {
    0: (7168, 4096),
    1: (7168, 4096),
    2: (2304, 1600),
    3: (2560, 2048),
    4: (1448, 1448),
    5: (1280, 4096),
}


class ConversionPipeline:
    def __init__(self, client_dir: str, map_id: int, out_dir: str, variant: str = "", source: str = "enhanced"):
        if source not in ("enhanced", "classic"):
            raise ValueError(f"Unknown source: {source}. Use 'enhanced' or 'classic'.")
        self.source = source
        self.client_dir = client_dir
        self.map_id = map_id
        self.out_dir = out_dir
        self.variant = variant

        if map_id not in MAP_DIMS:
            raise ValueError(f"Unknown map id: {map_id}. Supported: {list(MAP_DIMS.keys())}")
        self.map_w, self.map_h = MAP_DIMS[map_id]
        self.blocks_w = self.map_w // 8
        self.blocks_h = self.map_h // 8
        self.num_blocks = self.blocks_w * self.blocks_h

        self.chunks_x = math.ceil(self.map_w / 64)
        self.chunks_y = math.ceil(self.map_h / 64)
        self.num_chunks = self.chunks_x * self.chunks_y

    def _p(self, filename: str) -> str:
        return os.path.join(self.client_dir, filename)

    def run(self):
        t0 = time.time()
        print(f"=== Britannia 3D Converter: Map {self.map_id} ({self.map_w}x{self.map_h}) ===")

        # --- Step 1: Load shared client files ---
        client = None
        if self.source == 'enhanced':
            print("[1/8] Loading Enhanced client files (tileart, legacy terrain, hues, textures, art)...")
            client = enhanced.EnhancedClient(self.client_dir)
            tiledata = enhanced.EnhancedTileData(client)
            hues = enhanced.EnhancedHues(client)
            texmaps = enhanced.EnhancedTexMaps(client, tiledata)
            art = enhanced.EnhancedArt(client, tiledata)
            radarcol = enhanced.EnhancedRadarCol(tiledata, texmaps, art)
        else:
            print("[1/8] Loading Classic client files (tiledata, radar, hues, texmaps, art)...")
            tiledata = TileData(self._p('tiledata.mul'))
            radarcol = RadarCol(self._p('radarcol.mul'))
            hues = Hues(self._p('hues.mul'))
            texmaps = TexMaps(self._p('texidx.mul'), self._p('texmaps.mul'))
            art = ArtArchive(self._p('artLegacyMUL.uop'))

        shared_dir = os.path.join(self.out_dir, 'shared')
        map_dir = os.path.join(self.out_dir, f'map{self.map_id}')
        os.makedirs(shared_dir, exist_ok=True)
        os.makedirs(map_dir, exist_ok=True)
        os.makedirs(os.path.join(map_dir, 'terrain'), exist_ok=True)
        os.makedirs(os.path.join(map_dir, 'statics'), exist_ok=True)
        os.makedirs(os.path.join(map_dir, 'overview'), exist_ok=True)

        # Save hues.bin (32x3000 RGB5_A1)
        print("  Generating hues.bin...")
        hues_table = np.zeros((3000, 32), dtype=np.uint16)
        for i, h_colors in enumerate(hues.hues_555):
            for c_idx, col in enumerate(h_colors):
                conv = ((col & 0x7FFF) << 1) | 1 if col != 0 else 0
                hues_table[i, c_idx] = conv
        write_file_and_compressed(os.path.join(shared_dir, 'hues.bin'), hues_table.tobytes())

        # --- Steps 2-3: Load map terrain & statics ---
        if self.source == 'enhanced':
            print(f"[2/8] Reading map {self.map_id} sectors from facet{self.map_id}{self.variant}.uop...")
            tid_grid, z_grid, static_items_by_block, all_static_ids = enhanced.load_facet(
                client, self.map_id, self.variant, self.map_w, self.map_h)
            print(f"  Map {self.map_id} grid assembled: {self.map_w}x{self.map_h}, Z range: [{z_grid.min()}..{z_grid.max()}]")
            print(f"[3/8] Statics for map {self.map_id}...")
            print(f"  Statics loaded: {len(static_items_by_block)} active blocks, {len(all_static_ids)} unique static IDs")
            targets = enhanced.land_color_targets(client, self.map_id, self.variant, tid_grid, static_items_by_block)
            texmaps.set_targets(targets)
            print(f"  Overview colours for {len(targets)} land ids")
        else:
            # --- Step 2: Load map terrain & statics ---
            print(f"[2/8] Loading map {self.map_id} terrain...")
            uop_name = f'map{self.map_id}{self.variant}LegacyMUL.uop'
            mul_name = f'map{self.map_id}{self.variant}.mul'

            if os.path.exists(self._p(uop_name)):
                print(f"  Reading terrain from {uop_name}...")
                with UopReader(self._p(uop_name)) as uop:
                    parts = []
                    idx = 0
                    prefix = f"build/map{self.map_id}{self.variant}legacymul"
                    while True:
                        entry_name = f"{prefix}/{idx:08d}.dat"
                        data = uop.read_entry(entry_name)
                        if data is None:
                            break
                        parts.append(data)
                        idx += 1
                    raw_terrain = b''.join(parts)[:self.num_blocks * 196]
            else:
                print(f"  Reading terrain from {mul_name}...")
                with open(self._p(mul_name), 'rb') as f:
                    raw_terrain = f.read(self.num_blocks * 196)

            blk = np.frombuffer(raw_terrain, dtype=np.uint8).reshape(self.num_blocks, 196)
            cells = blk[:, 4:].reshape(self.num_blocks, 64, 3)
            tid = (cells[:, :, 0].astype(np.uint16) | (cells[:, :, 1].astype(np.uint16) << 8))
            z = cells[:, :, 2].view(np.int8)

            # Column-major block layout: block_idx = bx * blocks_h + by
            tid_grid = tid.reshape(self.blocks_w, self.blocks_h, 8, 8).transpose(1, 2, 0, 3).reshape(self.map_h, self.map_w)
            z_grid = z.reshape(self.blocks_w, self.blocks_h, 8, 8).transpose(1, 2, 0, 3).reshape(self.map_h, self.map_w)

            print(f"  Map {self.map_id} grid assembled: {self.map_w}x{self.map_h}, Z range: [{z_grid.min()}..{z_grid.max()}]")

            print(f"[3/8] Loading statics for map {self.map_id}...")
            staidx_name = f'staidx{self.map_id}{self.variant}.mul'
            statics_name = f'statics{self.map_id}{self.variant}.mul'
            staidx = np.fromfile(self._p(staidx_name), dtype='<i4').reshape(-1, 3)
            statics_data = np.fromfile(self._p(statics_name), dtype=np.uint8)

            dt = np.dtype([('id', '<u2'), ('x', 'u1'), ('y', 'u1'), ('z', 'i1'), ('hue', '<u2')])
            static_items_by_block: Dict[int, np.ndarray] = {}
            all_static_ids = set()

            for b_idx in range(min(len(staidx), self.num_blocks)):
                lk, ln, _ = staidx[b_idx]
                if lk >= 0 and ln > 0:
                    count = ln // 7
                    items = np.frombuffer(statics_data, dtype=dt, count=count, offset=lk)
                    static_items_by_block[b_idx] = items
                    all_static_ids.update(items['id'].tolist())

            print(f"  Statics loaded: {len(static_items_by_block)} active blocks, {len(all_static_ids)} unique static IDs")

        # --- Step 4: Build Materials & Land Texture Arrays ---
        print("[4/8] Building materials and land texture arrays...")
        used_land_ids = set(np.unique(tid_grid).tolist())
        mat_builder = MaterialsBuilder(tiledata, radarcol, texmaps, art)
        materials_bin, land64_bin, land128_bin = mat_builder.build_for_land_ids(used_land_ids)

        write_file_and_compressed(os.path.join(shared_dir, 'materials.bin'), materials_bin)
        if land64_bin:
            write_file_and_compressed(os.path.join(shared_dir, 'land64.bin'), land64_bin)
        if land128_bin:
            write_file_and_compressed(os.path.join(shared_dir, 'land128.bin'), land128_bin)

        # Parse landToMat LUT
        lut = struct.unpack_from('<16384H', materials_bin, 4)
        land_to_mat = {i: lut[i] for i in range(16384)}

        # --- Step 5: Build Sprite Atlas ---
        print("[5/8] Decoding sprites and packing into 4096x4096 atlas...")
        atlas = AtlasBuilder()
        sprite_id_to_index: Dict[int, int] = {}
        water_id_to_kind: Dict[int, int] = {}
        water_sprite_indices: List[int] = []

        # Find static water items
        for s_id in sorted(all_static_ids):
            td = tiledata.statics[s_id] if s_id < len(tiledata.statics) else None
            if td and (td.flags & FLAG_WET) and td.height == 0:
                kind = len(water_sprite_indices)
                if kind <= 255:
                    water_id_to_kind[s_id] = kind
                    water_sprite_indices.append(s_id)

        # Add all used static sprites
        for s_id in sorted(all_static_ids):
            art_data = art.read_static_art(s_id)
            if art_data is not None:
                w, h, px = art_data
                td_entry = tiledata.statics[s_id] if s_id < len(tiledata.statics) else None
                td_h = td_entry.height if td_entry else 0
                idx = atlas.add_sprite(orig_id=s_id, td_height=td_h, orig_w=w, orig_h=h, raw_555_pixels=px)
                if idx is not None:
                    sprite_id_to_index[s_id] = idx

        # Pack atlas
        page_bytes_list, sprites_bin = atlas.pack()
        print(f"  Atlas packed into {len(page_bytes_list)} page(s) ({len(atlas.sprites)} sprites)")

        write_file_and_compressed(os.path.join(shared_dir, 'sprites.bin'), sprites_bin)
        for p_idx, p_data in enumerate(page_bytes_list):
            write_file_and_compressed(os.path.join(shared_dir, f'sprites_{p_idx}.bin'), p_data)

        # Write waterkinds.bin: u16 spriteIndex[n]
        water_spr_indices = [sprite_id_to_index.get(sid, 0) for sid in water_sprite_indices]
        waterkinds_bin = struct.pack(f'<{len(water_spr_indices)}H', *water_spr_indices)
        write_file_and_compressed(os.path.join(shared_dir, 'waterkinds.bin'), waterkinds_bin)

        # --- Step 6: Generate Chunks ---
        print(f"[6/8] Generating chunks ({self.chunks_x}x{self.chunks_y} = {self.num_chunks})...")
        chunk_bitset = bytearray(math.ceil(self.num_chunks / 8))
        chunk_meta = bytearray(self.num_chunks * 2)  # i8 zMin, zMax per chunk
        active_chunks = 0

        for cy in range(self.chunks_y):
            for cx in range(self.chunks_x):
                c_idx = cy * self.chunks_x + cx
                gen = ChunkGenerator(cx, cy, tid_grid, z_grid, land_to_mat,
                                     static_items_by_block, tiledata.statics,
                                     sprite_id_to_index, water_id_to_kind,
                                     self.blocks_w, self.blocks_h)

                trn_bytes, sta_bytes, z_min, z_max = gen.build_terrain_and_statics()

                # Record zMin, zMax in chunkMeta regardless
                chunk_meta[c_idx * 2] = z_min & 0xFF
                chunk_meta[c_idx * 2 + 1] = z_max & 0xFF

                if trn_bytes is not None:
                    # Mark exists in bitset
                    chunk_bitset[c_idx // 8] |= (1 << (c_idx % 8))
                    active_chunks += 1

                    # Write chunk files
                    write_file_and_compressed(os.path.join(map_dir, 'terrain', f'{cx}_{cy}.bin'), trn_bytes)
                    if sta_bytes is not None:
                        write_file_and_compressed(os.path.join(map_dir, 'statics', f'{cx}_{cy}.bin'), sta_bytes)

        print(f"  Generated {active_chunks} active chunks (omitted {self.num_chunks - active_chunks} empty/void chunks)")

        # --- Step 7: Overview (Radar Map) ---
        print("[7/8] Generating overview radar map...")
        land_lut = np.zeros((65536, 3), dtype=np.uint8)
        for tid_val in np.unique(tid_grid).tolist():
            c = radarcol.get_land_color(int(tid_val))
            land_lut[tid_val] = [((c >> 10) & 0x1F) * 255 // 31, ((c >> 5) & 0x1F) * 255 // 31, (c & 0x1F) * 255 // 31]
        radar_pixels = land_lut[tid_grid]

        # Overlay statics
        for b_idx, items in static_items_by_block.items():
            bx = b_idx // self.blocks_h
            by = b_idx % self.blocks_h
            for item in items:
                s_id = int(item['id'])
                s_x = bx * 8 + int(item['x'])
                s_y = by * 8 + int(item['y'])
                if s_x < self.map_w and s_y < self.map_h:
                    c = radarcol.get_static_color(s_id)
                    if c != 0:
                        r = ((c >> 10) & 0x1F) * 255 // 31
                        g = ((c >> 5) & 0x1F) * 255 // 31
                        b = (c & 0x1F) * 255 // 31
                        radar_pixels[s_y, s_x] = [r, g, b]

        radar_pil = Image.fromarray(radar_pixels, 'RGB')
        radar_webp_path = os.path.join(map_dir, 'overview', 'radar.webp')
        radar_png_path = os.path.join(map_dir, 'overview', 'radar.png')
        radar_pil.save(radar_webp_path, 'WEBP', quality=85)
        radar_pil.save(radar_png_path, 'PNG')
        print(f"  Overview map saved to {radar_webp_path}")

        # --- Step 8: Manifest ---
        print("[8/8] Writing manifest.json...")
        manifest = {
            "map": self.map_id,
            "source": self.source,
            "width": self.map_w,
            "height": self.map_h,
            "chunk": 64,
            "chunksX": self.chunks_x,
            "chunksY": self.chunks_y,
            "zScale": 0.12856,
            "chunks": base64.b64encode(chunk_bitset).decode('ascii'),
            "chunkMeta": base64.b64encode(chunk_meta).decode('ascii'),
            "atlasPages": len(page_bytes_list),
            "sprites": len(atlas.sprites),
            "landLayers": {
                "64": len(land64_bin) // (64 * 64 * 2) if land64_bin else 0,
                "128": len(land128_bin) // (128 * 128 * 2) if land128_bin else 0
            }
        }
        with open(os.path.join(map_dir, 'manifest.json'), 'w') as f:
            json.dump(manifest, f, indent=2)

        # Cleanup
        texmaps.close()
        art.close()
        if client is not None:
            client.close()

        elapsed = time.time() - t0
        print(f"=== Conversion complete in {elapsed:.1f}s! ===")
