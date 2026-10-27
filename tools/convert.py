"""Converte o terreno de um mapa do UO para os formatos do map3d (TRN1 / MAT1 / TEX1).

Uso:
    python -I map3d/tools/convert.py [--source enhanced|classic] [--client <pasta do cliente>] [--map 0] [--out map3d/data]

Fonte padrão: cliente Enhanced (pasta "Ultima Online Enhanced" ao lado da do Classic). Com
--source classic lê os .mul/.uop do cliente Classic como antes.

Saída:
    data/map<N>/materials.bin   MAT1: tabela de materiais do terreno (índices próprios do mapa)
    data/map<N>/land64.bin      TEX1: texture array 64x64 RGB5_A1 (texmaps 64 + land art)
    data/map<N>/land128.bin     TEX1: texture array 128x128 RGB5_A1 (texmaps 128)
    data/map<N>/manifest.json   dimensões, chunks existentes, zMin/zMax por chunk
    data/map<N>/radar.png       minimapa (1 px a cada 4 tiles)
    data/map<N>/terrain/{cx}_{cy}.bin   TRN1, um por chunk 64x64 não-void
"""
import argparse, base64, json, os, struct, sys, time, zlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = {0: (7168, 4096), 1: (7168, 4096), 2: (2304, 1600), 3: (2560, 2048), 4: (1448, 1448), 5: (1280, 4096)}
CHUNK = 64
VOID_LAND = {0x0002, 0x01DB, 0x0244} | set(range(0x01AE, 0x01B6))
WET = 0x80
KIND_TEX, KIND_ART, KIND_WATER = 0, 1, 2

# ---------------------------------------------------------------- UOP

M32 = 0xFFFFFFFF

def _rot(x, k):
    return ((x << k) | (x >> (32 - k))) & M32

def hashlittle2(s: bytes) -> int:
    """Jenkins lookup3 hashlittle2; retorna (pb << 32) | pc, como o cliente usa nas UOP."""
    length = len(s)
    a = b = c = (0xDEADBEEF + length) & M32
    k = 0
    while length > 12:
        a = (a + int.from_bytes(s[k:k + 4], 'little')) & M32
        b = (b + int.from_bytes(s[k + 4:k + 8], 'little')) & M32
        c = (c + int.from_bytes(s[k + 8:k + 12], 'little')) & M32
        a = (a - c) & M32; a ^= _rot(c, 4); c = (c + b) & M32
        b = (b - a) & M32; b ^= _rot(a, 6); a = (a + c) & M32
        c = (c - b) & M32; c ^= _rot(b, 8); b = (b + a) & M32
        a = (a - c) & M32; a ^= _rot(c, 16); c = (c + b) & M32
        b = (b - a) & M32; b ^= _rot(a, 19); a = (a + c) & M32
        c = (c - b) & M32; c ^= _rot(b, 4); b = (b + a) & M32
        length -= 12; k += 12
    if length == 0:
        return (b << 32) | c
    t = s[k:]  # 1..12 bytes restantes, somados em a/b/c como little-endian
    a = (a + int.from_bytes(t[0:4], 'little')) & M32
    if length > 4:
        b = (b + int.from_bytes(t[4:8], 'little')) & M32
    if length > 8:
        c = (c + int.from_bytes(t[8:12], 'little')) & M32
    c ^= b; c = (c - _rot(b, 14)) & M32
    a ^= c; a = (a - _rot(c, 11)) & M32
    b ^= a; b = (b - _rot(a, 25)) & M32
    c ^= b; c = (c - _rot(b, 16)) & M32
    a ^= c; a = (a - _rot(c, 4)) & M32
    b ^= a; b = (b - _rot(a, 14)) & M32
    c ^= b; c = (c - _rot(b, 24)) & M32
    return (b << 32) | c


class Uop:
    def __init__(self, path):
        self.f = open(path, 'rb')
        magic, ver, sig, nxt, cap, cnt = struct.unpack('<4sIIQII', self.f.read(28))
        if magic != b'MYP\0':
            raise ValueError(f'{path}: não é UOP')
        self.entries = {}
        while nxt:
            self.f.seek(nxt)
            fc, nxt = struct.unpack('<IQ', self.f.read(12))
            for _ in range(fc):
                off, hl, cl, dl, h, adler, flag = struct.unpack('<QIIIQIH', self.f.read(34))
                if off:
                    self.entries[h] = (off + hl, cl, flag)

    def get(self, name: str):
        e = self.entries.get(hashlittle2(name.lower().encode()))
        if e is None:
            return None
        off, cl, flag = e
        self.f.seek(off)
        d = self.f.read(cl)
        return zlib.decompress(d) if flag == 1 else d


# ---------------------------------------------------------------- leitura

def read_map(client, n):
    w, h = MAPS[n]
    bw, bh = w // 8, h // 8
    nb = bw * bh
    uop_path = os.path.join(client, f'map{n}LegacyMUL.uop')
    if os.path.exists(uop_path):
        u = Uop(uop_path)
        parts, i = [], 0
        while (d := u.get(f'build/map{n}legacymul/{i:08d}.dat')) is not None:
            parts.append(d); i += 1
        raw = b''.join(parts)
        print(f'  {uop_path}: {i} entradas')
    else:
        raw = open(os.path.join(client, f'map{n}.mul'), 'rb').read()
    if len(raw) < nb * 196:
        raise ValueError(f'mapa curto: {len(raw)} < {nb * 196}')
    blk = np.frombuffer(raw[:nb * 196], np.uint8).reshape(nb, 196)[:, 4:].reshape(nb, 64, 3)
    tid = blk[:, :, 0].astype(np.uint16) | (blk[:, :, 1].astype(np.uint16) << 8)
    z = blk[:, :, 2].view(np.int8)
    # bloco = bx*bh + by ; célula = cy*8 + cx
    tid = tid.reshape(bw, bh, 8, 8).transpose(1, 2, 0, 3).reshape(h, w)
    z = z.reshape(bw, bh, 8, 8).transpose(1, 2, 0, 3).reshape(h, w)
    return tid, z


def read_tiledata_land(client):
    td = open(os.path.join(client, 'tiledata.mul'), 'rb').read()
    flags = np.zeros(0x4000, np.uint64)
    tex = np.zeros(0x4000, np.uint16)
    off = 0
    for i in range(0x4000):
        if i % 32 == 0:
            off += 4
        flags[i], tex[i] = struct.unpack_from('<QH', td, off)
        off += 30
    return flags, tex


def to5551(c):
    """UO 555 (xRRRRRGGGGGBBBBB) -> WebGL RGB5_A1 opaco (RRRRRGGGGGBBBBBA)."""
    return (((c.astype(np.uint16) & 0x7FFF) << 1) | 1).astype(np.uint16)


def decode_land_art(d):
    """Diamante 44x44 -> (cores u16[44,44], máscara bool[44,44])."""
    px = np.frombuffer(d, '<u2')
    img = np.zeros((44, 44), np.uint16)
    mask = np.zeros((44, 44), bool)
    p = 0
    for y in range(44):
        if y < 22:
            x0, n = 21 - y, 2 * (y + 1)
        else:
            x0, n = y - 22, 2 * (44 - y)
        img[y, x0:x0 + n] = px[p:p + n]
        mask[y, x0:x0 + n] = True
        p += n
    return img, mask


def art_to_square(img, mask, size=64):
    """Desfaz a projeção: u segue +x do mundo, v segue +y (canto norte do tile em uv 0,0)."""
    g = (np.arange(size) + 0.5) / size
    u, v = np.meshgrid(g, g)  # [v, u]
    sx = 22.0 + (u - v) * 22.0
    sy = (u + v) * 22.0
    for _ in range(4):
        ix = np.clip(sx.astype(int), 0, 43)
        iy = np.clip(sy.astype(int), 0, 43)
        bad = ~mask[iy, ix]
        if not bad.any():
            break
        sx = np.where(bad, sx + np.sign(22 - sx), sx)
        sy = np.where(bad, sy + np.sign(22 - sy), sy)
    ix = np.clip(sx.astype(int), 0, 43)
    iy = np.clip(sy.astype(int), 0, 43)
    return img[iy, ix]


def write_png(path, rgb):
    h, w, _ = rgb.shape
    raw = b''.join(b'\0' + rgb[y].tobytes() for y in range(h))
    def chunk(t, d):
        return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xFFFFFFFF)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        f.write(chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)))
        f.write(chunk(b'IDAT', zlib.compress(raw, 9)))
        f.write(chunk(b'IEND', b''))


def write_tex(path, size, layers):
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sHHI', b'TEX1', size, len(layers), 0))
        for l in layers:
            f.write(l.astype('<u2').tobytes())


# ---------------------------------------------------------------- statics

NODRAW_STATIC = {0x0001, 0x21BC, 0x63D3} | set(range(0x2198, 0x21A5))
SF_BACKGROUND, SF_WALL, SF_IMPASSABLE, SF_SURFACE, SF_BRIDGE = 0x1, 0x10, 0x40, 0x200, 0x400
SF_PARTIAL_HUE, SF_ROOF, SF_DOOR = 0x40000, 0x10000000, 0x20000000
SK_BOX, SK_FLAT, SK_SLOPE, SK_BILL = 0, 1, 2, 3
ATLAS = 4096
GUTTER = 2


def read_tiledata_static(client):
    td = open(os.path.join(client, 'tiledata.mul'), 'rb').read()
    off = 512 * (4 + 32 * 30)
    flags, height, nodraw = [], [], []
    while off + 4 <= len(td):
        off += 4
        for _ in range(32):
            if off + 41 > len(td):
                break
            flags.append(struct.unpack_from('<Q', td, off)[0])
            height.append(td[off + 20])
            nodraw.append(td[off + 21:off + 41].split(b'\0')[0].strip().lower() == b'nodraw')
            off += 41
    return np.array(flags, np.uint64), np.array(height, np.uint8), np.array(nodraw, bool)


def read_statics(client, n, W, H):
    """Todos os statics do mapa em ordem de arquivo: (gx, gy, z, id, hue)."""
    bh, nb = H // 8, (W // 8) * (H // 8)
    idx = np.fromfile(os.path.join(client, f'staidx{n}.mul'), '<i4').reshape(-1, 3)[:nb]
    data = np.fromfile(os.path.join(client, f'statics{n}.mul'), np.uint8)
    ok = (idx[:, 0] >= 0) & (idx[:, 1] >= 7) & (idx[:, 0].astype(np.int64) + idx[:, 1] <= data.size)
    blocks = np.nonzero(ok)[0]
    counts = idx[blocks, 1] // 7
    first = np.cumsum(counts) - counts
    k = np.arange(counts.sum()) - np.repeat(first, counts)
    off = np.repeat(idx[blocks, 0].astype(np.int64), counts) + 7 * k
    rec = data[off[:, None] + np.arange(7)]
    blk = np.repeat(blocks, counts)
    sid = rec[:, 0].astype(np.int64) | (rec[:, 1].astype(np.int64) << 8)
    gx = (blk // bh) * 8 + (rec[:, 2] & 7)
    gy = (blk % bh) * 8 + (rec[:, 3] & 7)
    z = rec[:, 4].view(np.int8).astype(np.int64)
    hue = rec[:, 5].astype(np.int64) | (rec[:, 6].astype(np.int64) << 8)
    return gx, gy, z, sid, hue


def decode_static_art(d):
    """Offset-run -> cores u16[h, w]; 0 = transparente (pixel 0x0000 também, como no ClassicUO)."""
    if d is None or len(d) < 8:
        return None
    _, w, h = struct.unpack_from('<IHH', d, 0)
    if not (0 < w <= 1024 and 0 < h <= 1024):
        return None
    buf = np.frombuffer(d[:len(d) // 2 * 2], '<u2')
    lookup = buf[4:4 + h]
    base = 4 + h
    img = np.zeros((h, w), np.uint16)
    for y in range(h):
        p = base + int(lookup[y])
        x = 0
        while p + 1 < len(buf):
            xo, xr = int(buf[p]), int(buf[p + 1])
            p += 2
            if xo + xr == 0:
                break
            x += xo
            n = max(0, min(xr, w - x))
            img[y, x:x + n] = buf[p:p + n]
            p += xr
            x += xr
    img &= 0x7FFF
    return img


def ground_contour(mask):
    """Contorno inferior da art projetado no chão (lz=0) -> (lx, ly) locais ao tile."""
    h, w = mask.shape
    cols = np.nonzero(mask.any(0))[0]
    bot = h - 1 - np.argmax(mask[::-1, cols], axis=0)
    a = (cols + 0.5 - w / 2) / 22
    s = (bot + 1 - h + 44) / 22
    return (a + s) / 2, (s - a) / 2


def flat_extent(mask, lz):
    """Retângulo (lx0, ly0, lx1, ly1) do plano lz que cobre todos os pixels opacos."""
    h, w = mask.shape
    v, u = np.nonzero(mask)
    d1 = (u + 0.5 - w / 2) / 22
    d2 = (v + 0.5 - h + 44 + 4 * lz) / 22
    lx, ly = (d1 + d2) / 2, (d2 - d1) / 2
    p = 0.03
    return float(lx.min() - p), float(ly.min() - p), float(lx.max() + p), float(ly.max() + p)


SLOPES = (-24, -12, -6, -3, 0, 3, 6, 12, 24)


def fit_slope(mask):
    """Plano inclinado sobre o tile (com beiral e) que melhor cobre a silhueta (IoU)."""
    h, w = mask.shape
    vv, uu = np.mgrid[0:h, 0:w]
    uu = uu + 0.5
    vv = vv + 0.5
    area = mask.sum()
    vbot = np.nonzero(mask.any(1))[0].max() + 1
    # A silhueta é ambígua: os planos de inclinação (α, β) e (11 − β, 11 − α) projetam o mesmo
    # paralelogramo. Entre candidatos de IoU quase igual fica o de menor inclinação (telhados do
    # UO sobem ~3 z por tile); sem isso o primeiro do laço vencia e o telhado virava para o lado errado.
    # Testa também o gêmeo exato de cada par da grade, (−11 − sy, −11 − sx) em termos de sx/sy.
    pairs = {(sx, sy) for sx in SLOPES for sy in SLOPES}
    pairs |= {(-11 - sy, -11 - sx) for sx, sy in pairs}
    cands = []
    for e in (0.0, 0.1, 0.2, 0.3):
        cl = ((-e, -e), (1 + e, -e), (1 + e, 1 + e), (-e, 1 + e))
        for sx, sy in sorted(pairs):
            pts = [(22 * (lx - ly) + w / 2, 22 * (lx + ly) - 4 * (sx * (1 - lx) + sy * (1 - ly)) + h - 44) for lx, ly in cl]
            c = (max(p[1] for p in pts) - vbot) / 4
            pts = [(pu, pv - 4 * c) for pu, pv in pts]  # sobe o plano c unidades de z: base encosta em vbot
            inside = np.ones_like(mask)
            for i in range(4):
                (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % 4]
                x3, y3 = pts[(i + 2) % 4]
                sign = 1 if (x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1) >= 0 else -1
                inside &= ((x2 - x1) * (vv - y1) - (y2 - y1) * (uu - x1)) * sign >= 0
            inter = (inside & mask).sum()
            cands.append((inter / (inside.sum() + area - inter), e, c, sx, sy))
    top = max(k[0] for k in cands)
    return min((k for k in cands if k[0] >= top - 0.02), key=lambda k: (abs(k[3]) + abs(k[4]), -k[0]))


def classify_sprite(img, flags, td_height):
    """-> (kind, params[6], qualidade) em unidades locais (tile, tile, z)."""
    mask = img != 0
    h, w = mask.shape
    lx, ly = ground_contour(mask)
    full = lx.min() < 0.15 and ly.min() < 0.15 and lx.max() > 0.85 and ly.max() > 0.85
    if flags & SF_ROOF:
        iou, e, c, sx, sy = fit_slope(mask)
        return SK_SLOPE, (e, c, sx, sy, 0, 0), iou
    # só estrutura ganha geometria (caixa): parede, porta e pisos/escadas/plataformas (Background
    # ou Bridge) com altura real (> 0). Tapetes e pisos rentes ao chão (td_height == 0) ficam planos.
    is_wall_door = bool(flags & (SF_WALL | SF_DOOR))
    is_surface = bool(full and (flags & (SF_BACKGROUND | SF_BRIDGE)))
    if is_wall_door or (is_surface and td_height > 0):
        x0 = 0.0 if lx.min() < 0.15 else min(float(lx.min()), 0.92)
        y0 = 0.0 if ly.min() < 0.15 else min(float(ly.min()), 0.92)
        vmin = np.nonzero(mask.any(1))[0].min()
        # altura da tiledata quando existe (mesa = 6): estimar pela art põe o tampo baixo demais
        # e as pernas acabam pintadas na face de cima
        hb_art = max(0.0, (22 * (x0 + y0) + h - 44 - vmin) / 4)
        hb = float(td_height) if td_height > 0 else hb_art
        if is_wall_door:
            # parede/porta: peças de arremate/frontão têm art muito mais baixa que a altura da tiledata (20)
            if td_height == 20 and hb_art < 10:
                hb = max(1.0, hb_art)
            else:
                hb = max(hb, hb_art)
        elif hb_art > hb + 3:
            # Background/Bridge com art bem mais alta que a caixa (tronco de árvore com copa, poste...):
            # numa caixa a copa seria pintada deitada na face de cima; fica com o casco visual
            return hull_box(mask, td_height)
        if hb >= 0.5:
            return SK_BOX, (x0, y0, hb, 0, 0, 0), 1.0
        return SK_FLAT, flat_extent(mask, 0.0) + (0.0, 0), 1.0
    # itens baixos (td_height <= 2): só viram plano se NÃO forem intransitáveis (móveis como camas/mesas têm SF_IMPASSABLE)
    if td_height <= 2 and not (flags & SF_IMPASSABLE):
        ext = flat_extent(mask, float(td_height))
        if min(ext[:2]) >= -0.3 and max(ext[2:]) <= 1.3:
            return SK_FLAT, ext + (float(td_height), 0), 1.0
        # não cabe deitado no tile: quadro, escudo, estandarte, placa... → plano vertical
        kind, params, q = vertical_plane(mask)
        return (kind, params, q) if kind == SK_FLAT else hull_box(mask, td_height)
    return hull_box(mask, td_height)


def hull_box(mask, td_height):
    """Caixa do casco visual: o viewer marcha raios dentro dela e um ponto é sólido quando sua
    projeção isométrica (e a do item girado 180° em torno do centro da caixa) cai num pixel opaco
    da art. Base [-a, 1 + a]² (a > 0 quando a art é mais larga que o tile). Topo justo: a altura da
    tiledata ou a menor que ainda alcança o pixel do topo no canto de trás da base; caixa alta
    demais vira "telhado" (o raio extrudado acima do objeto). params = (x0, y0, x1, y1, z0, z1)."""
    h, w = mask.shape
    v, u = np.nonzero(mask)
    a = max(0.0, (float(np.abs(np.r_[u, u + 1] - w / 2).max()) / 22 - 1) / 2)
    z_top = max(1.0, float(td_height), (h - 44 - float(v.min())) / 4 - 11 * a + 0.5)
    return SK_BILL, (-a, -a, 1 + a, 1 + a, 0.0, z_top), 1.0


def vertical_plane(mask):
    """Plano vertical que reproduz a art: x = c (modo 1) ou y = c (modo 2), escolhido pela
    inclinação da borda superior da silhueta (±1 na projeção). Fica em c ≥ 1.02, logo à frente
    da face visível (leste/sul) da parede do tile; arte simétrica ou que encosta no chão fica com SK_BILL (casco visual).
    params = (s0, z0, s1, z1, c, modo), s = coordenada ao longo do plano."""
    h, w = mask.shape
    cols = np.nonzero(mask.any(0))[0]
    top = np.argmax(mask[:, cols], axis=0)
    slope = np.polyfit(cols, top, 1)[0] if len(cols) > 1 else 0.0
    if abs(slope) < 0.4:
        return SK_BILL, (0, 0, 0, 0, 0, 0), 1.0
    v, u = np.nonzero(mask)
    v = np.r_[v, v + 1].astype(float)
    u = np.r_[u, u + 1].astype(float) - w / 2
    sg = -1.0 if slope < 0 else 1.0  # modo 1: s = ly = c − u/22 · modo 2: s = lx = c + u/22
    c = max(1.02, float(((sg * u + v - h + 44) / 44).max()))
    s = c + sg * u / 22
    z = (44 * c + sg * u + h - 44 - v) / 4
    if z.min() < 4:  # encosta no chão: móvel (cadeira...), não item pendurado
        return SK_BILL, (0, 0, 0, 0, 0, 0), 1.0
    return SK_FLAT, (float(s.min()), float(z.min()), float(s.max()), float(z.max()), c, 1.0 if sg < 0 else 2.0), 1.0


def build_hues(src, out):
    cols = src.hues()
    arr = to5551(np.array(cols))
    with open(os.path.join(out, 'hues.bin'), 'wb') as f:
        f.write(struct.pack('<4sHHI', b'HUE1', 32, len(cols), 0))
        f.write(arr.astype('<u2').tobytes())
    return len(cols)


GROUP_SLOT = 76          # texels por grupo em groups.bin: 3 de cabeçalho + 2 por peça
GROUP_MAX = 36


def roof_slopes(gx, gy, z, roof):
    """Inclinação real do telhado em cada tile (z por tile em x e y), pela diferença de z até os
    telhados vizinhos (diferença central; um lado só na borda). O plano ajustado à art tem a
    inclinação do desenho, não a do telhado montado: fileiras viravam degraus com buracos.
    -> (tem vizinho, gx, gy) com gx/gy quantizados em 1,5 z."""
    idx = np.nonzero(roof)[0]
    has = np.zeros(len(z), np.int64)
    qx = np.full(len(z), 4, np.int64)
    qy = np.full(len(z), 4, np.int64)
    if not len(idx):
        return has, qx, qy
    x, y, zz = gx[idx], gy[idx], z[idx]
    k = (x.astype(np.int64) * 8192 + y) * 512 + zz + 256
    order = np.argsort(k)
    ks = k[order]

    def near(dx, dy):
        # z do telhado vizinho mais próximo em z (|dz| <= 9); nan se não houver
        base = ((x + dx).astype(np.int64) * 8192 + (y + dy)) * 512 + 256
        best = np.full(len(idx), np.nan)
        for dz in sorted(range(-9, 10), key=abs):
            p = np.minimum(np.searchsorted(ks, base + zz + dz), len(ks) - 1)
            m = (ks[p] == base + zz + dz) & np.isnan(best)
            best[m] = zz[m] + dz
        return best

    def grad(a, b):
        g = np.where(np.isnan(a) | np.isnan(b), np.nan, (b - a) / 2)
        g = np.where(np.isnan(g) & ~np.isnan(b), b - zz, g)
        g = np.where(np.isnan(g) & ~np.isnan(a), zz - a, g)
        return g
    g1 = grad(near(-1, 0), near(1, 0))
    g2 = grad(near(0, -1), near(0, 1))
    ok = ~(np.isnan(g1) & np.isnan(g2))
    has[idx] = ok
    qx[idx] = np.clip(np.round(np.nan_to_num(g1) / 1.5) + 4, 0, 7)
    qy[idx] = np.clip(np.round(np.nan_to_num(g2) / 1.5) + 4, 0, 7)
    return has, qx, qy


def ceilings(gx, gy, z, sid, sflags):
    """Distância em z até o piso/telhado mais próximo acima de cada item no mesmo tile (0 = nada
    acima, máx. 63): o casco é cortado ali para itens não atravessarem o andar de cima."""
    f = sflags[sid]
    st = (f & np.uint64(SF_SURFACE | SF_ROOF | SF_BACKGROUND)) != 0
    cell = gx.astype(np.int64) * 8192 + gy
    k = np.sort(cell[st] * 1024 + z[st] + 512)
    q = cell * 1024 + z + 512 + 3
    p = np.minimum(np.searchsorted(k, q), max(len(k) - 1, 0))
    if not len(k):
        return np.zeros(len(sid), np.int64)
    hit = (k[p] >= q) & (k[p] // 1024 == cell)
    return np.where(hit, np.minimum(k[p] - (cell * 1024 + z + 512), 63), 0)


def merge_assemblies(gx, gy, z, sid, hue, tie, partial, ceil, sprites):
    """Junta peças de casco vizinhas (mesmo tile ou 8 vizinhos, z ±3, ids próximos — peças de um
    conjunto têm ids consecutivos) num objeto só (fonte, mesa grande, balcão): o casco simétrico
    passa a valer para o conjunto. Cada conjunto vira uma instância na peça âncora (a mais à frente
    na tela) que referencia um grupo = lista de peças (sprite, deslocamento) + caixa do conjunto.
    Devolve as instâncias, grp (−1 = item avulso) e a lista de grupos."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    none = np.full(len(sid), -1, np.int64)
    hull = np.array([sprites.get(s, (None,))[0] == SK_BILL for s in sid.tolist()], bool)
    idx = np.nonzero(hull)[0]
    if len(idx) < 2:
        return gx, gy, z, sid, hue, tie, partial, ceil, none, []
    x, y, zz, s = gx[idx], gy[idx], z[idx] + 128, sid[idx]

    def key(x, y, zz, b):
        return ((x * 8192 + y) * 512 + zz) * 4096 + b
    own = np.r_[key(x, y, zz, s // 64), key(x, y, zz, (s + 32) // 64 + 2048)]
    who = np.r_[np.arange(len(idx)), np.arange(len(idx))]
    order = np.argsort(own, kind='stable')
    own, who = own[order], who[order]
    same = own[1:] == own[:-1]                                # mesma chave: mesmo conjunto
    rows, cols = [who[1:][same]], [who[:-1][same]]
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in range(-3, 4):
                if dx == dy == dz == 0:
                    continue
                for b in (s // 64, (s + 32) // 64 + 2048):
                    k = key(x + dx, y + dy, zz + dz, b)
                    p = np.minimum(np.searchsorted(own, k), len(own) - 1)
                    m = own[p] == k
                    rows.append(np.nonzero(m)[0])
                    cols.append(who[p[m]])
    r, c = np.concatenate(rows), np.concatenate(cols)
    n = len(idx)
    _, comp = connected_components(coo_matrix((np.ones(len(r), np.int8), (r, c)), shape=(n, n)), directed=False)

    order = np.argsort(comp, kind='stable')
    bounds = np.r_[0, np.nonzero(np.diff(comp[order]))[0] + 1, n]
    grp = none.copy()
    drop = np.zeros(len(sid), bool)
    groups, cache = [], {}
    merged = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        mem = order[a:b]
        if len(mem) < 2 or len(mem) > GROUP_MAX:
            continue
        mx, my, mz, ms = x[mem], y[mem], zz[mem] - 128, s[mem]
        if mx.max() - mx.min() > 5 or my.max() - my.min() > 5:
            continue
        an = int(np.lexsort((mx, 22 * (mx + my) - 4 * mz))[-1])
        dx, dy, dz = mx - mx[an], my - my[an], mz - mz[an]
        ck = tuple(sorted(zip(dx.tolist(), dy.tolist(), dz.tolist(), ms.tolist())))
        if ck not in cache:
            # peças da frente para trás: na tela, a da frente cobre as outras
            parts = sorted(ck, key=lambda p: (p[0] + p[1], p[2], p[0]), reverse=True)
            lo, hi = np.full(3, 1e9), np.full(3, -1e9)
            for pdx, pdy, pdz, ps in parts:
                x0, y0, x1, y1, z0, z1 = sprites[ps][1]
                lo = np.minimum(lo, [pdx + x0, pdy + y0, pdz + z0])
                hi = np.maximum(hi, [pdx + x1, pdy + y1, pdz + z1])
            cache[ck] = len(groups)
            groups.append((parts, lo.tolist(), hi.tolist()))
        g = idx[mem]
        ga = g[an]
        drop[g] = True
        drop[ga] = False
        grp[ga] = cache[ck]
        cm = ceil[g][ceil[g] > 0]                            # teto do conjunto: o mais baixo das peças
        ceil[ga] = int((cm + z[g][ceil[g] > 0] - z[ga]).min()) if len(cm) else 0
        merged += len(mem)
    print(f'  conjuntos: {int((grp >= 0).sum())} instâncias de {merged} peças, {len(groups)} grupos')
    keep = ~drop
    return gx[keep], gy[keep], z[keep], sid[keep], hue[keep], tie[keep], partial[keep], ceil[keep], grp[keep], groups


def write_groups(path, groups, art_of):
    """GRP1: u32 magic, u32 n, u32 linhas | linhas × 1024 × u16[4], GROUP_SLOT texels por grupo:
    (nPeças, 0, 0, 0) (x0, y0, x1, y1)·64 (z0, z1, 0, 0)·64 e por peça, já pronto para o shader,
    (ax, ay, tw, th) no atlas e (u0, v0)·2, página: o pixel da peça para o ponto m da âncora é
    (22(mx − my), 22(mx + my) − 4mz) + (u0, v0). art_of(s) -> (página, ax, ay, tx, ty, tw, th, w, h)."""
    rows = -(-max(len(groups), 1) * GROUP_SLOT // 1024)
    t = np.zeros((rows * 1024, 4), np.uint16)
    q = lambda v: int(round(v * 64)) & 0xFFFF
    for g, (parts, lo, hi) in enumerate(groups):
        o = g * GROUP_SLOT
        t[o] = (len(parts), 0, 0, 0)
        t[o + 1] = (q(lo[0]), q(lo[1]), q(hi[0]), q(hi[1]))
        t[o + 2] = (q(lo[2]), q(hi[2]), 0, 0)
        for k, (dx, dy, dz, s) in enumerate(parts):
            pg, ax, ay, tx, ty, tw, th, w, h = art_of(s)
            u0 = -22 * (dx - dy) + w / 2 - tx
            v0 = -22 * (dx + dy) + 4 * dz + h - 44 - ty
            t[o + 3 + 2 * k] = (ax, ay, tw, th)
            t[o + 4 + 2 * k] = (int(round(u0 * 2)) & 0xFFFF, int(round(v0 * 2)) & 0xFFFF, pg, 0)
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'GRP1', len(groups), rows))
        f.write(t.astype('<u2').tobytes())


def build_statics(src, n, W, H, out_map):
    print('lendo statics...')
    sflags, sheight, snodraw = src.static_tiledata()
    gx, gy, z, sid, hue = src.read_statics(n, W, H)
    total_raw = len(sid)
    keep = (sid < len(sflags)) & ~np.isin(sid, list(NODRAW_STATIC))
    keep[keep] &= ~snodraw[sid[keep]]
    gx, gy, z, sid, hue = gx[keep], gy[keep], z[keep], sid[keep], hue[keep]
    key = (((gx * 8192 + gy) * 256 + (z + 128)) << 16) | sid
    _, first = np.unique(key, return_index=True)
    first.sort()
    gx, gy, z, sid, hue = gx[first], gy[first], z[first], sid[first], hue[first]
    print(f'  {total_raw} itens, {len(sid)} após NoDraw e duplicatas')

    # tie = ordem do item dentro da célula (ordem do arquivo), usado para desempatar profundidade
    cell = gy * W + gx
    order = np.argsort(cell, kind='stable')
    cs = cell[order]
    start = np.r_[0, np.nonzero(np.diff(cs))[0] + 1]
    rank = np.arange(len(cs)) - np.repeat(start, np.diff(np.r_[start, len(cs)]))
    tie = np.empty_like(rank)
    tie[order] = np.minimum(rank, 15)

    print('decodificando e classificando sprites...')
    sprites, imgs = {}, {}
    kinds_count = [0, 0, 0, 0]
    low_iou = 0
    for s in np.unique(sid).tolist():
        img = src.static_art(s)
        if img is None or not img.any():
            continue
        kind, params, q = classify_sprite(img, int(sflags[s]), int(sheight[s]))
        low_iou += kind == SK_SLOPE and q < 0.6
        sprites[s] = (kind, params)
        imgs[s] = img
        kinds_count[kind] += 1
    print(f'  {len(sprites)} sprites: box {kinds_count[0]}, flat {kinds_count[1]}, '
          f'slope {kinds_count[2]} (IoU<0.6: {low_iou}), casco {kinds_count[3]}')
    partial = ((sflags[sid] & np.uint64(SF_PARTIAL_HUE)) != 0).astype(np.int64)
    ceil = ceilings(gx, gy, z, sid, sflags)
    gx, gy, z, sid, hue, tie, partial, ceil, grp, groups = merge_assemblies(gx, gy, z, sid, hue, tie, partial, ceil, sprites)

    # atlas: recorta a bbox opaca e empacota em prateleiras
    trims = {}
    for s, img in imgs.items():
        m = img != 0
        ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
        trims[s] = (int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1))
    place, pages = {}, 1
    x = y = GUTTER
    row = 0
    for s in sorted(imgs, key=lambda s: -trims[s][3]):
        tw, th = trims[s][2], trims[s][3]
        if x + tw + GUTTER > ATLAS:
            x = GUTTER; y += row + GUTTER; row = 0
        if y + th + GUTTER > ATLAS:
            pages += 1; x = y = GUTTER; row = 0
        place[s] = (pages - 1, x, y)
        x += tw + GUTTER
        row = max(row, th)
    atlas = np.zeros((pages, ATLAS, ATLAS), np.uint16)
    index = {s: i for i, s in enumerate(sorted(imgs))}
    table = np.zeros((-(-len(index) // 256) * 256, 16), np.uint16)
    for s, i in index.items():
        p, ax, ay = place[s]
        tx, ty, tw, th = trims[s]
        img = imgs[s][ty:ty + th, tx:tx + tw]
        atlas[p, ay:ay + th, ax:ax + tw] = np.where(img != 0, (img << 1) | 1, 0)
        kind, params = sprites[s]
        h, w = imgs[s].shape
        table[i] = [ax, ay, tw, th, tx, ty, w, h, kind | (p << 8), 0] + [int(round(v * 64)) & 0xFFFF for v in params]
    with open(os.path.join(out_map, 'atlas.bin'), 'wb') as f:
        f.write(struct.pack('<4sHHI', b'ATL1', ATLAS, pages, 0))
        f.write(atlas.astype('<u2').tobytes())
    with open(os.path.join(out_map, 'sprites.bin'), 'wb') as f:
        f.write(struct.pack('<4sII', b'SPR1', len(index), len(table)))
        f.write(table.astype('<u2').tobytes())
    print(f'  atlas {pages} página(s) {ATLAS}², tabela {len(index)} sprites')
    write_groups(os.path.join(out_map, 'groups.bin'), groups,
                 lambda s: place[s] + trims[s] + imgs[s].shape[::-1])

    # chunks STA1: instâncias agrupadas por tipo de primitiva
    print('gravando chunks de statics...')
    ok = np.isin(sid, list(index))
    gx, gy, z, sid, hue, tie, partial, ceil, grp = gx[ok], gy[ok], z[ok], sid[ok], hue[ok], tie[ok], partial[ok], ceil[ok], grp[ok]
    top = max(int(sid.max()), max(index)) + 1  # peças só usadas em grupos também estão no índice
    lut = np.zeros(top, np.int64)
    kind_lut = np.zeros(top, np.int64)
    for s, i in index.items():
        lut[s] = i
        kind_lut[s] = sprites[s][0]
    kind = kind_lut[sid]
    hh = hue & 0x3FFF
    hh = np.where(hh > 3000, 0, hh)
    # bit 25: a instância é um conjunto e o campo sprite de B guarda o índice do grupo
    isg = (grp >= 0).astype(np.int64)
    # bits 26–31: teto (z até o andar de cima), só usado pelo casco
    ceil = np.clip(ceil, 0, 63)
    A = ((gx & 63) | ((gy & 63) << 6) | ((z + 128) << 12) | (tie << 20) | (partial << 24) | (isg << 25)
         | (ceil << 26))
    # telhados usam os bits 25–31 para a inclinação vinda dos vizinhos: tem:1 gx:3 gy:3 (×1,5 z, +4)
    has, qx, qy = roof_slopes(gx, gy, z, kind == SK_SLOPE)
    A = np.where(kind == SK_SLOPE, (A & 0x1FFFFFF) | (has << 25) | (qx << 26) | (qy << 29), A).astype('<u4')
    B = (np.where(isg == 1, grp, lut[sid]) | (hh << 16)).astype('<u4')
    cw, ch = -(-W // CHUNK), -(-H // CHUNK)
    cid = (gy // CHUNK) * cw + gx // CHUNK
    order = np.lexsort((kind, cid))
    cid, kind, A, B = cid[order], kind[order], A[order], B[order]
    bounds = np.r_[0, np.nonzero(np.diff(cid))[0] + 1, len(cid)]
    exists = np.zeros(cw * ch, np.uint8)
    os.makedirs(os.path.join(out_map, 'statics'), exist_ok=True)
    total = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        c = int(cid[a])
        cnt = np.bincount(kind[a:b], minlength=4).tolist()
        data = struct.pack('<4sHHIIIII', b'STA1', c % cw, c // cw, int(b - a), *cnt) + A[a:b].tobytes() + B[a:b].tobytes()
        with open(os.path.join(out_map, 'statics', f'{c % cw}_{c // cw}.bin'), 'wb') as f:
            f.write(data)
        exists[c] = 1
        total += len(data)
    print(f'  {len(bounds) - 1} chunks, {len(A)} instâncias, {total / 1e6:.1f} MB')
    return {
        'staticsChunks': base64.b64encode(np.packbits(exists, bitorder='little').tobytes()).decode(),
        'sprites': len(index), 'atlasPages': pages, 'groups': len(groups),
    }


# ---------------------------------------------------------------- fontes de dados

class ClassicSource:
    """Cliente Classic: mapN, staidx/statics, tiledata, texmaps, artLegacyMUL.uop, radarcol, hues.mul."""
    name = 'classic'
    tex_repeat = 1      # texmap por tile
    blend = 0.0         # bordas duras entre materiais, como no cliente 2D

    def __init__(self, client):
        self.client = client
        self.art = Uop(os.path.join(client, 'artLegacyMUL.uop'))

    def read_map(self, n, W, H):
        return read_map(self.client, n)

    def read_statics(self, n, W, H):
        return read_statics(self.client, n, W, H)

    def static_tiledata(self):
        return read_tiledata_static(self.client)

    def static_art(self, s):
        return decode_static_art(self.art.get(f'build/artlegacymul/{s + 0x4000:08d}.tga'))

    def hues(self):
        raw = open(os.path.join(self.client, 'hues.mul'), 'rb').read()
        cols = []
        for g in range(len(raw) // 708):
            for e in range(8):
                cols.append(np.frombuffer(raw, '<u2', 32, g * 708 + 4 + e * 88))
        return cols

    def radar(self, tid):
        radarcol = np.fromfile(os.path.join(self.client, 'radarcol.mul'), '<u2')
        t4 = tid[::4, ::4].astype(np.int64)
        c = radarcol[np.minimum(t4, len(radarcol) - 1)]
        return np.stack([(c >> 10) & 31, (c >> 5) & 31, c & 31], -1).astype(np.uint16) * 255 // 31

    def terrain_materials(self, tid):
        print('lendo tiledata, texidx...')
        lflags, ltex = read_tiledata_land(self.client)
        texidx = np.fromfile(os.path.join(self.client, 'texidx.mul'), '<i4').reshape(-1, 3)
        texmaps = open(os.path.join(self.client, 'texmaps.mul'), 'rb')
        land_to_mat = np.full(0x4000, 0xFFFF, np.uint16)
        mats = []                       # (kind, texArray, texLayer, artLayer, landId)
        l64, l128 = [], []
        tex_layer = {}                  # texId -> (array, layer)
        for lid in np.unique(tid).tolist():
            if lid in VOID_LAND:
                continue
            t = int(ltex[lid])
            if t and t < len(texidx) and texidx[t, 0] >= 0 and texidx[t, 1] > 0:
                if t not in tex_layer:
                    size = 128 if int(texidx[t, 1]) >= 32768 else 64
                    texmaps.seek(int(texidx[t, 0]))
                    px = np.frombuffer(texmaps.read(size * size * 2), '<u2').reshape(size, size)
                    arr = l128 if size == 128 else l64
                    tex_layer[t] = (1 if size == 128 else 0, len(arr))
                    arr.append(to5551(px))
                ta, tl = tex_layer[t]
                land_to_mat[lid] = len(mats)
                mats.append((KIND_TEX, ta, tl, 0xFFFF, lid))
                continue
            d = self.art.get(f'build/artlegacymul/{lid:08d}.tga')
            if d is None or len(d) < 2024:
                continue
            img, mask = decode_land_art(d)
            kind = KIND_WATER if int(lflags[lid]) & WET else KIND_ART
            land_to_mat[lid] = len(mats)
            mats.append((kind, 0, 0xFFFF, len(l64), lid))
            l64.append(to5551(art_to_square(img, mask)))
        return land_to_mat, mats, l64, l128


# Enhanced Client (UOSA). Contêineres UOP, nomes conhecidos:
#   facetN.uop          build/sectors/facet_NN/%08d.bin    setores 64x64 (terreno + statics)
#   tileart.uop         build/tileart/%08d.bin             flags (u64 em 65), largura/altura da art
#                                                          (i32 em 109/113), propriedades em 125
#   LegacyTexture.uop   build/tileartlegacy/%08d.dds       art clássica dos statics (DXT5, id = static)
#   Texture.uop         build/worldart/%08d.dds            texturas de terreno nas faixas 1M..5M
#   LegacyTerrain.uop   data/definitions/legacyterrain/%08d.legacyterrain   flags e texMap do land
#   Hues.uop            3000 BMP 256x2; a ordem da tabela é o índice do hue
#   facetNN.dds         minimapa 1 px por tile (cores de radar)
# Setor: u8 faceta, u16 id; 4096 células x-major (x fora, y dentro):
#   u8 z, u16 landId, u8 nDelim, nDelim × (u8 dir, [dir <= 7: u8 z, u32 landId vizinho]),
#   u8 nStatics, nStatics × (u32 id, u8 z, u32 hue)
ENH_FAMILIES = (1000000, 2000000, 3000000, 5000000, 4000000)
ENH_POOL_SCAN = 20000
TA_FLAGS, TA_W, TA_H, TA_PROPS, TA_PROP_HEIGHT = 65, 109, 113, 125, 3
ENH_NODRAW = {0x0001, 0x21BB, 0x21BC, 0x3F28, 0xA561, 0xA562, 0xA563, 0xA564} | set(range(0x2198, 0x21A4))
LEGACY_FLAGS = {'impassable': 0x40, 'wet': 0x80, 'surface': 0x200, 'wall': 0x10}
# cor lisa para land sem nenhuma textura no Enhanced e sem cor no minimapa
NAME_RGB = {'grass': (60, 110, 45), 'forest': (55, 90, 40), 'jungle': (50, 100, 40), 'dirt': (110, 85, 55),
            'sand': (200, 180, 120), 'rock': (110, 105, 100), 'snow': (235, 240, 245), 'cave': (90, 80, 70),
            'water': (30, 90, 150), 'lava': (200, 70, 20), 'acid': (110, 170, 40)}


def rgb555(r, g, b):
    return ((np.asarray(r).astype(np.uint16) >> 3) << 10) | ((np.asarray(g).astype(np.uint16) >> 3) << 5) \
        | (np.asarray(b).astype(np.uint16) >> 3)


class EnhancedSource:
    name = 'enhanced'
    tex_repeat = 4      # texturas do Enhanced cobrem vários tiles: uv contínuo em coordenadas do mundo
    blend = 0.35        # largura (fração do tile) da transição suave entre materiais vizinhos

    def __init__(self, client):
        import io, re
        from PIL import Image
        self._io, self._re, self._Image = io, re, Image
        self.client = client
        self._uops = {}
        self._facet = {}
        self._tex = {}
        self._targets = {}

    def uop(self, name):
        if name not in self._uops:
            self._uops[name] = Uop(os.path.join(self.client, name))
        return self._uops[name]

    def _raw(self, u, h):
        off, cl, flag = u.entries[h]
        u.f.seek(off)
        d = u.f.read(cl)
        return zlib.decompress(d) if flag == 1 else d

    def _dds(self, data):
        return np.asarray(self._Image.open(self._io.BytesIO(data)).convert('RGBA'))

    # ---- mapa e statics: os dois vêm dos mesmos setores, lidos uma vez
    def _read_facet(self, n, W, H):
        if n in self._facet:
            return self._facet[n]
        u = self.uop(f'facet{n}.uop')
        cw, ch = -(-W // CHUNK), -(-H // CHUNK)
        tid = np.full((ch * CHUNK, cw * CHUNK), 0x0244, np.uint16)
        z = np.zeros((ch * CHUNK, cw * CHUNK), np.int8)
        cell_st, st_st = struct.Struct('<BHB'), struct.Struct('<IBI')
        sx, sy, sz, sid, shue = [], [], [], [], []
        for cx in range(cw):
            for cy in range(ch):
                d = u.get(f'build/sectors/facet_{n:02d}/{cx * ch + cy:08d}.bin')
                if d is None:
                    continue
                land = np.empty(4096, np.uint16)
                zz = np.empty(4096, np.uint8)
                off = 3
                for c in range(4096):
                    zb, lid, nd = cell_st.unpack_from(d, off)
                    off += 4
                    land[c] = lid
                    zz[c] = zb
                    for _ in range(nd):
                        off += 6 if d[off] <= 7 else 1
                    ns = d[off]
                    off += 1
                    for _ in range(ns):
                        g, szb, hue = st_st.unpack_from(d, off)
                        off += 9
                        sx.append(cx * CHUNK + (c >> 6)); sy.append(cy * CHUNK + (c & 63))
                        sz.append(szb); sid.append(g); shue.append(hue & 0xFFFF)
                if off != len(d):
                    raise ValueError(f'setor {cx * ch + cy}: {off} de {len(d)} bytes lidos')
                tid[cy * CHUNK:(cy + 1) * CHUNK, cx * CHUNK:(cx + 1) * CHUNK] = land.reshape(64, 64).T
                z[cy * CHUNK:(cy + 1) * CHUNK, cx * CHUNK:(cx + 1) * CHUNK] = zz.view(np.int8).reshape(64, 64).T
        sz = np.array(sz, np.int64)
        st = (np.array(sx, np.int64), np.array(sy, np.int64), np.where(sz > 127, sz - 256, sz),
              np.array(sid, np.int64), np.array(shue, np.int64))
        print(f'  facet{n}.uop: {len(st[3])} statics')
        self._facet[n] = (tid[:H, :W], z[:H, :W], st)
        return self._facet[n]

    def read_map(self, n, W, H):
        self.W, self.H, self.n = W, H, n
        tid, z, _ = self._read_facet(n, W, H)
        return tid, z

    def read_statics(self, n, W, H):
        self.W, self.H, self.n = W, H, n
        return self._read_facet(n, W, H)[2]

    # ---- tileart
    def static_tiledata(self):
        u = self.uop('tileart.uop')
        flags = np.zeros(0x10000, np.uint64)
        height = np.zeros(0x10000, np.uint8)
        nodraw = np.zeros(0x10000, bool)
        nodraw[list(ENH_NODRAW)] = True
        for s in range(0x10000):
            d = u.get(f'build/tileart/{s:08d}.bin')
            if d is None or len(d) <= TA_PROPS:
                continue
            flags[s] = struct.unpack_from('<Q', d, TA_FLAGS)[0]
            p = TA_PROPS + 1
            for _ in range(d[TA_PROPS]):           # lista de (u8 chave, u32 valor); chave 3 = altura
                if p + 5 > len(d):
                    break
                if d[p] == TA_PROP_HEIGHT:
                    height[s] = min(struct.unpack_from('<I', d, p + 1)[0], 255)
                p += 5
        return flags, height, nodraw

    def static_art(self, s):
        """DDS da art clássica (com sobra até potência de 2) recortado ao tamanho do tileart -> u16 555."""
        meta = self.uop('tileart.uop').get(f'build/tileart/{s:08d}.bin')
        dds = self.uop('LegacyTexture.uop').get(f'build/tileartlegacy/{s:08d}.dds')
        if meta is None or dds is None or len(meta) < TA_H + 4:
            return None
        w, h = struct.unpack_from('<ii', meta, TA_W)
        if not (0 < w <= 1024 and 0 < h <= 1024):
            return None
        rgba = self._dds(dds)[:h, :w]
        img = np.zeros((h, w), np.uint16)
        px = rgb555(rgba[..., 0], rgba[..., 1], rgba[..., 2])
        img[:rgba.shape[0], :rgba.shape[1]] = np.where(rgba[..., 3] >= 128, np.maximum(px, 1), 0)
        return img

    def hues(self):
        u = self.uop('Hues.uop')
        cols = []
        for h in u.entries:                         # ordem da tabela = índice do hue
            d = self._raw(u, h)
            if d[:2] != b'BM':
                continue
            px = np.frombuffer(d, np.uint8, 2 * 256 * 4, struct.unpack_from('<I', d, 10)[0]).reshape(2, 256, 4)
            row = px[1, ::8][:32]                   # linha 1 = gradiente; 1 a cada 8 = as 32 cores clássicas
            cols.append(rgb555(row[:, 2], row[:, 1], row[:, 0]))
        return cols[:3000]

    # ---- terreno
    def _overview(self):
        if not hasattr(self, '_ov'):
            path = os.path.join(self.client, f'facet{self.n:02d}.dds')
            self._ov = None
            if os.path.exists(path):
                img = np.asarray(self._Image.open(path).convert('RGB'))
                if img.shape[0] >= self.H and img.shape[1] >= self.W:
                    self._ov = img[:self.H, :self.W]
        return self._ov

    def radar(self, tid):
        ov = self._overview()
        if ov is not None:
            return ov[::4, ::4].astype(np.uint16)
        t4 = tid[::4, ::4]
        rgb = np.zeros(t4.shape + (3,), np.uint16)
        for lid in np.unique(t4).tolist():
            rgb[t4 == lid] = self._targets.get(lid, (128, 128, 128))
        return rgb

    def _land_defs(self):
        u = self.uop('LegacyTerrain.uop')
        flags = np.zeros(0x4000, np.uint64)
        tex = np.zeros(0x4000, np.int64)
        names = [''] * 0x4000
        for h in u.entries:
            x = self._raw(u, h).decode('utf8', 'ignore')
            m = self._re.search(r'id="\s*(\d+)\s*"\s+name="([^"]*)"\s+texMap="\s*(\d+)\s*"', x)
            if not m or int(m.group(1)) >= 0x4000:
                continue
            i = int(m.group(1))
            tex[i], names[i] = int(m.group(3)), m.group(2).lower()
            for t in self._re.findall(r'<(\w+)\s*/>', x):
                flags[i] |= np.uint64(LEGACY_FLAGS.get(t, 0))
        return flags, tex, names

    def _texture(self, key):
        """worldart opaca e que não seja normal map -> RGB u8 128x128 (None se não existir ou não servir)."""
        if key not in self._tex:
            r = None
            d = self.uop('Texture.uop').get(f'build/worldart/{key:08d}.dds')
            if d is not None:
                rgba = self._dds(d)
                m = rgba[..., :3].reshape(-1, 3).mean(0)
                normal = m[2] > 200 and 100 < m[0] < 170 and 100 < m[1] < 170
                if rgba[..., 3].min() >= 250 and not normal:   # alpha de verdade = máscara de mistura
                    r = np.asarray(self._Image.fromarray(np.ascontiguousarray(rgba[..., :3]))
                                   .resize((128, 128), self._Image.LANCZOS))
            self._tex[key] = r
        return self._tex[key]

    def _own(self, t):
        out = []
        for b in ENH_FAMILIES:
            img = self._texture(b + t)
            if img is not None:
                out.append((b + t, img))
        return out

    def _pool(self):
        if not hasattr(self, '_pool_list'):
            u = self.uop('Texture.uop')
            self._pool_list = []
            for b in ENH_FAMILIES:
                for i in range(ENH_POOL_SCAN):
                    if hashlittle2(f'build/worldart/{b + i:08d}.dds'.encode()) in u.entries:
                        img = self._texture(b + i)
                        if img is not None:
                            self._pool_list.append((b + i, img))
            self._pool_mean = np.array([t.reshape(-1, 3).mean(0) for _, t in self._pool_list])
            self._pool_odd = np.array([self._oddness(t) for _, t in self._pool_list])
        return self._pool_list

    @staticmethod
    def _oddness(t):
        """Fração de pixels de cor muito diferente da média (veios roxos, flores, cristais): a cor média
        bate com a do minimapa, mas a textura não é o chão comum que o land representa."""
        px = t.reshape(-1, 3).astype(float)
        hue = px - px.mean(1, keepdims=True)                  # cromaticidade sem o brilho
        d = np.linalg.norm(hue - hue.mean(0), axis=1)
        return float((d > 25).mean())

    def terrain_materials(self, tid):
        """A ligação land -> textura do Enhanced (TerrainDefinition) não é conhecida e os ids das faixas
        1M..5M não seguem o texMap de forma confiável. Cada land recebe, entre as texturas do próprio
        texMap, as dos lands de mesmo nome e (com penalidade) todas as outras, a de cor média mais
        próxima da cor do land no minimapa facetNN.dds."""
        print('lendo LegacyTerrain, texturas, minimapa...')
        lflags, ltex, names = self._land_defs()
        st = self._read_facet(self.n, self.W, self.H)[2]
        ov = self._overview()
        targets = {}
        if ov is not None:
            free = np.ones(tid.shape, bool)
            free[st[1], st[0]] = False                      # tiles com statics tingem o minimapa
            ids, px = tid[free], ov[free]
            order = np.argsort(ids, kind='stable')
            ids, px = ids[order], px[order]
            bounds = np.r_[0, np.nonzero(np.diff(ids))[0] + 1, len(ids)]
            for a, b in zip(bounds[:-1], bounds[1:]):
                targets[int(ids[a])] = np.median(px[a:b], 0)
        self._targets = targets
        by_name = {}
        for i in range(0x4000):
            if names[i] and ltex[i]:
                by_name.setdefault(names[i], []).append(i)

        def pick(lid):
            tg = targets.get(lid)
            own = self._own(int(ltex[lid])) if ltex[lid] else []
            if tg is None:
                return own[0] if own else None
            cand = [(1.0, k, t) for k, t in own]
            for o in sorted(by_name.get(names[lid], []), key=lambda c: abs(c - lid))[:24]:
                cand += [(1.3, k, t) for k, t in self._own(int(ltex[o]))]
            sc = [p * float(np.linalg.norm(t.reshape(-1, 3).mean(0) - tg)) * (1 + 30 * self._oddness(t)) for p, k, t in cand]
            pool = self._pool()
            if pool:
                d = 1.7 * np.linalg.norm(self._pool_mean - tg, axis=1) * (1 + 30 * self._pool_odd)
                j = int(np.argmin(d))
                cand.append((1.7,) + pool[j])
                sc.append(float(d[j]))
            if not cand:
                return None
            _, k, t = cand[int(np.argmin(sc))]
            return k, t

        def flat(lid):
            c = targets.get(lid, NAME_RGB.get(names[lid], (128, 128, 128)))
            return np.full((64, 64), rgb555(*[int(v) for v in c]), np.uint16)

        land_to_mat = np.full(0x4000, 0xFFFF, np.uint16)
        mats, l64, l128 = [], [], []
        tex_layer = {}
        for lid in np.unique(tid).tolist():
            if lid in VOID_LAND or lid >= 0x4000:
                continue
            land_to_mat[lid] = len(mats)
            if int(lflags[lid]) & WET and ltex[lid] == 0:   # água: camada 64 animada no shader
                f = pick(lid)
                if f is not None:
                    t = np.asarray(self._Image.fromarray(f[1]).resize((64, 64), self._Image.LANCZOS))
                    img = rgb555(t[..., 0], t[..., 1], t[..., 2])
                else:
                    img = flat(lid)
                mats.append((KIND_WATER, 0, 0xFFFF, len(l64), lid))
                l64.append(to5551(img))
                continue
            f = pick(lid)
            if f is not None:
                k, t = f
                if k not in tex_layer:
                    tex_layer[k] = len(l128)
                    l128.append(to5551(rgb555(t[..., 0], t[..., 1], t[..., 2])))
                mats.append((KIND_TEX, 1, tex_layer[k], 0xFFFF, lid))
            else:
                mats.append((KIND_ART, 0, 0xFFFF, len(l64), lid))
                l64.append(to5551(flat(lid)))
        return land_to_mat, mats, l64, l128


# ---------------------------------------------------------------- terreno

def build_terrain(src, n, W, H, out_map):
    print('lendo mapa...')
    tid, z = src.read_map(n, W, H)
    os.makedirs(os.path.join(out_map, 'terrain'), exist_ok=True)
    land_to_mat, mats, l64, l128 = src.terrain_materials(tid)
    print(f'  materiais {len(mats)}, land64 {len(l64)} camadas, land128 {len(l128)} camadas')

    with open(os.path.join(out_map, 'materials.bin'), 'wb') as f:
        f.write(struct.pack('<4sI', b'MAT1', len(mats)))
        for m in mats:
            f.write(struct.pack('<BBHHH', *m))
    write_tex(os.path.join(out_map, 'land64.bin'), 64, l64)
    write_tex(os.path.join(out_map, 'land128.bin'), 128, l128)

    # ---- chunks de terreno
    print('gravando chunks de terreno...')
    # completa até múltiplo de 64 (map4 tem 1448x1448): sobra vira void
    cw, ch = -(-W // CHUNK), -(-H // CHUNK)
    mat = np.pad(land_to_mat[tid], ((0, ch * CHUNK - H), (0, cw * CHUNK - W)), constant_values=0xFFFF)
    # alturas com borda de 1 tile em todos os lados (tiles -1..64): a superfície suave
    # interpola entre centros de tiles e precisa dos 8 vizinhos de cada tile
    zp = np.pad(z, ((1, ch * CHUNK - H + 1), (1, cw * CHUNK - W + 1)), mode='edge')
    exists = np.zeros(cw * ch, np.uint8)
    zmeta = np.zeros(cw * ch * 2, np.int8)
    written = total = 0
    for cy in range(ch):
        for cx in range(cw):
            m = mat[cy * CHUNK:(cy + 1) * CHUNK, cx * CHUNK:(cx + 1) * CHUNK]
            void = m == 0xFFFF
            if void.all():
                continue
            hgt = zp[cy * CHUNK:cy * CHUNK + CHUNK + 2, cx * CHUNK:cx * CHUNK + CHUNK + 2]
            zmin, zmax = int(hgt.min()), int(hgt.max())
            flags = (2 if zmin == zmax else 0) | (4 if void.any() else 0) | 8  # bit3: grade 66x66
            hdr = struct.pack('<4sHHbbHI', b'TRN1', cx, cy, zmin, zmax, flags, 0)
            hbytes = struct.pack('<b3x', zmin) if zmin == zmax else hgt.astype(np.int8).tobytes()
            data = hdr + m.astype('<u2').tobytes() + hbytes
            with open(os.path.join(out_map, 'terrain', f'{cx}_{cy}.bin'), 'wb') as f:
                f.write(data)
            i = cy * cw + cx
            exists[i] = 1
            zmeta[2 * i], zmeta[2 * i + 1] = zmin, zmax
            written += 1
            total += len(data)
    print(f'  {written} chunks, {total / 1e6:.1f} MB')

    # ---- radar (1 px / 4 tiles)
    rgb = src.radar(tid)
    rgb[np.isin(tid[::4, ::4], list(VOID_LAND))] = 0
    write_png(os.path.join(out_map, 'radar.png'), rgb.astype(np.uint8))

    return {
        'map': n, 'width': W, 'height': H, 'chunk': CHUNK,
        'chunksX': cw, 'chunksY': ch, 'zScale': 4 / (22 * 2 ** 0.5),
        'chunks': base64.b64encode(np.packbits(exists, bitorder='little').tobytes()).decode(),
        'chunkZ': base64.b64encode(zmeta.tobytes()).decode(),
        'materials': len(mats), 'land64': len(l64), 'land128': len(l128),
        'radarScale': 4, 'start': [1495, 1629] if n in (0, 1) else [W // 2, H // 2],
        'source': src.name, 'texRepeat': src.tex_repeat, 'blend': src.blend,
    }


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', choices=('enhanced', 'classic'), default='enhanced')
    ap.add_argument('--client', default=None,
                    help='pasta do cliente (padrão: "Ultima Online Enhanced" ou a pasta do Classic, conforme --source)')
    ap.add_argument('--map', type=int, default=0)
    ap.add_argument('--out', default=os.path.normpath(os.path.join(HERE, '..', 'data')))
    ap.add_argument('--only', choices=('all', 'terrain', 'statics'), default='all')
    a = ap.parse_args()
    W, H = MAPS[a.map]
    out_map = os.path.join(a.out, f'map{a.map}')
    os.makedirs(out_map, exist_ok=True)
    if a.source == 'enhanced':
        src = EnhancedSource(a.client or os.path.normpath(os.path.join(HERE, '..', '..', '..', 'Ultima Online Enhanced')))
    else:
        src = ClassicSource(a.client or os.path.normpath(os.path.join(HERE, '..', '..')))
    print(f'fonte: {src.name} ({src.client})')

    mpath = os.path.join(out_map, 'manifest.json')
    manifest = json.load(open(mpath)) if os.path.exists(mpath) else {}
    if a.only in ('all', 'terrain'):
        manifest.update(build_terrain(src, a.map, W, H, out_map))
    elif 'chunks' not in manifest:
        sys.exit('rode o terreno primeiro (--only terrain ou all)')
    if a.only in ('all', 'statics'):
        manifest['hues'] = build_hues(src, a.out)
        manifest.update(build_statics(src, a.map, W, H, out_map))
    manifest['build'] = int(time.time())  # o viewer usa como ?v= nos .bin (cache)
    with open(mpath, 'w') as f:
        json.dump(manifest, f)
    # índice dos mapas convertidos, lido pelo seletor do viewer
    done = [i for i in MAPS if os.path.exists(os.path.join(a.out, f'map{i}', 'manifest.json'))]
    with open(os.path.join(a.out, 'maps.json'), 'w') as f:
        json.dump(done, f)
    print('ok:', out_map)


if __name__ == '__main__':
    main()


