"""Analise de imagem dos sprites: acrescenta 'f' (caracteristicas medidas no pixel) a cada item de data/items.json.

Uso: python -I items/analyze.py
Medidas (todas 0..1 sobre os pixels opacos, exceto onde indicado):
  gr verde   br marrom/madeira   gy cinza/metal   wh claro/branco   sat saturacao media   hue variedade de matizes (livros, flores)
  fill  area / caixa do sprite   el  largura/altura da caixa (px)    stripe  alternancia de cor em linhas (prateleiras)
  sym   simetria esquerda/direita da silhueta   dg  silhueta ao longo da diagonal (arma/ferramenta deitada)
"""
import json, os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'data')


def feats(rgba):
    a = rgba[..., 3] > 0
    n = int(a.sum())
    if n == 0:
        return {}
    rgb = rgba[..., :3].astype(np.float32) / 255
    mx, mn = rgb.max(2), rgb.min(2)
    lit = a & (mx > .25)                    # sem contorno preto
    m = max(1, int(lit.sum()))
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    hue = np.zeros_like(mx)
    d = np.maximum(mx - mn, 1e-6)
    hue = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6
    green = lit & (g > r * 1.12) & (g > b * 1.12) & (sat > .22)
    brown = lit & (r > g * 1.08) & (g > b * 1.05) & (sat > .22) & (sat < .85) & (mx < .85)
    gray = lit & (sat < .16)
    white = lit & (mx > .8) & (sat < .25)
    colorful = lit & (sat > .35)
    hh, _ = np.histogram(hue[colorful], bins=12, range=(0, 1)) if colorful.any() else (np.zeros(12), 0)
    hue_var = float((hh > max(3, colorful.sum() * .05)).sum() / 12)
    ys, xs = np.nonzero(a)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    box = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    sym = float((box & box[:, ::-1]).sum() / max(1, (box | box[:, ::-1]).sum()))
    lum = mx[lit] if lit.any() else mx[a]
    # alternancia vertical de luminancia media por linha (prateleiras = faixas)
    rows = np.array([mx[y][a[y]].mean() if a[y].any() else 0 for y in range(ys.min(), ys.max() + 1)])
    stripe = float(np.abs(np.diff(rows)).mean()) if len(rows) > 3 else 0.0
    # silhueta deitada: bbox da silhueta pequena em relacao a diagonal -> area/(bbox) baixa e el alto
    fill = float(box.sum() / box.size)
    return {'gr': round(float(green.sum() / m), 3), 'br': round(float(brown.sum() / m), 3), 'gy': round(float(gray.sum() / m), 3),
            'wh': round(float(white.sum() / m), 3), 'sat': round(float(sat[lit].mean()) if lit.any() else 0, 3),
            'hue': round(hue_var, 3), 'fill': round(fill, 3), 'el': round(float(bw / bh), 3), 'sym': round(sym, 3),
            'stripe': round(stripe, 3), 'lum': round(float(lum.mean()), 3)}


def main():
    data = json.load(open(os.path.join(D, 'items.json'), encoding='utf-8'))
    pages = {}
    for it in data['items']:
        im = pages.get(it['atlas'])
        if im is None:
            im = pages[it['atlas']] = np.array(Image.open(os.path.join(D, f"atlas_{it['atlas']}.png")).convert('RGBA'))
        it['f'] = feats(im[it['ay']:it['ay'] + it['hp'], it['ax']:it['ax'] + it['w']])
    json.dump(data, open(os.path.join(D, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    print('ok', len(data['items']))


if __name__ == '__main__':
    main()
