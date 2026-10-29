"""Grava o graphic de cada sprite na coluna 9 de sprites.bin (dados convertidos antes do conversor gravá-la).

O viewer usa essa coluna para trocar cada static pelo modelo 3D de items/ (opção "Itens 3D").
Os sprites estão em ordem crescente de graphic (pendurados, graphic + 0x10000/0x20000, no fim);
a art do cliente é recortada como no conversor e casada com a tabela e o atlas.

  python -I map3d/tools/sprite_ids.py [--map 0] [--client PASTA] [--data PASTA]
"""
import argparse, os, struct, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert  # noqa: E402
from sprite_lookup import load_atlas  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--map', type=int, default=0)
    ap.add_argument('--client', default=os.path.normpath(os.path.join(HERE, '..', '..')))
    ap.add_argument('--data', default=os.path.normpath(os.path.join(HERE, '..', 'data')))
    a = ap.parse_args()
    path = os.path.join(a.data, f'map{a.map}', 'sprites.bin')
    raw = bytearray(open(path, 'rb').read())
    n, rows = struct.unpack_from('<II', raw, 4)
    table = np.frombuffer(bytes(raw), '<u2', rows * 16, 12).reshape(rows, 16)[:n]
    atlas = load_atlas(a.data, a.map)
    src = convert.ClassicSource(a.client)

    # linhas por recorte (tw, th, tx, ty, w, h)
    by_key = {}
    for i, r in enumerate(table):
        by_key.setdefault(tuple(int(v) for v in r[2:8]), []).append(i)
    cand = [[] for _ in range(n)]          # graphics cuja art bate com a linha
    print('casando art do cliente com o atlas...')
    for g in range(0x10000):
        try:
            img = src.static_art(g)
        except Exception:
            continue
        if img is None or not img.any():
            continue
        m = img != 0
        ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
        tx, ty, tw, th = int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1)
        h, w = img.shape
        rs = by_key.get((tw, th, tx, ty, w, h))
        if not rs:
            continue
        want = convert.bleed(img[ty:ty + th, tx:tx + tw])
        for i in rs:
            ax, ay, p = int(table[i, 0]), int(table[i, 1]), int(table[i, 8]) >> 8
            if np.array_equal(atlas[p, ay:ay + th, ax:ax + tw], want):
                cand[i].append(g)

    # art repetida em vários graphics: a ordem crescente da tabela decide (menor graphic acima do anterior);
    # sem candidato acima do anterior, começou o bloco dos pendurados
    out = np.zeros(n, np.uint16)
    prev, miss = -1, 0
    for i in range(n):
        c = sorted(cand[i])
        if not c:
            miss += 1
            continue
        nxt = [g for g in c if g > prev]
        g = nxt[0] if nxt else c[0]
        out[i] = g
        prev = g
    struct.pack_into(f'<{n * 16}H', raw, 12, *np.ascontiguousarray(
        np.concatenate([table[:, :9], out[:, None], table[:, 10:]], 1)).ravel().tolist())
    open(path, 'wb').write(raw)
    print(f'{n} sprites, {n - miss} com graphic, {miss} sem art casada')


if __name__ == '__main__':
    main()
