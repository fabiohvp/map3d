"""Roda no host remoto (ver ai3d.py): redesenha as cabecas da vista de frente com SD 1.5 + ControlNet tile.

O tile mantem cores e layout do sprite ampliado e so inventa o detalhe (olhos, nariz, boca). Entra o recorte de cima
da silhueta (--head da altura), ampliado SCALE vezes; sai <saida>.png do tamanho da entrada * SCALE, com o recorte
redesenhado e o resto ampliado (bicubico), alfa da entrada.

Com escala 1 a entrada ja e a imagem em alta (ex. variacao do rosto da cabeca copiada, ver ai3d.py --twin).

Uso: python ai3d_face_remote.py <front.png> <saida.png> [fracao da cabeca] [forca] [semente] [prompt] [escala]
"""
import sys, time
import numpy as np
import torch
from PIL import Image
from diffusers import ControlNetModel, StableDiffusionControlNetImg2ImgPipeline

SCALE = 3
PROMPT = ('close-up of two ugly ogre faces, ettin, detailed eyes with pupils, heavy brow, big nose, open mouth with '
          'teeth, rough tanned skin, brown hair, fantasy game art, painterly, sharp focus, high detail')
NEG = 'blurry, lowres, jpeg artifacts, deformed, extra heads, extra eyes, text, watermark, plastic, smooth skin'

src, out = sys.argv[1], sys.argv[2]
head = float(sys.argv[3]) if len(sys.argv) > 3 else 0.32
strength = float(sys.argv[4]) if len(sys.argv) > 4 else 0.8
seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1234
prompt = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else PROMPT
SCALE = int(sys.argv[7]) if len(sys.argv) > 7 else SCALE
device = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
dtype = torch.float16 if device != 'cpu' else torch.float32

im = Image.open(src).convert('RGBA')
W, H = im.size
a = np.asarray(im)[..., 3] > 127
rows = np.flatnonzero(a.any(1))
y1 = int(rows.min() + (rows.max() - rows.min()) * head)
bg = Image.new('RGBA', im.size, (96, 92, 88, 255))
bg.alpha_composite(im)
big = bg.convert('RGB').resize((W * SCALE, H * SCALE), Image.BICUBIC)
cw, ch = W * SCALE // 8 * 8, y1 * SCALE // 8 * 8
crop = big.crop((0, 0, cw, ch))

cn = ControlNetModel.from_pretrained('lllyasviel/control_v11f1e_sd15_tile', torch_dtype=dtype)
pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
    'stable-diffusion-v1-5/stable-diffusion-v1-5', controlnet=cn, torch_dtype=dtype, variant='fp16',
    safety_checker=None, requires_safety_checker=False).to(device)
pipe.enable_attention_slicing()
t = time.time()
res = pipe(prompt=prompt, negative_prompt=NEG, image=crop, control_image=crop, strength=strength,
           num_inference_steps=40, guidance_scale=7.0, controlnet_conditioning_scale=1.0,
           generator=torch.Generator('cpu').manual_seed(seed)).images[0]
big.paste(res.resize((cw, ch), Image.LANCZOS), (0, 0))
alpha = im.getchannel('A').resize(big.size, Image.BICUBIC)
big.putalpha(alpha)
big.save(out)
print(f'{device}: rosto {cw}x{ch} redesenhado em {time.time() - t:.1f}s', flush=True)
