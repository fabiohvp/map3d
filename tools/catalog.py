"""Catalogo de statics para modelagem 3D: nomes, uso no mapa, sprites e conjuntos de varias pecas.

Uso:
    python -I map3d/tools/catalog.py [--client <pasta Classic>] [--map 0] [--out map3d/assets3d] [--min-sets 3]

Saida (em --out):
    catalog.json        entradas simples e conjuntos (kind: single | set), com sprites e dimensoes
    sprites/<id>.png    sprite original do jogo (RGBA) de cada id candidato
Um conjunto e um padrao de pecas (dx, dy, dz, id) que se repete >= --min-sets vezes no mapa,
formado por pecas candidatas vizinhas. Ele vira um unico asset, usado no lugar das pecas soltas.
"""
import argparse, json, os, re, struct, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import convert as C   # noqa: E402

# palavras (EN) que marcam moveis/utensilios reais do mundo medieval
FAMILY = {
    'table': r'\btable\b|\bdesk\b|\bcounter\b|\bbar\b',
    'chair': r'\bchair\b|\bthrone\b|\bstool\b|\bbench\b',
    'bed': r'\bbed\b|\bbedroll\b|\bcot\b',
    'shelf': r'\bbookshelf\b|\bshelf\b|\bshelves\b|\bcabinet\b|\barmoire\b|\bdresser\b|\bcupboard\b',
    'chest': r'\bchest\b|\bbarrel\b|\bcrate\b|\bkeg\b|\bbox\b|\btrunk\b',
    'forge': r'\bforge\b|\banvil\b|\bbellows\b|\bfurnace\b|\bfireplace\b|\boven\b',
}


def read_names(client):
    td = open(os.path.join(client, 'tiledata.mul'), 'rb').read()
    off = 512 * (4 + 32 * 30)
    names = []
    while off + 4 <= len(td):
        off += 4
        for _ in range(32):
            if off + 41 > len(td):
                break
            names.append(td[off + 21:off + 41].split(b'\0')[0].decode('latin1').strip())
            off += 41
    return names


def family_of(name):
    n = name.lower()
    for fam, rx in FAMILY.items():
        if re.search(rx, n):
            return fam
    return None


def sprite_rgba(art):
    h, w = art.shape
    a = (art != 0)
    r = ((art >> 10) & 31).astype(np.uint16) * 255 // 31
    g = ((art >> 5) & 31).astype(np.uint16) * 255 // 31
    b = (art & 31).astype(np.uint16) * 255 // 31
    return np.stack([r, g, b, a * 255], -1).astype(np.uint8)


def find_sets(gx, gy, z, sid, cand, min_sets):
    """Componentes conexos de pecas candidatas (8 vizinhos, |dz|<=3, ate 6 pecas) repetidos no mapa."""
    m = np.isin(sid, list(cand))
    gx, gy, z, sid = gx[m], gy[m], z[m], sid[m]
    key = (gx.astype(np.int64) << 20) | gy
    order = np.argsort(key, kind='stable')
    gx, gy, z, sid, key = gx[order], gy[order], z[order], sid[order], key[order]
    at = {}
    for i, k in enumerate(key.tolist()):
        at.setdefault(k, []).append(i)
    seen = np.zeros(len(gx), bool)
    sigs = {}
    for i0 in range(len(gx)):
        if seen[i0]:
            continue
        comp, stack = [], [i0]
        seen[i0] = True
        while stack and len(comp) <= 6:
            i = stack.pop()
            comp.append(i)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in at.get(((int(gx[i]) + dx) << 20) | (int(gy[i]) + dy), ()):
                        if not seen[j] and abs(int(z[j]) - int(z[i])) <= 3:
                            seen[j] = True
                            stack.append(j)
        if len(comp) < 2 or len(comp) > 6:
            continue
        ox, oy, oz = min(int(gx[i]) for i in comp), min(int(gy[i]) for i in comp), min(int(z[i]) for i in comp)
        sig = tuple(sorted((int(gx[i]) - ox, int(gy[i]) - oy, int(z[i]) - oz, int(sid[i])) for i in comp))
        sigs[sig] = sigs.get(sig, 0) + 1
    return {s: n for s, n in sigs.items() if n >= min_sets}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=os.path.normpath(os.path.join(HERE, '..', '..')))
    ap.add_argument('--map', type=int, default=0)
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'assets3d'))
    ap.add_argument('--min-sets', type=int, default=3)
    a = ap.parse_args()

    names = read_names(a.client)
    W, H = C.MAPS[a.map]
    gx, gy, z, sid, _ = C.read_statics(a.client, a.map, W, H)
    ids, counts = np.unique(sid, return_counts=True)
    use = dict(zip(ids.tolist(), counts.tolist()))
    src = C.ClassicSource(a.client)
    _, height, _ = src.static_tiledata()

    os.makedirs(os.path.join(a.out, 'sprites'), exist_ok=True)
    singles, cand = [], set()
    for s in sorted(use):
        nm = names[s] if s < len(names) else ''
        fam = family_of(nm)
        if not fam:
            continue
        art = src.static_art(s)
        if art is None:
            continue
        cand.add(s)
        Image.fromarray(sprite_rgba(art), 'RGBA').save(os.path.join(a.out, 'sprites', f'{s:04X}.png'))
        singles.append({'id': s, 'hex': f'0x{s:04X}', 'name': nm, 'family': fam, 'uses': use[s],
                        'height': int(height[s]), 'sprite': f'sprites/{s:04X}.png',
                        'size': [int(art.shape[1]), int(art.shape[0])]})

    sets = find_sets(gx, gy, z, sid, cand, a.min_sets)
    members = set()
    out_sets = []
    for sig, n in sorted(sets.items(), key=lambda kv: -kv[1]):
        pieces = [{'dx': p[0], 'dy': p[1], 'dz': p[2], 'id': p[3], 'hex': f'0x{p[3]:04X}'} for p in sig]
        fams = sorted({family_of(names[p[3]]) for p in sig})
        members.update(p[3] for p in sig)
        out_sets.append({'kind': 'set', 'name': ' + '.join(sorted({names[p[3]] for p in sig})),
                         'families': fams, 'uses': n, 'pieces': pieces})
    # ids que so aparecem em conjuntos continuam como entradas simples, marcadas com os conjuntos que os cobrem
    cat = {'map': a.map, 'singles': singles, 'sets': out_sets}
    with open(os.path.join(a.out, 'catalog.json'), 'w', encoding='utf-8') as f:
        json.dump(cat, f, indent=1, ensure_ascii=False)
    print(f'{len(singles)} ids candidatos, {len(out_sets)} conjuntos, {len(members)} ids em conjuntos')
    fam_n = {}
    for s in singles:
        fam_n[s['family']] = fam_n.get(s['family'], 0) + 1
    print(fam_n)


if __name__ == '__main__':
    main()
