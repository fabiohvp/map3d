"""Forma 3D por IA (Hunyuan3D-2mv) a partir dos sprites, rodando numa maquina remota por SSH, e cor dos sprites.

  1. frente (dir 0), esquerda (dir 2, olhando para a esquerda), costas (dir 4) e direita (dir 2 espelhada) do quadro,
     ampliados 4x, em data/ai/<id>/
  2. copia para o host (scp), roda ai3d_remote.py la (venv com torch + repo Hunyuan3D-2, MPS ou CUDA) e traz a forma
     para data/ai/<id>/shape.glb
  3. rosto: ai3d_face_remote.py redesenha as cabecas da vista de frente com SD 1.5 + ControlNet tile (mesmas cores e
     layout, olhos/nariz/boca nitidos) -> data/ai/<id>/front_hd.png
  4. model3d.py --mesh --face-img: alinha a forma ao casco visual dos sprites e pinta com a projecao deles (o rosto
     com front_hd) -> data/3d/<id>.ai.glb

Preparar o host (uma vez; Mac com Apple Silicon, ou Linux/Windows com CUDA):
  curl -LsSf https://astral.sh/uv/install.sh | sh
  mkdir -p ~/projects/hy3d && cd ~/projects/hy3d && git clone --depth 1 https://github.com/Tencent/Hunyuan3D-2.git
  uv venv -p 3.11 .venv && . .venv/bin/activate && uv pip install torch torchvision diffusers transformers einops \\
      omegaconf trimesh pymeshlab pygltflib accelerate scikit-image opencv-python-headless safetensors huggingface_hub
Os pesos (tencent/Hunyuan3D-2mv, stable-diffusion-v1-5, control_v11f1e_sd15_tile; fp16) baixam sozinhos na primeira
execucao. Versoes que carregam os pesos do Hunyuan: transformers==4.48.3 diffusers==0.32.2.

Uso: python -I anims/ai3d.py [--only 2] [--host macmini] [--octree 320] [--steps 30] [--seed 1234] [--skip-gen]
                             [--face-strength 0.8] [--face-prompt ...] [--skip-face] [--no-face]
                             [--neck 0.035] [--tilt 10] [--twin] [--twin-strength 0.4]
"""
import argparse, os, shlex, subprocess, sys
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import uoanim as U   # noqa: E402

TWIN_PROMPT = ('close-up of two ugly ogre faces, ettin, scar across the eye, broken tooth, warts, detailed eyes with '
               'pupils, heavy brow, big nose, open mouth with teeth, rough tanned skin, fantasy game art, painterly, '
               'sharp focus, high detail')
VIEWS = [('front', 0, False), ('left', 2, False), ('back', 4, False), ('right', 2, True)]


def sprite(pal, f, flip):
    """quadro -> RGBA ampliado 4x, cor sangrada sob o alfa e contorno firme."""
    m = f['mask']
    _, (iy, ix) = ndimage.distance_transform_edt(~m, return_indices=True)
    a = (ndimage.gaussian_filter(m.astype(np.float32), 0.6) * 255).astype(np.uint8)
    im = Image.fromarray(np.dstack([pal[f['idx']][iy, ix], a])).resize((f['w'] * 4, f['h'] * 4), Image.LANCZOS)
    px = np.asarray(im).copy()
    px[..., 3] = np.clip((px[..., 3].astype(np.float32) - 128) * 4 + 128, 0, 255).astype(np.uint8)
    im = Image.fromarray(px)
    return im.transpose(Image.FLIP_LEFT_RIGHT) if flip else im


def run(cmd):
    print('  $', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--client', default=U.find_client(HERE))
    ap.add_argument('--only', default='2')
    ap.add_argument('--act', default='Idle')
    ap.add_argument('--frame', type=int, default=0)
    ap.add_argument('--host', default='macmini', help='host SSH (alias do ~/.ssh/config)')
    ap.add_argument('--remote', default='projects/hy3d', help='pasta no host com .venv e Hunyuan3D-2')
    ap.add_argument('--octree', type=int, default=320)
    ap.add_argument('--steps', type=int, default=30)
    ap.add_argument('--seed', type=int, default=1234)
    ap.add_argument('--skip-gen', action='store_true', help='reusa data/ai/<id>/shape.glb')
    ap.add_argument('--face-strength', type=float, default=0.8,
                    help='quanto o SD pode mudar o rosto (0..1); abaixo de ~0,7 ele copia o borrao do sprite')
    ap.add_argument('--face-prompt', default='', help='prompt do SD para o rosto (padrao: o de ai3d_face_remote.py, '
                                                       'feito para o ettin)')
    ap.add_argument('--neck', type=float, default=0.035, help='pescoco: levanta as cabecas esta fracao da altura')
    ap.add_argument('--tilt', type=float, default=10, help='pescoco: inclina as cabecas para tras (graus)')
    ap.add_argument('--twin', action='store_true', help='cabeca da esquerda = copia espelhada da direita, com rosto '
                                                        'variado pelo SD (cicatriz, outros dentes)')
    ap.add_argument('--twin-strength', type=float, default=0.4, help='quanto o SD muda o rosto da copia (0..1)')
    ap.add_argument('--skip-face', action='store_true', help='reusa data/ai/<id>/front_hd.png')
    ap.add_argument('--no-face', action='store_true', help='rosto so do sprite (sem SD)')
    a = ap.parse_args()
    A = U.Anims(a.client)
    for body in [int(t, 0) for t in a.only.split(',') if t.strip()]:
        d = os.path.join(HERE, 'data', 'ai', str(body))
        os.makedirs(d, exist_ok=True)
        shape, hd = os.path.join(d, 'shape.glb'), os.path.join(d, 'front_hd.png')
        rel = f'in/{body}'                                           # relativo a --remote (o ssh faz cd la)
        rd = f'{a.remote}/{rel}'
        py = f'cd {a.remote} && . .venv/bin/activate && PYTORCH_ENABLE_MPS_FALLBACK=1 python'
        if not a.skip_gen:
            acts = {name.lower(): raws for _, name, raws in A.actions(body)}
            raws = acts.get(a.act.lower()) or next(iter(acts.values()))
            for name, k, flip in VIEWS:
                pal, fr = U.decode(raws[k])
                sprite(pal, fr[min(a.frame, len(fr) - 1)], flip).save(os.path.join(d, f'{name}.png'))
            run(['ssh', a.host, f'mkdir -p {rd}'])
            run(['scp', '-q', os.path.join(HERE, 'ai3d_remote.py')] + [os.path.join(d, f'{n}.png') for n, _, _ in VIEWS]
                + [f'{a.host}:{rd}/'])
            run(['ssh', a.host, f'{py} {rel}/ai3d_remote.py {rel} {rel}/shape.glb {a.octree} {a.steps} {a.seed}'])
            run(['scp', '-q', f'{a.host}:{rd}/shape.glb', shape])
        if not a.no_face and not a.skip_face:
            run(['ssh', a.host, f'mkdir -p {rd}'])
            run(['scp', '-q', os.path.join(HERE, 'ai3d_face_remote.py'), os.path.join(d, 'front.png'), f'{a.host}:{rd}/'])
            run(['ssh', a.host, f'{py} {rel}/ai3d_face_remote.py {rel}/front.png {rel}/front_hd.png 0.32 '
                 f'{a.face_strength} {a.seed}' + (f' {shlex.quote(a.face_prompt)}' if a.face_prompt else '')])
            run(['scp', '-q', f'{a.host}:{rd}/front_hd.png', hd])
        extra = ['--face-img', hd] if not a.no_face and os.path.exists(hd) else []
        cmd = [sys.executable, '-I', os.path.join(HERE, 'model3d.py'), '--client', a.client, '--only', str(body),
               '--act', a.act, '--frame', str(a.frame), '--mesh', shape, '--neck', str(a.neck), '--tilt', str(a.tilt)]
        if a.twin and extra:
            # 1a passada so para gerar a imagem com a direita espelhada; o SD varia; a 2a usa a variacao na copia
            tw, tv = os.path.join(d, 'front_twin.png'), os.path.join(d, 'front_twin_hd.png')
            if not a.skip_face or not os.path.exists(tv):
                run(cmd + extra + ['--twin', '--twin-out', tw])
                run(['scp', '-q', os.path.join(HERE, 'ai3d_face_remote.py'), tw, f'{a.host}:{rd}/'])
                run(['ssh', a.host, f'{py} {rel}/ai3d_face_remote.py {rel}/front_twin.png {rel}/front_twin_hd.png 0.32 '
                     f'{a.twin_strength} {a.seed + 1} {shlex.quote(TWIN_PROMPT)} 1'])
                run(['scp', '-q', f'{a.host}:{rd}/front_twin_hd.png', tv])
            extra += ['--twin', '--twin-face', tv]
        elif a.twin:
            extra += ['--twin']
        run(cmd + extra)


if __name__ == '__main__':
    main()
