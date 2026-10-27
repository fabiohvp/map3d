"""Mini-kit para montar malhas low-poly texturizadas e gravar .glb (so numpy + PIL).

Unidades: 1 tile UO = 1.0; Y e para cima. Cada primitiva recebe uv=(u0,v0,u1,v1) em pixels da textura
(origem no canto superior esquerdo) para amostrar a regiao do sprite original.
    m = Mesh('textura.png')
    m.cylinder((0,0,0), r0=.12, r1=.08, h=.6, uv=(40,90,60,120))
    m.ellipsoid((0,.9,0), (.5,.4,.5), uv=(0,0,100,70))
    m.cone((0,.6,0), r=.5, h=.6, uv=(0,0,100,70))
    m.quad(p0,p1,p2,p3, uv=...)   # p0..p3 em ordem, p0->p1 = eixo u
    m.save('model.glb')
"""
import json, struct
import numpy as np
from PIL import Image


class Mesh:
    def __init__(self, tex):
        self.tex = tex
        self.im = Image.open(tex).convert('RGBA')
        self.w, self.h = self.im.size
        self.P, self.N, self.T, self.I = [], [], [], []

    def _uv(self, uv, a, b):
        u0, v0, u1, v1 = uv
        return ((u0 + (u1 - u0) * a) / self.w, (v0 + (v1 - v0) * b) / self.h)

    def _add(self, p, n, t, idx):
        o = len(self.P)
        self.P += [tuple(map(float, x)) for x in p]
        self.N += [tuple(map(float, x)) for x in n]
        self.T += t
        self.I += [o + i for i in idx]

    def quad(self, p0, p1, p2, p3, uv, double=True):
        p = [np.array(x, float) for x in (p0, p1, p2, p3)]
        n = np.cross(p[1] - p[0], p[3] - p[0])
        n = n / (np.linalg.norm(n) or 1)
        t = [self._uv(uv, 0, 1), self._uv(uv, 1, 1), self._uv(uv, 1, 0), self._uv(uv, 0, 0)]
        idx = [0, 1, 2, 0, 2, 3]
        if double:
            idx += [0, 2, 1, 0, 3, 2]
        self._add(p, [n] * 4, t, idx)

    def cylinder(self, base, r0, r1, h, uv, seg=10, cap=True):
        bx, by, bz = base
        P, N, T, I = [], [], [], []
        for k in range(seg + 1):
            a = 2 * np.pi * k / seg
            c, s = np.cos(a), np.sin(a)
            for r, y, v in ((r0, 0, 1), (r1, h, 0)):
                P.append((bx + r * c, by + y, bz + r * s))
                N.append((c, 0, s))
                T.append(self._uv(uv, k / seg, v))
        for k in range(seg):
            a, b = 2 * k, 2 * k + 2
            I += [a, b, a + 1, b, b + 1, a + 1]
        self._add(P, N, T, I)
        if cap:
            self.disc((bx, by + h, bz), r1, uv, seg)

    def disc(self, c, r, uv, seg=10, up=True):
        P = [c] + [(c[0] + r * np.cos(2 * np.pi * k / seg), c[1], c[2] + r * np.sin(2 * np.pi * k / seg)) for k in range(seg)]
        T = [self._uv(uv, .5, .5)] + [self._uv(uv, .5 + .5 * np.cos(2 * np.pi * k / seg), .5 + .5 * np.sin(2 * np.pi * k / seg)) for k in range(seg)]
        I = []
        for k in range(seg):
            I += [0, 1 + (k + 1) % seg, 1 + k]
        self._add(P, [(0, 1, 0)] * len(P), T, I)

    def cone(self, base, r, h, uv, seg=12):
        bx, by, bz = base
        P, N, T, I = [], [], [], []
        for k in range(seg + 1):
            a = 2 * np.pi * k / seg
            c, s = np.cos(a), np.sin(a)
            P += [(bx + r * c, by, bz + r * s), (bx, by + h, bz)]
            N += [(c, .5, s)] * 2
            T += [self._uv(uv, k / seg, 1), self._uv(uv, k / seg, 0)]
        for k in range(seg):
            I += [2 * k, 2 * k + 2, 2 * k + 1]
        self._add(P, N, T, I)

    def ellipsoid(self, c, r, uv, seg=12, rings=8):
        cx, cy, cz = c
        rx, ry, rz = r
        P, N, T, I = [], [], [], []
        for j in range(rings + 1):
            th = np.pi * j / rings
            for k in range(seg + 1):
                ph = 2 * np.pi * k / seg
                n = (np.sin(th) * np.cos(ph), np.cos(th), np.sin(th) * np.sin(ph))
                P.append((cx + rx * n[0], cy + ry * n[1], cz + rz * n[2]))
                N.append(n)
                T.append(self._uv(uv, k / seg, j / rings))
        for j in range(rings):
            for k in range(seg):
                a = j * (seg + 1) + k
                b = a + seg + 1
                I += [a, a + 1, b, a + 1, b + 1, b]
        self._add(P, N, T, I)

    def save(self, path):
        P = np.array(self.P, np.float32); N = np.array(self.N, np.float32)
        T = np.array(self.T, np.float32); I = np.array(self.I, np.uint32)
        import io
        buf = io.BytesIO(); self.im.save(buf, 'PNG'); png = buf.getvalue()
        parts, views = [], []
        def add(b, target=None):
            while sum(map(len, parts)) % 4: parts.append(b'\0')
            off = sum(map(len, parts)); parts.append(b)
            v = {'buffer': 0, 'byteOffset': off, 'byteLength': len(b)}
            if target: v['target'] = target
            views.append(v); return len(views) - 1
        vp = add(P.tobytes(), 34962); vn = add(N.tobytes(), 34962); vt = add(T.tobytes(), 34962)
        vi = add(I.tobytes(), 34963); vimg = add(png)
        acc = [
            {'bufferView': vp, 'componentType': 5126, 'count': len(P), 'type': 'VEC3', 'min': P.min(0).tolist(), 'max': P.max(0).tolist()},
            {'bufferView': vn, 'componentType': 5126, 'count': len(N), 'type': 'VEC3'},
            {'bufferView': vt, 'componentType': 5126, 'count': len(T), 'type': 'VEC2'},
            {'bufferView': vi, 'componentType': 5125, 'count': len(I), 'type': 'SCALAR'}]
        g = {'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
             'meshes': [{'primitives': [{'attributes': {'POSITION': 0, 'NORMAL': 1, 'TEXCOORD_0': 2}, 'indices': 3, 'material': 0}]}],
             'materials': [{'pbrMetallicRoughness': {'baseColorTexture': {'index': 0}, 'metallicFactor': 0, 'roughnessFactor': 1}, 'alphaMode': 'MASK', 'alphaCutoff': .5, 'doubleSided': True}],
             'textures': [{'source': 0, 'sampler': 0}], 'samplers': [{'magFilter': 9728, 'minFilter': 9728}],
             'images': [{'bufferView': vimg, 'mimeType': 'image/png'}],
             'accessors': acc, 'bufferViews': views}
        body = b''.join(parts)
        while len(body) % 4: body += b'\0'
        g['buffers'] = [{'byteLength': len(body)}]
        js = json.dumps(g).encode()
        while len(js) % 4: js += b' '
        out = struct.pack('<III', 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(body)) + struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(body), 0x004E4942) + body
        open(path, 'wb').write(out)
