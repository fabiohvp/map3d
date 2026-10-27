"""Catalogo de flora (arvores, plantas, arbustos): entradas simples e conjuntos de varias entries.

Uso: python -I map3d/tools/catalog_flora.py [--client <pasta>] [--map 0] [--out map3d/assets3d/flora] [--min-sets 3]
Saida: catalog.json (singles + sets), sprites/<id>.png. Conjunto = padrao de pecas vizinhas repetido no mapa,
vira um unico asset combinado (todas as entries membros apontam para ele).
"""
import argparse, json, os, re, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import catalog as K   # noqa: E402
import convert as C   # noqa: E402

FAMILY = {
    'tree': r'\btrees?\b|\bpalm\b|\bsapling\b|\bstump\b|\btrunk\b|\bcypress\b|\byew\b|\bwillow\b|\bbonsai\b',
    'bush': r'\bbush\b|\bshrub\b|\bhedge\b|\bbrush\b|\bthorn',
    'plant': r'\bplants?\b|\bfern\b|\bcactus\b|\bflowers?\b|\bvines?\b|\bgrass(es)?\b|\breeds?\b|\bweed\b|\bmushrooms?\b|\bwheat\b|\bcorn\b|\bcotton\b|\bpumpkin\b|\blilypad|\byucca\b|\borchid|\bseaweed\b|\bcattails?\b|\bleaves\b|\bfronds?\b',
}
EXCL = r'wall|roof|rug|corner|spear|table|stool|flute|log post|planter|pot\b|potted|window|arch|bale|bowl|kit|hat|frame|carving|fairy|dappled|horse|face\d|green pumpkin|pumpkin (tall|wide)|pumpkin_|on \d|off$'

def fam(n):
    n = n.lower()
    if re.search(EXCL, n):
        return None
    for f, rx in FAMILY.items():
        if re.search(rx, n):
            return f

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=os.path.normpath(os.path.join(HERE, '..', '..')))
    ap.add_argument('--map', type=int, default=0)
    ap.add_argument('--out', default=os.path.join(HERE, '..', 'assets3d', 'flora'))
    ap.add_argument('--min-sets', type=int, default=3)
    a = ap.parse_args()
    names = K.read_names(a.client)
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
        f = fam(nm)
        art = src.static_art(s) if f else None
        if art is None:
            continue
        cand.add(s)
        Image.fromarray(K.sprite_rgba(art), 'RGBA').save(os.path.join(a.out, 'sprites', f'{s:04X}.png'))
        singles.append({'id': s, 'hex': f'0x{s:04X}', 'name': nm, 'family': f, 'uses': use[s],
                        'height': int(height[s]), 'sprite': f'sprites/{s:04X}.png',
                        'size': [int(art.shape[1]), int(art.shape[0])]})
    sets = K.find_sets(gx, gy, z, sid, cand, a.min_sets)
    out_sets = []
    for sig, n in sorted(sets.items(), key=lambda kv: -kv[1]):
        pieces = [{'dx': p[0], 'dy': p[1], 'dz': p[2], 'id': p[3], 'hex': f'0x{p[3]:04X}'} for p in sig]
        out_sets.append({'kind': 'set', 'name': ' + '.join(sorted({names[p[3]] for p in sig})),
                         'families': sorted({fam(names[p[3]]) for p in sig}), 'uses': n, 'pieces': pieces})
    with open(os.path.join(a.out, 'catalog.json'), 'w', encoding='utf-8') as fh:
        json.dump({'map': a.map, 'singles': singles, 'sets': out_sets}, fh, indent=1, ensure_ascii=False)
    fn = {}
    for s in singles:
        fn[s['family']] = fn.get(s['family'], 0) + 1
    print(len(singles), 'singles', len(out_sets), 'sets', fn)

if __name__ == '__main__':
    main()
