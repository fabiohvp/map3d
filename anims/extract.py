"""Extrai as animacoes classicas (anim*.mul) para anims/data e gera um modelo 3D (voxels) de cada quadro.

Uso: python -I anims/extract.py [--client <pasta Classic>] [--only 400,1,9] [--grid 64] [--jobs N] [--no-3d] [--thumbs]
                               [--smooth 2] [--scan 2] [--fill 2]

Analise: as 5 direcoes gravadas de uma acao sao o mesmo modelo 3D renderizado em camera ortografica fixa, girado de
45 em 45 graus. Com a elevacao certa, as silhuetas se reprojetam quase sem erro (IoU ~0,98 com atan(1/2) = 26,57 graus,
a projecao 2:1 do UO; calibrado com --calib). Entao cada quadro vira um casco visual: voxel fica se cai dentro da
silhueta nas 5 vistas. A cor de cada voxel de superficie vem da vista em que ele aparece mais de frente.

Saida (anims/data):
  index.json         corpos (id, tipo, arquivo de origem, acoes com n de quadros, thumb = celula em thumbs.png)
  thumbs.png         miniaturas 64x64 em grade de 32 colunas
  2d/<id>.png(.N)    quadros originais em atlas (RGBA)
  2d/<id>.json       retangulos: act[acao][dir 0..4][quadro] = [pagina, x, y, w, h, cx, cy]
  3d/<id>.bin.gz     voxels; 3d/<id>.json = {s, theta, o:[x0,y0,z0], n:[nx,ny,nz], smooth, act[acao][quadro] = [off, nvox]}
                     smooth: cor suavizada (--smooth, ver SMOOTH), em vez do pixel da vista mais de frente
                     scan: cor por varredura pixel a pixel dos 8 angulos do 2D (--scan, ver bake); forma igual
    em off: uint8 xyz[3n] (indices no grid), alinhado a 2, uint16 cor[n] (RGB565)
    posicao do voxel em pixels do sprite: (i + x0) * s; x = direita, y = para a camera, z = para cima
"""
import argparse, gzip, json, math, os, sys, time
from multiprocessing import Pool
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import uoanim as U   # noqa: E402

THETA = math.degrees(math.atan(0.5))   # elevacao da camera dos sprites
SIGN = 1                               # direcao do arquivo k = modelo girado +45k graus
ATLAS_W = 2048
PAGE_H = 8192

_A = None
_ARGS = None


def _init(client, args):
    global _A, _ARGS
    _A = U.Anims(client)
    _ARGS = args


def load_body(body):
    """{acao: (nome, [[quadros] por direcao 0..4])}, quadros com rgba."""
    out = {}
    for a, name, raws in _A.actions(body):
        dirs = []
        for r in raws:
            pal, fr = U.decode(r)
            for f in fr:
                rgba = np.zeros((f['h'], f['w'], 4), np.uint8)
                rgba[..., :3] = pal[f['idx']]
                rgba[..., 3] = f['mask'] * 255
                f['rgba'] = rgba
            dirs.append(fr)
        if any(dirs):
            out[a] = (name, dirs)
    return out


# ---------------------------------------------------------------- 2D

def pack_2d(body, acts, outdir):
    frames = [(a, d, i, f) for a, (_, dirs) in acts.items() for d, fr in enumerate(dirs) for i, f in enumerate(fr)]
    order = sorted(range(len(frames)), key=lambda k: -frames[k][3]['h'])
    area = sum(f['w'] * f['h'] for *_, f in frames)
    W = int(min(ATLAS_W, max(max(f['w'] for *_, f in frames), math.sqrt(area) * 1.15)))
    pos, pages, x, y, rowh, ph = {}, [], 0, 0, 0, []
    for k in order:
        f = frames[k][3]
        if x + f['w'] > W:
            x, y, rowh = 0, y + rowh + 1, 0
        if y + f['h'] > PAGE_H:
            ph.append(y)
            x, y, rowh = 0, 0, 0
        pos[k] = (len(ph), x, y)
        x += f['w'] + 1
        rowh = max(rowh, f['h'])
    ph.append(y + rowh)
    imgs = [np.zeros((max(h, 1), W, 4), np.uint8) for h in ph]
    rects = {}
    for k, (a, d, i, f) in enumerate(frames):
        p, x, y = pos[k]
        imgs[p][y:y + f['h'], x:x + f['w']] = f['rgba']
        rects.setdefault(a, [[] for _ in range(5)])[d].append([p, x, y, f['w'], f['h'], f['cx'], f['cy']])
    # ate 255 cores no corpo: PNG com paleta (exato, bem menor); senao WebP sem perda
    rgb = np.concatenate([f['rgba'][f['mask']][:, :3] for *_, f in frames])
    key = (rgb[:, 0].astype(np.uint32) << 16) | (rgb[:, 1].astype(np.uint32) << 8) | rgb[:, 2]
    cols = np.unique(key)
    ext = 'png' if len(cols) <= 255 else 'webp'
    for p, im in enumerate(imgs):
        fn = os.path.join(outdir, f'{body}.{ext}' if p == 0 else f'{body}.{p}.{ext}')
        if ext == 'png':
            k = (im[..., 0].astype(np.uint32) << 16) | (im[..., 1].astype(np.uint32) << 8) | im[..., 2]
            ind = (np.searchsorted(cols, k) + 1).astype(np.uint8)
            ind[im[..., 3] == 0] = 0
            pim = Image.fromarray(ind, 'P')
            pal = np.zeros((256, 3), np.uint8)
            pal[1:len(cols) + 1] = np.stack([cols >> 16, (cols >> 8) & 255, cols & 255], 1)
            pim.putpalette(pal.ravel().tolist())
            pim.save(fn, transparency=0, optimize=True)
        else:
            Image.fromarray(im).save(fn, lossless=True, method=4)
    json.dump({'pages': len(imgs), 'ext': ext, 'act': rects}, open(os.path.join(outdir, f'{body}.json'), 'w'),
              separators=(',', ':'))


# ---------------------------------------------------------------- 3D

def project_f(P, ang):
    """como project, em float e com angulo em graus: (x na tela, y na tela para baixo, profundidade para a camera)."""
    th, ph = math.radians(THETA), math.radians(ang) * SIGN
    xr = P[:, 0] * math.cos(ph) - P[:, 1] * math.sin(ph)
    yr = P[:, 0] * math.sin(ph) + P[:, 1] * math.cos(ph)
    sy = -P[:, 2] * math.cos(th) + yr * math.sin(th)
    depth = yr * math.cos(th) + P[:, 2] * math.sin(th)
    return xr, sy, depth


# os 8 angulos do 2D: (direcao do arquivo, angulo da vista, espelhada). As espelhadas sao o sprite invertido visto
# do outro lado (-45k graus), como o UO desenha as direcoes 0..2 do jogo.
ANGLES_2D = [(k, 45 * k, False) for k in range(5)] + [(k, -45 * k, True) for k in (1, 2, 3)]


def fill_views(g, views, occ, rounds=4, extra=()):
    """Amplia o casco ate cobrir todo pixel de sprite nos 8 angulos do 2D: o casco das 5 vistas perde partes (as
    vistas do UO nao sao 100% coerentes e as espelhadas nem entram no corte). Pixel coberto = centro do pixel dentro
    da area garantida de algum cubo projetado (caixa de +-0,44 voxel em volta do centro: o cubo projetado sempre
    contem esse quadrado). Para cada pixel descoberto, liga o voxel cuja area o cobre e que mais angulos aceitam (no
    empate, o mais perto do casco). O excesso que isso cria em outro angulo nao aparece: a textura descarta o que cai
    fora da imagem daquele angulo. extra: (quadro, angulo) a mais, as imagens geradas por viewmorph.py."""
    flat = occ.ravel().copy()
    score = np.zeros(len(g.P), np.int16)
    rin = 0.44 * g.s
    span = int(math.ceil(rin)) + 1
    proj = []
    todos = [(views[fd], ang, mir) for fd, ang, mir in ANGLES_2D] + [(f, ang, False) for f, ang in extra]
    for f, ang, mirror in todos:
        if f is None:
            continue
        sx, sy, _ = project_f(g.P, ang)
        if mirror:
            sx = -sx
        X, Y = f['cx'] + sx, f['cy'] + f['h'] + sy
        px, py = np.floor(X).astype(int), np.floor(Y).astype(int)
        ok = (px >= 0) & (px < f['w']) & (py >= 0) & (py < f['h'])
        score += ok & f['dil'].ravel()[np.where(ok, py * f['w'] + px, 0)]
        # pares (voxel, pixel) com o centro do pixel na area garantida do cubo
        pairs_v, pairs_p = [], []
        for oy in range(-span, span + 1):
            for ox in range(-span, span + 1):
                qx, qy = px + ox, py + oy
                inside = (np.abs(qx + 0.5 - X) <= rin) & (np.abs(qy + 0.5 - Y) <= rin)
                inside &= (qx >= 0) & (qx < f['w']) & (qy >= 0) & (qy < f['h'])
                v = np.flatnonzero(inside)
                pairs_v.append(v)
                pairs_p.append(qy[v] * f['w'] + qx[v])
        proj.append((f, np.concatenate(pairs_v), np.concatenate(pairs_p)))
    added = 0
    for _ in range(rounds):
        near = ndimage.distance_transform_edt(~flat.reshape(g.n)).ravel()
        new = 0
        for f, pv, pp in proj:
            cov = np.zeros(f['h'] * f['w'], bool)
            cov[pp[flat[pv]]] = True
            miss = f['mask'].ravel() & ~cov
            if not miss.any():
                continue
            sel = np.flatnonzero(miss[pp])
            if not len(sel):
                continue
            cv, cp = pv[sel], pp[sel]
            key = score[cv].astype(np.float64) * 1000 - near[cv]
            order = np.argsort(-key, kind='stable')
            _, first = np.unique(cp[order], return_index=True)
            pick = cv[order[first]]
            new += int((~flat[pick]).sum())
            flat[pick] = True
        added += new
        if not new:
            break
    return flat.reshape(occ.shape), added


def bake(g, views, si, base):
    """Textura por varredura: para cada angulo do 2D desenha os cubos de superficie como o visualizador (projecao
    do UO, z-buffer), ve qual voxel aparece em cada pixel e soma nele a cor do pixel do sprite. Cor final = media
    de todos os pixels recebidos, de todos os angulos; voxel que nenhum angulo mostra fica com a cor base."""
    P = g.P[si]
    n = len(si)
    acc = np.zeros((n, 3), np.float64)
    cnt = np.zeros(n, np.float64)
    h = g.s / 2
    corners = np.array([(a, b, c) for a in (-h, h) for b in (-h, h) for c in (-h, h)], np.float32)
    for fdir, ang, mirror in ANGLES_2D:
        f = views[fdir]
        if f is None:
            continue
        sx, sy, depth = project_f(P, ang)
        if mirror:
            sx = -sx
        # caixa do cubo projetado (igual para todos os voxels)
        cx_, cy_, _ = project_f(corners, ang)
        ex, ey = float(np.abs(cx_).max()), float(np.abs(cy_).max())
        X = f['cx'] + sx
        Y = f['cy'] + f['h'] + sy
        # pixels cujo centro cai dentro da caixa do cubo
        x0 = np.ceil(X - ex - 0.5).astype(int)
        y0 = np.ceil(Y - ey - 0.5).astype(int)
        x1 = np.floor(X + ex - 0.5).astype(int)
        y1 = np.floor(Y + ey - 0.5).astype(int)
        W, H = f['w'], f['h']
        zb = np.full(W * H, -np.inf)
        spans = []
        for oy in range(int(math.ceil(2 * ey)) + 1):
            for ox in range(int(math.ceil(2 * ex)) + 1):
                px, py = x0 + ox, y0 + oy
                ok = (px <= x1) & (py <= y1) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
                v = np.flatnonzero(ok)
                pix = py[v] * W + px[v]
                np.maximum.at(zb, pix, depth[v])
                spans.append((v, pix))
        owner = np.full(W * H, -1)
        for v, pix in spans:
            win = depth[v] >= zb[pix] - 1e-4
            owner[pix[win]] = v[win]
        m = f['mask'].ravel() & (owner >= 0)
        ids = owner[m]
        np.add.at(acc, ids, f['rgba'].reshape(-1, 4)[m, :3].astype(np.float64))
        np.add.at(cnt, ids, 1)
    col = base.astype(np.float64)
    ok = cnt > 0
    col[ok] = acc[ok] / cnt[ok, None]
    return np.clip(np.round(col), 0, 255).astype(np.uint8), float(ok.mean())


def project(P, k):
    """deslocamento inteiro em pixels (dx, dy) dos pontos P (em pixels do modelo) na vista k, relativo a ancora."""
    th, ph = math.radians(THETA), math.radians(45 * k) * SIGN
    xr = P[:, 0] * math.cos(ph) - P[:, 1] * math.sin(ph)
    yr = P[:, 0] * math.sin(ph) + P[:, 1] * math.cos(ph)
    return np.round(xr).astype(np.int32), np.round(-P[:, 2] * math.cos(th) + yr * math.sin(th)).astype(np.int32)


def union_view(frames):
    """silhueta dilatada de todos os quadros de uma direcao, alinhados pela ancora (no formato de quadro)."""
    L = max(f['cx'] for f in frames)
    Rt = max(f['w'] - f['cx'] for f in frames)
    Up = max(f['cy'] + f['h'] for f in frames)
    Dn = max(max(-f['cy'] for f in frames), 0)
    W, H = L + Rt, Up + Dn
    m = np.zeros((H, W), bool)
    for f in frames:
        x, y = L - f['cx'], Up - (f['cy'] + f['h'])
        m[y:y + f['h'], x:x + f['w']] |= f['dil']
    return {'cx': L, 'cy': Up - H, 'w': W, 'h': H, 'dil': m}


def axes(o, n):
    X, Y, Z = np.meshgrid(*(np.arange(k) + a for k, a in zip(n, o)), indexing='ij')
    return np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1).astype(np.float32)


class Grid:
    """Grid de voxels do corpo e o deslocamento em pixels de cada voxel em cada vista (relativo a ancora).
    O tamanho do voxel (s, em pixels) vem do quadro mais alto; os limites saem de um casco grosso feito com a
    uniao das silhuetas de cada direcao, para nao gastar voxels no vazio."""

    MAX_VOX = 3_500_000

    def __init__(self, acts, target):
        th = math.radians(THETA)
        dirs = [[] for _ in range(5)]
        for _, ds in acts.values():
            for k, d in enumerate(ds):
                dirs[k] += d
        un = [union_view(d) if d else None for d in dirs]
        fr = [f for d in dirs for f in d]
        R = max(max(f['cx'], f['w'] - f['cx']) for f in fr) + 2
        up = max(f['cy'] + f['h'] for f in fr) + 2
        dn = max(max(-f['cy'] for f in fr), 0) + 2
        s = max(1.0, max(f['h'] for f in fr) / target)
        while True:
            c = 3                                  # passo do casco grosso, em voxels
            n = int(math.ceil(R / s / c))
            z0 = int(math.floor(-(dn + R * math.sin(th)) / (s * math.cos(th)) / c))
            z1 = int(math.ceil((up + R * math.sin(th)) / (s * math.cos(th)) / c))
            Q = axes((-n, -n, z0), (2 * n + 1, 2 * n + 1, z1 - z0 + 1)) * (c * s)
            keep = np.ones(len(Q), bool)
            for k, u in enumerate(un):
                if u is not None:
                    keep &= frame_lookup(u, *project(Q, k))[0] | self._near(u, Q, k, c * s)
            Q = Q[keep] / s
            lo = np.floor(Q.min(0)).astype(int) - c - 1
            hi = np.ceil(Q.max(0)).astype(int) + c + 1
            dims = hi - lo + 1
            if dims.prod() <= self.MAX_VOX and dims.max() <= 255:
                break
            s *= max(1.05, (dims.prod() / self.MAX_VOX) ** (1 / 3), dims.max() / 255)
        self.s, self.o, self.n = s, tuple(int(v) for v in lo), tuple(int(v) for v in dims)
        self.P = axes(self.o, self.n) * s
        self.dx, self.dy, self.v = [], [], []
        for k in range(5):
            dx, dy = project(self.P, k)
            self.dx.append(dx)
            self.dy.append(dy)
            ph = math.radians(45 * k) * SIGN
            # vetor do modelo para a camera nessa vista
            self.v.append(np.array([math.cos(th) * math.sin(ph), math.cos(th) * math.cos(ph), math.sin(th)], np.float32))

    @staticmethod
    def _near(u, Q, k, step):
        """celula grossa encosta na silhueta (testa os cantos do cubo, nao so o centro)."""
        hit = np.zeros(len(Q), bool)
        h = step / 2
        for sx in (-h, h):
            for sy in (-h, h):
                for sz in (-h, h):
                    hit |= frame_lookup(u, *project(Q + np.array([sx, sy, sz], np.float32), k))[0]
        return hit


def frame_lookup(f, dx, dy):
    """(dentro da silhueta dilatada, px, py) para os voxels nessa vista."""
    ax, ay = f['cx'], f['cy'] + f['h']
    px, py = ax + dx, ay + dy
    ok = (px >= 0) & (px < f['w']) & (py >= 0) & (py < f['h'])
    inside = np.zeros(len(px), bool)
    inside[ok] = f['dil'][py[ok], px[ok]]
    return inside, px, py


def carve(g, views, smooth=False, scan=False, fill=False, extra=()):
    """views: quadro por direcao (ou None). -> (ijk uint8 Nx3, cor RGB565) dos voxels de superficie."""
    idx = np.arange(len(g.P))
    for k, f in enumerate(views):
        if f is None:
            continue
        inside, _, _ = frame_lookup(f, g.dx[k][idx], g.dy[k][idx])
        idx = idx[inside]
        if len(idx) == 0:
            return None
    nx, ny, nz = g.n
    occ = np.zeros(nx * ny * nz, bool)
    occ[idx] = True
    occ = occ.reshape(nx, ny, nz)
    if fill:
        occ, _ = fill_views(g, views, occ, extra=extra)
    surf = occ & ~ndimage.binary_erosion(occ, border_value=0)
    si = np.flatnonzero(surf.ravel())
    if len(si) == 0:
        return None
    # normal pela borda suavizada da ocupacao
    sm = ndimage.uniform_filter(occ.astype(np.float32), 3)
    I, J, K = np.unravel_index(si, g.n)
    Ip, Im = np.minimum(I + 1, nx - 1), np.maximum(I - 1, 0)
    Jp, Jm = np.minimum(J + 1, ny - 1), np.maximum(J - 1, 0)
    Kp, Km = np.minimum(K + 1, nz - 1), np.maximum(K - 1, 0)
    N = -np.stack([sm[Ip, J, K] - sm[Im, J, K], sm[I, Jp, K] - sm[I, Jm, K], sm[I, J, Kp] - sm[I, J, Km]], 1)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-6)
    best = np.full(len(si), -9.0, np.float32)
    col = np.zeros((len(si), 3), np.uint8)
    seen = np.zeros(len(si), bool)
    cand = []
    for k, f in enumerate(views):
        if f is None:
            continue
        _, px, py = frame_lookup(f, g.dx[k][si], g.dy[k][si])
        px = np.clip(px, 0, f['w'] - 1)
        py = np.clip(py, 0, f['h'] - 1)
        depth = g.P[si] @ g.v[k]
        zb = np.full(f['w'] * f['h'], -1e9, np.float32)
        pix = py * f['w'] + px
        np.maximum.at(zb, pix, depth)
        vis = depth >= zb[pix] - 1.5 * g.s
        # pixel mais proximo dentro da silhueta original (a dilatacao pode cair fora)
        qy, qx = f['near'][0][py, px], f['near'][1][py, px]
        c = (f['box'] if smooth and smooth['box'] else f['rgba'])[qy, qx, :3]
        score = N @ g.v[k]
        cand.append((score, vis, c))
    for score, vis, c in cand:                  # primeiro so vistas que enxergam o voxel
        m = vis & (score > best)
        best[m], col[m], seen[m] = score[m], c[m], True
    for score, vis, c in cand:                  # voxels escondidos em todas: vista mais de frente
        m = ~seen & (score > best)
        best[m], col[m] = score[m], c[m]
    if smooth:
        # textura suave: media das vistas que enxergam o voxel (peso = quao de frente, na potencia pow) e depois
        # media com os vizinhos de superficie (nb x nb x nb); perde o pixel duro de uma vista so
        acc = np.zeros((len(si), 3), np.float32)
        wsum = np.zeros(len(si), np.float32)
        for score, vis, c in cand:
            w = vis * np.clip(score, 0, None) ** smooth['pow']
            acc += w[:, None] * c
            wsum += w
        ok = wsum > 1e-4
        colf = col.astype(np.float32)
        colf[ok] = acc[ok] / wsum[ok, None]
        if smooth['nb'] > 1:
            grid = np.zeros((nx, ny, nz, 3), np.float32)
            grid[I, J, K] = colf
            wgt = ndimage.uniform_filter(surf.astype(np.float32), smooth['nb'])
            sm_c = np.stack([ndimage.uniform_filter(grid[..., ch], smooth['nb']) for ch in range(3)], -1)
            colf = sm_c[I, J, K] / np.maximum(wgt[I, J, K], 1e-6)[:, None]
        col = np.clip(np.round(colf), 0, 255).astype(np.uint8)
    faces = None
    if scan:
        col, _ = bake(g, views, si, col)
        faces = bake_faces(g, views, occ, col)
    ijk = np.stack([I, J, K], 1).astype(np.uint8)
    return ijk, rgb565(col), faces


def rgb565(c):
    c = c.astype(np.uint16)
    return (((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)).astype(np.uint16)


# faces do cubo: (eixo, sinal). Face = quadrado com canto P0 e lados E1 (eixo b) e E2 (eixo c), b < c os outros dois
# eixos; (u, v) em [0,1)^2 -> P0 + u*E1 + v*E2. O visualizador monta a mesma face com a mesma convencao.
FACE_DIRS = [(0, 1), (0, -1), (1, 1), (1, -1), (2, 1), (2, -1)]
TEX = 4         # texels por lado de face
# camadas de textura por vista, na ordem do angulo: -135 .. 180 de 45 em 45 (camada = (angulo + 135) / 45); a
# camada 8 e a base (media ponderada de todas). Na camada: 0 = texel que a vista nao ve, 1 = transparente (cai fora
# do sprite nesse angulo), >= 2 = cor RGB565.
LAYER_ANGLES = [-135, -90, -45, 0, 45, 90, 135, 180]


def bake_faces(g, views, occ, base):
    """Textura por face: cada face exposta dos voxels de superficie ganha TEX x TEX texels. Para cada angulo do 2D
    rasteriza as faces visiveis como o visualizador (projecao do UO, z-buffer), acha em que face e em que (u, v) cai
    cada pixel do sprite e grava a cor no texel. Varios angulos no mesmo texel: media com peso (n.v)^4, o angulo que
    ve a face mais de frente manda. Texel que nenhum angulo ve: media da face, ou a cor do voxel.
    Alem dessa base, guarda a textura de cada angulo sozinho (camada por vista): no angulo exato o visualizador
    usa so a camada dele, e a imagem sai do proprio sprite; entre dois angulos mistura as duas camadas.
    -> (ijk uint8 Nx3, dir uint8 N, texels uint16 RGB565 (len(LAYER_ANGLES)+1) x N x TEX x TEX)"""
    nx, ny, nz = g.n
    pad = np.pad(occ, 1)
    fijk, fdir = [], []
    for d, (ax, sg) in enumerate(FACE_DIRS):
        sh = [slice(1, -1)] * 3
        sh[ax] = slice(1 + sg, pad.shape[ax] - 1 + sg)
        exp = occ & ~pad[tuple(sh)]
        idx = np.argwhere(exp)
        fijk.append(idx)
        fdir.append(np.full(len(idx), d, np.uint8))
    fijk = np.concatenate(fijk)
    fdir = np.concatenate(fdir)
    n = len(fijk)
    h = g.s / 2
    C = (fijk + np.array(g.o)).astype(np.float64) * g.s           # centro do voxel em px do modelo
    P0 = C.copy()
    E1 = np.zeros((n, 3))
    E2 = np.zeros((n, 3))
    normal = np.zeros((n, 3))
    for d, (ax, sg) in enumerate(FACE_DIRS):
        m = fdir == d
        b, c = [k for k in range(3) if k != ax]
        P0[m, ax] += sg * h
        P0[m, b] -= h
        P0[m, c] -= h
        E1[m, b] = 2 * h
        E2[m, c] = 2 * h
        normal[m, ax] = sg
    acc = np.zeros((n, TEX, TEX, 3))
    wsum = np.zeros((n, TEX, TEX))
    layers = np.zeros((len(LAYER_ANGLES), n, TEX, TEX, 3), np.uint8)
    seen = np.zeros((len(LAYER_ANGLES), n, TEX, TEX), bool)
    clear = np.zeros((len(LAYER_ANGLES), n, TEX, TEX), bool)
    th = math.radians(THETA)
    for fdir_view, ang, mirror in ANGLES_2D:
        f = views[fdir_view]
        if f is None:
            continue
        ph = math.radians(ang) * SIGN
        vv = np.array([math.cos(th) * math.sin(ph), math.cos(th) * math.cos(ph), math.sin(th)])
        facing = normal @ vv
        live = np.flatnonzero(facing > 1e-3)
        sgn = -1.0 if mirror else 1.0
        L = LAYER_ANGLES.index(ang)

        def scr(Q):
            x, y, dep = project_f(Q, ang)
            return f['cx'] + sgn * x, f['cy'] + f['h'] + y, dep
        # silhueta: texel de qualquer face (tambem as de tras) cujo centro cai fora do sprite nesse angulo fica
        # transparente na camada; o visualizador descarta e a imagem tem o contorno do sprite, sem mexer na malha
        A0, B0, _ = scr(P0)
        A1, B1, _ = scr(P0 + E1)
        A2, B2, _ = scr(P0 + E2)
        for tu in range(TEX):
            for tv in range(TEX):
                uu, vv_ = (tu + 0.5) / TEX, (tv + 0.5) / TEX
                px = np.floor(A0 + uu * (A1 - A0) + vv_ * (A2 - A0)).astype(int)
                py = np.floor(B0 + uu * (B1 - B0) + vv_ * (B2 - B0)).astype(int)
                inb = (px >= 0) & (px < f['w']) & (py >= 0) & (py < f['h'])
                out_ = ~inb
                out_[inb] = ~f['mask'][py[inb], px[inb]]
                clear[L, :, tu, tv] = out_
        if not len(live):
            continue
        X0, Y0, D0 = scr(P0[live])
        X1, Y1, D1 = scr(P0[live] + E1[live])
        X2, Y2, D2 = scr(P0[live] + E2[live])
        ax_, ay_, ad = X1 - X0, Y1 - Y0, D1 - D0
        bx_, by_, bd = X2 - X0, Y2 - Y0, D2 - D0
        det = ax_ * by_ - bx_ * ay_
        ok_f = np.abs(det) > 1e-6
        xs = np.stack([X0, X0 + ax_, X0 + bx_, X0 + ax_ + bx_])
        ys = np.stack([Y0, Y0 + ay_, Y0 + by_, Y0 + ay_ + by_])
        px0 = np.floor(xs.min(0)).astype(int)
        py0 = np.floor(ys.min(0)).astype(int)
        wx = int(np.ceil((xs.max(0) - xs.min(0)).max())) + 1
        wy = int(np.ceil((ys.max(0) - ys.min(0)).max())) + 1
        W, H = f['w'], f['h']
        cand = []
        for oy in range(wy + 1):
            for ox in range(wx + 1):
                px, py = px0 + ox, py0 + oy
                rx, ry = px + 0.5 - X0, py + 0.5 - Y0
                with np.errstate(divide='ignore', invalid='ignore'):
                    u = (rx * by_ - bx_ * ry) / det
                    v = (ax_ * ry - rx * ay_) / det
                ok = ok_f & (u >= 0) & (u < 1) & (v >= 0) & (v < 1) & (px >= 0) & (px < W) & (py >= 0) & (py < H)
                k = np.flatnonzero(ok)
                cand.append((k, py[k] * W + px[k], u[k], v[k], D0[k] + u[k] * ad[k] + v[k] * bd[k]))
        k = np.concatenate([c[0] for c in cand])
        pix = np.concatenate([c[1] for c in cand])
        u = np.concatenate([c[2] for c in cand])
        v = np.concatenate([c[3] for c in cand])
        dep = np.concatenate([c[4] for c in cand])
        zb = np.full(W * H, -np.inf)
        np.maximum.at(zb, pix, dep)
        # cada texel le o pixel do sprite onde cai o seu centro, se nesse pixel ele esta na frente (tolerancia de
        # meio voxel: o centro do pixel pode cair na face vizinha da mesma superficie)
        rgba = f['rgba'].reshape(-1, 4)
        tol = 0.5 * g.s
        for tu in range(TEX):
            for tv in range(TEX):
                uu, vv_ = (tu + 0.5) / TEX, (tv + 0.5) / TEX
                px = np.floor(X0 + uu * ax_ + vv_ * bx_).astype(int)
                py = np.floor(Y0 + uu * ay_ + vv_ * by_).astype(int)
                tdep = D0 + uu * ad + vv_ * bd
                inb = (px >= 0) & (px < W) & (py >= 0) & (py < H)
                kk = np.flatnonzero(inb)
                p = py[kk] * W + px[kk]
                ok = (tdep[kk] >= zb[p] - tol) & (rgba[p, 3] > 0)
                kk, p = kk[ok], p[ok]
                fi = live[kk]
                w = facing[fi] ** 4
                acc[fi, tu, tv] += w[:, None] * rgba[p, :3]
                wsum[fi, tu, tv] += w
                layers[L, fi, tu, tv] = rgba[p, :3]
                seen[L, fi, tu, tv] = True
    tex = np.zeros((n, TEX, TEX, 3))
    hit = wsum > 0
    tex[hit] = acc[hit] / wsum[hit][:, None]
    # texel sem pixel: media dos texels da face; face sem nenhum: cor do voxel
    fsum = (tex * hit[..., None]).sum((1, 2))
    fcnt = hit.sum((1, 2))
    vid = np.full(occ.shape, -1, np.int64)
    surf = occ & ~ndimage.binary_erosion(occ, border_value=0)
    vid[surf] = np.arange(int(surf.sum()))
    vcol = base[vid[fijk[:, 0], fijk[:, 1], fijk[:, 2]]].astype(np.float64)
    fill = np.where(fcnt[:, None] > 0, fsum / np.maximum(fcnt, 1)[:, None], vcol)
    tex = np.where(hit[..., None], tex, fill[:, None, None, :])
    base = np.clip(np.round(tex), 0, 255).astype(np.uint8)
    # 565 das camadas: 0 = nao visto, 1 = transparente; cor que daria 0 ou 1 vira 2
    out = np.zeros((len(LAYER_ANGLES) + 1, n, TEX, TEX), np.uint16)
    for L in range(len(LAYER_ANGLES)):
        c = np.maximum(rgb565(layers[L]), 2)
        out[L] = np.where(seen[L], c, np.where(clear[L], 1, 0))
    out[-1] = np.maximum(rgb565(base), 2)
    return fijk.astype(np.uint8), fdir, out


# --smooth: cor de cada vista = media dos pixels do sprite sob o voxel (caixa do tamanho do voxel, antialias), vistas
# misturadas com peso linear de quao de frente estao, sem media de vizinhos. Medido no corpo 2 reprojetando os voxels
# nas 5 vistas: erro medio de cor 23,1 (pixel da vista mais de frente) -> 20,0; media de vizinhos 3x3x3 piorava (20,6).
SMOOTH = {'box': 0, 'pow': 1, 'nb': 1}      # box 0 = tamanho do voxel arredondado


def box_rgba(f, n):
    m = f['mask'].astype(np.float32)
    w = ndimage.uniform_filter(m, n)
    out = f['rgba'].copy()
    for ch in range(3):
        out[..., ch] = np.clip(np.round(ndimage.uniform_filter(f['rgba'][..., ch] * m, n) / np.maximum(w, 1e-6)), 0, 255)
    return out


def load_morph(body, outdir):
    """imagens dos angulos intermediarios (viewmorph.py), se existirem: {json, paginas RGBA}."""
    p = os.path.join(outdir, f'{body}.morph.json')
    if not os.path.exists(p):
        return None
    m = json.load(open(p))
    m['pg'] = [np.asarray(Image.open(os.path.join(outdir, f'{body}.morph{"" if k == 0 else "." + str(k)}.webp'))
                          .convert('RGBA')) for k in range(m['pages'])]
    return m


def morph_frames(m, act, i):
    """[(quadro, angulo)] das imagens geradas (nao as do 2D) do quadro i da acao, no formato de quadro do decode."""
    if not m or str(act) not in m['act']:
        return []
    rows = m['act'][str(act)]
    out = []
    for k, r in enumerate(rows[min(i, len(rows) - 1)]):
        if k % m['steps'] == 0 or not r[3]:
            continue
        pg, x, y, w, h, cx, cy = r
        mask = m['pg'][pg][y:y + h, x:x + w, 3] > 0
        out.append(({'cx': cx, 'cy': cy, 'w': w, 'h': h, 'mask': mask, 'dil': mask},
                    m['angles'][0] + k * 45 / m['steps']))
    return out


def build_3d(body, acts, outdir, target, smooth=False, scan=False, fill=False):
    # voxel de ~1 px: silhueta exata (dilatar engorda o casco); voxel maior: dilata ~meio voxel para nao perder
    # partes finas (cabo de arma, rabo) entre os centros amostrados
    s0 = max(1.0, max(f['h'] for _, dirs in acts.values() for d in dirs for f in d) / target)
    grow = int(round((s0 - 1) / 2))
    for _, dirs in acts.values():
        for fr in dirs:
            for f in fr:
                f['dil'] = ndimage.binary_dilation(f['mask'], iterations=grow) if grow else f['mask']
                f['near'] = ndimage.distance_transform_edt(~f['mask'], return_distances=False, return_indices=True)
    g = Grid(acts, target)
    if smooth:
        smooth = dict(SMOOTH, box=SMOOTH['box'] or max(1, int(round(g.s))))
        for _, dirs in acts.values():
            for fr in dirs:
                for f in fr:
                    f['box'] = box_rgba(f, smooth['box'])
    morph = load_morph(body, outdir) if fill else None
    blob, table, nvox = bytearray(), {}, 0
    for a, (_, dirs) in acts.items():
        nf = max(len(d) for d in dirs)
        rows = []
        for i in range(nf):
            views = [d[i] if i < len(d) else None for d in dirs]
            r = carve(g, views, smooth, scan, fill, morph_frames(morph, a, i))
            if r is None:
                rows.append([0, 0])
                continue
            ijk, c, faces = r
            while len(blob) % 4:
                blob.append(0)
            off = len(blob)
            blob += ijk.tobytes()
            if len(blob) % 2:
                blob.append(0)
            blob += c.tobytes()
            row = [off, len(c)]
            if faces is not None:
                fijk, fdir, tex = faces
                while len(blob) % 4:
                    blob.append(0)
                row += [len(blob), len(fdir)]
                blob += fijk.tobytes() + fdir.tobytes()
                if len(blob) % 2:
                    blob.append(0)
                blob += tex.tobytes()                  # (camadas, faces, TEX, TEX) RGB565
            rows.append(row)
            nvox += len(c)
        table[a] = rows
    with gzip.open(os.path.join(outdir, f'{body}.bin.gz'), 'wb', compresslevel=6) as fh:
        fh.write(bytes(blob))
    json.dump({'s': round(g.s, 4), 'theta': THETA, 'o': g.o, 'n': g.n, 'smooth': bool(smooth or scan), 'scan': scan, 'fill': fill, 'tex': TEX if scan else 0,
               'layers': LAYER_ANGLES if scan else [], 'act': table},
              open(os.path.join(outdir, f'{body}.json'), 'w'), separators=(',', ':'))
    return nvox


def work(body):
    t = time.time()
    try:
        acts = load_body(body)
        if not acts:
            return body, None, 'sem quadros'
        out = os.path.join(_ARGS['out'], '2d')
        pack_2d(body, acts, out)
        nvox = 0
        if _ARGS['3d']:
            nvox = build_3d(body, acts, os.path.join(_ARGS['out'], '3d'), _ARGS['grid'],
                            body in _ARGS['smooth'], body in _ARGS['scan'], body in _ARGS['fill'])
        src = _A.source(body)
        info = {'id': body, 'type': _A.types.get(body, ''), 'file': src[0], 'fbody': src[1],
                'kind': U.body_layout(*src)[1],
                'act': [[a, name, max(len(d) for d in dirs)] for a, (name, dirs) in sorted(acts.items())]}
        return body, info, f'{round(time.time() - t, 1)}s {nvox} voxels'
    except Exception as e:
        return body, None, 'falhou ' + repr(e)[:120]


def make_thumbs(out, infos, cell=64):
    """thumbs.png: um quadro parado (direcao 1, de frente para a esquerda) de cada corpo, numa grade de cell x cell.
    infos[...]['thumb'] = posicao na grade."""
    ids = sorted(infos)
    cols = 32
    sheet = np.zeros(((len(ids) + cols - 1) // cols * cell, cols * cell, 4), np.uint8)
    pages = {}
    for n, b in enumerate(ids):
        info = infos[b]
        infos[b]['thumb'] = n
        try:
            meta = json.load(open(os.path.join(out, '2d', f'{b}.json')))
            acts = info['act']
            a = next((x[0] for x in acts if x[1].lower().startswith('idle')), acts[0][0])
            dirs = meta['act'][str(a)]
            fr = (dirs[1] or next(d for d in dirs if d))[0]
            p, x, y, w, h = fr[:5]
            key = (b, p)
            if key not in pages:
                ext = meta.get('ext', 'png')
                pages[key] = np.asarray(Image.open(os.path.join(out, '2d', f'{b}.{ext}' if p == 0 else f'{b}.{p}.{ext}'))
                                        .convert('RGBA'))
            im = Image.fromarray(pages.pop(key)[y:y + h, x:x + w])
            k = min(1.0, (cell - 2) / max(w, h))
            im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS if k < 1 else Image.NEAREST)
            r, c = divmod(n, cols)
            ox, oy = c * cell + (cell - im.width) // 2, r * cell + (cell - im.height) // 2
            sheet[oy:oy + im.height, ox:ox + im.width] = np.asarray(im)
        except Exception as e:
            print('thumb', b, repr(e)[:80])
    Image.fromarray(sheet).save(os.path.join(out, 'thumbs.png'), optimize=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=U.find_client(HERE))
    ap.add_argument('--only', default='')
    ap.add_argument('--grid', type=int, default=64, help='voxels na altura do quadro mais alto')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--no-3d', action='store_true')
    ap.add_argument('--smooth', default='', help='corpos com a cor dos voxels suavizada (ex.: 2)')
    ap.add_argument('--scan', default='', help='corpos com textura por varredura dos 8 angulos do 2D (ex.: 2)')
    ap.add_argument('--fill', default='', help='corpos com casco ampliado ate cobrir os 8 angulos do 2D (ex.: 2)')
    ap.add_argument('--thumbs', action='store_true', help='so refaz thumbs.png a partir de data/')
    a = ap.parse_args()
    out = os.path.join(HERE, 'data')
    for d in ('2d', '3d'):
        os.makedirs(os.path.join(out, d), exist_ok=True)
    idx_path = os.path.join(out, 'index.json')
    if a.thumbs:
        idx = json.load(open(idx_path))
        infos = {b['id']: b for b in idx['bodies']}
        make_thumbs(out, infos)
        idx['bodies'] = [infos[b] for b in sorted(infos)]
        json.dump(idx, open(idx_path, 'w'), separators=(',', ':'))
        print('ok thumbs', len(infos))
        return
    A = U.Anims(a.client)
    bodies = A.bodies()
    if a.only:
        want = {int(t, 0) for t in a.only.split(',') if t.strip()}
        bodies = [b for b in bodies if b in want]
    print(len(bodies), 'corpos;', a.jobs, 'processos', flush=True)
    args = {'out': out, 'grid': a.grid, '3d': not a.no_3d, 'smooth': {int(t, 0) for t in a.smooth.split(',') if t.strip()},
            'scan': {int(t, 0) for t in a.scan.split(',') if t.strip()},
            'fill': {int(t, 0) for t in a.fill.split(',') if t.strip()}}
    infos = {}
    if a.only and os.path.exists(idx_path):
        infos = {b['id']: b for b in json.load(open(idx_path))['bodies']}
    t0 = time.time()
    with Pool(a.jobs, _init, (a.client, args)) as pool:
        for n, (body, info, msg) in enumerate(pool.imap_unordered(work, bodies)):
            print(f'[{n + 1}/{len(bodies)}] {body} {info["type"] if info else ""} {msg}', flush=True)
            if info:
                infos[body] = info
    make_thumbs(out, infos)
    json.dump({'theta': THETA, 'has3d': not a.no_3d, 'bodies': [infos[b] for b in sorted(infos)]},
              open(idx_path, 'w'), separators=(',', ':'))
    print('ok', len(infos), 'corpos em', round(time.time() - t0), 's')


if __name__ == '__main__':
    main()
