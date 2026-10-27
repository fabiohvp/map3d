"""Classifica cada sprite pela imagem (CLIP zero-shot) e grava 'cl' = [[chave, prob], ...top3] em data/items.json.

Uso: python -I items/classify.py
Modelo: openai/clip-vit-base-patch32 (HuggingFace, baixado uma vez para ~/.cache/huggingface).
"""
import json, os
import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, 'data')

# chave (usada por gen.js) -> descricao em ingles para o CLIP
LABELS = {
    'tree': 'a tree with a trunk and leafy crown', 'palm': 'a palm tree', 'deadtree': 'a bare dead tree or tree stump',
    'bush': 'a green bush or shrub', 'flower': 'flowers', 'crop': 'crop plants growing in a field', 'mushroom': 'mushrooms',
    'grass': 'a tuft of grass or leaves lying on the ground', 'cactus': 'a cactus',
    'boulder': 'a grey boulder rock', 'crystal': 'a glowing crystal', 'bones': 'a pile of bones or a skeleton',
    'table': 'a wooden table', 'chair': 'a wooden chair', 'bench': 'a long bench', 'stool': 'a small stool',
    'bed': 'a bed with pillow', 'wardrobe': 'a tall wardrobe or armoire', 'bookcase': 'a bookcase full of books',
    'shelf': 'an empty wooden shelf', 'dresser': 'a dresser with a mirror', 'throne': 'a throne',
    'chest': 'a treasure chest', 'crate': 'a wooden crate', 'barrel': 'a wooden barrel', 'bag': 'a cloth sack or bag',
    'basket': 'a woven basket', 'vase': 'a pottery vase or urn', 'statue': 'a stone statue', 'painting': 'a framed painting',
    'rug': 'a carpet or rug', 'banner': 'a hanging banner or flag', 'sign': 'a wooden signboard',
    'sword': 'a sword', 'dagger': 'a dagger or knife', 'axe': 'an axe', 'mace': 'a mace or war hammer', 'bow': 'a bow',
    'staff': 'a wooden staff or wand', 'polearm': 'a spear or halberd', 'cannon': 'a cannon', 'catapult': 'a catapult siege engine',
    'breastplate': 'a suit of body armor', 'helm': 'a helmet', 'shield': 'a shield', 'boots': 'a pair of boots',
    'robe': 'a robe or tunic or dress', 'hat': 'a hat or cap', 'cloak': 'a cloak or cape',
    'ring': 'a ring', 'necklace': 'a necklace or amulet',
    'potion': 'a glass potion bottle', 'bread': 'a loaf of bread', 'fruit': 'fruit', 'meat': 'a piece of meat or fish',
    'reagent': 'a small pile of magic reagents or herbs', 'gem': 'a gemstone',
    'tool': 'a hand tool such as hammer or saw', 'pickaxe': 'a pickaxe or shovel', 'pot': 'a cooking pot or cauldron',
    'key': 'a key', 'ingot': 'stacked metal ingots', 'log': 'a wooden log or lumber planks', 'ore': 'ore rocks', 'cloth': 'a bolt of cloth',
    'torch': 'a burning torch', 'lantern': 'a lantern', 'candle': 'a candle', 'brazier': 'a fire brazier or campfire',
    'book': 'a book', 'scroll': 'a scroll of parchment', 'books': 'a stack of books',
    'wall': 'a stone or brick wall segment', 'floor': 'a flat floor tile', 'roof': 'a roof with shingles', 'stairs': 'a flight of stairs',
    'door': 'a wooden door', 'window': 'a window', 'arch': 'a stone archway', 'column': 'a stone pillar or column',
    'fence': 'a wooden fence', 'bridge': 'a wooden bridge', 'water': 'water', 'lava': 'lava', 'ground': 'flat dirt or grass ground texture',
    'sails': 'a ship sail', 'hull': 'a wooden boat', 'fire': 'flames of fire', 'magic': 'a magic spell effect with sparkles',
    'smoke': 'smoke or fog', 'web': 'a spider web', 'blood': 'a blood stain or splatter', 'cart': 'a wooden cart or wagon',
    'wheel': 'a wooden wheel', 'anvil': 'an anvil', 'forge': 'a forge or furnace or oven', 'well': 'a stone well',
    'fountain': 'a fountain', 'tent': 'a tent', 'pillar': 'a tall obelisk monolith', 'misc': 'a small unidentifiable object',
}
TEMPL = ['a pixel art sprite of {}', 'an isometric video game icon of {}', 'a small low resolution image of {}']


def prep(im):
    bg = Image.new('RGBA', im.size, (128, 128, 128, 255))
    bg.alpha_composite(im)
    s = max(bg.size) + 8
    sq = Image.new('RGB', (s, s), (128, 128, 128))
    sq.paste(bg.convert('RGB'), ((s - bg.width) // 2, (s - bg.height) // 2))
    return sq.resize((224, 224), Image.BICUBIC)


def main():
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    model = CLIPModel.from_pretrained('openai/clip-vit-base-patch32').to(dev).eval()
    proc = CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32')
    keys = list(LABELS)
    with torch.no_grad():
        tf = []
        for t in TEMPL:
            inp = proc(text=[t.format(LABELS[k]) for k in keys], return_tensors='pt', padding=True).to(dev)
            e = model.get_text_features(**inp)
            tf.append(e / e.norm(dim=-1, keepdim=True))
        text = torch.stack(tf).mean(0)
        text = text / text.norm(dim=-1, keepdim=True)
    data = json.load(open(os.path.join(D, 'items.json'), encoding='utf-8'))
    pages = {}
    items = data['items']
    B = 96
    for b in range(0, len(items), B):
        chunk = items[b:b + B]
        ims = []
        for it in chunk:
            at = pages.get(it['atlas'])
            if at is None:
                at = pages[it['atlas']] = Image.open(os.path.join(D, f"atlas_{it['atlas']}.png")).convert('RGBA')
            ims.append(prep(at.crop((it['ax'], it['ay'], it['ax'] + it['w'], it['ay'] + it['hp']))))
        with torch.no_grad():
            px = proc(images=ims, return_tensors='pt')['pixel_values'].to(dev)
            e = model.get_image_features(pixel_values=px)
            e = e / e.norm(dim=-1, keepdim=True)
            p = (100 * e @ text.T).softmax(-1).cpu().numpy()
        for it, row in zip(chunk, p):
            top = np.argsort(-row)[:3]
            it['cl'] = [[keys[j], round(float(row[j]), 3)] for j in top]
        if b % (B * 10) == 0:
            print(b, len(items), flush=True)
    json.dump(data, open(os.path.join(D, 'items.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(keys, open(os.path.join(D, 'labels.json'), 'w'))
    print('ok', len(items))


if __name__ == '__main__':
    main()
