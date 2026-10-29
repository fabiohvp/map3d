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
import argparse, base64, json, math, os, re, struct, sys, time, zlib
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MAPS = {0: (7168, 4096), 1: (7168, 4096), 2: (2304, 1600), 3: (2560, 2048), 4: (1448, 1448), 5: (1280, 4096)}
CHUNK = 64
VOID_LAND = {0x0002, 0x01DB, 0x0244} | set(range(0x01AE, 0x01B6))
HOLE = 0xFFFE            # material de void com static embaixo: o viewer não desenha
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
SK_MESH, SK_SLOPE = 0, 2
ATLAS = 4096
GUTTER = 2
TILE_FLAGS = ('Background', 'Weapon', 'Transparent', 'Translucent', 'Wall', 'Damaging', 'Impassable', 'Wet',
              'Unknown1', 'Surface', 'Bridge', 'Generic', 'Window', 'NoShoot', 'ArticleA', 'ArticleAn', 'Internal',
              'Foliage', 'PartialHue', 'NoHouse', 'Map', 'Container', 'Wearable', 'LightSource', 'Animation',
              'HoverOver', 'NoDiagonal', 'Armor', 'Roof', 'Door', 'StairBack', 'StairRight')


def read_tiledata_static(client):
    td = open(os.path.join(client, 'tiledata.mul'), 'rb').read()
    off = 512 * (4 + 32 * 30)
    flags, height, names = [], [], []
    while off + 4 <= len(td):
        off += 4
        for _ in range(32):
            if off + 41 > len(td):
                break
            flags.append(struct.unpack_from('<Q', td, off)[0])
            height.append(td[off + 20])
            names.append(td[off + 21:off + 41].split(b'\0')[0].decode('latin-1').strip())
            off += 41
    nodraw = np.array([n.lower() == 'nodraw' for n in names], bool)
    return np.array(flags, np.uint64), np.array(height, np.uint8), nodraw, names


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


# ---- malhas reconstruídas da art (motores do assets3d do uo3d2)
# A art do UO é uma projeção oblíqua: o ponto (lx, ly, lz) local ao tile (lx, ly em tiles, canto norte
# na origem; lz em unidades de z) cai no pixel
#     u = 22(lx − ly) + w/2      v = 22(lx + ly) − 4·lz + h − 44
# Cada sprite vira uma malha neste referencial; a textura de cada vértice é o pixel do sprite na câmera
# do UO (faces que a câmera não vê reusam o pixel da face oposta). Motores:
#   box     caixa medida do hexágono da silhueta (pegada a × b e altura saem da art, nada é chutado)
#   hull    "almofada" fechada inflada da silhueta, com a profundidade 2:1 da art de objetos redondos
#   flat    silhueta deitada no chão (tapetes, decalques, pisos que não fecham como caixa)
#   card    casco fino (efeitos, armas, quadros e sprites esparsos)
HT = 22.0
SQ2 = 2 ** 0.5
PXP = HT * SQ2           # px por tile no eixo horizontal da tela
PZ = 4.0                 # px por unidade de z
ART_DEPTH = HT / 2       # px por unidade de lx + ly na art de objetos redondos (2:1; o chão usa HT)
METRIC_Z = 0.1           # 1 z = 0,1 tile: referencial "métrico" das normais
MIN_DIM = 0.08
HULL_CELLS = 32          # células da grade do casco (o assets3d usa 420; aqui são milhões de instâncias)
CARD_CELLS = 16          # casco fino: o recorte da art (alpha) já dá a silhueta
FLAT_CELLS = 12
FLAT_THICK = 0.4         # espessura do slab deitado, em z
DECAL_THICK = 1.0        # slab de entulho/tapete sobre o piso: acima da laje do piso no mesmo z
MESH_CLASSES = (6, 36, 96, 192, 384, 768, 1536, 3072)   # vértices por instância de cada lote; 0 = telhado
MESH_MAX = MESH_CLASSES[-1]


def _load_taxonomy():
    tx = json.load(open(os.path.join(HERE, 'taxonomy.json'), encoding='utf-8'))
    tx['_names'] = [(c, s, re.compile(p, re.I)) for c, s, p in tx['name_rules']]
    return tx


def categorize(tx, name, flags, area, fill):
    """Categoria/subcategoria do assets3d: regras de nome, depois de flags; confiança baixa = unknown."""
    fl = {TILE_FLAGS[b] for b in range(32) if flags >> b & 1}
    cat = sub = None
    conf = 0.0
    for c, s, rx in tx['_names']:
        if name and rx.search(name):
            cat, sub, conf = c, s, 0.88
            break
    for c, s, need, fc in tx['flag_rules']:
        if set(need) <= fl:
            if cat is None:
                cat, sub, conf = c, s, fc
            elif (c, s) != (cat, sub) and c != cat:
                # o nome vence, a não ser que as flags sejam estruturais (telhado/porta/janela)
                if s in ('roof', 'door', 'window') and fc >= 0.8:
                    cat, sub, conf = c, s, fc
            break
    if cat is None or conf < tx['min_confidence']:
        cat, sub = 'unknown', 'unknown'
    if cat != 'architecture' and ({'Surface', 'Background'} <= fl or {'Surface', 'Bridge'} <= fl):
        cat, sub = 'architecture', 'floor'  # piso pelas flags (o nome "wooden planks" casava com recurso)
    sr = tx['sparse_rule']
    if cat in sr['categories'] and (area < sr['max_area'] or fill < sr['max_fill']):
        cat, sub = 'effect', 'decal'        # faíscas, decalques, entulho: sem volume sólido
    return cat, sub


def floor_iou(mask):
    """IoU entre a silhueta e o losango de um tile de chão (44 × 44 na base da art)."""
    h, w = mask.shape
    vv, uu = np.mgrid[0:h, 0:w] + 0.5
    tile = np.abs(uu - w / 2) / HT + np.abs(vv - (h - HT)) / HT <= 1
    union = (tile | mask).sum()
    return float((tile & mask).sum()) / float(union) if union else 0.0


def archetype(tx, cat, sub):
    if cat == 'terrain':
        return 'box'
    if f'{cat}/{sub}' == 'decoration/rug':
        return 'flat'
    m = tx['archetype_by_subcategory']
    a = m.get(f'{cat}/{sub}') or m.get(f'{cat}/*') or m['*']
    return {'box_iso': 'box', 'visual_hull': 'hull', 'billboard': 'card', 'terrain_tile': 'box'}[a]


def _bbox(mask):
    ys, xs = np.nonzero(mask.any(1))[0], np.nonzero(mask.any(0))[0]
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def _proj(P, w, h):
    return np.stack([HT * (P[:, 0] - P[:, 1]) + w / 2, HT * (P[:, 0] + P[:, 1]) - PZ * P[:, 2] + h - 44], 1)


def _metric(P):
    return P * np.array([1.0, 1.0, METRIC_Z])


def _face_normals(P, tris):
    M = _metric(P)
    return np.cross(M[tris[:, 1]] - M[tris[:, 0]], M[tris[:, 2]] - M[tris[:, 0]])


def _expand(P, px, tris, nrm=None):
    """Malha indexada -> lista de triângulos (pos, pixel, normal unitária). Sem nrm: normal da face."""
    if nrm is None:
        fn = _face_normals(P, tris)
        n = np.repeat(fn, 3, 0)
    else:
        n = nrm[tris.ravel()]
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return P[tris.ravel()], px[tris.ravel()], n


def fit_box(mask):
    """Caixa [x0, x1] × [y0, y1] × [0, H] cuja projeção é a silhueta: largura = 22(a + b), o vértice de
    baixo fica 11(a − b) à direita do centro e a altura é o que sobra acima da pegada."""
    h, w = mask.shape
    bx0, by0, bx1, by1 = _bbox(mask)
    s = (bx1 - bx0) / HT
    cols = np.nonzero(mask[max(by1 - 3, by0):by1, bx0:bx1].any(0))[0]
    d = (cols.mean() + 0.5 - (bx1 - bx0) / 2) / (HT / 2) if len(cols) else 0.0
    lim = max(s - 2 * MIN_DIM, 0.0)
    d = float(np.clip(d, -lim, lim))
    a, b = max((s + d) / 2, MIN_DIM), max((s - d) / 2, MIN_DIM)
    sum1 = (by1 - h + 44) / HT                  # x1 + y1: vértice de baixo na última linha
    dif1 = (bx0 + HT * a - w / 2) / HT          # x1 − y1
    x1, y1 = (sum1 + dif1) / 2, (sum1 - dif1) / 2
    x0, y0 = x1 - a, y1 - b
    H = max((HT * (x0 + y0) + h - 44 - by0) / PZ, 0.2)
    return x0, y0, x1, y1, H


def fit_top_box(mask, H=None):
    """Caixa de móvel com tampo (mesa, balcão, banco): a pegada sai do losango do tampo (vértices de
    cima, esquerda e direita da silhueta) e a caixa desce até o chão; o recorte por alpha deixa só as
    pernas. Peças do meio da mesa são só o tampo flutuando, sem pixel no chão, então fit_box as
    deitava no piso. H = altura do tampo (tiledata); sem H, o tampo fica centrado no tile."""
    h, w = mask.shape
    bx0, by0, bx1, by1 = _bbox(mask)
    rows = np.arange(by0, by1)
    rows = rows[mask[rows].any(1)]
    L = np.array([np.nonzero(mask[v])[0][0] for v in rows])
    R = np.array([np.nonzero(mask[v])[0][-1] + 1 for v in rows])

    def vertex(E, sgn):
        # desce pelas bordas de cima do tampo (1 px por linha) até pararem de abrir: pés e pernas
        # que saem para o lado abaixo do tampo não contam
        k = 0
        while k + 4 < len(E) and sgn * (E[k + 4] - E[k]) >= 3:
            k += 1
        while k + 1 < len(E) and sgn * (E[k + 1] - E[k]) >= 1:
            k += 1
        return k

    kl, kr = vertex(L, -1), vertex(R, 1)
    lu, ru = float(L[kl]), float(R[kr])
    a, b = (rows[kr] + 0.5 - by0) / HT, (rows[kl] + 0.5 - by0) / HT   # vértices direito (x1, y0) e esquerdo (x0, y1)
    s = (ru - lu) / HT
    a, b = (s * a / (a + b), s * b / (a + b)) if a + b > 0 else (s / 2, s / 2)
    a, b = max(a, MIN_DIM), max(b, MIN_DIM)
    bx0 = lu
    if H is None:
        sum0 = 1 - (a + b) / 2
        H = (HT * sum0 + h - 44 - by0) / PZ
    else:
        sum0 = (by0 - h + 44 + PZ * H) / HT                  # x0 + y0 pelo vértice de cima
    dif0 = (bx0 - w / 2) / HT + b                            # x0 − y0 pelo vértice esquerdo
    x0, y0 = (sum0 + dif0) / 2, (sum0 - dif0) / 2
    return x0, y0, x0 + a, y0 + b, max(float(H), 0.2)


def _box_corners(x0, y0, x1, y1, H):
    return np.array([(x, y, z) for z in (0.0, H) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])


def _convex(pts):
    pts = sorted(set(map(tuple, np.round(pts, 6))))
    cross = lambda o, a, b: (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cross(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    return lo[:-1] + hi[:-1]


def _hexagon_cover(shape, boxes):
    """Pixels cobertos pela projeção das caixas (cada uma = fecho convexo dos seus 8 cantos)."""
    h, w = shape
    vv, uu = np.mgrid[0:h, 0:w] + 0.5
    cover = np.zeros((h, w), bool)
    for box in boxes:
        poly = _convex(_proj(_box_corners(*box), w, h))
        inside = np.ones((h, w), bool)
        for i in range(len(poly)):
            (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
            inside &= (bx - ax) * (vv - ay) - (by - ay) * (uu - ax) >= -1e-9
        cover |= inside
    return cover


def hexagon_iou(mask, boxes, of_mask=False):
    """IoU entre a silhueta e a projeção das caixas (cada uma = fecho convexo dos seus 8 cantos).
    of_mask: fração da silhueta coberta (o recorte por alpha apaga o que sobra da caixa)."""
    cover = _hexagon_cover(mask.shape, boxes)
    inter = (cover & mask).sum()
    union = mask.sum() if of_mask else (cover | mask).sum()
    return float(inter) / float(union) if union else 0.0


WALL_LIKE = {'architecture/wall', 'architecture/window', 'architecture/door', 'architecture/fence', 'architecture/arch',
             'architecture/column', 'architecture/bridge'}
WALL_T = 0.16            # espessura das paredes do UO (as retas medem 0,14–0,16 tile)


def fit_boxes(mask, corners):
    """Caixa medida ou, para peças de canto, um L de duas paredes finas nas bordas da caixa:
    sul + leste (V, encontro na frente) ou norte + oeste (Λ, encontro atrás). -> (caixas, IoU)."""
    x0, y0, x1, y1, H = box = fit_box(mask)
    cands = [[box]]
    if corners and x1 - x0 > 2.5 * WALL_T and y1 - y0 > 2.5 * WALL_T:
        t = WALL_T
        h = mask.shape[0]
        top = np.nonzero(mask.any(1))[0][0]
        for pair in (((x0, y1 - t, x1, y1), (x1 - t, y0, x1, y1 - t)), ((x0, y0, x1, y0 + t), (x0, y0 + t, x0 + t, y1))):
            # altura: o canto de trás mais alto das duas paredes encosta no topo da art
            hv = max((HT * min(b[0] + b[1] for b in pair) + h - 44 - top) / PZ, 0.2)
            cands.append([b + (hv,) for b in pair])
    # o L só vence a caixa com folga
    scored = [(hexagon_iou(mask, c), c) for c in cands]
    best = max(scored, key=lambda k: k[0] - 0.03 * (len(k[1]) > 1))
    return best[1], best[0]


def box_mesh(mask, boxes):
    """6 faces por caixa; oeste, norte e base não aparecem na art e reusam o pixel da face oposta."""
    h, w = mask.shape
    meshes = [_box_mesh(w, h, *b) for b in boxes]
    return tuple(np.concatenate([m[k] for m in meshes]) for k in range(3))


def _box_mesh(w, h, x0, y0, x1, y1, H):
    faces = (  # (quad, coordenada fixa que o pixel copia da face oposta)
        (((x0, y0, H), (x1, y0, H), (x1, y1, H), (x0, y1, H)), None),
        (((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)), (2, H)),
        (((x1, y0, 0), (x1, y1, 0), (x1, y1, H), (x1, y0, H)), None),
        (((x0, y0, 0), (x0, y1, 0), (x0, y1, H), (x0, y0, H)), (0, x1)),
        (((x0, y1, 0), (x1, y1, 0), (x1, y1, H), (x0, y1, H)), None),
        (((x0, y0, 0), (x1, y0, 0), (x1, y0, H), (x0, y0, H)), (1, y1)),
    )
    P, S = [], []
    for quad, mirror in faces:
        q = np.array(quad, float)
        s = q.copy()
        if mirror:
            s[:, mirror[0]] = mirror[1]
        P.append(q)
        S.append(s)
    P, S = np.concatenate(P), np.concatenate(S)
    tris = np.array([(k, k + 1, k + 2) for k in range(0, 24, 4)] + [(k, k + 2, k + 3) for k in range(0, 24, 4)])
    return _expand(P, _proj(S, w, h), tris)


def _cells(mask, c, fill=0.3):
    h, w = mask.shape
    R, C = -(-h // c), -(-w // c)
    pad = np.zeros((R * c, C * c), np.float32)
    pad[:h, :w] = mask
    return pad.reshape(R, c, C, c).mean(axis=(1, 3)) >= fill


def _grid(cin):
    R, C = cin.shape
    exists = np.zeros((R + 1, C + 1), bool)
    for dy in (0, 1):
        for dx in (0, 1):
            exists[dy:dy + R, dx:dx + C] |= cin
    ii, jj = np.nonzero(exists)
    vid = -np.ones(exists.shape, np.int64)
    vid[ii, jj] = np.arange(len(ii))
    return ii, jj, vid


def _compact(P, px, tris, min_area=1e-10):
    ok = ~((tris[:, 0] == tris[:, 1]) | (tris[:, 1] == tris[:, 2]) | (tris[:, 0] == tris[:, 2]))
    tris = tris[ok]
    tris = tris[np.linalg.norm(_face_normals(P, tris), axis=1) > min_area]
    used = np.unique(tris)
    remap = -np.ones(len(P), np.int64)
    remap[used] = np.arange(len(used))
    return P[used], px[used], remap[tris]


def flat_mesh(mask, t=FLAT_THICK, target=FLAT_CELLS, plinth=False):
    """Silhueta desprojetada no chão: pele de cima (na altura t), base e paredes laterais na borda.
    plinth: a pegada é a do chão (z = 0) também em cima: arte pintada no losango do tile, erguida."""
    h, w = mask.shape
    x0, y0, x1, y1 = _bbox(mask)
    m = mask[y0:y1, x0:x1]
    c = max(1, int(math.ceil(math.sqrt(max(int(m.sum()), 1) / target))))
    cin = _cells(m, c, 1e-6)   # cobre a silhueta inteira; o alpha recorta a sobra
    R, C = cin.shape
    ii, jj, vid = _grid(cin)
    sx = np.minimum(x0 + jj * c, x1).astype(float)
    sy = (y0 + np.minimum(ii * c, y1 - y0)).astype(float)

    def ground(z):
        d = (sx - w / 2) / HT                       # lx − ly
        s = (sy - (h - 44) + PZ * (0.0 if plinth else z)) / HT   # lx + ly
        return np.stack([(s + d) / 2, (s - d) / 2, np.full(len(sx), z)], 1)

    n = len(sx)
    P = np.concatenate([ground(t), ground(0.0)])
    px = np.concatenate([np.stack([sx, sy], 1)] * 2)
    tris = []
    for i in range(R):
        for j in range(C):
            if not cin[i, j]:
                continue
            a, b, d, e = vid[i, j], vid[i, j + 1], vid[i + 1, j + 1], vid[i + 1, j]
            tris += [(a, e, d), (a, d, b), (n + a, n + b, n + d), (n + a, n + d, n + e)]
            for p, q, (ni, nj) in ((a, b, (i - 1, j)), (b, d, (i, j + 1)), (d, e, (i + 1, j)), (e, a, (i, j - 1))):
                if not (0 <= ni < R and 0 <= nj < C and cin[ni, nj]):
                    tris += [(p, q, n + q), (p, n + q, n + p)]
    P, px, tris = _compact(P, px, np.array(tris, np.int64))
    return _expand(P, px, tris)


def _chamfer(zero):
    """Distância (em células) de cada vértice ao zero mais próximo; chamfer 1 / √2 em duas passadas."""
    H, W = zero.shape
    d = np.where(zero, 0.0, 1e9)
    for i in range(H):
        for j in range(W):
            if d[i, j] == 0:
                continue
            v = d[i, j]
            if i > 0:
                v = min(v, d[i - 1, j] + 1)
                if j > 0:
                    v = min(v, d[i - 1, j - 1] + SQ2)
                if j < W - 1:
                    v = min(v, d[i - 1, j + 1] + SQ2)
            if j > 0:
                v = min(v, d[i, j - 1] + 1)
            d[i, j] = v
    for i in range(H - 1, -1, -1):
        for j in range(W - 1, -1, -1):
            v = d[i, j]
            if i < H - 1:
                v = min(v, d[i + 1, j] + 1)
                if j > 0:
                    v = min(v, d[i + 1, j - 1] + SQ2)
                if j < W - 1:
                    v = min(v, d[i + 1, j + 1] + SQ2)
            if j < W - 1:
                v = min(v, d[i, j + 1] + 1)
            d[i, j] = v
    return d


def _local_radius(d, window):
    """Raio do maior disco inscrito que cobre cada vértice (máx. de d(u) com |u − v| <= d(u))."""
    H, W = d.shape
    r = d.copy()
    for dy in range(-window, window + 1):
        for dx in range(-window, window + 1):
            dist = math.hypot(dy, dx)
            if dist == 0 or dist > window:
                continue
            vs0, vs1 = max(0, -dy), H - max(0, dy)
            us0, us1 = max(0, -dx), W - max(0, dx)
            if vs1 <= vs0 or us1 <= us0:
                continue
            sh = np.zeros_like(d)
            sh[vs0:vs1, us0:us1] = d[vs0 + dy:vs1 + dy, us0 + dx:us1 + dx]
            r = np.maximum(r, np.where(sh >= dist, sh, 0.0))
    return r


def _smooth_normals(P, tris):
    fn = _face_normals(P, tris)
    acc = np.zeros_like(P)
    for k in range(3):
        np.add.at(acc, tris[:, k], fn)
    ln = np.linalg.norm(acc, axis=1)
    bad = ln < 1e-9 * max(1.0, float(np.abs(fn).max()))
    if bad.any():
        # vértices soldados na costura: frente e verso se anulam -> aponta para fora dos vizinhos
        M = _metric(P)
        nsum, ncnt = np.zeros_like(M), np.zeros(len(M))
        for a, b in ((0, 1), (1, 2), (2, 0)):
            np.add.at(nsum, tris[:, a], M[tris[:, b]])
            np.add.at(ncnt, tris[:, a], 1)
            np.add.at(nsum, tris[:, b], M[tris[:, a]])
            np.add.at(ncnt, tris[:, b], 1)
        away = M - nsum / np.maximum(ncnt, 1)[:, None]
        away[np.linalg.norm(away, axis=1) < 1e-9] = (0.0, 0.0, 1.0)
        acc[bad] = away[bad]
    return acc


def hull_mesh(mask, rho, target=HULL_CELLS):
    """Casco fechado inflado da silhueta. Espessura T(v) = ρ·√(d(2r − d)), d = distância à borda e r = raio
    inscrito local. O plano médio é o plano vertical pelo centro do tile (lx + ly = 1) voltado para a câmera;
    frente e verso se afastam ±T dele na horizontal, soldados na borda.
    Objetos redondos são desenhados em 2:1 (a boca do barril é uma elipse 2:1), não na oblíqua do chão:
    o pixel de (lx, ly, lz) é v = 11(lx + ly) − 4·lz + c. A altura de cada vértice sai daí, com 4 px por z
    (a escala de paredes, pisos e do tiledata) e a profundidade comprimida como na art, ancorada como no
    UO (centro do tile no chão na linha h − 22). Se a frente afundaria, o objeto sobe até encostar no chão;
    o verso, que cairia abaixo, para no chão. A câmera 3D que mostra
    essas proporções como a art olha a atan(1/2) ≈ 26,6° do chão. A vista 2D do viewer não depende disso:
    lá cada vértice vai para o pixel que carrega e a profundidade só ordena.
    Peças do mesmo tile (tronco e copa de uma árvore) ficam centradas no tile e alinhadas entre si.
    A borda de baixo conta como interior (espelhada para baixo): base com volume."""
    h, w = mask.shape
    ax = w / 2
    x0, y0, x1, y1 = _bbox(mask)
    m = mask[y0:y1, x0:x1]
    c = max(1, int(math.ceil(math.sqrt(max(int(m.sum()), 1) / target))))
    # toda célula com algum pixel: a casca cobre a silhueta inteira e o alpha da art recorta a sobra
    cin = _cells(m, c, 1e-6)
    R, C = cin.shape
    padc = np.zeros((2 * R + 2, C + 2), bool)
    padc[1:R + 1, 1:C + 1] = cin
    padc[R + 1:2 * R + 1, 1:C + 1] = cin[::-1]
    near_in = np.zeros((2 * R + 3, C + 3), bool)
    near_out = np.zeros_like(near_in)
    for dy in (0, 1):
        for dx in (0, 1):
            near_in[dy:dy + padc.shape[0], dx:dx + padc.shape[1]] |= padc
            near_out[dy:dy + padc.shape[0], dx:dx + padc.shape[1]] |= ~padc
    d = _chamfer((~near_in) | near_out)
    r_loc = _local_radius(d, int(min(24, max(2, math.ceil(d.max())))))
    d_px, r_px = d * c, np.maximum(r_loc * c, 1e-6)
    T = rho * np.sqrt(np.clip(d_px * (2 * r_px - d_px), 0, None)) / PXP
    Tv = T[1:R + 2, 1:C + 2]

    ii, jj, vid = _grid(cin)
    sx = np.minimum(x0 + jj * c, x1).astype(float)
    sy = (y0 + np.minimum(ii * c, y1 - y0)).astype(float)
    Tf = Tv[ii, jj]
    dd = (sx - ax) / HT                               # lx − ly
    sf, sb = 1 + SQ2 * Tf, 1 - SQ2 * Tf               # lx + ly da frente e do verso
    # âncora do UO: o centro do tile no chão cai na linha h − 22; o que afundaria sobe até z = 0
    # (copas, que começam alto na art, ficam onde estão e alinhadas com o tronco)
    def monotone(lz):
        # descendo a coluna da art a altura não sobe: a casca não dobra onde T cresce rápido (perto do topo)
        g = np.full(vid.shape, -np.inf)
        g[ii, jj] = lz
        g = np.maximum.accumulate(g[::-1], axis=0)[::-1]
        return g[ii, jj]

    lzf = monotone((h - 22 - sy + ART_DEPTH * (sf - 1)) / PZ)
    lift = max(0.0, -float(lzf.min()))
    lzf += lift
    lzb = np.maximum(monotone((h - 22 - sy + ART_DEPTH * (sb - 1)) / PZ) + lift, 0.0)
    front = np.stack([(sf + dd) / 2, (sf - dd) / 2, lzf], 1)
    back = np.stack([(sb + dd) / 2, (sb - dd) / 2, lzb], 1)
    interior = Tf > 1e-4
    nF = len(front)
    back_idx = np.where(interior, nF + np.cumsum(interior) - 1, np.arange(nF))
    P = np.concatenate([front, back[interior]])
    px = np.stack([sx, sy], 1)
    px = np.concatenate([px, px[interior]])
    tris = []
    for i in range(R):
        for j in range(C):
            if cin[i, j]:
                a, b, c2, d2 = vid[i, j], vid[i, j + 1], vid[i + 1, j + 1], vid[i + 1, j]
                tris += [(a, d2, c2), (a, c2, b)]
    tris = np.array(tris, np.int64)
    if (_face_normals(P, tris) @ np.array([1.0, 1.0, 0.8])).sum() < 0:   # frente virada para a câmera
        tris = tris[:, ::-1]
    tris = np.concatenate([tris, back_idx[tris[:, ::-1]]])
    P, px, tris = _compact(P, px, tris)
    return _expand(P, px, tris, _smooth_normals(P, tris))


def _plane_mesh(mask, place, target=CARD_CELLS):
    """Superfície fina sobre a silhueta: grade de células (toda célula com pixel; o alpha recorta) e
    place(sx, sy) -> pontos (lx, ly, lz) que caem nesses pixels. Dupla face (as duas ordens)."""
    x0, y0, x1, y1 = _bbox(mask)
    m = mask[y0:y1, x0:x1]
    c = max(1, int(math.ceil(math.sqrt(max(int(m.sum()), 1) / target))))
    cin = _cells(m, c, 1e-6)
    R, C = cin.shape
    ii, jj, vid = _grid(cin)
    sx = np.minimum(x0 + jj * c, x1).astype(float)
    sy = (y0 + np.minimum(ii * c, y1 - y0)).astype(float)
    P = place(sx, sy)
    px = np.stack([sx, sy], 1)
    tris = []
    for i in range(R):
        for j in range(C):
            if cin[i, j]:
                a, b, c2, d2 = vid[i, j], vid[i, j + 1], vid[i + 1, j + 1], vid[i + 1, j]
                tris += [(a, d2, c2), (a, c2, b)]
    tris = np.array(tris, np.int64)
    P, px, tris = _compact(P, px, np.concatenate([tris, tris[:, ::-1]]))
    return _expand(P, px, tris)


def _facing_plane(mask, s):
    """Plano vertical lx + ly = s voltado para a câmera; cada pixel no seu raio do UO (exato)."""
    h, w = mask.shape

    def place(sx, sy):
        d = (sx - w / 2) / HT
        return np.stack([(s + d) / 2, (s - d) / 2, (HT * s + h - 44 - sy) / PZ], 1)
    return place


def cylinder_mesh(mask, segs=16):
    """Barril, barrica, balde: cilindro vertical no eixo da silhueta, no centro do tile. Objetos redondos
    são desenhados em 2:1 (a boca é uma elipse com metade da largura de altura), então a altura é a da art
    menos essa elipse, com 4 px por z. O raio de cada anel sai da largura da silhueta na linha do centro da
    elipse daquela altura: o bojo do barril aparece. Textura: a mesma projeção 2:1 da art,
    u = w/2 + 22(lx − ly), v = Y + 11(lx + ly) − 4·lz, com o ponto mais baixo da frente na última linha.
    -> None se a silhueta não for de cilindro."""
    h, w = mask.shape
    x0, y0, x1, y1 = _bbox(mask)
    W = x1 - x0
    e = W / 4                                        # meia altura da elipse 2:1
    H = (y1 - y0 - 2 * e) / PZ
    if W < 6 or H < 0.5:
        return None
    axis = (x0 + x1) / 2
    rmax = max(axis - x0, x1 - axis) / PXP
    rows = np.nonzero(mask.any(1))[0]

    def half(v0, v1):
        # maior afastamento do eixo nas linhas [v0, v1] (silhueta pode ser assimétrica)
        v0, v1 = min(max(v0, rows[0]), rows[-1]), min(max(v1, rows[0]), rows[-1])
        cols = np.nonzero(mask[v0:v1 + 1].any(0))[0]
        return max(axis - cols[0], cols[-1] + 1 - axis) if len(cols) else W / 2

    def radius(lz, top=False):
        v = int(round(y1 - e - PZ * lz))
        hw = half(int(y0), int(y0 + 2 * e)) if top else half(v - 1, v + 1)   # topo: a boca inteira
        return float(np.clip(hw / PXP, 0.35 * rmax, rmax))

    K = int(np.clip(round(H / 1.5), 2, 10))
    zs = np.linspace(0.0, H, K + 1)
    rs = np.array([radius(z, k == K) for k, z in enumerate(zs)])
    # altura final: o fundo do anel de cima encosta na primeira linha da art (frente de baixo na última)
    H = (y1 - y0 - ART_DEPTH * SQ2 * (rs[0] + rs[-1])) / PZ
    zs = np.linspace(0.0, H, K + 1)
    d = (axis - w / 2) / HT
    cx, cy = (1 + d) / 2, (1 - d) / 2                # eixo: centro do tile na profundidade
    th = np.linspace(0, 2 * math.pi, segs, endpoint=False)
    ring = np.stack([np.cos(th), np.sin(th)], 1)
    # lateral: anéis com normal radial; tampa: anel de cima repetido + centro, normal para cima
    side = np.concatenate([np.column_stack([cx + r * ring[:, 0], cy + r * ring[:, 1], np.full(segs, z)])
                           for r, z in zip(rs, zs)])
    cap = np.concatenate([side[-segs:], [[cx, cy, H]]])
    P = np.concatenate([side, cap])
    N = np.concatenate([np.tile(np.column_stack([ring, np.zeros(segs)]), (K + 1, 1)),
                        np.tile([0.0, 0.0, 1.0], (segs + 1, 1))])
    tris = []
    for k in range(K):
        for i in range(segs):
            a, b = k * segs + i, k * segs + (i + 1) % segs
            tris += [(a, b, b + segs), (a, b + segs, a + segs)]
    c0, mid = len(side), len(P) - 1
    tris += [(c0 + i, c0 + (i + 1) % segs, mid) for i in range(segs)]
    tris = np.array(tris, np.int64)   # θ crescente gira de x para y: com z para cima, faces para fora
    s = P[:, 0] + P[:, 1]
    Y = y1 - ART_DEPTH * float(s[:segs].max())
    # a metade de trás da lateral não aparece na art: reusa o pixel do ponto da frente (espelho no eixo)
    st = np.where((np.arange(len(P)) < len(side)) & (s < cx + cy), 2 * (cx + cy) - s, s)
    px = np.stack([w / 2 + HT * (P[:, 0] - P[:, 1]), Y + ART_DEPTH * st - PZ * P[:, 2]], 1)
    return _expand(P, px, tris, N)


def bed_mesh(img, H):
    """Peça de cama: colchão = caixa do tile na altura do tiledata. Do resto da silhueta, o lençol que
    transborda o tile (cinza/branco, sem saturação) é uma aba horizontal na altura do colchão; a madeira
    (cabeceira, postes, dossel) é um cartão vertical voltado para a câmera, apoiado no colchão ou no chão."""
    mask = img != 0
    h, w = mask.shape
    box = (0.0, 0.0, 1.0, 1.0, float(H))
    cover = _hexagon_cover(mask.shape, [box])
    rest = mask & ~cover
    parts = [box_mesh(mask, [box])]
    r, g, b = (img >> 10) & 31, (img >> 5) & 31, img & 31
    sheet = rest & ((np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)) <= 3)
    if sheet.sum() >= 8:
        def flat_at(sx, sy):   # raio do pixel até z = H
            d, s = (sx - w / 2) / HT, (sy - (h - 44) + PZ * H) / HT
            return np.stack([(s + d) / 2, (s - d) / 2, np.full(len(sx), float(H))], 1)
        parts.append(_plane_mesh(sheet, flat_at))
    rest &= ~sheet
    if rest.sum() >= 8:
        # plano: pela base do resto. Apoiado no colchão (logo abaixo é colchão) é cabeceira/dossel e fica
        # na borda de trás da cama; no chão (pés, postes da frente), onde a base encosta
        ss, on_top = [], 0
        for j in np.nonzero(rest.any(0))[0]:
            vb = np.nonzero(rest[:, j])[0][-1]
            top = vb + 1 < h and cover[vb + 1, j]
            on_top += top
            ss.append((vb + 1 - (h - 44) + PZ * (H if top else 0.0)) / HT)
        s = 0.15 if on_top > len(ss) / 2 else float(np.clip(np.median(ss), 0.0, 2.0))
        parts.append(_plane_mesh(rest, _facing_plane(rest, s)))
    return tuple(np.concatenate([p[k] for p in parts]) for k in range(3))


def pew_mesh(mask, Hs=5.0, depth=0.55):
    """Banco de encosto: o encosto é um plano vertical na borda do tile (eixo e borda pelo contorno de cima,
    como os trilhos); o assento, um plano horizontal na altura Hs com depth de fundo na frente dele; o que
    fica abaixo do assento na frente (avental, pés), um plano vertical na borda da frente do assento. Cada
    pixel vai para a primeira peça que o cobre: assento, encosto, avental. -> None se não achar o eixo."""
    fit = rail_mesh(mask, snap=True, plane=True)
    if fit is None or fit[0] not in ('\\', '/'):
        # peça da ponta: o braço do banco quebra o contorno; o eixo sai das colunas do encosto (as mais altas)
        top = np.array([np.argmax(c) if c.any() else mask.shape[0] for c in mask.T])
        keep = top <= np.median(top[top < mask.shape[0]])
        fit = rail_mesh(mask & keep[None, :], snap=True, plane=True)
        if fit is not None and fit[0] in 'AV':
            # encosto + lateral da ponta (Λ): o encosto é o trecho mais comprido
            cols = np.nonzero((mask & keep[None, :]).any(0))[0]
            j = np.arange(mask.shape[1])
            side = j < fit[2] if fit[2] - cols[0] > cols[-1] - fit[2] else j > fit[2]
            fit = rail_mesh(mask & (keep & side)[None, :], snap=True, plane=True)
    if fit is None or fit[0] not in ('\\', '/'):
        return None
    kind, E, _ = fit
    h, w = mask.shape
    F = E + depth if E < 0.5 else E - depth      # borda da frente do assento
    lo, hi = min(E, F), max(E, F)
    ai = 0 if kind == '/' else 1                 # coordenada fixa do encosto: lx (/) ou ly (\)

    def at_z(sx, sy, z):                         # raio do pixel até a altura z
        d, s = (sx - w / 2) / HT, (sy - (h - 44) + PZ * z) / HT
        return np.stack([(s + d) / 2, (s - d) / 2, np.full(len(sx), float(z))], 1)

    def at_plane(a):                             # raio do pixel até o plano vertical (lx ou ly) = a
        def place(sx, sy):
            d = (sx - w / 2) / HT
            lx, ly = (np.full(len(sx), a), a - d) if ai == 0 else (a + d, np.full(len(sx), a))
            return np.stack([lx, ly, (HT * (lx + ly) + h - 44 - sy) / PZ], 1)
        return place

    vs, us = np.nonzero(mask)
    sx, sy = us + 0.5, vs + 0.5
    S = at_z(sx, sy, Hs)
    seat = (S[:, ai] >= lo - 0.02) & (S[:, ai] <= hi + 0.02) & (S[:, 1 - ai] >= -0.05) & (S[:, 1 - ai] <= 1.05)
    back = ~seat & (at_plane(E)(sx, sy)[:, 2] >= -0.5)
    parts = []
    for sel, place in ((seat, lambda x, y: at_z(x, y, Hs)), (back, at_plane(E)), (~seat & ~back, at_plane(F))):
        if sel.sum() >= 4:
            m = np.zeros_like(mask)
            m[vs[sel], us[sel]] = True
            parts.append(_plane_mesh(m, place))
    return tuple(np.concatenate([p[k] for p in parts]) for k in range(3)) if parts else None


def slab_mesh(mask, H, rest_plane=None):
    """Caixa do tile na altura H com o resto da silhueta num plano (rest_plane, ou um cartão no centro do
    tile): banco de encosto = assento em caixa e o encosto num plano na borda do tile."""
    box = (0.0, 0.0, 1.0, 1.0, float(H))
    rest = mask & ~_hexagon_cover(mask.shape, [box])
    parts = [box_mesh(mask, [box])]
    if rest.sum() >= 8:
        mesh = rest_plane(rest) if rest_plane else None
        parts.append(mesh if mesh is not None else _plane_mesh(rest, _facing_plane(rest, 1.0)))
    return tuple(np.concatenate([p[k] for p in parts]) for k in range(3))


def _blobs(m):
    """Componentes 4-conexas de uma máscara -> lista de (ys, xs)."""
    seen = np.zeros_like(m, bool)
    out = []
    for y, x in zip(*np.nonzero(m)):
        if seen[y, x]:
            continue
        seen[y, x] = True
        stack, ys, xs = [(y, x)], [], []
        while stack:
            cy, cx = stack.pop()
            ys.append(cy); xs.append(cx)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and m[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append((np.array(ys), np.array(xs)))
    return out


def fountain_meshes(pieces, segs=48):
    """Chafariz de vários tiles: cada peça é a fatia da imagem do chafariz que cai no losango do seu tile.
    Monta a imagem inteira, tira dela um sólido de revolução e reparte as faces entre as peças pelo pixel.
    Perfil (desenho 2:1 dos objetos redondos, eixo = meio da largura, centro no chão Yc = base − W/4):
    - cada mancha de água (azul) é uma bacia: a linha mais larga é o centro da elipse -> altura da água,
      a meia largura -> raio; a borda fica um pouco acima e por fora;
    - paredes de baixo até a borda da bacia de baixo: raio pelo contorno lateral da silhueta (degraus);
    - coluna entre as bacias: a falha sem água no meio da mancha de baixo;
    - bacia de cima: borda, parede curta e fundo até a coluna.
    pieces: [(dx, dy, img)] na mesma altura. -> {índice da peça: malha} ou None sem água."""
    pad = 40
    lo_u = min(HT * (dx - dy) - img.shape[1] // 2 for dx, dy, img in pieces)
    lo_v = min(HT * (dx + dy) - (img.shape[0] - 44) for dx, dy, img in pieces)
    OX, OY = pad - lo_u, pad - lo_v
    Wc = int(max(OX + HT * (dx - dy) - img.shape[1] // 2 + img.shape[1] for dx, dy, img in pieces)) + pad
    Hc = int(max(OY + HT * (dx + dy) - (img.shape[0] - 44) + img.shape[0] for dx, dy, img in pieces)) + pad
    canvas = np.zeros((Hc, Wc), np.uint16)
    own = np.full((len(pieces), Hc, Wc), False)
    origin = [None] * len(pieces)
    for k, (dx, dy, img) in sorted(enumerate(pieces), key=lambda t: t[1][0] + t[1][1]):   # ordem do cliente
        h, w = img.shape
        u0, v0 = int(OX + HT * (dx - dy) - w // 2), int(OY + HT * (dx + dy) - (h - 44))
        m = img != 0
        canvas[v0:v0 + h, u0:u0 + w][m] = img[m]
        own[k, v0:v0 + h, u0:u0 + w] = m
        origin[k] = (u0, v0)
    mask = canvas != 0
    x0, y0, x1, y1 = _bbox(mask)
    axis, W = (x0 + x1) / 2, x1 - x0
    Yc = y1 - W / 4
    r5, g5, b5 = (canvas >> 10) & 31, (canvas >> 5) & 31, canvas & 31
    water = mask & (b5.astype(int) > r5 + 3) & (b5 >= g5)
    basins = []
    for ys, xs in _blobs(water):
        if len(ys) < 20:
            continue
        rows = np.unique(ys)
        width = np.array([np.ptp(xs[ys == r]) for r in rows])
        cy = float(rows[np.argmax(width)])
        a = (xs.max() - xs.min() + 1) / 2
        # coluna: a falha sem água em volta do eixo, nas linhas da mancha acima do centro
        gaps = []
        for r in rows[rows <= cy]:
            row = water[r, int(xs.min()):int(xs.max()) + 1]
            c = int(round(axis)) - int(xs.min())
            if 0 <= c < len(row) and not row[c]:
                l, rr = c, c
                while l > 0 and not row[l - 1]:
                    l -= 1
                while rr < len(row) - 1 and not row[rr + 1]:
                    rr += 1
                if l > 0 and rr < len(row) - 1:
                    gaps.append(rr - l + 1)
        basins.append(((Yc - cy) / PZ, a / PXP, (np.median(gaps) / 2 / PXP) if gaps else None))
    if not basins:
        return None
    basins.sort()

    def contour(z):   # raio da silhueta na linha da altura z (meia largura em volta do eixo)
        v = int(round(Yc - PZ * z))
        cols = np.nonzero(mask[min(max(v, y0), y1 - 1)])[0]
        return max(axis - cols[0], cols[-1] + 1 - axis) / PXP

    RIM, LIP = 1.0, 0.06                         # borda: 1 z acima da água e 0,06 tile por fora
    prof = []                                    # perfil (r, z) de fora/baixo para dentro/cima
    zw, rw, gap = basins[0]
    R = max(float(np.median([contour(z) for z in np.arange(0.0, zw + RIM, 0.5)])), rw + LIP)
    prof += [(R, 0.0), (R, zw + RIM), (rw, zw + RIM), (rw, zw)]
    for zw, rw, nxt in basins[1:]:
        col = min(gap or rw * 0.4, rw * 0.6)     # coluna que sai da bacia de baixo
        R = rw + LIP
        bottom = max(prof[-1][1] + 0.5, zw - 0.5 * (zw - prof[-1][1]))
        prof += [(col, prof[-1][1]), (col, bottom), (R, bottom + 0.3), (R, zw + RIM), (rw, zw + RIM), (rw, zw)]
        gap = nxt
    if gap and gap < rw * 0.5:                   # bico no meio da bacia de cima
        prof += [(gap, prof[-1][1]), (gap, prof[-1][1] + 1.5)]
    prof.append((0.0, prof[-1][1]))

    # malha: cada trecho do perfil vira um anel de quads com vértices próprios (normais do trecho)
    ox = (axis - OX) / HT                        # lx − ly do eixo (relativo à peça de referência)
    dxs = np.array([dx for dx, _, _ in pieces], float); dys = np.array([dy for _, dy, _ in pieces], float)
    oxy = (dxs + dys).mean() + 1.0               # lx + ly: centro da pegada das peças
    cx, cy = (oxy + ox) / 2, (oxy - ox) / 2
    th = np.linspace(0, 2 * math.pi, segs + 1)
    P, N, PX = [], [], []
    tris = []
    for (ra, za), (rb, zb) in zip(prof, prof[1:]):
        if abs(ra - rb) + abs(za - zb) < 1e-6:
            continue
        nr, nz = (zb - za) * METRIC_Z, -(rb - ra)
        nl = math.hypot(nr, nz)
        nr, nz = nr / nl, nz / nl
        steps = max(1, int(math.ceil(max(abs(rb - ra) * PXP, abs(zb - za) * PZ) / 6)))
        base = len(P)
        for t in np.linspace(0, 1, steps + 1):
            r, z = ra + (rb - ra) * t, za + (zb - za) * t
            for a in th:
                ex, ey = math.cos(a), math.sin(a)
                P.append((cx + r * ex, cy + r * ey, z))
                N.append((nr * ex, nr * ey, nz))
                s = r * (ex + ey)
                if s < 0 and nz < 0.5:           # lado de trás de parede: pixel da frente (espelho)
                    s = -s
                PX.append((axis + HT * r * (ex - ey), Yc + ART_DEPTH * s - PZ * z))
        n = segs + 1
        for i in range(steps):
            for j in range(segs):
                a, b = base + i * n + j, base + i * n + j + 1
                tris += [(a, b, b + n), (a, b + n, a + n)]
    P, N, PX = np.array(P), np.array(N), np.array(PX)
    tris = np.array(tris, np.int64)
    # reparte: a face vai para toda peça com pixel opaco em algum vértice ou no centro (a costura fecha)
    pts = np.concatenate([PX[tris], PX[tris].mean(1, keepdims=True)], 1)
    ui = np.clip(np.round(pts[..., 0]).astype(int), 0, Wc - 1)
    vi = np.clip(np.round(pts[..., 1]).astype(int), 0, Hc - 1)
    hit = own[:, vi, ui].any(2)                  # (peça, face)
    centers = np.array([(u0 + pieces[k][2].shape[1] / 2, v0 + pieces[k][2].shape[0] - 22)
                        for k, (u0, v0) in enumerate(origin)])
    near = np.argmin(((pts[:, 3, None, :] - centers[None]) ** 2).sum(2), 1)
    none = ~hit.any(0)
    hit[near[none], np.nonzero(none)[0]] = True
    out = {}
    for k, (dx, dy, img) in enumerate(pieces):
        sel = tris[hit[k]]
        if not len(sel):
            continue
        u0, v0 = origin[k]
        Pk = P - np.array([dx, dy, 0.0])
        out[k] = _expand(Pk, PX - np.array([u0, v0]), sel, N)
    if max(len(m[0]) for m in out.values()) > MESH_CLASSES[-1]:
        return None                              # não cabe no maior lote: fica a laje
    return out


PLANT_NAMES = (r'bramble|sapling|rushes|\bweeds?\b|cattail|fan plant|elephant ear|snake plant|poppies|'
               r'century plant|yucca|grapevine|blade plant|water plants|\bfern|\breeds?\b|\bgrass|'
               r'\bflowers?\b|mushroom|\bcrops?\b|wheat|\bcorn\b|cotton|\bflax|hay sheave|lettuce|cabbage|'
               r'turnip|onion|carrot|pumpkin plant|\bvines?\b|\bivy\b|orfluer|cactus|\bhedge')
FLAT_NAMES = (r'lill?y pads?|water lill?y|\bacid\b|garbage|refuse|debris|spilled|wood curls|\bpuddle|'
              r'^\s*blood\s*$|blood smear|blood pool|damaged books')
LOG_NAMES = r'fallen log|sunken log|\btree trunk|\blog\b'


def log_mesh(mask):
    """Tora deitada (tronco caído): cilindro horizontal no eixo x (silhueta descendo para a direita) ou y
    (subindo), apoiado no chão. Na projeção do UO o corte de raio r tem 2·√(22² + (4/zs)²)·r px de altura
    na vertical; o eixo e o comprimento saem da linha central da silhueta. Textura = projeção do UO
    (exata, a casca toda cai dentro da faixa). Galhos e o que sobra fora da faixa: cartão no eixo.
    -> None se a silhueta não for alongada na diagonal."""
    h, w = mask.shape
    vs, us = np.nonzero(mask)
    if len(us) < 30:
        return None
    u, v = us + 0.5, vs + 0.5
    cu, cv = u.mean(), v.mean()
    cov = np.cov(np.stack([u - cu, v - cv]))
    ev, evec = np.linalg.eigh(cov)
    du, dv = evec[:, 1]
    if ev[1] < 1.6 * ev[0] or min(abs(du), abs(dv)) < 0.2:
        return None                                   # não é uma faixa diagonal (ponta, toco)
    along_x = du * dv > 0
    # espessura vertical da faixa: mediana, por coluna, da altura ocupada
    cols = np.unique(us)
    thick = np.median([np.ptp(vs[us == c]) + 1 for c in cols])
    zs = 0.1286
    r = float(thick / (2 * math.hypot(HT, PZ / zs)))
    if r < 0.05:
        return None
    lzc = r / zs                                      # eixo a r do chão, em z
    # linha central: v − u (eixo x) ou v + u (eixo y) constante = mediana; extremos pelo alcance em u
    k = np.median(v - u) if along_x else np.median(v + u)
    ua, ub = float(u.min()), float(u.max())
    segs = 10
    th = np.linspace(0, 2 * math.pi, segs, endpoint=False)
    rings = []
    for ue in (ua, ub):
        ve = ue + k if along_x else k - ue
        # ponto do eixo que cai em (ue, ve) na altura lzc: d = lx − ly, s = lx + ly
        d = (ue - w / 2) / HT
        s = (ve - (h - 44) + PZ * lzc) / HT
        lx, ly = (s + d) / 2, (s - d) / 2
        a, b = r * np.cos(th), r * np.sin(th) / zs     # (horizontal perpendicular, vertical em z)
        if along_x:
            rings.append(np.column_stack([np.full(segs, lx), ly + a, lzc + b]))
        else:
            rings.append(np.column_stack([lx + a, np.full(segs, ly), lzc + b]))
    P = np.concatenate(rings)
    tris = []
    for i in range(segs):
        j = (i + 1) % segs
        tris += [(i, j, segs + j), (i, segs + j, segs + i)]
    c0, c1 = len(P), len(P) + 1                       # tampas nas pontas
    P = np.concatenate([P, [P[:segs].mean(0), P[segs:].mean(0)]])
    tris += [(c0, (i + 1) % segs, i) for i in range(segs)] + [(c1, segs + i, segs + (i + 1) % segs) for i in range(segs)]
    tris = np.array(tris, np.int64)
    tris = np.concatenate([tris, tris[:, ::-1]])     # dupla face: não depende da orientação
    P, px, tris = _compact(P, _proj(P, w, h), tris)
    parts = [_expand(P, px, tris)]
    cover = np.zeros_like(mask)
    vv, uu = np.mgrid[0:h, 0:w] + 0.5
    for t in tris[: len(tris) // 2]:
        (ax, ay), (bx, by), (cx2, cy2) = px[t]
        dd = (bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)
        if abs(dd) < 1e-9:
            continue
        l1 = ((bx - uu) * (cy2 - vv) - (by - vv) * (cx2 - uu)) / dd
        l2 = ((cx2 - uu) * (ay - vv) - (cy2 - vv) * (ax - uu)) / dd
        cover |= (l1 >= -1e-6) & (l2 >= -1e-6) & (1 - l1 - l2 >= -1e-6)
    rest = mask & ~cover
    if rest.sum() >= 8:
        smid = ((cv - (h - 44) + PZ * lzc) / HT)       # plano pelo centro da tora
        parts.append(_plane_mesh(rest, _facing_plane(rest, smid)))
    return tuple(np.concatenate([p[k2] for p in parts]) for k2 in range(3))
PANEL_NAMES = r'banner|tapestry|curtain|painting|portrait|standard|\bmap\b|\bsign\b(?!post)|\bmirror|trophy'


def plant_mesh(mask, height=0, tree=False):
    """Planta (grama, flor, broto, junco, árvore): dois cartões em X nos eixos x e y, cruzando no eixo
    vertical da silhueta no centro do tile, com o pé (última linha) no chão. Os dois carregam o pixel da
    art: na vista 2D caem um sobre o outro; em 3D a planta tem volume de qualquer lado. A art espalha a
    planta pela profundidade do tile (tufos de grama de 45 px), então a altura, de 4 px por z, fica
    limitada a 2 × max(altura do tiledata, 2) z. Árvores: eixo no centro do tile (w/2) e pé na linha do
    centro do tile (h − 22), para tronco e copa (sprites separados no mesmo tile) ficarem alinhados."""
    h, w = mask.shape
    x0, y0, x1, y1 = _bbox(mask)
    if tree:
        axis, y1 = w / 2, h - 22                     # raízes desenhadas à frente afundam no chão
    else:
        axis = (x0 + x1) / 2
    k = min(1.0, 2 * max(height, 2) / max((y1 - y0) / PZ, 1e-6)) if not tree else 1.0
    d = (axis - w / 2) / HT
    cx, cy = (1 + d) / 2, (1 - d) / 2

    def plane(along_x):
        def place(sx, sy):
            t = (sx - axis) / HT                     # deslocamento horizontal na tela, em tiles de eixo
            lz = (y1 - sy) / PZ * k
            if along_x:
                return np.stack([cx + t, np.full(len(sx), cy), lz], 1)
            return np.stack([np.full(len(sx), cx), cy - t, lz], 1)
        return place
    a, b = _plane_mesh(mask, plane(True)), _plane_mesh(mask, plane(False))
    return tuple(np.concatenate([a[k], b[k]]) for k in range(3))


def rail_mesh(mask, snap=None, plane=False, max_err=1.5, foot=None):
    """Corrimão / grade fina: na art, retas de inclinação ±1 são trilhos nos eixos do mapa, então cada
    trecho fica num plano vertical: descendo para a direita (\\) é o eixo x (ly = c), subindo (/) é o y
    (lx = c'). Formas: \\, /, Λ (ápice em cima) e V (ápice embaixo), escolhidas pelo contorno de cima de cada
    coluna; os dois planos se cruzam no ápice. O pixel mais baixo (o pé do pino) fica no chão.
    -> None se o contorno não for desse tipo."""
    h, w = mask.shape
    cols = np.nonzero(mask.any(0))[0]
    if len(cols) < 6:
        return None
    t = np.array([np.nonzero(mask[:, j])[0][0] for j in cols], float)
    best = None
    for kind in ('\\', '/', 'A', 'V'):
        if kind in '\\/':
            sg = np.full(len(cols), 1.0 if kind == '\\' else -1.0)
            apex = [0]
        else:
            apex = range(2, len(cols) - 2)
        for a in apex:
            if kind in 'AV':
                left = -1.0 if kind == 'A' else 1.0
                sg = np.where(np.arange(len(cols)) <= a, left, -left)
            # contorno modelo: t = t[a] + sg·(col − col[a]) por trecho, com deslocamento ótimo (mediana)
            base = t - sg * (cols - cols[a])
            err = float(np.mean(np.abs(base - np.median(base))))
            if best is None or err < best[0]:
                best = (err, kind, a, sg)
    err, kind, a, sg = best
    if err > max_err:
        return None
    ua = float(cols[a]) + 0.5
    # trecho \\ (sg > 0): plano ly = c; trecho / : plano lx = c + (ua − w/2)/22 (cruzam no ápice).
    # Nos dois a altura é (base + 44c)/4: c põe o pixel mais baixo da peça (o pé do pino) no chão

    def place(sx, sy, c):
        xside = (np.where(sx > ua, sg[-1] > 0, sg[0] > 0) if kind in 'AV' else np.full(len(sx), sg[0] > 0))
        du = (sx - w / 2) / HT
        cy_ = c + (ua - w / 2) / HT
        lx = np.where(xside, du + c, cy_)
        ly = np.where(xside, c, cy_ - du)
        return np.stack([lx, ly, (HT * (lx + ly) + h - 44 - sy) / PZ], 1)

    vs, us = np.nonzero(mask if foot is None else foot)   # foot: peça inteira (o pino), quando mask é só um trecho
    cg = -float(place(us + 0.5, vs + 1.0, 0.0)[:, 2].min()) * PZ / (2 * HT)
    # Na art, peça no meio do tile e baixa ou na borda e 11 z mais alta por tile dão o mesmo pixel.
    # Trilhos de vitrine e cercas ficam apoiados pelo pé do pino (cg: coincide com a borda das peças
    # vizinhas). snap (quadros, estandartes): o plano encaixa na borda do tile (a parede) mais próxima
    # que não deixa a peça abaixo do próprio z (c ≥ cg); sem borda assim, fica apoiado
    k = (ua - w / 2) / HT
    edges = []
    if kind in 'AV' or sg[0] > 0:
        edges += [0.0, 1.0]                  # plano x: ly = c
    if kind in 'AV' or sg[0] < 0:
        edges += [0.0 - k, 1.0 - k]          # plano y: lx = c + k
    ok = [e for e in edges if e >= cg - 0.05]
    c = min(ok) if ok and snap else cg
    if plane:                                # só o plano: (forma, coordenada fixa lx (/) ou ly (\))
        return kind, (c + k if kind == '/' else c), ua
    return _plane_mesh(mask, lambda sx, sy: place(sx, sy, c))


def rail_parts(mask, min_px=8):
    """Moldura de vitrine (barras + pino): cada barra reta é um trilho de 1 tile sobre a borda do tile.
    \ (desce à direita) fica no plano ly = c, / no plano lx = c; c sai da extensão horizontal da barra
    (ela cobre exatamente lx ou ly de 0 a 1) e a altura vem da projeção do pixel."""
    h, w = mask.shape
    tris = [], [], []
    ys0, xs0 = np.nonzero(mask)
    left = np.ones(len(ys0), bool)
    bars = []
    while left.sum() >= min_px:                         # retas de inclinação ±1: a mais populosa sai primeiro
        best = None
        for back, key in ((True, ys0 - xs0), (False, ys0 + xs0)):
            vals = np.bincount((key[left] - key.min() + 1))
            win = vals + np.r_[vals[1:], 0] + np.r_[0, vals[:-1]]
            i = int(win.argmax())
            if best is None or win[i] > best[0]:
                best = (int(win[i]), back, key, i + key.min() - 1)
        n, back, key, k = best
        if n < min_px:
            break
        sel = left & (np.abs(key - k) <= 1)
        if np.ptp(xs0[sel]) >= 5:
            bars.append((back, ys0[sel], xs0[sel]))
        left &= ~sel
    for back, ys, xs in bars:
        x0, x1 = float(xs.min()), float(xs.max()) + 1
        c = -(x0 - w / 2) / HT if back else (x1 - w / 2) / HT

        def place(sx, sy, back=back, c=c):
            du = (sx - w / 2) / HT
            lx, ly = (du + c, np.full_like(du, c)) if back else (np.full_like(du, c), c - du)
            return np.stack([lx, ly, (HT * (lx + ly) + h - 44 - sy) / PZ], 1)

        part = np.zeros_like(mask)
        part[ys, xs] = True
        m = _plane_mesh(part, place)
        for k in range(3):
            tris[k].append(m[k])
    if not tris[0]:
        return None
    return tuple(np.concatenate(t) for t in tris)


def sprite_mesh(img, tx, cat, sub, name='', height=0, surface=False):
    """-> (motor, (pos, pixel, normal)) em listas de triângulos."""
    mask = img != 0
    arch = archetype(tx, cat, sub)
    rho = tx['default_depth_ratio'].get(f'{cat}/{sub}', tx['category_default_depth_ratio'].get(cat, 0.5))
    floor = ((surface and height == 0 and (cat != 'architecture' or sub == 'floor'))
             or (sub == 'water' and re.fullmatch(r'\s*water\s*', name, re.I)))
    if arch == 'flat' or floor or re.search(FLAT_NAMES, name, re.I):
        # tapetes, pentagramas, pisos, água, vitórias-régias, entulho: deitam no chão (ou na água); o que
        # fica sobre o piso (entulho, livros, tapete) é mais grosso que a laje dele, senão briga de profundidade
        return 'flat', flat_mesh(mask, FLAT_THICK if floor else DECAL_THICK)
    if (re.search(PLANT_NAMES, name, re.I) or cat == 'vegetation' and sub in ('flower', 'mushroom', 'crop')
            or cat == 'terrain' and sub == 'ground' and height <= 2):
        return 'planta', plant_mesh(mask, height)
    if cat == 'vegetation' and sub == 'tree':
        return 'arvore', plant_mesh(mask, height, tree=True)
    if re.search(LOG_NAMES, name, re.I):
        mesh = log_mesh(mask)
        if mesh is not None:
            return 'tora', mesh
    if f'{cat}/{sub}' == 'architecture/arch':
        arch = 'box'                         # arco = parede com vão: caixa fina e o alpha recorta o vão
    if re.search(PANEL_NAMES, name, re.I) or sub == 'painting':
        mesh = rail_mesh(mask, snap=True)   # quadro/estandarte: plano na parede (borda do tile)
        if mesh is not None:
            return 'painel', mesh
    if cat == 'container' and sub == 'barrel':
        mesh = cylinder_mesh(mask)
        if mesh is not None:
            return 'cilindro', mesh
    if cat == 'furniture' and sub == 'bed':
        return 'cama', bed_mesh(img, height if height > 0 else 5)
    if re.search(r'\bfountain\b', name, re.I) and mask.shape[1] <= 46 and mask.shape[0] <= 60:
        # fatia de chafariz de vários tiles: a bacia é pintada no losango do chão; vira laje erguida
        return 'laje', flat_mesh(mask, max(height, 1), plinth=True)
    if re.search(r'\bbench\b', name, re.I) and mask.shape[0] >= 70:
        mesh = pew_mesh(mask)                    # banco de encosto
        if mesh is not None:
            return 'banco', mesh
    if 'display case' in name.lower() and cat == 'container' and surface is not None and mask.shape[1] <= 46:
        boxes, iou = fit_boxes(mask, False)           # bandejas de meia largura: a pegada vem da silhueta
        if iou >= 0.7:
            return 'caixa', box_mesh(mask, boxes)
        hh = max(1.0, (mask.shape[0] - 44 - _bbox(mask)[1]) / 4.0)    # topo do losango = (0,0,H)
        return 'caixa', box_mesh(mask, [(0.0, 0.0, 1.0, 1.0, hh)])
    if 'hanging pole' in name.lower() and mask.sum() < 150:
        mesh = rail_mesh(mask, snap=True)        # vara reta presa à parede: plano na borda do tile
        if mesh is not None:
            return 'grade', mesh
    if re.search(r'display case|\brail|railing|\bfence', name, re.I) and height <= (6 if 'display case' in name.lower() else 3) and not surface:
        mesh = (rail_parts(mask) if 'display case' in name.lower() else None) or rail_mesh(mask)
        if mesh is not None:
            return 'grade', mesh
    if cat == 'furniture' and ((sub == 'table' and surface and height >= 2) or re.search(r'\bbench\b', name, re.I)):
        # mesa, balcão, banco: tampo na altura do tiledata (bancos: centrado no tile)
        box = fit_top_box(mask, height if surface and height >= 2 else None)
        if hexagon_iou(mask, [box], of_mask=True) >= 0.8:   # pés abertos de banco ficam de fora
            return 'tampo', box_mesh(mask, [box])
    if arch == 'box':
        # o fragment shader descarta os pixels transparentes da art: janelas, arcos e recortes ficam
        # vazados e a caixa de arquitetura só precisa acertar a pegada (o assets3d, sem esse corte, pede 0,8)
        kind = f'{cat}/{sub}'
        boxes, iou = fit_boxes(mask, kind in WALL_LIKE)
        need = {'architecture/stairs': 0.6, 'furniture/bed': 0.6}.get(kind, 0.5 if kind in WALL_LIKE else 0.8)
        if iou >= need:
            return 'box' if len(boxes) == 1 else 'canto', box_mesh(mask, boxes)
        if kind in ('architecture/floor', 'architecture/bridge'):   # superfície pisável: casco vira almofada
            return 'flat', flat_mesh(mask)
        arch = 'hull'
    fill = mask.sum() / max(1, np.prod(np.ptp(np.argwhere(mask), 0) + 1))
    if arch == 'card' or fill < 0.33:
        return 'card', _hull_fit(mask, min(rho, 0.08), CARD_CELLS)
    return 'hull', _hull_fit(mask, rho, HULL_CELLS)


def _hull_fit(mask, rho, target):
    while True:
        mesh = hull_mesh(mask, rho, target)
        if len(mesh[0]) <= MESH_MAX or target <= 4:
            return mesh
        target //= 2


def oct_encode(n):
    n = n / np.abs(n).sum(1, keepdims=True)
    o = n[:, :2].copy()
    neg = n[:, 2] < 0
    o[neg] = (1 - np.abs(n[neg][:, ::-1][:, :2])) * np.where(n[neg][:, :2] >= 0, 1.0, -1.0)
    return o


def bleed(img, iters=3):
    """Cor dos pixels opacos espalhada nos transparentes vizinhos (alpha continua 0): mipmaps sem halo."""
    rgb = np.stack([(img >> 10) & 31, (img >> 5) & 31, img & 31], -1).astype(np.float32)
    valid = img != 0
    for _ in range(iters):
        acc = np.zeros_like(rgb)
        cnt = np.zeros(valid.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            v = np.roll(np.roll(valid, dy, 0), dx, 1)
            acc += np.roll(np.roll(rgb, dy, 0), dx, 1) * v[..., None]
            cnt += v
        grow = ~valid & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        valid |= grow
    c = np.clip(np.round(rgb), 0, 31).astype(np.uint16)
    out = (c[..., 0] << 11) | (c[..., 1] << 6) | (c[..., 2] << 1)
    return np.where(img != 0, out | 1, np.where(valid, out, 0)).astype(np.uint16)


def build_hues(src, out):
    cols = src.hues()
    arr = to5551(np.array(cols))
    with open(os.path.join(out, 'hues.bin'), 'wb') as f:
        f.write(struct.pack('<4sHHI', b'HUE1', 32, len(cols), 0))
        f.write(arr.astype('<u2').tobytes())
    return len(cols)


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


def ceilings(gx, gy, z, sid, sflags, sheight):
    """Distância em z até o piso/telhado mais próximo acima de cada item no mesmo tile (0 = nada
    acima, máx. 63): a malha é cortada ali para itens não atravessarem o andar de cima.
    Andar de cima = telhado ou piso (superfície sem altura); objetos pequenos apoiados em cima
    (reagentes numa vitrine, louça na mesa) não contam."""
    f = sflags[sid]
    st = ((f & np.uint64(SF_ROOF)) != 0) | (((f & np.uint64(SF_SURFACE)) != 0) & (sheight[sid] == 0))
    cell = gx.astype(np.int64) * 8192 + gy
    k = np.sort(cell[st] * 1024 + z[st] + 512)
    q = cell * 1024 + z + 512 + 3
    p = np.minimum(np.searchsorted(k, q), max(len(k) - 1, 0))
    if not len(k):
        return np.zeros(len(sid), np.int64)
    hit = (k[p] >= q) & (k[p] // 1024 == cell)
    return np.where(hit, np.minimum(k[p] - (cell * 1024 + z + 512), 63), 0)


def under_roof(gx, gy, z, sid, sflags, reach=12):
    """Itens com telhado no mesmo tile de 0 a reach z acima (empenas e oitões, que o 2D esconde junto com
    o telhado). ceilings() só olha a partir de z + 3 e perde a peça do topo, no z do próprio telhado."""
    roof = (sflags[sid] & np.uint64(SF_ROOF)) != 0
    cell = gx.astype(np.int64) * 8192 + gy
    k = np.sort(cell[roof] * 1024 + z[roof] + 512)
    if not len(k):
        return np.zeros(len(sid), bool)
    q = cell * 1024 + z + 512
    p = np.minimum(np.searchsorted(k, q), len(k) - 1)
    return (k[p] >= q) & (k[p] - q <= reach) & ~roof


def write_meshes(path, meshes):
    """MSH1: u32 magic, u32 vértices, u32 linhas | linhas × 2048 × i16[4], 2 texels por vértice:
    (lx·256, ly·256, lz·16, 0) (u·8, v·8, normal octaédrica ·32767). Devolve o 1º vértice de cada malha."""
    total = sum(len(m[0]) for m in meshes.values())
    rows = max(1, -(-total // 1024))
    t = np.zeros((rows * 1024, 2, 4), np.int16)
    first, o = {}, 0
    for s, (P, px, n) in meshes.items():
        k = len(P)
        t[o:o + k, 0, 0] = np.round(P[:, 0] * 256)
        t[o:o + k, 0, 1] = np.round(P[:, 1] * 256)
        t[o:o + k, 0, 2] = np.round(P[:, 2] * 16)
        t[o:o + k, 1, :2] = np.round(px * 8)
        t[o:o + k, 1, 2:] = np.round(oct_encode(n) * 32767)
        first[s] = o
        o += k
    with open(path, 'wb') as f:
        f.write(struct.pack('<4sII', b'MSH1', total, rows))
        f.write(t.astype('<i2').tobytes())
    return first, total


def fountain_groups(src, gx, gy, z, sid, snames):
    """Peças de chafariz vizinhas (mesmo z) formam um chafariz; cada sprite usa a malha do primeiro
    chafariz em que aparece. -> {sprite: malha}"""
    named = {s for s in np.unique(sid).tolist() if s < len(snames) and re.search(r'\bfountain\b', snames[s], re.I)}
    idx = np.nonzero(np.isin(sid, list(named)))[0]
    at = {(int(gx[i]), int(gy[i]), int(z[i])): int(sid[i]) for i in idx}
    out, seen = {}, set()
    for p0 in at:
        if p0 in seen:
            continue
        comp, stack = [], [p0]
        seen.add(p0)
        while stack:
            p = stack.pop()
            comp.append(p)
            for ddx in (-1, 0, 1):
                for ddy in (-1, 0, 1):
                    q = (p[0] + ddx, p[1] + ddy, p[2])
                    if q in at and q not in seen:
                        seen.add(q)
                        stack.append(q)
        if len(comp) < 4 or all(at[p] in out for p in comp):
            continue
        bx, by = min(p[0] for p in comp), min(p[1] for p in comp)
        pieces, sids = [], []
        for p in sorted(comp):
            img = src.static_art(at[p])
            if img is not None and img.any():
                pieces.append((p[0] - bx, p[1] - by, img))
                sids.append(at[p])
        res = fountain_meshes(pieces) if len(pieces) >= 4 else None
        for k, mesh in (res or {}).items():
            out.setdefault(sids[k], mesh)
    return out


def wall_plane_mesh(img, d):
    """Peça pendurada de arte frontal (armadura num suporte de parede): plano vertical paralelo à parede
    (d 1 = parede ao norte, 2 = a oeste), 22 px por tile ao longo dela e 4 px por z, como na tela do UO."""
    mask = img != 0
    x0, y0, x1, y1 = _bbox(mask)
    cx = (x0 + x1) / 2.0

    def place(sx, sy):
        t = (sx - cx) / HT
        z = 1.0 + (y1 - sy) / PZ
        a = np.full_like(t, 0.12)
        return np.stack([0.5 + t, a, z], 1) if d == 1 else np.stack([a, 0.5 - t, z], 1)
    return _plane_mesh(mask, place)


def hung_sprite(img, cat):
    """Arte alta e estreita de armadura/roupa: o sprite de peça pendurada num suporte."""
    if img is None or cat not in ('armor', 'clothing') or img.shape[0] < 66:
        return False
    x0, y0, x1, y1 = _bbox(img != 0)
    return x1 - x0 <= 26 and y1 - y0 >= 36


def build_statics(src, n, W, H, out_map):
    print('lendo statics...')
    sflags, sheight, snodraw, snames = src.static_tiledata()
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

    # tie = ordem de desenho do item dentro da célula, usado para desempatar profundidade. Como no cliente:
    # z, −1 se Background (piso), +1 se tem altura; empate fica na ordem do arquivo (entulho listado antes do
    # piso no mesmo z é desenhado por cima dele)
    cell = gy * W + gx
    sf = sflags[sid]
    pri = z.astype(np.int64) - ((sf & np.uint64(SF_BACKGROUND)) != 0) + (sheight[sid] > 0)
    order = np.lexsort((np.arange(len(cell)), pri, cell))
    cs = cell[order]
    start = np.r_[0, np.nonzero(np.diff(cs))[0] + 1]
    rank = np.arange(len(cs)) - np.repeat(start, np.diff(np.r_[start, len(cs)]))
    tie = np.empty_like(rank)
    tie[order] = np.minimum(rank, 15)

    print('decodificando sprites e gerando malhas...')
    tx = _load_taxonomy()
    # peças penduradas com parede vizinha viram variantes do sprite (id + 0x10000·lado): o plano acompanha a parede
    vid = sid.copy()
    hung = set()
    for s in np.unique(sid).tolist():
        nm = snames[s] if s < len(snames) else ''
        if not re.search(r'tunic|leggings|sleeves|armor|gorget|gloves|helm|cap|shield|robe|dress|cloak|mask|kilt|tabard|sash|cap\b', nm, re.I):
            continue
        a_ = src.static_art(s)
        if a_ is None or not a_.any():
            continue
        m_ = a_ != 0
        bx0, by0, bx1, by1 = _bbox(m_)
        ar_ = int(m_.sum())
        cat_, _sub = categorize(tx, nm, int(sflags[s]), ar_, ar_ / ((bx1 - bx0) * (by1 - by0)))
        if hung_sprite(a_, cat_):
            hung.add(s)
    walls = np.array([bool(re.search(r'\bwall\b', n or '', re.I)) for n in snames], bool)
    wcells = np.unique((gy * W + gx)[walls[np.minimum(sid, len(walls) - 1)]])
    is_h = np.isin(sid, list(hung))
    north = is_h & np.isin((gy - 1) * W + gx, wcells)
    west = is_h & ~north & np.isin(gy * W + gx - 1, wcells)
    vid = np.where(north, sid + 0x10000, np.where(west, sid + 0x20000, sid))
    print(f'  {len(hung)} sprites pendurados, {int(is_h.sum())} instâncias, {int(north.sum() + west.sum())} na parede, {len(wcells)} células de parede')
    sprites, imgs, meshes = {}, {}, {}
    engines = {}
    fountain = fountain_groups(src, gx, gy, z, sid, snames)
    for s in np.unique(vid).tolist():
        img = src.static_art(s & 0xFFFF)
        if img is None or not img.any():
            continue
        imgs[s] = img
        if s >= 0x10000:
            meshes[s] = wall_plane_mesh(img, s >> 16)
            sprites[s] = (SK_MESH, None)
            engines['pendurado'] = engines.get('pendurado', 0) + 1
            continue
        if s in fountain:
            meshes[s] = fountain[s]
            sprites[s] = (SK_MESH, None)
            engines['chafariz'] = engines.get('chafariz', 0) + 1
            continue
        name = snames[s] if s < len(snames) else ''
        roof = int(sflags[s]) & SF_ROOF
        if roof or re.search(r'\broof', name, re.I):
            # telhas sem a flag de telhado (stone/marble/slate roof) também viram plano inclinado, se
            # a silhueta for de telha; oitões e empenas com esse nome seguem como peça comum
            iou, e, c, sx, sy = fit_slope(img != 0)
            if roof or iou >= 0.85:
                sprites[s] = (SK_SLOPE, (e, c, sx, sy, 0, 0))
                engines['telhado'] = engines.get('telhado', 0) + 1
                continue
        mask = img != 0
        x0, y0, x1, y1 = _bbox(mask)
        area = int(mask.sum())
        cat, sub = categorize(tx, snames[s] if s < len(snames) else '', int(sflags[s]), area,
                              area / ((x1 - x0) * (y1 - y0)))
        if cat == 'unknown' and sheight[s] <= 1 and floor_iou(mask) >= 0.85:
            cat, sub = 'architecture', 'floor'  # losango de chão sem nome conhecido (placas das virtudes)
        eng, mesh = sprite_mesh(img, tx, cat, sub, snames[s] if s < len(snames) else '', int(sheight[s]),
                                bool(int(sflags[s]) & SF_SURFACE))
        meshes[s] = mesh
        sprites[s] = (SK_MESH, None)
        engines[eng] = engines.get(eng, 0) + 1
    print('  ' + ', '.join(f'{k} {v}' for k, v in sorted(engines.items())))
    mfirst, mtotal = write_meshes(os.path.join(out_map, 'meshes.bin'), meshes)
    print(f'  malhas: {mtotal} vértices ({mtotal * 16 / 1e6:.1f} MB)')
    partial = ((sflags[sid] & np.uint64(SF_PARTIAL_HUE)) != 0).astype(np.int64)
    ceil = ceilings(gx, gy, z, sid, sflags, sheight)
    hide = (((ceil > 0) & (ceil <= 12)) | under_roof(gx, gy, z, sid, sflags)).astype(np.int64)

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
    nverts = np.zeros(len(index), np.int64)
    for s, i in index.items():
        p, ax, ay = place[s]
        tx_, ty, tw, th = trims[s]
        atlas[p, ay:ay + th, ax:ax + tw] = bleed(imgs[s][ty:ty + th, tx_:tx_ + tw])
        kind, params = sprites[s]
        h, w = imgs[s].shape
        if kind == SK_MESH:
            o = mfirst[s]
            nverts[i] = len(meshes[s][0])
            params = [o & 0xFFFF, o >> 16, nverts[i], 0, 0, 0]
        else:
            params = [int(round(v * 64)) & 0xFFFF for v in params]
        table[i] = [ax, ay, tw, th, tx_, ty, w, h, kind | (p << 8), s & 0xFFFF] + params   # 9: graphic (Itens 3D do viewer)
    with open(os.path.join(out_map, 'atlas.bin'), 'wb') as f:
        f.write(struct.pack('<4sHHI', b'ATL1', ATLAS, pages, 0))
        f.write(atlas.astype('<u2').tobytes())
    with open(os.path.join(out_map, 'sprites.bin'), 'wb') as f:
        f.write(struct.pack('<4sII', b'SPR1', len(index), len(table)))
        f.write(table.astype('<u2').tobytes())
    print(f'  atlas {pages} página(s) {ATLAS}², tabela {len(index)} sprites')
    old = os.path.join(out_map, 'groups.bin')
    if os.path.exists(old):
        os.remove(old)

    # chunks STA2: instâncias agrupadas por lote (0 = telhado, k = malhas de até MESH_CLASSES[k] vértices)
    print('gravando chunks de statics...')
    ok = np.isin(vid, list(index))
    vid = vid[ok]
    gx, gy, z, sid, hue, tie, partial, ceil, hide = (gx[ok], gy[ok], z[ok], sid[ok], hue[ok], tie[ok], partial[ok],
                                                     ceil[ok], hide[ok])
    top = int(vid.max()) + 1
    lut = np.zeros(top, np.int64)
    kind_lut = np.zeros(top, np.int64)
    for s, i in index.items():
        if s < top:
            lut[s] = i
            kind_lut[s] = 0 if sprites[s][0] == SK_SLOPE else int(np.searchsorted(MESH_CLASSES, nverts[i]))
    kind = kind_lut[vid]
    hh = hue & 0x3FFF
    hh = np.where(hh > 3000, 0, hh)
    # bit 25: some com os telhados desligados; bits 26–31: teto (z até o andar de cima), corta a malha
    ceil = np.clip(ceil, 0, 63)
    A = (gx & 63) | ((gy & 63) << 6) | ((z + 128) << 12) | (tie << 20) | (partial << 24) | (hide << 25) | (ceil << 26)
    # telhados usam os bits 25–31 para a inclinação vinda dos vizinhos: tem:1 gx:3 gy:3 (×1,5 z, +4)
    has, qx, qy = roof_slopes(gx, gy, z, kind == 0)
    A = np.where(kind == 0, (A & 0x1FFFFFF) | (has << 25) | (qx << 26) | (qy << 29), A).astype('<u4')
    B = (lut[vid] | (hh << 16)).astype('<u4')
    cw, ch = -(-W // CHUNK), -(-H // CHUNK)
    cid = (gy // CHUNK) * cw + gx // CHUNK
    order = np.lexsort((kind, cid))
    cid, kind, A, B = cid[order], kind[order], A[order], B[order]
    bounds = np.r_[0, np.nonzero(np.diff(cid))[0] + 1, len(cid)]
    exists = np.zeros(cw * ch, np.uint8)
    os.makedirs(os.path.join(out_map, 'statics'), exist_ok=True)
    nk = len(MESH_CLASSES)
    total = 0
    for a, b in zip(bounds[:-1], bounds[1:]):
        c = int(cid[a])
        cnt = np.bincount(kind[a:b], minlength=nk).tolist()
        data = (struct.pack(f'<4sHHII{nk}I', b'STA2', c % cw, c // cw, int(b - a), nk, *cnt)
                + A[a:b].tobytes() + B[a:b].tobytes())
        with open(os.path.join(out_map, 'statics', f'{c % cw}_{c // cw}.bin'), 'wb') as f:
            f.write(data)
        exists[c] = 1
        total += len(data)
    print(f'  {len(bounds) - 1} chunks, {len(A)} instâncias, {total / 1e6:.1f} MB')
    return {
        'staticsChunks': base64.b64encode(np.packbits(exists, bitorder='little').tobytes()).decode(),
        'sprites': len(index), 'atlasPages': pages, 'meshVerts': int(mtotal), 'meshClasses': list(MESH_CLASSES),
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
        return flags, height, nodraw, [''] * len(flags)

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
    # void com static abaixo (vão da escada do porão): o cliente não desenha o void, então o chão
    # vira buraco ali e o que está embaixo aparece; o resto do void segue preto
    sflags = src.static_tiledata()[0]
    sx, sy, sz, ssid, _ = src.read_statics(n, W, H)
    ok = ssid < len(sflags)
    sx, sy, sz = sx[ok], sy[ok], sz[ok]
    low = np.isin(tid[sy, sx], list(VOID_LAND)) & (sz < z[sy, sx])
    mat[sy[low], sx[low]] = HOLE
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

def find_classic_client(start):
    """Sobe a partir de start até a pasta do cliente Classic (a que tem artLegacyMUL.uop): serve também em worktrees."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, 'artLegacyMUL.uop')):
            return d
        up = os.path.dirname(d)
        if up == d:
            sys.exit('pasta do cliente Classic não encontrada: passe --client <pasta com artLegacyMUL.uop>')
        d = up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', choices=('enhanced', 'classic'), default='classic')
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
        src = ClassicSource(a.client or find_classic_client(HERE))
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


