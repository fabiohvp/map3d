"""Materials table and land texture array generator (MAT1, land64, land128)."""
import struct
import numpy as np
from typing import Dict, List, Set, Tuple, Optional
from .formats import TileData, RadarCol, TexMaps, ArtArchive, FLAG_WET

VOID_IDS = {0x0002, 0x01DB, 0x0244} | set(range(0x01AE, 0x01B6))


class MaterialEntry:
    __slots__ = ('kind', 'tex_array', 'tex_layer', 'art_layer', 'radar555', 'flags')

    def __init__(self, kind: int, tex_array: int, tex_layer: int, art_layer: int, radar555: int, flags: int):
        self.kind = kind          # 0: texmap, 1: art only, 2: water, 3: void
        self.tex_array = tex_array  # 0: land64, 1: land128, 255: none
        self.tex_layer = tex_layer
        self.art_layer = art_layer
        self.radar555 = radar555
        self.flags = flags


def diamond_to_64(pixels_44: np.ndarray) -> np.ndarray:
    """Rotates 44x44 diamond to 32x32 and scales to 64x64 (RGB5_A1)."""
    # Map 32x32 from diamond
    u, v = np.meshgrid(np.arange(32), np.arange(32))
    xd = np.clip(np.round(21.5 + (u - v) * (21.5 / 31.0)).astype(int), 0, 43)
    yd = np.clip(np.round((u + v) * (21.5 / 31.0)).astype(int), 0, 43)
    square_32 = pixels_44[yd, xd]

    # Nearest neighbor upscale to 64x64
    square_64 = np.repeat(np.repeat(square_32, 2, axis=0), 2, axis=1)

    # Convert to RGB5_A1
    res = np.zeros_like(square_64, dtype=np.uint16)
    mask = square_64 != 0
    res[mask] = ((square_64[mask] & 0x7FFF) << 1) | 1
    return res


class MaterialsBuilder:
    """Builds materials.bin, land64.bin, and land128.bin."""

    def __init__(self, tiledata: TileData, radarcol: RadarCol, texmaps: TexMaps, art: ArtArchive):
        self.tiledata = tiledata
        self.radarcol = radarcol
        self.texmaps = texmaps
        self.art = art

    def build_for_land_ids(self, used_land_ids: Set[int]) -> Tuple[bytes, bytes, bytes]:
        """
        Builds materials for the set of land IDs used.
        Returns (materials_bin, land64_bin, land128_bin).
        """
        land_to_mat = [0xFFFF] * 16384
        materials: List[MaterialEntry] = []

        # Deduplicate texmaps: tex_id -> (tex_array, layer_index)
        tex64_cache: Dict[int, int] = {}
        tex128_cache: Dict[int, int] = {}
        layers_64: List[np.ndarray] = []
        layers_128: List[np.ndarray] = []

        # Default void material (index 0)
        void_mat = MaterialEntry(kind=3, tex_array=255, tex_layer=0, art_layer=0xFFFF, radar555=0, flags=0)
        materials.append(void_mat)
        void_idx = 0

        # Process each unique land id
        for land_id in sorted(used_land_ids):
            if land_id < 0 or land_id >= 16384:
                continue

            td_entry = self.tiledata.land[land_id] if land_id < len(self.tiledata.land) else None
            flags = td_entry.flags if td_entry else 0
            tex_id = td_entry.tex_id if td_entry else 0
            radar = self.radarcol.get_land_color(land_id)

            if land_id in VOID_IDS:
                land_to_mat[land_id] = void_idx
                continue

            # Water check
            is_wet = bool(flags & FLAG_WET)
            if is_wet and (tex_id == 0 or land_id in range(168, 172) or land_id in range(11790, 11834)):
                mat = MaterialEntry(kind=2, tex_array=255, tex_layer=0, art_layer=0xFFFF, radar555=radar, flags=int(flags & 0xFFFFFFFF))
                mat_idx = len(materials)
                materials.append(mat)
                land_to_mat[land_id] = mat_idx
                continue

            # Check texmap
            if getattr(self.texmaps, 'by_land', False):
                # Enhanced client: texture is resolved per land id (texMap families + name fallback)
                found = self.texmaps.get_land_texmap(land_id)
                tex_data = (found[0], found[1]) if found else None
                if found:
                    tex_id = found[2]
            else:
                tex_data = self.texmaps.get_texmap(tex_id) if tex_id > 0 else None
            if tex_data:
                dim, raw_bytes = tex_data
                raw_px = np.frombuffer(raw_bytes, dtype='<u2')
                # Convert to RGB5_A1: ((c & 0x7FFF) << 1) | 1
                conv = ((raw_px & 0x7FFF) << 1) | 1

                if dim == 64:
                    if tex_id not in tex64_cache:
                        tex64_cache[tex_id] = len(layers_64)
                        layers_64.append(conv.reshape(64, 64))
                    layer_idx = tex64_cache[tex_id]
                    mat = MaterialEntry(kind=0, tex_array=0, tex_layer=layer_idx, art_layer=0xFFFF, radar555=radar, flags=int(flags & 0xFFFFFFFF))
                else:  # dim == 128
                    if tex_id not in tex128_cache:
                        tex128_cache[tex_id] = len(layers_128)
                        layers_128.append(conv.reshape(128, 128))
                    layer_idx = tex128_cache[tex_id]
                    mat = MaterialEntry(kind=0, tex_array=1, tex_layer=layer_idx, art_layer=0xFFFF, radar555=radar, flags=int(flags & 0xFFFFFFFF))

                mat_idx = len(materials)
                materials.append(mat)
                land_to_mat[land_id] = mat_idx
            else:
                # Land art fallback
                art_px = self.art.read_land_art(land_id)
                if art_px is None and hasattr(self.radarcol, 'land_rgb'):
                    # Enhanced client has no land diamonds: flat tile in the land's mean/name colour
                    art_px = np.full((44, 44), max(radar, 1), dtype=np.uint16)
                if art_px is not None:
                    art_64 = diamond_to_64(art_px)
                    layer_idx = len(layers_64)
                    layers_64.append(art_64)
                    mat = MaterialEntry(kind=1, tex_array=0, tex_layer=layer_idx, art_layer=layer_idx, radar555=radar, flags=int(flags & 0xFFFFFFFF))
                else:
                    # Void fallback if no texture and no art
                    mat = MaterialEntry(kind=3, tex_array=255, tex_layer=0, art_layer=0xFFFF, radar555=radar, flags=int(flags & 0xFFFFFFFF))

                mat_idx = len(materials)
                materials.append(mat)
                land_to_mat[land_id] = mat_idx

        # Ensure unused land IDs map to void (void_idx = 0)
        for i in range(16384):
            if land_to_mat[i] == 0xFFFF:
                land_to_mat[i] = void_idx

        # Pack materials.bin:
        # u32 'MAT1'; u16 landToMat[16384]; u32 nMat; nMat * 12 B
        header = struct.pack('<4s', b'MAT1')
        lut = struct.pack('<16384H', *land_to_mat)
        n_mat = len(materials)
        mat_count = struct.pack('<I', n_mat)
        mat_entries = []
        for m in materials:
            # u8 kind, u8 texArray, u16 texLayer, u16 artLayer, u16 radar555, u32 flags
            e = struct.pack('<BBHHHI', m.kind, m.tex_array, m.tex_layer, m.art_layer, m.radar555, m.flags)
            mat_entries.append(e)

        materials_bin = header + lut + mat_count + b''.join(mat_entries)

        # Pack land64 and land128
        land64_bin = b''.join(l.tobytes() for l in layers_64) if layers_64 else b''
        land128_bin = b''.join(l.tobytes() for l in layers_128) if layers_128 else b''

        return materials_bin, land64_bin, land128_bin
