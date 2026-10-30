"""Modelo 3D estatico (malha lisa + cor por vertice) de um quadro de um corpo, para ver iluminado e girar livre.

Diferente do sprite3d (textura projetada que depende da vista, igual ao 2D no angulo exato), aqui a cor fica presa
na malha, como num modelo de jogo 3D:

  1. silhuetas: cada direcao do quadro ampliada UP vezes com o alfa bilinear (contorno redondo em vez de degraus)
  2. casco visual das 5 direcoes gravadas (vista k = modelo girado 45k graus, camera ortografica, elevacao atan 1/2),
     primeiro grosso para achar a caixa, depois fino (voxel --voxel px)
  3. ocupacao suavizada (gauss) -> surface nets -> maior componente -> Taubin (alisa sem encolher)
  4. cor de cada vertice: media das vistas que o enxergam (mapa de profundidade por vista), peso (normal . camera)^P;
     as 3 direcoes que o UO espelha entram com peso menor (o sprite invertido e a vista do lado oposto se o corpo e
     simetrico); vertice que nenhuma vista ve (topo da cabeca, sola, entre as pernas) recebe a cor por difusao na malha;
     na cabeca (--head: fracao de cima da altura) o que olha para frente leva so a vista 0 com nitidez reforcada
     (as vistas do UO nao batem entre si e a media borra olhos, nariz e boca); ver face()
  5. exporta glTF binario: data/3d/<id>.glb em tiles (1 tile = 44/sqrt2 px), chao em y=0, three: x direita, y cima,
     z para a camera da vista 0; --neck/--tilt levantam e inclinam as cabecas depois da cor (ver neck())

Com --mesh a forma vem de fora (ex. Hunyuan3D-2mv a partir dos sprites, ver ai3d.py): ela e alinhada ao casco e
recebe a cor do mesmo jeito (passo 4).

Uso: python -I anims/model3d.py [--only 2] [--act Idle] [--frame 0] [--voxel 0.5] [--mesh forma.glb]
"""
import argparse, math, os, sys, time
import numpy as np
from PIL import Image
from scipy import ndimage, sparse
from scipy.spatial import cKDTree
import trimesh

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import uoanim as U   # noqa: E402
from sprite3d import THETA, PX_TILE, project, surface_nets   # noqa: E402

UP = 4                      # ampliacao das silhuetas e cores
VIEWS = [(k, 45 * k, False) for k in range(5)] + [(k, -45 * k, True) for k in (1, 2, 3)]
MIRROR_W = 0.35             # peso das vistas espelhadas na cor
POW = 10                    # nitidez da escolha da vista na cor (alto = quase so a vista mais de frente)
SIGMA = 2.0                 # suavizacao da ocupacao, em voxels
TAUBIN = 40
SHARP = (0.7, 0.8)          # mascara de nitidez da cor do rosto: (raio em px do sprite, intensidade)


def view(pal, f, mirror):
    """quadro -> silhueta e cor ampliadas; cx, cy, w, h em px do sprite (cx espelhado se mirror)."""
    m, idx = f['mask'], f['idx']
    if mirror:
        m, idx = m[:, ::-1], idx[:, ::-1]
    h, w = m.shape
    rgb = pal[idx].astype(np.float32)
    # cor sangrada para fora do alfa, para a amostra bilinear na borda nao puxar preto
    _, (iy, ix) = ndimage.distance_transform_edt(~m, return_indices=True)
    rgb = rgb[iy, ix]
    size = (w * UP, h * UP)
    a = np.asarray(Image.fromarray((ndimage.gaussian_filter(m.astype(np.float32), 0.6) * 255).astype(np.uint8))
                   .resize(size, Image.BILINEAR), np.float32) / 255
    col = np.stack([np.asarray(Image.fromarray(rgb[..., c]).resize(size, Image.BICUBIC), np.float32)
                    for c in range(3)], -1)
    cx = w - f['cx'] if mirror else f['cx']
    return {'cx': cx, 'cy': f['cy'], 'w': w, 'h': h, 'hm': a > 0.5, 'col': np.clip(col, 0, 255)}


def pix(v, P, ang):
    """posicao continua (u, v) em px ampliados dos pontos P (x direita, y para a camera, z cima)."""
    sx, sy = project(P, ang)
    return (v['cx'] + sx) * UP, (v['cy'] + v['h'] + sy) * UP


def inside(v, P, ang, tol):
    u, w = pix(v, P, ang)
    m = ndimage.binary_dilation(v['hm'], iterations=tol) if tol else v['hm']
    px, py = np.floor(u).astype(int), np.floor(w).astype(int)
    ok = (px >= 0) & (px < m.shape[1]) & (py >= 0) & (py < m.shape[0])
    r = np.zeros(len(P), bool)
    r[ok] = m[py[ok], px[ok]]
    return r


def grid(lo, hi, s):
    ax = [np.arange(math.floor(a / s), math.ceil(b / s) + 1) * s for a, b in zip(lo, hi)]
    X, Y, Z = np.meshgrid(*ax, indexing='ij')
    return np.stack([X.ravel(), Y.ravel(), Z.ravel()], 1).astype(np.float32), tuple(len(a) for a in ax), \
        np.array([a[0] for a in ax])


def hull(views, s, tol, lo=None, hi=None):
    if lo is None:
        R = max(max(v['cx'], v['w'] - v['cx']) for v in views.values()) + 4
        top = max(v['cy'] + v['h'] for v in views.values()) / math.cos(math.radians(THETA)) + R
        lo, hi = (-R, -R, -2 * R), (R, R, top)
    P, shape, org = grid(lo, hi, s)
    keep = np.ones(len(P), bool)
    for k, ang, mir in VIEWS:
        if not mir:
            keep[keep] = inside(views[(k, False)], P[keep], ang, tol)
    return keep.reshape(shape), org


def build(views, s, tol):
    occ, org = hull(views, 2.0, UP)                                  # grosso, com folga, so para a caixa
    nz = np.argwhere(occ)
    lo = org + (nz.min(0) - 2) * 2.0
    hi = org + (nz.max(0) + 2) * 2.0
    occ, org = hull(views, s, tol, lo, hi)
    F = ndimage.gaussian_filter(np.pad(occ.astype(np.float32), 3), SIGMA)
    V, T = surface_nets(F, 0.5)
    # surface nets nao orienta os quads: a normal de cada triangulo tem que apontar para onde o campo cai
    G = np.stack(np.gradient(F), 0)
    C = V[T].mean(1)
    g = np.stack([ndimage.map_coordinates(G[i], C.T, order=1) for i in range(3)], 1)
    n = np.cross(V[T[:, 1]] - V[T[:, 0]], V[T[:, 2]] - V[T[:, 0]])
    flip = (n * g).sum(1) > 0
    T[flip] = T[flip][:, ::-1]
    P = (V - 3) * s + org
    mesh = trimesh.Trimesh(P, T, process=True)
    parts = mesh.split(only_watertight=False)
    mesh = max(parts, key=lambda m: len(m.faces))
    trimesh.smoothing.filter_taubin(mesh, lamb=0.5, nu=-0.53, iterations=TAUBIN)
    return mesh


def external(path, ref, yaw=None):
    """forma de fora (glTF, y cima, frente para +z) alinhada ao casco ref: escala por eixo pela caixa e depois ICP
    (rigido + escala) contra a superficie do casco. yaw None = testa os 4 giros de 90 graus e fica com o menor erro."""
    m = trimesh.load(path, force='mesh')
    m = max(m.split(only_watertight=False), key=lambda p: len(p.faces))
    P0 = np.asarray(m.vertices)
    P0 = np.stack([P0[:, 0], P0[:, 2], P0[:, 1]], 1)                # three (x, y cima, z) -> modelo (x, z, y)
    lo, hi = ref.bounds
    rv = np.asarray(ref.vertices)
    rv = rv[np.random.default_rng(1).choice(len(rv), min(len(rv), 40000), replace=False)]
    best = None
    for k in ([yaw] if yaw is not None else [0, 90, 180, 270]):
        r = math.radians(k)
        Rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
        P = P0 @ Rz.T
        a, b = P.min(0), P.max(0)
        P = (P - a) / (b - a) * (hi - lo) + lo
        sample = P[np.random.default_rng(0).choice(len(P), min(len(P), 6000), replace=False)]
        M, _, cost = trimesh.registration.icp(sample, rv, threshold=1e-6, max_iterations=40, reflection=False,
                                              translation=True, scale=True)
        if best is None or cost < best[0]:
            best = (cost, k, trimesh.transform_points(P, M))
    cost, k, P = best
    out = trimesh.Trimesh(P, m.faces, process=True)
    if out.volume < 0:                                               # a troca y/z espelha: desvira
        out.invert()
    print(f'  forma externa: giro {k} graus, erro ICP {cost:.2f} px, {len(out.faces)} triangulos')
    return out


def chin(V):
    """altura do queixo: em cada cabeca (metade esquerda e direita das fatias de 4% a 12% do topo), o perfil da frente
    (maior y por fatia de 1% numa coluna de 6 px no meio dela) cai de uma vez onde o queixo encontra o peito."""
    z = V[:, 2]
    top, hgt = z.max(), z.max() - z.min()
    hv = V[(z > top - 0.12 * hgt) & (z < top - 0.04 * hgt)]
    out = []
    for sel in (hv[:, 0] < np.median(hv[:, 0]), hv[:, 0] >= np.median(hv[:, 0])):
        col = V[np.abs(V[:, 0] - np.median(hv[sel, 0])) < 3]
        fr = np.arange(0.12, 0.36, 0.01)
        y = [col[(col[:, 2] <= top - f * hgt) & (col[:, 2] > top - (f + 0.01) * hgt), 1] for f in fr]
        y = np.array([b.max() if len(b) else np.nan for b in y])
        d = np.diff(y)
        out.append(fr[int(np.nanargmin(d)) + 1])
    return top - np.mean(out) * hgt


def footprint(V):
    """pegada das cabecas em (x, y): fatias de 3% a 13% do topo rasterizadas a 1 px, fechadas e suavizadas (0..1 por
    vertice), para a deformacao nao rasgar a malha na borda."""
    z = V[:, 2]
    top, hgt = z.max(), z.max() - z.min()
    head = V[(z <= top - 0.03 * hgt) & (z > top - 0.13 * hgt)]
    lo = np.floor(V[:, :2].min(0)).astype(int) - 8
    m = np.zeros(tuple(np.ceil(V[:, :2].max(0)).astype(int) - lo + 9), np.float32)
    m[tuple((np.round(head[:, :2]) - lo).astype(int).T)] = 1
    m = ndimage.binary_fill_holes(ndimage.binary_closing(m > 0, iterations=3))
    m = ndimage.gaussian_filter(ndimage.binary_dilation(m, iterations=3).astype(np.float32), 2)
    return ndimage.map_coordinates(m, (V[:, :2] - lo).T, order=1)


def twin(V, P, T, rgb, f, uv, yaw=8.0, tint=(1.3, 1.15, 0.8)):
    """troca a cabeca da esquerda por uma copia espelhada da direita (com cor, peso e uv do rosto), cortando no meio do
    pescoco. V: posicoes antes do pescoco (para escolher as regioes), P: as finais. Detalhes para nao ser clone: a copia
    vira yaw graus para fora e o couro cabeludo leva tint. O rosto da copia le a metade esquerda da imagem do rosto
    (onde ficava a cabeca apagada), espelhada: main() poe la a direita espelhada ou uma variacao dela (--twin-face). A borda do corte da copia gruda na borda que sobrou do
    corpo (deslocamento que some em 3 px para dentro)."""
    z = V[:, 2]
    top, hgt = z.max(), z.max() - z.min()
    zc = chin(V)
    cut = zc - 0.03 * hgt
    hv = V[(z > top - 0.12 * hgt) & (z < top - 0.04 * hgt)]
    xm = np.median(hv[:, 0])
    xl, xr = np.median(hv[hv[:, 0] < xm, 0]), np.median(hv[hv[:, 0] >= xm, 0])
    mid = (xl + xr) / 2
    fp = footprint(V) > 0.4
    src = fp & (z > cut) & (V[:, 0] >= mid)
    dst = fp & (z > cut) & (V[:, 0] < mid)
    keepT = T[~dst[T].all(1)]
    cT = T[src[T].all(1)]
    idx, inv = np.unique(cT, return_inverse=True)
    Q = P[idx].copy()
    Q[:, 0] = 2 * mid - Q[:, 0]
    # giro para fora em torno do eixo vertical da cabeca copiada; nada no corte, inteiro da altura do queixo para cima
    c = np.array([2 * mid - xr, np.median(P[idx, 1])])
    a = math.radians(yaw) * smoothstep(V[idx, 2], cut, zc + 0.02 * hgt)
    dx, dy = Q[:, 0] - c[0], Q[:, 1] - c[1]
    Q[:, 0] = c[0] + dx * np.cos(a) - dy * np.sin(a)
    Q[:, 1] = c[1] + dx * np.sin(a) + dy * np.cos(a)
    # gruda a borda do corte da copia na borda que sobrou no corpo
    def border(F):
        e = np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), 1)
        u, n = np.unique(e, axis=0, return_counts=True)
        return np.unique(u[n == 1])
    cb = border(inv.reshape(-1, 3))
    hole = border(keepT)
    hole = hole[dst[hole] | (fp[hole] & (V[hole, 0] < mid) & (np.abs(z[hole] - cut) < 0.02 * hgt))]
    if len(hole) and len(cb):
        tree = cKDTree(P[hole])
        _, j = tree.query(Q[cb])
        disp = np.zeros_like(Q)
        disp[cb] = P[hole][j] - Q[cb]
        d, k = cKDTree(Q[cb]).query(Q)
        disp = disp[cb][k] * np.clip(1 - d / 3, 0, 1)[:, None]
        Q += disp
    rgb2 = rgb[idx].astype(np.float32)
    scalp = (f[idx] < 0.3) & (V[idx, 2] > top - 0.1 * hgt)
    rgb2[scalp] = np.clip(rgb2[scalp] * np.array(tint), 0, 255)
    n = len(P)
    T2 = np.concatenate([keepT, (inv.reshape(-1, 3) + n)[:, ::-1]])  # espelho inverte o giro dos triangulos
    mu = None
    if uv is not None:                                               # coluna da imagem do plano do espelho
        k, b = np.polyfit(V[:, 0], uv[:, 0], 1)
        mu = k * mid + b
        uv2 = uv[idx].copy()
        uv2[:, 0] = 2 * mu - uv2[:, 0]                               # a copia le a metade esquerda da imagem
        uv = np.concatenate([uv, uv2])
    return (np.concatenate([P, Q]), T2, np.concatenate([rgb, rgb2.astype(np.uint8)]), np.concatenate([f, f[idx]]),
            uv, mu)


def neck(V, lift, tilt, zs=None):
    """pescoco: levanta as cabecas lift * altura e inclina tilt graus para tras (rosto para cima), so na pegada delas
    (x, y das fatias de 3% a 13% do topo). Tudo acima do queixo zs (padrao: chin) sobe inteiro; a faixa de 2,5% abaixo
    estica e vira pescoco, e o peito fica. Roda depois da cor, que acompanha."""
    z = V[:, 2]
    top, hgt = z.max(), z.max() - z.min()
    band = lambda a, b: (z <= top - a * hgt) & (z > top - b * hgt)
    zs = chin(V) if zs is None else zs
    head = V[band(0.03, 0.13)]
    w = smoothstep(z, zs - 0.025 * hgt, zs) * np.clip(footprint(V) * 1.5, 0, 1)
    # giro em torno do eixo x, pivo no meio da cabeca na altura do pescoco
    y0 = np.median(head[:, 1])
    a = math.radians(tilt) * w
    dy, dz = V[:, 1] - y0, z - zs
    out = V.copy()
    out[:, 1] = y0 + dy * np.cos(a) - dz * np.sin(a)
    out[:, 2] = zs + dy * np.sin(a) + dz * np.cos(a) + lift * hgt * w
    return out


def smoothstep(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def face(out, V, N, v, head, hd=None):
    """rosto: cor so da vista 0, projetada na horizontal (elevacao 0) e encaixada pela caixa da silhueta. A forma da IA
    leu a imagem de frente como vista horizontal, entao olhos, nariz e boca esculpidos caem onde a imagem os mostra
    nessa projecao, e nao na de 26,6 graus do UO. hd: a vista 0 redesenhada em alta (ai3d_face_remote.py), mesma
    moldura que v ampliada; dispensa a mascara de nitidez.
    -> (cor, f = peso do rosto por vertice, uv em hd (x, y em px) ou None)"""
    rows, cols = np.nonzero(v['hm'])
    lo, hi = V.min(0), V.max(0)
    u = (V[:, 0] - lo[0]) / (hi[0] - lo[0]) * (cols.max() + 1 - cols.min()) + cols.min()
    w = (hi[2] - V[:, 2]) / (hi[2] - lo[2]) * (rows.max() + 1 - rows.min()) + rows.min()
    zs = UP // 2                                                     # mapa de profundidade como em colours
    H, W = v['hm'].shape[0] // zs + 2, v['hm'].shape[1] // zs + 2
    zx = np.clip(np.floor(u / zs).astype(int), 0, W - 1)
    zy = np.clip(np.floor(w / zs).astype(int), 0, H - 1)
    zb = np.full((H, W), -np.inf, np.float32)
    np.maximum.at(zb, (zy, zx), V[:, 1])
    vis = V[:, 1] >= ndimage.maximum_filter(zb, 3)[zy, zx] - 1.5
    hgt = hi[2] - lo[2]
    f = smoothstep(V[:, 2], hi[2] - (head + 0.04) * hgt, hi[2] - head * hgt) * smoothstep(N[:, 1], 0.15, 0.45) * vis
    zc = chin(V)                                                     # o peito sob o queixo nao leva rosto
    f *= smoothstep(V[:, 2], zc - 0.005 * hgt, zc + 0.01 * hgt)
    if hd is None:
        r, amt = SHARP
        img, k = [c * (1 + amt) - ndimage.gaussian_filter(c, r * UP) * amt for c in np.moveaxis(v['col'], -1, 0)], 1
    else:
        img, k = list(np.moveaxis(hd, -1, 0)), hd.shape[1] / v['hm'].shape[1]
    col = np.stack([ndimage.map_coordinates(c, [w * k - 0.5, u * k - 0.5], order=1, mode='nearest') for c in img], -1)
    return out * (1 - f[:, None]) + col * f[:, None], f, (np.stack([u * k, w * k], 1) if hd is not None else None)


def colours(mesh, views, head=0.0, hd=None):
    V = np.asarray(mesh.vertices, np.float32)
    N = np.asarray(mesh.vertex_normals, np.float32)
    th = math.radians(THETA)
    acc = np.zeros((len(V), 3))
    wsum = np.zeros(len(V))
    for k, ang, mir in VIEWS:
        v = views[(k, mir)]
        ph = math.radians(ang)
        c = np.array([math.sin(ph) * math.cos(th), math.cos(ph) * math.cos(th), math.sin(th)], np.float32)
        d = V @ c                                                    # maior = mais perto da camera
        u, w = pix(v, V, ang)
        # mapa de profundidade a 1/2 px do sprite, buracos entre vertices fechados por maximo 3x3
        zs = UP // 2
        H, W = v['hm'].shape[0] // zs + 2, v['hm'].shape[1] // zs + 2
        zx = np.clip(np.floor(u / zs).astype(int), 0, W - 1)
        zy = np.clip(np.floor(w / zs).astype(int), 0, H - 1)
        zb = np.full((H, W), -np.inf, np.float32)
        np.maximum.at(zb, (zy, zx), d)
        zb = ndimage.maximum_filter(zb, 3)
        vis = d >= zb[zy, zx] - 1.5
        hy, hx = np.clip(np.floor(w).astype(int), 0, v['hm'].shape[0] - 1), \
            np.clip(np.floor(u).astype(int), 0, v['hm'].shape[1] - 1)
        vis &= v['hm'][hy, hx]
        wt = np.clip(N @ c, 0, None) ** POW * vis * (MIRROR_W if mir else 1.0)
        col = np.stack([ndimage.map_coordinates(v['col'][..., ch], [w - 0.5, u - 0.5], order=1, mode='nearest')
                        for ch in range(3)], -1)
        acc += col * wt[:, None]
        wsum += wt
    known = wsum > 1e-3
    out = np.zeros((len(V), 3))
    out[known] = acc[known] / wsum[known, None]
    # difusao: vertices sem vista recebem a media dos vizinhos ate estabilizar
    E = mesh.edges_unique
    A = sparse.coo_matrix((np.ones(len(E) * 2), (np.r_[E[:, 0], E[:, 1]], np.r_[E[:, 1], E[:, 0]])),
                          shape=(len(V), len(V))).tocsr()
    deg = np.asarray(A.sum(1)).ravel()
    unk = ~known
    for _ in range(400):
        if not unk.any():
            break
        out[unk] = (A @ out)[unk] / np.maximum(deg[unk, None], 1)
    f = uv = None
    if head > 0:
        out, f, uv = face(out, V, N, views[(0, False)], head, hd)
    return np.clip(out, 0, 255).astype(np.uint8), known.mean(), f, uv


def export(path, P, T, rgb, f=None, uv=None, hd=None):
    """glb com cor por vertice; com uv o miolo do rosto (f ~ 1) vai num segundo pedaco com textura (recorte de hd):
    a cor por vertice (um vertice a cada ~5 px da imagem em alta) nao guarda olho, nariz e boca."""
    m = trimesh.Trimesh(P, T, process=False)
    if m.volume < 0:                                                 # a troca y/z espelha: desvira
        T = T[:, ::-1]
    tex = (f[T] > 0.98).all(1) if uv is not None else np.zeros(len(T), bool)
    parts = []
    body = trimesh.Trimesh(P, T[~tex], vertex_colors=np.c_[rgb, np.full(len(rgb), 255, np.uint8)], process=False)
    body.remove_unreferenced_vertices()
    parts.append(body)
    if tex.any():
        idx, inv = np.unique(T[tex], return_inverse=True)
        q = uv[idx]
        x0, y0 = np.floor(q.min(0)).astype(int) - 4
        x1, y1 = np.ceil(q.max(0)).astype(int) + 4
        crop = Image.fromarray(np.clip(hd[max(y0, 0):y1, max(x0, 0):x1], 0, 255).astype(np.uint8))
        x0, y0 = max(x0, 0), max(y0, 0)
        st = np.stack([(q[:, 0] - x0) / crop.width, 1 - (q[:, 1] - y0) / crop.height], 1)
        mat = trimesh.visual.material.PBRMaterial(baseColorTexture=crop, metallicFactor=0.0, roughnessFactor=0.85)
        parts.append(trimesh.Trimesh(P[idx], inv.reshape(-1, 3), process=False,
                                     visual=trimesh.visual.TextureVisuals(uv=st, material=mat)))
    trimesh.Scene(parts).export(path)
    return int(tex.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=U.find_client(HERE))
    ap.add_argument('--only', default='2')
    ap.add_argument('--act', default='Idle')
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--voxel', type=float, default=0.5, help='voxel do casco fino, em px do sprite')
    ap.add_argument('--tol', type=int, default=3, help='folga da silhueta no casco, em px ampliados')
    ap.add_argument('--head', type=float, default=0.22, help='fracao de cima da altura com rosto so da vista 0')
    ap.add_argument('--face-img', help='vista 0 redesenhada em alta (RGBA, multiplo do sprite ampliado) para o rosto')
    ap.add_argument('--neck', type=float, default=0.0, help='pescoco: levanta as cabecas esta fracao da altura')
    ap.add_argument('--tilt', type=float, default=0.0, help='pescoco: inclina as cabecas para tras (graus)')
    ap.add_argument('--twin', action='store_true', help='cabeca da esquerda = copia espelhada da direita (ver twin())')
    ap.add_argument('--twin-out', help='salva a imagem do rosto com a direita espelhada na esquerda (entrada da variacao)')
    ap.add_argument('--twin-face', help='variacao dessa imagem (mesmo tamanho); a metade esquerda vira o rosto da copia')
    ap.add_argument('--mesh', help='forma pronta (.glb, ex. gerada por IA) no lugar do casco; so para um corpo')
    ap.add_argument('--yaw', type=int, help='giro da forma pronta em graus (padrao: o de menor erro)')
    ap.add_argument('--out', help='nome do .glb de saida (padrao <id>.glb, ou <id>.ai.glb com --mesh)')
    a = ap.parse_args()
    A = U.Anims(a.client)
    out = os.path.join(HERE, 'data', '3d')
    os.makedirs(out, exist_ok=True)
    for body in [int(t, 0) for t in a.only.split(',') if t.strip()]:
        t0 = time.time()
        acts = {name.lower(): raws for _, name, raws in A.actions(body)}
        raws = acts.get(a.act.lower()) or next(iter(acts.values()))
        views = {}
        for k, ang, mir in VIEWS:
            pal, fr = U.decode(raws[k])
            views[(k, mir)] = view(pal, fr[min(a.frame, len(fr) - 1)], mir)
        mesh = build(views, a.voxel, a.tol)
        if a.mesh:
            mesh = external(a.mesh, mesh, a.yaw)
        hd = np.asarray(Image.open(a.face_img).convert('RGB'), np.float32) if a.face_img else None
        rgb, seen, f, uv = colours(mesh, views, a.head, hd)
        # px do modelo (x direita, y para a camera, z cima) -> tiles, three (x, z, y), chao em 0
        V0 = np.asarray(mesh.vertices)
        P, T = (neck(V0, a.neck, a.tilt) if a.neck or a.tilt else V0), np.asarray(mesh.faces)
        if a.twin:
            P, T, rgb, f, uv, mu = twin(V0, P, T, rgb, f if f is not None else np.zeros(len(V0)), uv)
            if hd is not None:
                m = int(round(mu))
                src = np.clip(2 * m - 1 - np.arange(m), 0, hd.shape[1] - 1)
                hd = hd.copy()
                hd[:, :m] = hd[:, src]                                # direita espelhada no lugar da esquerda
                if a.twin_out:
                    Image.fromarray(np.clip(hd, 0, 255).astype(np.uint8)).save(a.twin_out)
                if a.twin_face:
                    var = np.asarray(Image.open(a.twin_face).convert('RGB'), np.float32)
                    hd[:, :m] = var[:, :m]
        P = np.stack([P[:, 0], P[:, 2] - P[:, 2].min(), P[:, 1]], 1) / PX_TILE
        name = a.out or (f'{body}.ai.glb' if a.mesh else f'{body}.glb')
        ntex = export(os.path.join(out, name), P, T, rgb, f, uv, hd)
        print(f'{name}: {len(P)} vertices, {len(T)} triangulos ({ntex} com textura de rosto), {seen:.1%} '
              f'vistos, {os.path.getsize(os.path.join(out, name)) // 1024} KB, {time.time() - t0:.1f}s')


if __name__ == '__main__':
    main()
