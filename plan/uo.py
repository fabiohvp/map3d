import struct, os, sys, zlib

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
def P(n): return os.path.join(ROOT, n)

M = 0xFFFFFFFF
def rot(x, k): return ((x << k) | (x >> (32 - k))) & M

def hashlittle2(s: bytes):
    length = len(s)
    a = b = c = (0xDEADBEEF + length) & M
    k = 0
    while length > 12:
        a = (a + (s[k] | s[k+1] << 8 | s[k+2] << 16 | s[k+3] << 24)) & M
        b = (b + (s[k+4] | s[k+5] << 8 | s[k+6] << 16 | s[k+7] << 24)) & M
        c = (c + (s[k+8] | s[k+9] << 8 | s[k+10] << 16 | s[k+11] << 24)) & M
        a = (a - c) & M; a ^= rot(c, 4); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 6); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 8); b = (b + a) & M
        a = (a - c) & M; a ^= rot(c, 16); c = (c + b) & M
        b = (b - a) & M; b ^= rot(a, 19); a = (a + c) & M
        c = (c - b) & M; c ^= rot(b, 4); b = (b + a) & M
        length -= 12; k += 12
    if length == 0:
        return (b << 32) | c
    t = s[k:] + b'\0' * 12
    if length >= 12: c = (c + (t[11] << 24)) & M
    if length >= 11: c = (c + (t[10] << 16)) & M
    if length >= 10: c = (c + (t[9] << 8)) & M
    if length >= 9: c = (c + t[8]) & M
    if length >= 8: b = (b + (t[7] << 24)) & M
    if length >= 7: b = (b + (t[6] << 16)) & M
    if length >= 6: b = (b + (t[5] << 8)) & M
    if length >= 5: b = (b + t[4]) & M
    if length >= 4: a = (a + (t[3] << 24)) & M
    if length >= 3: a = (a + (t[2] << 16)) & M
    if length >= 2: a = (a + (t[1] << 8)) & M
    if length >= 1: a = (a + t[0]) & M
    c ^= b; c = (c - rot(b, 14)) & M
    a ^= c; a = (a - rot(c, 11)) & M
    b ^= a; b = (b - rot(a, 25)) & M
    c ^= b; c = (c - rot(b, 16)) & M
    a ^= c; a = (a - rot(c, 4)) & M
    b ^= a; b = (b - rot(a, 14)) & M
    c ^= b; c = (c - rot(b, 24)) & M
    return (b << 32) | c

def uop_entries(path):
    f = open(path, 'rb')
    magic, ver, sig, nxt, bsz, cnt = struct.unpack('<4sIIQII', f.read(28))
    ents = {}
    while nxt:
        f.seek(nxt)
        fc, nxt = struct.unpack('<IQ', f.read(12))
        for _ in range(fc):
            off, hl, cl, dl, h, adl, flag = struct.unpack('<QIIIQIH', f.read(34))
            if off: ents[h] = (off + hl, cl, dl, flag)
    return f, ver, ents

def uop_read(f, e):
    off, cl, dl, flag = e
    f.seek(off); d = f.read(cl)
    if flag == 1: d = zlib.decompress(d)
    return d
