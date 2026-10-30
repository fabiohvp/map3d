"""Imagens dos angulos que o 2D nao tem: morph entre o sprite do angulo anterior e o do posterior.

Os 8 angulos do 2D (45 em 45 graus; os 3 espelhados sao o sprite invertido) ficam como estao. Entre dois vizinhos,
fluxo optico nos dois sentidos (casamento de blocos em piramide: grosso na metade da resolucao, refinado na
resolucao cheia), e cada imagem intermediaria em t leva os pixels de A ate t e os de B ate 1-t pelo fluxo; a cor vem
da mais perto no tempo (a outra so tapa buracos) e a silhueta e a interpolada.

Uso: python -I anims/viewmorph.py [--only 2] [--steps 4]
Saida: data/3d/<id>.morph.json = {steps, angles, act[acao][quadro] = [[pagina, x, y, w, h, cx, cy] por imagem]}
       data/3d/<id>.morph[.N].webp (sem perda). Imagem i do quadro = angulo -135 + i * 45 / steps.
"""
import argparse, json, math, os, sys, time
from multiprocessing import Pool
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import uoanim as U   # noqa: E402

ANGLES = [-135, -90, -45, 0, 45, 90, 135, 180]          # (arquivo, espelhado) de cada um abaixo
ANGLE_SRC = [(3, True), (2, True), (1, True), (0, False), (1, False), (2, False), (3, False), (4, False)]
WIN = 7


def match(a, b, fy0, fx0, R, cost=0.002):
    """refina o fluxo (fy0, fx0) de a para b procurando +-R px; a, b HxWxC float. So onde a tem alfa."""
    H, W = a.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    best = np.full((H, W), np.inf, np.float32)
    by, bx = fy0.copy(), fx0.copy()
    for dy in range(-R, R + 1):
        for dx in range(-R, R + 1):
            ty = np.clip(np.round(yy + fy0 + dy).astype(int), 0, H - 1)
            tx = np.clip(np.round(xx + fx0 + dx).astype(int), 0, W - 1)
            d = ((a - b[ty, tx]) ** 2).sum(2)
            c = ndimage.uniform_filter(d, WIN, mode='constant') + cost * ((fy0 + dy) ** 2 + (fx0 + dx) ** 2)
            m = c < best
            best[m] = c[m]
            by[m] = fy0[m] + dy
            bx[m] = fx0[m] + dx
    return by, bx


def smooth(f, alpha, s):
    w = alpha.astype(np.float32)
    f = ndimage.median_filter(f, 5)
    f = ndimage.gaussian_filter(f * w, s) / np.maximum(ndimage.gaussian_filter(w, s), 1e-4)
    f[~alpha] = 0
    return f


def down(im):
    """metade da resolucao (media 2x2)."""
    H, W = im.shape[0] // 2 * 2, im.shape[1] // 2 * 2
    return im[:H, :W].reshape(H // 2, 2, W // 2, 2, -1).mean((1, 3))


def up(f, shape):
    f = np.repeat(np.repeat(f, 2, 0), 2, 1) * 2
    out = np.zeros(shape, np.float32)
    h, w = min(shape[0], f.shape[0]), min(shape[1], f.shape[1])
    out[:h, :w] = f[:h, :w]
    return out


def flow(a, b, levels=3):
    """fluxo (fy, fx) de cada pixel de a para b em piramide: +-8 px no nivel mais grosso (1/4: +-32 px cheios),
    refinado +-3 px em cada nivel ate a resolucao cheia."""
    pa, pb = [a], [b]
    for _ in range(levels - 1):
        pa.append(down(pa[-1]))
        pb.append(down(pb[-1]))
    fy = fx = None
    for lv in range(levels - 1, -1, -1):
        A, B = pa[lv], pb[lv]
        if fy is None:
            fy = fx = np.zeros(A.shape[:2], np.float32)
            R = 8
        else:
            fy, fx = up(fy, A.shape[:2]), up(fx, A.shape[:2])
            R = 3
        fy, fx = match(A, B, fy, fx, R)
        al = A[..., 3] > 0.5
        fy, fx = smooth(fy, al, 1.5 if lv else 2.0), smooth(fx, al, 1.5 if lv else 2.0)
    return fy, fx


def carry(fy, fx, mask, t):
    """leva o campo (e a silhueta) de A para as posicoes em t."""
    H, W = mask.shape
    ys, xs = np.nonzero(mask)
    ty = np.round(ys + t * fy[ys, xs]).astype(int)
    tx = np.round(xs + t * fx[ys, xs]).astype(int)
    ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
    m = np.zeros((H, W), bool)
    Fy = np.zeros((H, W), np.float32)
    Fx = np.zeros((H, W), np.float32)
    m[ty[ok], tx[ok]] = True
    Fy[ty[ok], tx[ok]] = fy[ys[ok], xs[ok]]
    Fx[ty[ok], tx[ok]] = fx[ys[ok], xs[ok]]
    if not m.any():
        return Fy, Fx, m
    idx = ndimage.distance_transform_edt(~m, return_distances=False, return_indices=True)
    Fy, Fx = Fy[idx[0], idx[1]], Fx[idx[0], idx[1]]
    sil = ndimage.binary_closing(m, iterations=2, border_value=0) | m
    return Fy, Fx, sil


def sample(img, y, x):
    H, W = img.shape[:2]
    return img[np.clip(np.round(y).astype(int), 0, H - 1), np.clip(np.round(x).astype(int), 0, W - 1)]


def tween(a, b, fab, fba, t):
    """a, b uint8 HxWx4 no mesmo canvas (ancora no mesmo ponto). Cor = mistura (1-t, t) das duas amostras."""
    H, W = a.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    FyA, FxA, silA = carry(*fab, a[..., 3] > 0, t)          # fluxo A->B na posicao t
    FyB, FxB, silB = carry(*fba, b[..., 3] > 0, 1 - t)      # fluxo B->A na posicao t
    ca = sample(a, yy - t * FyA, xx - t * FxA).astype(np.float32)
    cb = sample(b, yy - (1 - t) * FyB, xx - (1 - t) * FxB).astype(np.float32)
    ha, hb = ca[..., 3:] > 0, cb[..., 3:] > 0
    # cor: so a imagem mais perto no tempo (deformada pelo fluxo); a outra tapa onde ela nao tem cor. Misturar as
    # duas duplicava feicoes (cabecas) onde o fluxo nao casa perfeito
    tb = 0.0 if t <= 0.5 else 1.0
    wa, wb = (1 - tb) * ha + 1e-3 * ha, tb * hb + 1e-3 * hb
    col = (ca[..., :3] * wa + cb[..., :3] * wb) / np.maximum(wa + wb, 1e-6)
    sil = ((1 - t) * silA + t * silB) >= 0.5
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = np.clip(np.round(col), 0, 255)
    out[..., 3] = sil * 255
    # silhueta sem cor das duas amostras: vizinho mais proximo com cor
    have = sil & ((wa + wb)[..., 0] > 0)
    miss = sil & ~have
    if miss.any() and have.any():
        idx = ndimage.distance_transform_edt(~have, return_distances=False, return_indices=True)
        out[miss] = out[idx[0][miss], idx[1][miss]]
    return out


def view_images(dirs, i):
    """os 8 angulos do quadro i no mesmo canvas (ancora em (L, Up)); -> (lista RGBA, L, Up)."""
    fr = []
    for fdir, mir in ANGLE_SRC:
        d = dirs[fdir]
        f = d[min(i, len(d) - 1)] if d else None
        fr.append((f, mir))
    ok = [(f, m) for f, m in fr if f is not None]
    L = max(max(f['cx'], f['w'] - f['cx']) for f, _ in ok) + 2
    Up = max(f['cy'] + f['h'] for f, _ in ok) + 2
    Dn = max(max(-f['cy'] for f, _ in ok), 0) + 2
    out = []
    for f, mir in fr:
        im = np.zeros((Up + Dn, 2 * L, 4), np.uint8)
        if f is not None:
            src = f['rgba'][:, ::-1] if mir else f['rgba']
            cx = f['w'] - f['cx'] if mir else f['cx']
            x, y = L - cx, Up - (f['cy'] + f['h'])
            im[y:y + f['h'], x:x + f['w']] = src
        out.append(im)
    return out, L, Up


def prep(im):
    g = im.astype(np.float32) / 255
    g[..., :3] *= g[..., 3:]
    g[..., 3] *= 2
    return g


def frame_morphs(dirs, i, steps):
    imgs, L, Up = view_images(dirs, i)
    out = []
    for k in range(8):
        a, b = imgs[k], imgs[(k + 1) % 8]
        out.append(a)
        if not a[..., 3].any() or not b[..., 3].any():
            out += [a] * (steps - 1)
            continue
        pa, pb = prep(a), prep(b)
        fab, fba = flow(pa, pb), flow(pb, pa)
        for s in range(1, steps):
            out.append(tween(a, b, fab, fba, s / steps))
    return out, L, Up


_A = None


def _init(client):
    global _A
    _A = U.Anims(client)


def decode_rgba(raw):
    pal, frames = U.decode(raw)
    for f in frames:
        f['rgba'] = np.zeros((f['h'], f['w'], 4), np.uint8)
        f['rgba'][..., :3] = pal[f['idx']]
        f['rgba'][..., 3] = f['mask'] * 255
    return frames


def work(job):
    body, act, i, steps = job
    for a, name, raws in _A.actions(body):
        if a == act:
            dirs = [decode_rgba(r) for r in raws]
            imgs, L, Up = frame_morphs(dirs, i, steps)
            return act, i, imgs, L, Up


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=U.find_client(HERE))
    ap.add_argument('--only', default='2')
    ap.add_argument('--steps', type=int, default=4, help='imagens por intervalo de 45 graus (1 = so as do 2D)')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    A = U.Anims(a.client)
    out = os.path.join(HERE, 'data', '3d')
    for body in [int(t, 0) for t in a.only.split(',') if t.strip()]:
        t0 = time.time()
        jobs = []
        for act, name, raws in A.actions(body):
            nf = max(len(U.decode(r)[1]) for r in raws if r is not None)
            jobs += [(body, act, i, a.steps) for i in range(nf)]
        res = {}
        with Pool(a.jobs, _init, (a.client,)) as pool:
            for n, (act, i, imgs, L, Up) in enumerate(pool.imap_unordered(work, jobs)):
                res[(act, i)] = (imgs, L, Up)
                print(f'[{n + 1}/{len(jobs)}] acao {act} quadro {i}', flush=True)
        # atlas: recorta cada imagem na caixa do alfa
        tiles, table = [], {}
        for (act, i) in sorted(res):
            imgs, L, Up = res[(act, i)]
            row = []
            for im in imgs:
                ys, xs = np.nonzero(im[..., 3])
                if len(ys) == 0:
                    row.append([0, 0, 0, 0, 0, 0, 0])
                    continue
                y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
                h = int(y1 - y0)
                row.append(len(tiles))
                tiles.append((im[y0:y1, x0:x1], int(L - x0), int(Up - y0 - h)))
            table.setdefault(str(act), {})[i] = row
        W, PH = 4096, 8192
        pages, pos, x, y, rowh = [], [], 0, 0, 0
        cur = []
        for crop, _, _ in tiles:
            h, w = crop.shape[:2]
            if x + w > W:
                x, y, rowh = 0, y + rowh + 1, 0
            if y + h > PH:
                pages.append(y + rowh)
                x, y, rowh = 0, 0, 0
            pos.append((len(pages), x, y))
            x += w + 1
            rowh = max(rowh, h)
        pages.append(y + rowh)
        imgs_out = [np.zeros((max(hh, 1), W, 4), np.uint8) for hh in pages]
        rects = []
        for (crop, cx, cy), (p, x, y) in zip(tiles, pos):
            h, w = crop.shape[:2]
            imgs_out[p][y:y + h, x:x + w] = crop
            rects.append([p, x, y, w, h, cx, cy])
        for p, im in enumerate(imgs_out):
            Image.fromarray(im).save(os.path.join(out, f'{body}.morph{"" if p == 0 else "." + str(p)}.webp'),
                                     lossless=True, method=4)
        act_rows = {act: [[rects[k] if isinstance(k, int) else k for k in fr[i]] for i in sorted(fr)]
                    for act, fr in table.items()}
        json.dump({'steps': a.steps, 'angles': ANGLES, 'pages': len(imgs_out), 'act': act_rows},
                  open(os.path.join(out, f'{body}.morph.json'), 'w'), separators=(',', ':'))
        sz = sum(os.path.getsize(os.path.join(out, f)) for f in os.listdir(out) if f.startswith(f'{body}.morph'))
        print(f'{body}: {len(tiles)} imagens, {len(imgs_out)} paginas, {sz // 1024} KB, {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
