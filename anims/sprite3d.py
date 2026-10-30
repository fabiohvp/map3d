"""Modelo 3D com a textura dos sprites originais.

Malha: casco visual de cada quadro. As 5 direcoes gravadas sao o modelo girado +45k graus em camera ortografica
(elevacao atan 1/2), com a silhueta dilatada DILATE px para que de toda vista a malha cubra o sprite inteiro. A
ocupacao e suavizada (gauss) e vira superficie por surface nets. As 3 direcoes que o UO espelha nao entram: na
caminhada o espelho troca a perna da frente, entao nao existe um modelo unico que bata com as 8 vistas. Como no UO,
com a camera do lado espelhado o visualizador reflete a malha (e a imagem), e as 8 vistas batem com o 2D.

Textura (no visualizador): projecao do sprite da vista. No angulo exato de uma vista todo fragmento le o mesmo pixel
do sprite e o transparente e descartado, entao a imagem 3D e a 2D sao iguais; entre duas vistas mistura as duas
(pesos pelo angulo, so onde a vista enxerga o ponto, por mapa de profundidade).

Saida:
  data/3d/<id>.json = {mode: 'mesh', theta, px_tile, ground, shadow, smooth, roles, act, mesh}
    ground   z (px do modelo) do chao: menor z da caminhada
    shadow   [meia largura, meio comprimento] da pegada em tiles
    smooth   textura com filtro linear (true) ou pixel a pixel (false)
    roles    acao de cada papel: idle, walk, attack[], hit, die[], fidget[]
    act[a]   {name, frames, fps, loop}; caminhada tambem stride (px por quadro do pe apoiado no perfil) e speed
             (tiles/s do UO); fps da caminhada = speed * px_tile / stride, para o pe nao deslizar
    mesh[a]  [[off, nv, ni] por quadro] em <id>.mesh.gz: int16 pos[nv*3] em 1/4 px do modelo (x direita, y cima,
             z para a camera da vista 0), uint16 idx[ni] (uint32 se nv > 65535), alinhado a 4

Uso: python -I anims/sprite3d.py [--only 1] [--smooth <ids>] [--voxel 2]
"""
import argparse, gzip, json, math, os, sys, time
import numpy as np
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import uoanim as U   # noqa: E402

THETA = math.degrees(math.atan(0.5))
PX_TILE = 44 / math.sqrt(2)
WALK_SPEED = 1 / 0.4        # tiles/s: monstro a pe anda 1 tile a cada 400 ms no UO
SIDE = 2                    # direcao do arquivo de perfil (olhando para a esquerda da tela)
FRONT = 0
DILATE = 3                  # px de folga na silhueta do casco
SIGMA = 1.0                 # suavizacao da ocupacao, em voxels
ISO = 0.2                   # nivel da superficie no campo suavizado: abaixo de 0,5 a malha passa ~1 px do ultimo
                            # centro de voxel e cobre o pixel de borda inteiro (o excesso e descartado pelo alfa)
# (direcao do arquivo, angulo da vista em graus)
VIEWS = [(k, 45 * k) for k in range(5)]


# ---------------------------------------------------------------- analise dos quadros (chao, passada, pegada)

def aligned(frames):
    """mascaras dos quadros alinhadas pela ancora; devolve (lista, x da ancora, y da ancora)."""
    L = max(f['cx'] for f in frames)
    R = max(f['w'] - f['cx'] for f in frames)
    Up = max(f['cy'] + f['h'] for f in frames)
    Dn = max(max(-f['cy'] for f in frames), 0)
    out = []
    for f in frames:
        m = np.zeros((Up + Dn, L + R), bool)
        x, y = L - f['cx'], Up - (f['cy'] + f['h'])
        m[y:y + f['h'], x:x + f['w']] = f['mask']
        out.append(m)
    return out, L, Up


def contact(m, band=3):
    """pe mais baixo do quadro: (linha, x do centro) do trecho continuo mais largo nas ultimas linhas."""
    low = int(np.flatnonzero(m.any(1)).max())
    cols = m[low - band + 1:low + 1].any(0)
    runs, x = [], None
    for i, c in enumerate(np.append(cols, False)):
        if c and x is None:
            x = i
        elif not c and x is not None:
            runs.append((x, i - 1))
            x = None
    x0, x1 = max(runs, key=lambda r: r[1] - r[0])
    return low, (x0 + x1) / 2


def stride(frames):
    """px por quadro que o pe apoiado escorrega para tras no perfil (= quanto o corpo anda para frente)."""
    al, _, _ = aligned(frames)
    c = [contact(m) for m in al]
    d = []
    for i in range(len(c)):
        a, b = c[i], c[(i + 1) % len(c)]
        if abs(a[0] - b[0]) <= 3:                 # mesmo pe no chao nos dois quadros
            d.append(b[1] - a[1])                 # olhando para a esquerda: pe apoiado vai para a direita
    d = [v for v in d if v > 0]
    return float(np.median(d)) if d else 0.0


# ---------------------------------------------------------------- casco e malha

def project(P, ang):
    """deslocamento (sx, sy) em px, relativo a ancora, dos pontos P (x direita, y para a camera, z cima) na vista."""
    th, ph = math.radians(THETA), math.radians(ang)
    xr = P[:, 0] * math.cos(ph) - P[:, 1] * math.sin(ph)
    yr = P[:, 0] * math.sin(ph) + P[:, 1] * math.cos(ph)
    return xr, -P[:, 2] * math.cos(th) + yr * math.sin(th)


def inside(f, P, ang):
    sx, sy = project(P, ang)
    px = np.floor(f['cx'] + sx).astype(int)
    py = np.floor(f['cy'] + f['h'] + sy).astype(int)
    ok = (px >= 0) & (px < f['w']) & (py >= 0) & (py < f['h'])
    r = np.zeros(len(P), bool)
    r[ok] = f['dil'][py[ok], px[ok]]
    return r


def hull(P, views):
    keep = np.ones(len(P), bool)
    for fdir, ang in VIEWS:
        f = views[fdir]
        if f is not None:
            keep[keep] = inside(f, P[keep], ang)
    return keep


CORNERS = np.array([(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)])
EDGES = [(a, b) for a in range(8) for b in range(a + 1, 8) if np.abs(CORNERS[a] - CORNERS[b]).sum() == 1]


def surface_nets(F, iso):
    """superficie de nivel iso do campo F (borda ja zerada) -> (vertices em indices do grid, triangulos)."""
    nx, ny, nz = F.shape
    c = [F[i:nx - 1 + i, j:ny - 1 + j, k:nz - 1 + k] for i, j, k in CORNERS]
    ins = [v > iso for v in c]
    active = np.logical_or.reduce(ins) & ~np.logical_and.reduce(ins)
    cells = np.argwhere(active)
    vid = np.full(active.shape, -1, np.int64)
    vid[active] = np.arange(len(cells))
    acc = np.zeros((len(cells), 3))
    cnt = np.zeros(len(cells))
    for a, b in EDGES:
        fa, fb = c[a][active], c[b][active]
        cr = (fa > iso) != (fb > iso)
        t = (iso - fa[cr]) / (fb[cr] - fa[cr])
        acc[cr] += cells[cr] + CORNERS[a] + t[:, None] * (CORNERS[b] - CORNERS[a])
        cnt[cr] += 1
    V = acc / cnt[:, None]
    inn = F > iso
    tris = []
    for ax in range(3):
        b, c2 = [d for d in range(3) if d != ax]
        sl0 = [slice(None)] * 3
        sl1 = [slice(None)] * 3
        sl0[ax], sl1[ax] = slice(0, -1), slice(1, None)
        p = np.argwhere(inn[tuple(sl0)] != inn[tuple(sl1)])
        # a aresta precisa das 4 celulas em volta: indices b-1..b e c-1..c dentro do grid de celulas
        p = p[(p[:, b] >= 1) & (p[:, c2] >= 1) & (p[:, b] <= F.shape[b] - 2) & (p[:, c2] <= F.shape[c2] - 2)]
        q = []
        for db, dc in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            o = p.copy()
            o[:, b] += db
            o[:, c2] += dc
            q.append(vid[o[:, 0], o[:, 1], o[:, 2]])
        q = np.stack(q, 1)
        q = q[(q >= 0).all(1)]
        tris.append(q[:, [0, 1, 2]])
        tris.append(q[:, [0, 2, 3]])
    return V, np.concatenate(tris).astype(np.uint32)


class Body:
    def __init__(self, acts, vox):
        fr = [f for _, dirs in acts.values() for d in dirs for f in d]
        th = math.radians(THETA)
        R = max(max(f['cx'], f['w'] - f['cx']) for f in fr) + DILATE + 2
        up = max(f['cy'] + f['h'] for f in fr) + DILATE + 2
        dn = max(max(-f['cy'] for f in fr), 0) + DILATE + 2
        self.s = s = vox
        n = int(math.ceil(R / s))
        z0 = int(math.floor(-(dn + R * math.sin(th)) / (s * math.cos(th))))
        z1 = int(math.ceil((up + R * math.sin(th)) / (s * math.cos(th))))
        self.o = np.array([-n, -n, z0])
        self.n = (2 * n + 1, 2 * n + 1, z1 - z0 + 1)
        X, Y, Z = np.meshgrid(*(np.arange(k) + o for k, o in zip(self.n, self.o)), indexing='ij')
        self.P = np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1).astype(np.float32) * s

    def patch(self, solid, views):
        """voxels a forcar para que a malha cubra todo pixel de sprite: as vistas do UO nao sao 100% coerentes e o
        casco perde uns pixels. Para cada pixel descoberto, o voxel do raio que mais vistas aceitam (o mais perto do
        casco no empate). O excesso em outra vista nao aparece: la o sprite e transparente e o fragmento e descartado."""
        force = np.zeros(len(self.P), bool)
        near = ndimage.distance_transform_edt(~solid.reshape(self.n)).ravel()
        for fdir, ang in VIEWS:
            f = views[fdir]
            if f is None:
                continue
            sx, sy = project(self.P, ang)
            px = np.floor(f['cx'] + sx).astype(int)
            py = np.floor(f['cy'] + f['h'] + sy).astype(int)
            ok = (px >= 0) & (px < f['w']) & (py >= 0) & (py < f['h'])
            pix = np.where(ok, py * f['w'] + px, 0)
            cov = np.zeros(f['h'] * f['w'], bool)
            cov[pix[ok & (solid | force)]] = True
            cov = cov.reshape(f['h'], f['w'])           # so o centro do voxel conta: a borda da malha fica com folga
            miss = (f['mask'] & ~cov).ravel()
            if not miss.any():
                continue
            ci = np.flatnonzero(ok & miss[pix])
            score = sum(inside(views[k], self.P[ci], a).astype(np.float32) for k, a in VIEWS if views[k] is not None)
            key = score * 1000 - near[ci]
            order = np.argsort(-key, kind='stable')
            _, first = np.unique(pix[ci][order], return_index=True)
            force[ci[order[first]]] = True
        return force

    def mesh(self, views):
        occ = hull(self.P, views)
        if not occ.any():
            return None

        def field(o):
            F = ndimage.gaussian_filter(np.pad(o.reshape(self.n).astype(np.float32), 2), SIGMA)
            F[[0, -1]] = 0
            F[:, [0, -1]] = 0
            F[:, :, [0, -1]] = 0
            return F

        F = field(occ)
        force = self.patch((F[2:-2, 2:-2, 2:-2] > ISO).ravel(), views)
        if force.any():
            blk = np.pad(ndimage.binary_dilation(force.reshape(self.n)).astype(np.float32), 2)
            F = np.maximum(F, blk)
        V, T = surface_nets(F, ISO)
        P = (V - 2 + self.o) * self.s               # px do modelo: x direita, y para a camera, z cima
        pos = np.stack([P[:, 0], P[:, 2], P[:, 1]], 1).astype(np.float32)   # three: (x, z, y)
        return pos, T


def coverage(pos, views, s):
    """menor fracao dos pixels de sprite cobertos pela projecao da malha (vertices com raio de um voxel)."""
    P = np.stack([pos[:, 0], pos[:, 2], pos[:, 1]], 1)
    out = []
    for fdir, ang in VIEWS:
        f = views[fdir]
        if f is None:
            continue
        sx, sy = project(P, ang)
        px = np.floor(f['cx'] + sx).astype(int)
        py = np.floor(f['cy'] + f['h'] + sy).astype(int)
        cov = np.zeros((f['h'] + 2, f['w'] + 2), bool)
        ok = (px >= -1) & (px <= f['w']) & (py >= -1) & (py <= f['h'])
        cov[py[ok] + 1, px[ok] + 1] = True
        cov = ndimage.binary_fill_holes(ndimage.binary_dilation(cov, iterations=int(math.ceil(s / 2))))[1:-1, 1:-1]
        m = f['mask']
        out.append(float((cov & m).sum() / max(m.sum(), 1)))
    return min(out) if out else 1.0


# ---------------------------------------------------------------- principal

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=U.find_client(HERE))
    ap.add_argument('--only', default='1')
    ap.add_argument('--smooth', default='', help='corpos com textura filtrada (linear)')
    ap.add_argument('--voxel', type=float, default=2.0, help='tamanho do voxel do casco, em px do sprite')
    a = ap.parse_args()
    A = U.Anims(a.client)
    smooth = {int(t, 0) for t in a.smooth.split(',') if t.strip()}
    out = os.path.join(HERE, 'data', '3d')
    os.makedirs(out, exist_ok=True)
    for body in [int(t, 0) for t in a.only.split(',') if t.strip()]:
        t0 = time.time()
        acts = {}
        for act, name, raws in A.actions(body):
            dirs = []
            for r in raws:
                fr = U.decode(r)[1]
                for f in fr:
                    f['dil'] = ndimage.binary_dilation(f['mask'], iterations=DILATE)
                dirs.append(fr)
            acts[act] = (name, dirs)
        names = {name.lower(): act for act, (name, _) in acts.items()}

        def pick(*keys):
            return [names[k] for k in keys if k in names]

        roles = {'idle': (pick('idle', 'idle_01') or [min(acts)])[0], 'walk': (pick('walk', 'walk_01') or [None])[0],
                 'attack': pick('attack1', 'attack2', 'attack3', 'attackslash1h_01', 'attackbash1h_01'),
                 'hit': (pick('gethit', 'gethit_fr_hi_01') or [None])[0],
                 'die': pick('die1', 'die2', 'die_hard_fwd_01', 'die_hard_back_01'),
                 'fidget': pick('fidget', 'idle2', 'fidget_yawn_stretch_01')}
        meta = {}
        for act, (name, dirs) in acts.items():
            meta[act] = {'name': name, 'frames': max(len(d) for d in dirs), 'fps': 10,
                         'loop': act in (roles['idle'], roles['walk'])}
        if roles['walk'] is not None and acts[roles['walk']][1][SIDE]:
            st = stride(acts[roles['walk']][1][SIDE])
            w = meta[roles['walk']]
            w['stride'], w['speed'] = round(st, 2), WALK_SPEED
            w['fps'] = round(WALK_SPEED * PX_TILE / st, 2) if st else 10
        shadow = [0.5, 0.5]
        idle = acts[roles['idle']][1]
        ext = []
        for k in (FRONT, SIDE):
            if idle[k]:
                al, L, _ = aligned(idle[k])
                m = al[0]
                low = int(np.flatnonzero(m.any(1)).max())
                cols = np.flatnonzero(m[low - 8:low + 1].any(0))
                ext.append(max(abs(cols.min() - L), abs(cols.max() - L)) / PX_TILE)
        if len(ext) == 2:
            shadow = [round(float(ext[0]) * 0.9, 3), round(float(ext[1]) * 0.9, 3)]

        # malhas
        B = Body(acts, a.voxel)
        blob, table, ground, worst, nv_tot = bytearray(), {}, None, 1.0, 0
        for act, (name, dirs) in acts.items():
            rows = []
            for i in range(max(len(d) for d in dirs)):
                views = [d[i] if i < len(d) else None for d in dirs]
                m = B.mesh(views)
                if m is None:
                    rows.append([0, 0, 0])
                    continue
                pos, idx = m
                worst = min(worst, coverage(pos, views, B.s))
                if act == roles['walk']:
                    g = float(pos[:, 1].min())
                    ground = g if ground is None else min(ground, g)
                while len(blob) % 4:
                    blob.append(0)
                off = len(blob)
                blob += np.round(pos * 4).astype(np.int16).tobytes()
                while len(blob) % 4:
                    blob.append(0)
                blob += idx.astype(np.uint16 if len(pos) < 65536 else np.uint32).tobytes()
                rows.append([off, len(pos), int(idx.size)])
                nv_tot += len(pos)
            table[act] = rows
        if ground is None:
            ground = min(float(np.frombuffer(blob, np.int16, r[1] * 3, r[0])[1::3].min()) / 4
                         for rows in table.values() for r in rows if r[1])
        with gzip.open(os.path.join(out, f'{body}.mesh.gz'), 'wb', compresslevel=6) as fh:
            fh.write(bytes(blob))
        doc = {'mode': 'mesh', 'theta': THETA, 'px_tile': PX_TILE, 'ground': round(ground, 2), 'shadow': shadow,
               'smooth': body in smooth, 'roles': roles, 'act': meta, 'mesh': table}
        json.dump(doc, open(os.path.join(out, f'{body}.json'), 'w'), separators=(',', ':'))
        for old in (f'{body}.bin.gz', f'{body}.tw.png'):
            if os.path.exists(os.path.join(out, old)):
                os.remove(os.path.join(out, old))
        print(f'{body}: {sum(len(r) for r in table.values())} quadros, {nv_tot} vertices, '
              f'{len(blob) // 1024} KB, cobertura minima {worst:.4f}, chao z={ground:.1f}, '
              f'grid {B.n} voxel {B.s}px, {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
