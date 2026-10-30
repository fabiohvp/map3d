"""Leitor das animacoes classicas do UO (anim*.idx / anim*.mul, Bodyconv.def, mobtypes.txt).

Layout de um registro (acao + direcao) no .mul:
  uint16 paleta[256] (ARGB1555)
  int32  nframes
  int32  offs[nframes]          relativos ao fim da paleta
  quadro: int16 cx, int16 cy, uint16 w, uint16 h; runs int32 ate 0x7FFF7FFF
    run: x = bits 22..31 (10 bits com sinal), y = bits 12..21 (com sinal), n = bits 0..11; seguem n indices da paleta
    pixel (x + cx, y + cy + h) no quadro; o pe do mobile (ancora) fica em (cx, cy + h)

Direcoes gravadas no arquivo (0..4): 0 = de frente (tela para baixo), cada passo gira 45 graus para a esquerda da tela
ate 4 = de costas. As outras tres sao espelhos de 1..3.
"""
import os
import struct
import numpy as np

TYPES = ('MONSTER', 'SEA_MONSTER', 'ANIMAL', 'HUMAN', 'EQUIPMENT')

# nomes das acoes por tipo de corpo (como no UOFiddler)
ACTIONS_HIGH = ['Walk', 'Idle', 'Die1', 'Die2', 'Attack1', 'Attack2', 'Attack3', 'AttackBow', 'AttackCrossBow',
                'AttackThrow', 'GetHit', 'Pillage', 'Stomp', 'Cast2', 'Cast3', 'BlockRight', 'BlockLeft', 'Idle2',
                'Fidget', 'Fly', 'TakeOff', 'GetHitInAir']
ACTIONS_LOW = ['Walk', 'Run', 'Idle', 'Eat', 'Alert', 'Attack1', 'Attack2', 'GetHit', 'Die1', 'Idle2', 'Fidget',
               'LieDown', 'Die2']
ACTIONS_PEOPLE = ['Walk_01', 'WalkStaff_01', 'Run_01', 'RunStaff_01', 'Idle_01', 'Idle_01b', 'Fidget_Yawn_Stretch_01',
                  'CombatIdle1H_01', 'CombatIdle1H_01b', 'AttackSlash1H_01', 'AttackPierce1H_01', 'AttackBash1H_01',
                  'AttackBash2H_01', 'AttackSlash2H_01', 'AttackPierce2H_01', 'CombatAdvance_1H_01', 'Spell1',
                  'Spell2', 'AttackBow_01', 'AttackCrossbow_01', 'GetHit_Fr_Hi_01', 'Die_Hard_Fwd_01',
                  'Die_Hard_Back_01', 'Horse_Walk_01', 'Horse_Run_01', 'Horse_Idle_01', 'Horse_Attack1H_SlashRight_01',
                  'Horse_AttackBow_01', 'Horse_AttackCrossbow_01', 'Horse_Attack2H_SlashRight_01', 'Block_Shield_Hard_01',
                  'Punch_Punch_Jab_01', 'Bow_Lesser_01', 'Salute_Armed1h_01', 'Ingest_Eat_01']
ACTIONS = {110: ACTIONS_HIGH, 65: ACTIONS_LOW, 175: ACTIONS_PEOPLE}


def find_client(start):
    """Sobe a partir de start ate achar a pasta do cliente (a que tem anim.idx)."""
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, 'anim.idx')):
            return d
        up = os.path.dirname(d)
        if up == d:
            raise SystemExit('pasta do cliente nao encontrada: passe --client <pasta com anim.idx>')
        d = up


def body_layout(fileno, body):
    """(indice do primeiro registro, registros do corpo) no arquivo animN (regras do Ultima SDK)."""
    if fileno == 2:
        return (body * 110, 110) if body < 200 else (22000 + (body - 200) * 65, 65)
    if fileno == 3:
        if body < 300:
            return body * 65, 65
        if body < 400:
            return 33000 + (body - 300) * 110, 110
        return 35000 + (body - 400) * 175, 175
    if fileno == 5 and body == 34:
        return 22000 + (body - 200) * 65, 65
    if body < 200:
        return body * 110, 110
    if body < 400:
        return 22000 + (body - 200) * 65, 65
    return 35000 + (body - 400) * 175, 175


def argb1555(c):
    c = np.asarray(c, np.uint32)
    r = (c >> 10) & 31
    g = (c >> 5) & 31
    b = c & 31
    return np.stack([(r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)], -1).astype(np.uint8)


class AnimFile:
    def __init__(self, client, fileno):
        n = '' if fileno == 1 else str(fileno)
        self.fileno = fileno
        self.idx = np.fromfile(os.path.join(client, f'anim{n}.idx'), np.int32).reshape(-1, 3)
        self.mul = open(os.path.join(client, f'anim{n}.mul'), 'rb')

    def entry(self, i):
        if i < 0 or i >= len(self.idx):
            return None
        off, ln, _ = self.idx[i]
        if off < 0 or ln <= 0:
            return None
        self.mul.seek(int(off))
        return self.mul.read(int(ln))

    def has_body(self, body):
        a, n = body_layout(self.fileno, body)
        e = self.idx[a:a + n]
        return len(e) > 0 and bool(((e[:, 0] >= 0) & (e[:, 1] > 0)).any())


def decode(raw):
    """Registro -> (paleta RGB 256x3, [quadros]); quadro = dict(cx, cy, w, h, idx=uint8 HxW, mask=bool HxW)."""
    if raw is None or len(raw) < 516:
        return None, []
    pal = argb1555(np.frombuffer(raw, '<u2', 256))
    nf = struct.unpack_from('<i', raw, 512)[0]
    if nf <= 0 or nf > 256:
        return pal, []
    offs = struct.unpack_from(f'<{nf}i', raw, 516)
    frames = []
    for o in offs:
        p = 512 + o
        if p + 8 > len(raw):
            continue
        cx, cy, w, h = struct.unpack_from('<hhHH', raw, p)
        p += 8
        if w == 0 or h == 0 or w > 1024 or h > 1024:
            continue
        idx = np.zeros((h, w), np.uint8)
        mask = np.zeros((h, w), bool)
        while p + 4 <= len(raw):
            hd = struct.unpack_from('<I', raw, p)[0]
            p += 4
            if hd == 0x7FFF7FFF:
                break
            x = (hd >> 22) & 0x3FF
            y = (hd >> 12) & 0x3FF
            if x & 0x200:
                x -= 0x400
            if y & 0x200:
                y -= 0x400
            n = hd & 0xFFF
            run = np.frombuffer(raw, np.uint8, n, p)
            p += n
            px, py = x + cx, y + cy + h
            if 0 <= py < h:
                a, b = max(px, 0), min(px + n, w)
                if b > a:
                    idx[py, a:b] = run[a - px:b - px]
                    mask[py, a:b] = True
        frames.append({'cx': cx, 'cy': cy, 'w': w, 'h': h, 'idx': idx, 'mask': mask})
    return pal, frames


def read_bodyconv(client):
    """body -> (arquivo, corpo nesse arquivo) para corpos redirecionados ao anim2..anim5."""
    conv = {}
    p = os.path.join(client, 'Bodyconv.def')
    if not os.path.exists(p):
        return conv
    for ln in open(p, encoding='latin-1'):
        ln = ln.split('#')[0].split()
        if len(ln) < 2:
            continue
        try:
            v = [int(t) for t in ln]
        except ValueError:
            continue
        for k, b in enumerate(v[1:5]):
            if b >= 0:
                conv[v[0]] = (k + 2, b)
                break
    return conv


def read_mobtypes(client):
    out = {}
    p = os.path.join(client, 'mobtypes.txt')
    if not os.path.exists(p):
        return out
    for ln in open(p, encoding='latin-1'):
        t = ln.split('#')[0].split()
        if len(t) >= 2 and t[0].isdigit() and t[1] in TYPES:
            out[int(t[0])] = t[1]
    return out


class Anims:
    def __init__(self, client):
        self.client = client
        self.files = {}
        for f in range(1, 6):
            n = '' if f == 1 else str(f)
            if os.path.exists(os.path.join(client, f'anim{n}.idx')):
                self.files[f] = AnimFile(client, f)
        self.conv = read_bodyconv(client)
        self.types = read_mobtypes(client)

    def source(self, body):
        """(arquivo, corpo no arquivo) de onde sai a animacao do corpo, ou None."""
        if body in self.conv:
            f, b = self.conv[body]
            if f in self.files and self.files[f].has_body(b):
                return f, b
        if self.files[1].has_body(body):
            return 1, body
        return None

    def bodies(self, maxbody=2048):
        return [b for b in range(maxbody) if self.source(b)]

    def actions(self, body):
        """lista de (acao, nome, [registro por direcao 0..4]) com dados."""
        src = self.source(body)
        if not src:
            return []
        f, b = src
        af = self.files[f]
        first, n = body_layout(f, b)
        names = ACTIONS[n]
        out = []
        for a in range(n // 5):
            raws = [af.entry(first + a * 5 + d) for d in range(5)]
            if any(r is not None for r in raws):
                out.append((a, names[a], raws))
        return out
