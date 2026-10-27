"""Extrai todos os itens (statics) do cliente Classic para a pagina items/.

Uso: python -I items/extract.py [--client <pasta Classic>] [--min-sets 8]

Saida (items/data): items.json (itens, conjuntos, categorias) e atlas_N.png (sprites originais empacotados).
- cada id usado em algum mapa e com art vira um item (nome, flags, altura, categoria do taxonomy.json, paleta do sprite)
- pecas vizinhas que se repetem formando um movel/objeto viram um conjunto (item unico); pecas de arquitetura e
  terreno nao entram em conjuntos
"""
import argparse, collections, json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import convert as C   # noqa: E402
import catalog as K   # noqa: E402

NO_SET = {'architecture', 'terrain', 'effect', 'unknown'}   # pecas de construcao/solo nao viram conjunto
ATLAS = 2048


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


def palette(rgba, k=3):
    px = rgba[rgba[..., 3] > 0][:, :3].astype(np.float32)
    lit = px[px.max(1) > 60]          # descarta o contorno preto da art
    if len(lit) > 12:
        px = lit
    if len(px) == 0:
        return ['#808080'] * k
    if len(px) > 4000:
        px = px[np.random.RandomState(1).choice(len(px), 4000, replace=False)]
    cen = px[np.argsort(px.sum(1))[np.linspace(0, len(px) - 1, k + 2).astype(int)[1:-1]]].copy()
    for _ in range(8):
        lab = np.argmin(((px[:, None] - cen[None]) ** 2).sum(2), 1)
        for j in range(k):
            if (lab == j).any():
                cen[j] = px[lab == j].mean(0)
    cnt = np.bincount(lab, minlength=k)
    order = np.argsort(-cnt)
    return ['#%02x%02x%02x' % tuple(int(v) for v in cen[j]) for j in order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=find_client(HERE))
    ap.add_argument('--min-sets', type=int, default=8)
    a = ap.parse_args()
    out = os.path.join(HERE, 'data')
    os.makedirs(out, exist_ok=True)

    src = C.ClassicSource(a.client)
    flags, height, _, names = src.static_tiledata()
    tx = C._load_taxonomy()

    use = collections.Counter()
    maps = {}
    for m, (W, H) in C.MAPS.items():
        try:
            gx, gy, z, sid, _ = C.read_statics(a.client, m, W, H)
        except Exception as e:      # mapa sem statics
            print('map', m, 'sem statics:', e)
            continue
        u, c = np.unique(sid, return_counts=True)
        use.update(dict(zip(u.tolist(), c.tolist())))
        maps[m] = (gx, gy, z, sid)
    print(len(use), 'ids usados')

    items, sprites, cat_of = {}, {}, {}
    for s in sorted(use):
        art = src.static_art(s)
        if art is None:
            continue
        mask = art != 0
        area = int(mask.sum())
        if area == 0:
            continue
        nm = names[s] if s < len(names) else ''
        cat, sub = C.categorize(tx, nm, int(flags[s]), area, area / mask.size)
        rgba = K.sprite_rgba(art)
        sprites[s] = rgba
        cat_of[s] = cat
        fl = [C.TILE_FLAGS[b] for b in range(len(C.TILE_FLAGS)) if int(flags[s]) >> b & 1]
        items[s] = {'id': s, 'hex': f'{s:04X}', 'name': nm, 'cat': cat, 'sub': sub, 'flags': fl,
                    'h': int(height[s]), 'w': int(art.shape[1]), 'hp': int(art.shape[0]),
                    'pal': palette(rgba), 'uses': use[s]}
    print(len(items), 'itens com art')

    # ---- conjuntos
    cand = {s for s, c in cat_of.items() if c not in NO_SET}
    sigs = collections.Counter()
    for m, (gx, gy, z, sid) in maps.items():
        for sig, n in K.find_sets(gx, gy, z, sid, cand, 2).items():
            sigs[sig] += n
    sets, absorbed = [], collections.Counter()
    for sig, n in sorted(sigs.items(), key=lambda kv: (-len(kv[0]), -kv[1])):
        if n < a.min_sets:
            continue
        ids = [p[3] for p in sig]
        if len(set(ids)) == 1 and len(ids) == 1:
            continue
        # repetido com mesmo conjunto de ids em outra disposicao: ja contado
        sets.append({'uses': n, 'pieces': [{'id': f'{p[3]:04X}', 'dx': p[0], 'dy': p[1], 'dz': p[2]} for p in sig]})
        for i in ids:
            absorbed[i] += n
    for st in sets:
        ps = [items[int(p['id'], 16)] for p in st['pieces']]
        top = collections.Counter((p['cat'], p['sub']) for p in ps).most_common(1)[0][0]
        st['cat'], st['sub'] = top
        names_ = sorted({p['name'] for p in ps if p['name']})
        st['name'] = ' + '.join(names_) if names_ else top[1]
    for it in items.values():
        ab = absorbed.get(it['id'], 0)
        it['absorbed'] = ab >= 0.7 * it['uses']      # quase so aparece dentro de conjuntos
    print(len(sets), 'conjuntos;', sum(i['absorbed'] for i in items.values()), 'itens absorvidos')

    # ---- atlas de sprites (prateleiras)
    order = sorted(items, key=lambda s: -sprites[s].shape[0])
    pages, cur, x, y, rowh = [], Image.new('RGBA', (ATLAS, ATLAS)), 0, 0, 0
    for s in order:
        im = sprites[s]
        h, w = im.shape[:2]
        if x + w > ATLAS:
            x, y, rowh = 0, y + rowh + 1, 0
        if y + h > ATLAS:
            pages.append(cur)
            cur, x, y, rowh = Image.new('RGBA', (ATLAS, ATLAS)), 0, 0, 0
        cur.paste(Image.fromarray(im), (x, y))
        items[s]['atlas'], items[s]['ax'], items[s]['ay'] = len(pages), x, y
        x += w + 1
        rowh = max(rowh, h)
    pages.append(cur)
    for f in os.listdir(out):
        if f.startswith('atlas_'):
            os.remove(os.path.join(out, f))
    for i, p in enumerate(pages):
        p.save(os.path.join(out, f'atlas_{i}.png'), optimize=True)
    cats = collections.Counter(i['cat'] for i in items.values() if not i['absorbed'])
    with open(os.path.join(out, 'items.json'), 'w', encoding='utf-8') as f:
        json.dump({'atlases': len(pages), 'items': [items[s] for s in sorted(items)], 'sets': sets,
                   'cats': cats}, f, ensure_ascii=False, separators=(',', ':'))
    print(len(pages), 'atlas;', dict(cats))


if __name__ == '__main__':
    main()
