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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=os.path.normpath(os.path.join(HERE, '..', '..', '..', '..', '..')))
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
