"""Roda no host remoto (ver ai3d.py): Hunyuan3D-2mv com as vistas front/left/back/right de <pasta> -> <saida>.glb.

Uso: python ai3d_remote.py <pasta> <saida.glb> [octree] [passos] [semente]   (cwd = pasta com Hunyuan3D-2/)
"""
import os, sys, time
import torch
from PIL import Image

sys.path.insert(0, 'Hunyuan3D-2')
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline   # noqa: E402

src, out = sys.argv[1], sys.argv[2]
octree = int(sys.argv[3]) if len(sys.argv) > 3 else 320
steps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1234
device = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
images = {k: Image.open(os.path.join(src, f'{k}.png')).convert('RGBA')
          for k in ('front', 'left', 'back', 'right') if os.path.exists(os.path.join(src, f'{k}.png'))}
pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained('tencent/Hunyuan3D-2mv', subfolder='hunyuan3d-dit-v2-mv',
                                                         variant='fp16', device=device, dtype=torch.float16)
t = time.time()
mesh = pipe(image=images, num_inference_steps=steps, octree_resolution=octree, num_chunks=20000,
            generator=torch.manual_seed(seed), output_type='trimesh')[0]
mesh.export(out)
print(f'{device}: {len(mesh.vertices)} vertices, {len(mesh.faces)} triangulos, {time.time() - t:.1f}s', flush=True)
