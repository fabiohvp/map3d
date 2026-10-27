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
#   hull    "almofada" fechada inflada da silhueta; a casca da frente reprojeta exatamente no sprite
#   flat    silhueta deitada no chão (tapetes, decalques, pisos que não fecham como caixa)
#   card    casco fino (efeitos, armas, quadros e sprites esparsos)
HT = 22.0
SQ2 = 2 ** 0.5
PXP = HT * SQ2           # px por tile no eixo horizontal da tela
PZ = 4.0                 # px por unidade de z
METRIC_Z = 0.1           # 1 z = 0,1 tile: referencial "métrico" das normais
MIN_DIM = 0.08
HULL_CELLS = 32          # células da grade do casco (o assets3d usa 420; aqui são milhões de instâncias)
CARD_CELLS = 16          # casco fino: o recorte da art (alpha) já dá a silhueta
FLAT_CELLS = 12
FLAT_THICK = 0.4         # espessura do slab deitado, em z
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


def hexagon_iou(mask, boxes, of_mask=False):
    """IoU entre a silhueta e a projeção das caixas (cada uma = fecho convexo dos seus 8 cantos).
    of_mask: fração da silhueta coberta (o recorte por alpha apaga o que sobra da caixa)."""
    h, w = mask.shape
    vv, uu = np.mgrid[0:h, 0:w] + 0.5
    cover = np.zeros((h, w), bool)
    for box in boxes:
        poly = _convex(_proj(_box_corners(*box), w, h))
        inside = np.ones((h, w), bool)
        for i in range(len(poly)):
            (ax, ay), (bx, by) = poly[i], poly[(i + 1) % len(poly)]
            inside &= (bx - ax) * (vv - ay) - (by - ay) * (uu - ax) >= -1e-9
        cover |= inside
    inter = (cover & mask).sum()
    union = mask.sum() if of_mask else (cover | mask).sum()
    return float(inter) / float(union) if union else 0.0


WALL_LIKE = {'architecture/wall', 'architecture/window', 'architecture/door', 'architecture/fence',
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


def _cells(mask, c):
    h, w = mask.shape
    R, C = -(-h // c), -(-w // c)
    pad = np.zeros((R * c, C * c), np.float32)
    pad[:h, :w] = mask
    return pad.reshape(R, c, C, c).mean(axis=(1, 3)) >= 0.3


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


def flat_mesh(mask, t=FLAT_THICK, target=FLAT_CELLS):
    """Silhueta desprojetada no chão: pele de cima (na altura t), base e paredes laterais na borda."""
    h, w = mask.shape
    x0, y0, x1, y1 = _bbox(mask)
    m = mask[y0:y1, x0:x1]
    c = max(1, int(math.ceil(math.sqrt(max(int(m.sum()), 1) / target))))
    cin = _cells(m, c)
    if not cin.any():
        c, cin = 1, _cells(m, 1)
    R, C = cin.shape
    ii, jj, vid = _grid(cin)
    sx = np.minimum(x0 + jj * c, x1).astype(float)
    sy = (y0 + np.minimum(ii * c, y1 - y0)).astype(float)

    def ground(z):
        d = (sx - w / 2) / HT                       # lx − ly
        s = (sy - (h - 44) + PZ * z) / HT           # lx + ly
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
    frente e verso se afastam ±T dele na horizontal, soldados na borda. A altura de cada vértice sai da
    linha do pixel (última linha da art ≈ chão). Assim peças do mesmo tile (tronco e copa
    de uma árvore) ficam centradas no tile e alinhadas entre si; o assets3d aterra cada sprite pelo próprio
    pixel mais baixo, o que jogava o tronco no canto da frente do tile e a copa para trás.
    A borda de baixo conta como interior (espelhada para baixo): base com volume."""
    h, w = mask.shape
    ax = w / 2
    x0, y0, x1, y1 = _bbox(mask)
    m = mask[y0:y1, x0:x1]
    c = max(1, int(math.ceil(math.sqrt(max(int(m.sum()), 1) / target))))
    cin = _cells(m, c)
    if not cin.any():
        c, cin = 1, _cells(m, 1)
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
    p = (sx - ax) / PXP

    lz = (h - sy) / PZ
    # o pé do objeto fica um pouco acima da última linha da art: desce até 4 z (copas, que começam bem
    # mais alto, descem os mesmos 4 z que o tronco e continuam alinhadas com ele)
    lz -= min(float(lz.min()), 4.0)
    q_c = 1 / SQ2                                     # centro do tile: lx + ly = 1
    qf, qb = q_c + Tf, q_c - Tf
    front = np.stack([(qf + p) / SQ2, (qf - p) / SQ2, lz], 1)
    back = np.stack([(qb + p) / SQ2, (qb - p) / SQ2, lz], 1)
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


def sprite_mesh(img, tx, cat, sub, name='', height=0, surface=False):
    """-> (motor, (pos, pixel, normal)) em listas de triângulos."""
    mask = img != 0
    arch = archetype(tx, cat, sub)
    rho = tx['default_depth_ratio'].get(f'{cat}/{sub}', tx['category_default_depth_ratio'].get(cat, 0.5))
    if arch == 'flat':
        return 'flat', flat_mesh(mask)
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


def ceilings(gx, gy, z, sid, sflags):
    """Distância em z até o piso/telhado mais próximo acima de cada item no mesmo tile (0 = nada
    acima, máx. 63): a malha é cortada ali para itens não atravessarem o andar de cima."""
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

    # tie = ordem do item dentro da célula (ordem do arquivo), usado para desempatar profundidade
    cell = gy * W + gx
    order = np.argsort(cell, kind='stable')
    cs = cell[order]
    start = np.r_[0, np.nonzero(np.diff(cs))[0] + 1]
    rank = np.arange(len(cs)) - np.repeat(start, np.diff(np.r_[start, len(cs)]))
    tie = np.empty_like(rank)
    tie[order] = np.minimum(rank, 15)

    print('decodificando sprites e gerando malhas...')
    tx = _load_taxonomy()
    sprites, imgs, meshes = {}, {}, {}
    engines = {}
    for s in np.unique(sid).tolist():
        img = src.static_art(s)
        if img is None or not img.any():
            continue
        imgs[s] = img
        if int(sflags[s]) & SF_ROOF:
            iou, e, c, sx, sy = fit_slope(img != 0)
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
    ceil = ceilings(gx, gy, z, sid, sflags)

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
        table[i] = [ax, ay, tw, th, tx_, ty, w, h, kind | (p << 8), 0] + params
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
    ok = np.isin(sid, list(index))
    gx, gy, z, sid, hue, tie, partial, ceil = gx[ok], gy[ok], z[ok], sid[ok], hue[ok], tie[ok], partial[ok], ceil[ok]
    top = int(sid.max()) + 1
    lut = np.zeros(top, np.int64)
    kind_lut = np.zeros(top, np.int64)
    for s, i in index.items():
        if s < top:
            lut[s] = i
            kind_lut[s] = 0 if sprites[s][0] == SK_SLOPE else int(np.searchsorted(MESH_CLASSES, nverts[i]))
    kind = kind_lut[sid]
    hh = hue & 0x3FFF
    hh = np.where(hh > 3000, 0, hh)
    # bits 26–31: teto (z até o andar de cima), corta a malha
    ceil = np.clip(ceil, 0, 63)
    A = (gx & 63) | ((gy & 63) << 6) | ((z + 128) << 12) | (tie << 20) | (partial << 24) | (ceil << 26)
    # telhados usam os bits 25–31 para a inclinação vinda dos vizinhos: tem:1 gx:3 gy:3 (×1,5 z, +4)
    has, qx, qy = roof_slopes(gx, gy, z, kind == 0)
    A = np.where(kind == 0, (A & 0x1FFFFFF) | (has << 25) | (qx << 26) | (qy << 29), A).astype('<u4')
    B = (lut[sid] | (hh << 16)).astype('<u4')
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


