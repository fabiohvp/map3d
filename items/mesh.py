"""Malhas fieis a art: reaproveita sprite_mesh() do conversor do mapa (casco/caixa/plano/cilindro ajustado a silhueta)
para cada item e grava data/meshes.bin + data/meshes.json (indice por id).

Uso: python -I items/mesh.py [--client <pasta Classic>] [--only 0A63,0B3F] [--cells 24]

Formato por item (little endian, todos alinhados a 4):
  float32  pos[nv*3]   x = lx-0.5, y = lz*ZS, z = ly-0.5   (lx,ly em tiles, lz em unidades de z do UO)
  uint16   uv[nv*2]    pixel (u, v) do sprite, em 1/16 de pixel
  int8     nrm[nv*4]   normal unitaria * 127 (4o byte de padding)
  uint32   idx[nt*3]
"""
import argparse, json, os, struct, sys, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import convert as C   # noqa: E402

ZS = 0.144          # 1 unidade de z em tiles (4 px de z / (31.1 px por tile * cos 26,6 graus))


def find_client(start):
    """Sobe a partir de start ate achar a pasta do cliente (a que tem tiledata.mul)."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, 'tiledata.mul')):
            return d
        up = os.path.dirname(d)
        if up == d:
            raise SystemExit('pasta do cliente nao encontrada: passe --client <pasta com tiledata.mul>')
        d = up


def pack(tris):
    """(pos, pixel, normal) em lista de triangulos -> malha indexada (junta vertices iguais)."""
    P, px, N = tris
    if len(P) == 0:
        return None
    key = np.concatenate([np.round(P * 1e4), np.round(px * 16), np.round(N * 100)], 1).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    P, px, N = P[first], px[first], N[first]
    pos = np.stack([P[:, 0] - 0.5, P[:, 2] * ZS, P[:, 1] - 0.5], 1).astype(np.float32)
    nr = np.stack([N[:, 0], N[:, 2], N[:, 1]], 1)
    nr = nr / np.maximum(np.linalg.norm(nr, axis=1, keepdims=True), 1e-9)
    nrm = np.zeros((len(nr), 4), np.int8)
    nrm[:, :3] = np.round(nr * 127)
    uv = np.clip(np.round(px * 16), 0, 65535).astype(np.uint16)
    idx = inv.reshape(-1, 3).astype(np.uint32)
    return pos, uv, nrm, idx


def roof_tris(mask, thick=0.6):
    """Telhado = plano inclinado de 1 tile (com beiral) ajustado a silhueta por fit_slope, com espessura.
    O sprite cobre a face de cima; as demais faces reusam o pixel da borda."""
    h, w = mask.shape
    _, e, c, sx, sy = C.fit_slope(mask)
    cl = [(-e, -e), (1 + e, -e), (1 + e, 1 + e), (-e, 1 + e)]

    def pt(lx, ly, dz=0.0):
        return np.array([lx, ly, sx * (1 - lx) + sy * (1 - ly) + c + dz])

    def pix(lx, ly):
        return np.array([22 * (lx - ly) + w / 2, 22 * (lx + ly) - 4 * (sx * (1 - lx) + sy * (1 - ly) + c) + h - 44])

    P, PX, N = [], [], []

    def quad(pts, pxs, out):
        for a, b, d in ((0, 1, 2), (0, 2, 3)):
            n = np.cross(pts[b] - pts[a], pts[d] - pts[a])
            order = (a, b, d) if n @ out >= 0 else (a, d, b)
            n = np.cross(pts[order[1]] - pts[order[0]], pts[order[2]] - pts[order[0]])
            n = n / max(np.linalg.norm(n), 1e-9)
            for k in order:
                P.append(pts[k]); PX.append(pxs[k]); N.append(n)

    top = [pt(*q) for q in cl]
    bot = [pt(*q, dz=-thick) for q in cl]
    pxs = [pix(*q) for q in cl]
    quad(top, pxs, np.array([0, 0, 1.0]))
    quad(bot, pxs, np.array([0, 0, -1.0]))
    cen = np.array([.5, .5, 0.0])
    for i in range(4):
        j = (i + 1) % 4
        mid = (top[i] + top[j]) / 2
        quad([top[i], top[j], bot[j], bot[i]], [pxs[i], pxs[j], pxs[j], pxs[i]], np.array([mid[0] - cen[0], mid[1] - cen[1], 0.0]))
    return np.array(P), np.array(PX), np.array(N)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=find_client(HERE))
    ap.add_argument('--only', default='')
    ap.add_argument('--cells', type=int, default=0, help='sobrescreve HULL_CELLS')
    a = ap.parse_args()
    if a.cells:
        C.HULL_CELLS = a.cells
    data = json.load(open(os.path.join(HERE, 'data', 'items.json'), encoding='utf-8'))
    src = C.ClassicSource(a.client)
    flags, height, _, _ = src.static_tiledata()
    tx = C._load_taxonomy()
    surf = C.TILE_FLAGS.index('Surface')
    only = {s.strip().upper() for s in a.only.split(',') if s.strip()}
    index, blob, t0, nv_tot = {}, bytearray(), time.time(), 0
    items = [i for i in data['items'] if not only or i['hex'] in only]
    for n, it in enumerate(items):
        art = src.static_art(it['id'])
        if art is None:
            continue
        try:
            if it['sub'] == 'roof':
                motor, tris = 'telhado', roof_tris(art != 0)
            else:
                motor, tris = C.sprite_mesh(art, tx, it['cat'], it['sub'], it['name'], int(height[it['id']]),
                                            bool(int(flags[it['id']]) >> surf & 1))
            m = pack(tris)
        except Exception as e:
            print('falhou', it['hex'], it['name'], repr(e)[:80])
            continue
        if m is None:
            continue
        pos, uv, nrm, idx = m
        while len(blob) % 4:
            blob.append(0)
        off = len(blob)
        blob += pos.tobytes() + uv.tobytes() + nrm.tobytes() + idx.tobytes()
        index[it['hex']] = {'o': off, 'nv': len(pos), 'nt': len(idx), 'm': motor}
        nv_tot += len(pos)
        if n % 500 == 0:
            print(n, len(items), len(blob) // 1024, 'KB', round(time.time() - t0), 's', flush=True)
    if not only:
        open(os.path.join(HERE, 'data', 'meshes.bin'), 'wb').write(blob)
        json.dump(index, open(os.path.join(HERE, 'data', 'meshes.json'), 'w'), separators=(',', ':'))
    print('ok', len(index), 'malhas', nv_tot, 'vertices', len(blob) // 1024, 'KB')


if __name__ == '__main__':
    main()
