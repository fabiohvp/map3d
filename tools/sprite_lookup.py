"""Acha o índice de sprites.bin (e o lote de malha) de um ou mais graphics de static.

O conversor numera os sprites pela ordem dos graphics usados no mapa e não grava essa tabela;
aqui a art do cliente é recortada como no conversor e casada com a tabela e o atlas gerados.

  python -I map3d/tools/sprite_lookup.py 0x0E77 [--map 0] [--client PASTA] [--data PASTA]
Saída por graphic: graphic sprite kind (o que o viewer aceita em ?items=).
"""
import argparse, os, struct, sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert  # noqa: E402


def load_table(data, m):
    raw = open(os.path.join(data, f'map{m}', 'sprites.bin'), 'rb').read()
    n, rows = struct.unpack_from('<II', raw, 4)
    return np.frombuffer(raw, '<u2', rows * 16, 12).reshape(rows, 16)[:n]


def load_atlas(data, m):
    raw = open(os.path.join(data, f'map{m}', 'atlas.bin'), 'rb').read()
    size, pages = struct.unpack_from('<HH', raw, 4)
    return np.frombuffer(raw, '<u2', pages * size * size, 12).reshape(pages, size, size)


def lookup(src, table, atlas, g):
    img = src.static_art(g)
    if img is None or not img.any():
        return None
    m = img != 0
    ys, xs = np.nonzero(m.any(1))[0], np.nonzero(m.any(0))[0]
    tx, ty, tw, th = int(xs[0]), int(ys[0]), int(xs[-1] - xs[0] + 1), int(ys[-1] - ys[0] + 1)
    h, w = img.shape
    want = convert.bleed(img[ty:ty + th, tx:tx + tw])
    cand = np.nonzero((table[:, 2] == tw) & (table[:, 3] == th) & (table[:, 4] == tx) & (table[:, 5] == ty)
                      & (table[:, 6] == w) & (table[:, 7] == h))[0]
    for i in cand.tolist():
        ax, ay, p = int(table[i, 0]), int(table[i, 1]), int(table[i, 8]) >> 8
        if np.array_equal(atlas[p, ay:ay + th, ax:ax + tw], want):
            if table[i, 8] & 255 == convert.SK_SLOPE:
                return i, 0
            return i, int(np.searchsorted(convert.MESH_CLASSES, int(table[i, 12])))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('graphics', nargs='+', type=lambda v: int(v, 0))
    ap.add_argument('--map', type=int, default=0)
    ap.add_argument('--client', default=os.path.normpath(os.path.join(HERE, '..', '..')))
    ap.add_argument('--data', default=os.path.normpath(os.path.join(HERE, '..', 'data')))
    a = ap.parse_args()
    src = convert.ClassicSource(a.client)
    table, atlas = load_table(a.data, a.map), load_atlas(a.data, a.map)
    for g in a.graphics:
        r = lookup(src, table, atlas, g)
        print(f'0x{g:04X} ' + ('-' if r is None else f'{r[0]} {r[1]}'))


if __name__ == '__main__':
    main()
