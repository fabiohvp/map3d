"""Readers for the Ultima Online Enhanced Client (UOSA) assets.

Exposes the same interfaces that ``formats.py`` offers for the Classic client
(TileData, RadarCol, Hues, TexMaps, ArtArchive) so the pipeline can run on either.

Enhanced sources (all UOP/MYP containers, hash = Jenkins lookup3 of the lowercase name):
  facetN[x].uop      build/sectors/facet_NN/%08d.bin   64x64 sectors (land, z, statics)
  tileart.uop        build/tileart/%08d.bin            per-item flags, art size, properties
  LegacyTexture.uop  build/tileartlegacy/%08d.dds      classic-look item art (DXT5)
  Texture.uop        build/worldart/%08d.dds           item art and terrain textures
  LegacyTerrain.uop  data/definitions/legacyterrain/%08d.legacyterrain   land flags + texMap
  Hues.uop           3000 BMP gradients (256x2 BGRA), table order == hue index

Sector layout (little-endian), index = chunkX * chunksY + chunkY:
  u8 facet, u16 fileId
  4096 cells, x-major (x outer, y inner):
    u8 z, u16 landId
    u8 nDelimiters, nDelimiters * (u8 dir, [dir <= 7: u8 z, u32 neighbourLandId])
    u8 nStatics,    nStatics    * (u32 staticId, u8 z, u32 hue)
"""
import io
import os
import re
import struct
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from PIL import Image

from .uop import UopReader, hashlittle2
from .formats import (
    LandEntry, StaticEntry,
    FLAG_WALL, FLAG_IMPASSABLE, FLAG_WET, FLAG_SURFACE,
)

WORLDART_TERRAIN_FAMILIES = (1000000, 2000000, 3000000, 5000000, 4000000)
TILEART_FLAGS_OFFSET = 65
TILEART_WIDTH_OFFSET = 109
TILEART_HEIGHT_OFFSET = 113
TILEART_PROPS_OFFSET = 125
PROP_HEIGHT = 3

NODRAW_STATIC_IDS = {0x0001, 0x21BB, 0x21BC, 0x3F28, 0xA561, 0xA562, 0xA563, 0xA564} | set(range(0x2198, 0x21A4))

LEGACY_FLAG_MAP = {
    'impassable': FLAG_IMPASSABLE,
    'wet': FLAG_WET,
    'surface': FLAG_SURFACE,
    'wall': FLAG_WALL,
}

# Flat colours (RGB) for land that has no Enhanced texture at all.
NAME_COLORS = {
    'cobblestones': (128, 124, 116), 'leaves': (70, 110, 50), 'embank': (110, 90, 60),
    'marble': (200, 196, 190), 'sand stone': (190, 165, 110), 'tree': (60, 95, 45),
    'brick': (140, 80, 60), 'obsidian': (30, 28, 34), 'flagstone': (120, 120, 120),
    'wooden floor': (130, 95, 55), 'stone': (125, 125, 125), 'planks': (140, 100, 60),
    'tile': (150, 140, 120), 'cave exit': (90, 80, 70), 'cave': (90, 80, 70),
    'grass': (60, 110, 45), 'sand': (200, 180, 120), 'snow': (235, 240, 245),
    'dirt': (110, 85, 55), 'rock': (110, 105, 100), 'jungle': (50, 100, 40),
    'forest': (55, 90, 40), 'water': (30, 90, 150), 'lava': (200, 70, 20),
    'acid': (110, 170, 40), 'furrows': (100, 75, 50),
}
DEFAULT_COLOR = (128, 128, 128)


def _rgb888_to_555(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (((r.astype(np.uint16) >> 3) << 10) | ((g.astype(np.uint16) >> 3) << 5) | (b.astype(np.uint16) >> 3))


def _color555(rgb: Tuple[int, int, int]) -> int:
    return ((rgb[0] >> 3) << 10) | ((rgb[1] >> 3) << 5) | (rgb[2] >> 3)


class EnhancedClient:
    """Holds the client directory and caches opened UOP archives."""

    def __init__(self, client_dir: str):
        self.dir = client_dir
        self._uops: Dict[str, UopReader] = {}

    def path(self, name: str) -> str:
        return os.path.join(self.dir, name)

    def uop(self, name: str) -> UopReader:
        if name not in self._uops:
            self._uops[name] = UopReader(self.path(name))
        return self._uops[name]

    def close(self):
        for u in self._uops.values():
            u.close()
        self._uops.clear()


# --------------------------------------------------------------------------- map

_CELL = struct.Struct('<BHB')
_STATIC = struct.Struct('<IBI')


def parse_sector(data: bytes):
    """Returns (file_id, land u16[4096], z i8[4096], statics [(cell, id, z, hue)]); cell = lx * 64 + ly."""
    file_id = struct.unpack_from('<H', data, 1)[0]
    off = 3
    land = np.zeros(4096, dtype=np.uint16)
    zs = np.zeros(4096, dtype=np.int8)
    statics: List[Tuple[int, int, int, int]] = []
    cell_unpack = _CELL.unpack_from
    static_unpack = _STATIC.unpack_from
    for c in range(4096):
        z, lid, nd = cell_unpack(data, off)
        off += 4
        zs[c] = z - 256 if z > 127 else z
        land[c] = lid
        for _ in range(nd):
            direction = data[off]
            off += 6 if direction <= 7 else 1
        ns = data[off]
        off += 1
        for _ in range(ns):
            g, sz, hue = static_unpack(data, off)
            off += 9
            statics.append((c, g, sz - 256 if sz > 127 else sz, hue))
    if off != len(data):
        raise ValueError(f"sector {file_id}: parsed {off} of {len(data)} bytes")
    return file_id, land, zs, statics


STATIC_DT = np.dtype([('id', '<u2'), ('x', 'u1'), ('y', 'u1'), ('z', 'i1'), ('hue', '<u2')])


def load_facet(client: EnhancedClient, map_id: int, variant: str, map_w: int, map_h: int):
    """Reads every sector of a facet.

    Returns (tid_grid[h, w] u16, z_grid[h, w] i8, static_items_by_block, all_static_ids),
    the same structures the classic loader produces (block index = bx * blocks_h + by).
    """
    uop = client.uop(f'facet{map_id}{variant}.uop')
    chunks_x = -(-map_w // 64)
    chunks_y = -(-map_h // 64)
    blocks_h = map_h // 8
    tid_grid = np.full((chunks_y * 64, chunks_x * 64), 0x0244, dtype=np.uint16)
    z_grid = np.zeros((chunks_y * 64, chunks_x * 64), dtype=np.int8)
    per_block: Dict[int, List[Tuple[int, int, int, int, int]]] = {}
    all_ids: Set[int] = set()

    for cx in range(chunks_x):
        for cy in range(chunks_y):
            idx = cx * chunks_y + cy
            raw = uop.read_entry(f'build/sectors/facet_{map_id:02d}/{idx:08d}.bin')
            if raw is None:
                continue
            _, land, zs, statics = parse_sector(raw)
            tid_grid[cy * 64:cy * 64 + 64, cx * 64:cx * 64 + 64] = land.reshape(64, 64).T
            z_grid[cy * 64:cy * 64 + 64, cx * 64:cx * 64 + 64] = zs.reshape(64, 64).T
            for cell, sid, sz, hue in statics:
                x = cx * 64 + (cell >> 6)
                y = cy * 64 + (cell & 63)
                all_ids.add(sid)
                per_block.setdefault((x >> 3) * blocks_h + (y >> 3), []).append((sid, x & 7, y & 7, sz, hue & 0xFFFF))

    items = {}
    for b, lst in per_block.items():
        arr = np.empty(len(lst), dtype=STATIC_DT)
        arr['id'], arr['x'], arr['y'], arr['z'], arr['hue'] = zip(*lst)
        items[b] = arr
    return tid_grid[:map_h, :map_w], z_grid[:map_h, :map_w], items, all_ids


def land_color_targets(client: EnhancedClient, map_id: int, variant: str, tid_grid: np.ndarray,
                       static_items_by_block: Dict[int, np.ndarray]) -> Dict[int, Tuple[int, int, int]]:
    """Mean minimap colour per land id, from the facetNN.dds overview (1 px per tile, same colours as the radar).

    Only tiles without statics are sampled, so trees and buildings do not tint the land colour.
    Returns {} when the overview is not available.
    """
    h, w = tid_grid.shape
    for name in (f'facet{map_id:02d}{variant}.dds', f'facet{map_id:02d}.dds'):
        path = client.path(name)
        if os.path.exists(path):
            break
    else:
        return {}
    img = np.asarray(Image.open(path).convert('RGB'))
    if img.shape[0] < h or img.shape[1] < w:
        return {}
    img = img[:h, :w]
    free = np.ones((h, w), dtype=bool)
    blocks_h = h // 8
    for b, arr in static_items_by_block.items():
        bx, by = divmod(b, blocks_h)
        free[by * 8 + arr['y'].astype(int), bx * 8 + arr['x'].astype(int)] = False
    ids = tid_grid[free].astype(np.int64)
    px = img[free].astype(np.float64)
    out: Dict[int, Tuple[int, int, int]] = {}
    for lid in np.unique(ids).tolist():
        m = ids == lid
        out[lid] = tuple(int(v) for v in np.median(px[m], axis=0))
    return out


# ---------------------------------------------------------------------- tiledata

class _LazyStatics:
    """list-like view over tileart.uop entries; entries are parsed on first access."""

    def __init__(self, uop: UopReader, count: int):
        self._uop = uop
        self._count = count
        self._cache: Dict[int, Optional[StaticEntry]] = {}

    def __len__(self):
        return self._count

    def __getitem__(self, sid: int) -> Optional[StaticEntry]:
        if sid in self._cache:
            return self._cache[sid]
        raw = self._uop.read_entry(f'build/tileart/{sid:08d}.bin')
        entry = None
        if raw is not None and len(raw) > TILEART_PROPS_OFFSET:
            flags = struct.unpack_from('<Q', raw, TILEART_FLAGS_OFFSET)[0]
            height = 0
            n = raw[TILEART_PROPS_OFFSET]
            p = TILEART_PROPS_OFFSET + 1
            for _ in range(n):
                if p + 5 > len(raw):
                    break
                if raw[p] == PROP_HEIGHT:
                    height = min(struct.unpack_from('<I', raw, p + 1)[0], 255)
                p += 5
            name = 'nodraw' if sid in NODRAW_STATIC_IDS else ''
            entry = StaticEntry(flags, height, 0, 0, name)
        self._cache[sid] = entry
        return entry


class EnhancedTileData:
    """Replacement for TileData: land flags/texMap from LegacyTerrain, statics from tileart."""

    STATIC_COUNT = 0x10000

    def __init__(self, client: EnhancedClient):
        self.terrain: Dict[int, Tuple[str, int, List[str]]] = {}
        lt = client.uop('LegacyTerrain.uop')
        for h in lt.entries:
            xml = lt.read_entry_by_hash(h).decode('utf8', 'ignore')
            m = re.search(r'id="\s*(\d+)\s*"\s+name="([^"]*)"\s+texMap="\s*(\d+)\s*"', xml)
            if not m:
                continue
            self.terrain[int(m.group(1))] = (m.group(2), int(m.group(3)), re.findall(r'<(\w+)\s*/>', xml))

        self.land: List[LandEntry] = []
        for i in range(16384):
            name, tex, tags = self.terrain.get(i, ('', 0, []))
            flags = 0
            for t in tags:
                flags |= LEGACY_FLAG_MAP.get(t, 0)
            self.land.append(LandEntry(flags, tex, name))
        self.statics = _LazyStatics(client.uop('tileart.uop'), self.STATIC_COUNT)


# --------------------------------------------------------------------------- hues

class EnhancedHues:
    """Hues.uop stores each hue as a 256x2 BMP; row 1 is the gradient and every 8th pixel is the classic colour."""

    def __init__(self, client: EnhancedClient):
        uop = client.uop('Hues.uop')
        self.hues_555: List[List[int]] = []
        for h in uop.entries:
            d = uop.read_entry_by_hash(h)
            if d[:2] != b'BM':
                continue
            off = struct.unpack_from('<I', d, 10)[0]
            px = np.frombuffer(d, np.uint8, count=2 * 256 * 4, offset=off).reshape(2, 256, 4)
            row = px[1][::8][:32]
            self.hues_555.append(_rgb888_to_555(row[:, 2], row[:, 1], row[:, 0]).tolist())
        if len(self.hues_555) < 3000:
            raise ValueError(f"Hues.uop: expected 3000 hues, found {len(self.hues_555)}")
        del self.hues_555[3000:]


# --------------------------------------------------------------------------- art

def _decode_dds(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert('RGBA'))


class EnhancedArt:
    """Static sprites from tileartlegacy DDS, sized by tileart.bin (the DDS is padded to a power of two)."""

    def __init__(self, client: EnhancedClient, tiledata: EnhancedTileData):
        self.legacy = client.uop('LegacyTexture.uop')
        self.tileart = client.uop('tileart.uop')

    def read_static_art(self, static_id: int) -> Optional[Tuple[int, int, np.ndarray]]:
        meta = self.tileart.read_entry(f'build/tileart/{static_id:08d}.bin')
        dds = self.legacy.read_entry(f'build/tileartlegacy/{static_id:08d}.dds')
        if meta is None or dds is None or len(meta) < TILEART_HEIGHT_OFFSET + 4:
            return None
        w = struct.unpack_from('<i', meta, TILEART_WIDTH_OFFSET)[0]
        h = struct.unpack_from('<i', meta, TILEART_HEIGHT_OFFSET)[0]
        if w <= 0 or h <= 0 or w > 1024 or h > 1024:
            return None
        rgba = _decode_dds(dds)[:h, :w]
        px = _rgb888_to_555(rgba[..., 0], rgba[..., 1], rgba[..., 2])
        opaque = rgba[..., 3] >= 128
        px = np.where(opaque, np.maximum(px, 1), 0).astype(np.uint16)
        full = np.zeros((h, w), dtype=np.uint16)
        full[:px.shape[0], :px.shape[1]] = px
        return (w, h, full)

    def read_land_art(self, land_id: int) -> Optional[np.ndarray]:
        """Enhanced ships no classic land diamonds; the pipeline asks this only when a land has no texture."""
        return None

    def close(self):
        pass


# ---------------------------------------------------------------------- textures

class EnhancedTexMaps:
    """Terrain textures from Texture.uop (worldart ids 1M/2M/3M/4M/5M + texMap), resampled to 128x128.

    The id space is shared with other assets, so for each land id the candidate closest to the
    overview colour of that land wins; lands without a usable texture borrow one from a land with the same name.
    Normal maps and alpha blend masks share the id space and are skipped.
    """
    by_land = True
    OUT_DIM = 128
    POOL_SCAN = 20000
    SAME_NAME_PENALTY = 1.3
    ANY_PENALTY = 1.7
    _pool = None

    def __init__(self, client: EnhancedClient, tiledata: EnhancedTileData):
        self.uop = client.uop('Texture.uop')
        self.tiledata = tiledata
        self._tex: Dict[int, Optional[np.ndarray]] = {}
        self._land_key: Dict[int, Optional[int]] = {}
        self.targets: Dict[int, Tuple[int, int, int]] = {}
        self._by_name: Dict[str, List[int]] = {}
        for i, e in enumerate(tiledata.land):
            if e.name and e.tex_id:
                self._by_name.setdefault(e.name.lower(), []).append(i)

    def _load_key(self, key: int) -> Optional[np.ndarray]:
        if key in self._tex:
            return self._tex[key]
        res = None
        raw = self.uop.read_entry(f'build/worldart/{key:08d}.dds')
        if raw is not None:
            rgba = _decode_dds(raw)
            mean = rgba[..., :3].reshape(-1, 3).mean(axis=0)
            is_normal = mean[2] > 200 and 100 < mean[0] < 170 and 100 < mean[1] < 170
            # DXT5 entries with real alpha are blend/splat masks, not diffuse textures
            is_opaque = int(rgba[..., 3].min()) >= 250
            if is_opaque and not is_normal:
                img = Image.fromarray(rgba[..., :3]).resize((self.OUT_DIM, self.OUT_DIM), Image.LANCZOS)
                a = np.asarray(img)
                res = _rgb888_to_555(a[..., 0], a[..., 1], a[..., 2])
        self._tex[key] = res
        return res

    def set_targets(self, targets: Dict[int, Tuple[int, int, int]]):
        """Expected mean colour per land id (from the overview); used to pick the matching texture family."""
        self.targets = targets
        self._land_key.clear()

    def _own_textures(self, tex_id: int) -> List[Tuple[int, np.ndarray]]:
        out = []
        for base in WORLDART_TERRAIN_FAMILIES:
            t = self._load_key(base + tex_id)
            if t is not None:
                out.append((base + tex_id, t))
        return out

    @staticmethod
    def _mean_rgb(t: np.ndarray) -> np.ndarray:
        return np.array([((t >> 10) & 31).mean() * 8, ((t >> 5) & 31).mean() * 8, (t & 31).mean() * 8])

    def _global_pool(self) -> List[Tuple[int, np.ndarray]]:
        """Every opaque terrain texture of the known worldart families (scanned once)."""
        if self._pool is None:
            self._pool = []
            for base in WORLDART_TERRAIN_FAMILIES:
                for i in range(self.POOL_SCAN):
                    if hashlittle2(f'build/worldart/{base + i:08d}.dds'.encode()) in self.uop.entries:
                        t = self._load_key(base + i)
                        if t is not None:
                            self._pool.append((base + i, t))
        return self._pool

    def _score(self, tex: np.ndarray, target) -> float:
        return float(np.linalg.norm(self._mean_rgb(tex) - np.array(target, dtype=float)))

    def resolve_land(self, land_id: int) -> Optional[Tuple[int, np.ndarray]]:
        """Returns (cache key, 128x128 u16 555) for a land id, or None.

        Candidates are the land's own texMap textures, those of lands with the same name and, as a last
        resort, every terrain texture; the one closest to the overview colour wins (own > same name > any).
        Without overview colours only the own textures are considered.
        """
        if land_id in self._land_key:
            k = self._land_key[land_id]
            return None if k is None else (k, self._tex[k])
        entry = self.tiledata.land[land_id] if land_id < len(self.tiledata.land) else None
        target = self.targets.get(land_id)
        found = None
        if entry and entry.tex_id:
            own = self._own_textures(entry.tex_id)
            if target is None:
                found = own[0] if own else None
            else:
                scored = [(self._score(t, target), k, t) for k, t in own]
                if entry.name:
                    same = sorted(self._by_name.get(entry.name.lower(), []), key=lambda c: abs(c - land_id))
                    for cand in same[:24]:
                        scored += [(self._score(t, target) * self.SAME_NAME_PENALTY, k, t)
                                   for k, t in self._own_textures(self.tiledata.land[cand].tex_id)]
                scored += [(self._score(t, target) * self.ANY_PENALTY, k, t) for k, t in self._global_pool()]
                if scored:
                    _, k, t = min(scored, key=lambda x: x[0])
                    found = (k, t)
        self._land_key[land_id] = found[0] if found else None
        return found

    def get_land_texmap(self, land_id: int) -> Optional[Tuple[int, bytes, int]]:
        found = self.resolve_land(land_id)
        if not found:
            return None
        return (self.OUT_DIM, found[1].astype('<u2').tobytes(), found[0])

    def close(self):
        pass


# ---------------------------------------------------------------------- radar

class EnhancedRadarCol:
    """Mean colour of the land texture / static sprite, in RGB555."""

    def __init__(self, tiledata: EnhancedTileData, texmaps: EnhancedTexMaps, art: EnhancedArt):
        self.tiledata, self.texmaps, self.art = tiledata, texmaps, art
        self._land: Dict[int, int] = {}
        self._static: Dict[int, int] = {}

    def land_rgb(self, land_id: int) -> Tuple[int, int, int]:
        target = self.texmaps.targets.get(land_id)
        if target is not None:
            return target
        found = self.texmaps.resolve_land(land_id) if 0 <= land_id < 16384 else None
        if found:
            t = found[1]
            return (int(((t >> 10) & 31).mean() * 8), int(((t >> 5) & 31).mean() * 8), int((t & 31).mean() * 8))
        name = self.tiledata.land[land_id].name.lower() if 0 <= land_id < 16384 else ''
        return NAME_COLORS.get(name, DEFAULT_COLOR)

    def get_land_color(self, land_id: int) -> int:
        if land_id not in self._land:
            self._land[land_id] = _color555(self.land_rgb(land_id))
        return self._land[land_id]

    def get_static_color(self, static_id: int) -> int:
        if static_id not in self._static:
            c = 0
            a = self.art.read_static_art(static_id)
            if a is not None:
                px = a[2][a[2] != 0]
                if px.size:
                    c = _color555((int(((px >> 10) & 31).mean() * 8), int(((px >> 5) & 31).mean() * 8), int((px & 31).mean() * 8)))
            self._static[static_id] = c
        return self._static[static_id]
