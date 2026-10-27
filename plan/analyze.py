import sys, os, struct, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uo import *

W, H = 7168, 4096
BW, BH = W // 8, H // 8
NB = BW * BH

# ---- map0.mul vs map0LegacyMUL.uop vs map0x.mul
raw = np.fromfile(P('map0.mul'), dtype=np.uint8)
print('map0.mul blocks', raw.size / 196, 'expected', NB)
f, ver, ents = uop_entries(P('map0LegacyMUL.uop'))
print('uop ver', ver, 'entries', len(ents))
parts = []
i = 0
while True:
    h = hashlittle2(b'build/map0legacymul/%08d.dat' % i)
    if h not in ents: break
    parts.append(uop_read(f, ents[h])); i += 1
uopdata = b"".join(parts)[:NB*196]
print('uop chunks', i, 'bytes', len(uopdata), 'flags', set(e[3] for e in ents.values()))
print('map0.mul == uop:', uopdata == raw.tobytes())
rawx = np.fromfile(P('map0x.mul'), dtype=np.uint8)
print('map0.mul == map0x.mul:', np.array_equal(raw, rawx), 'diff bytes', int((raw != rawx).sum()))
uop_bytes = np.frombuffer(uopdata, dtype=np.uint8)
if len(uopdata) == raw.size:
    print('uop vs mul diff bytes', int((uop_bytes != raw).sum()), 'uop vs mulx', int((uop_bytes != rawx).sum()))

# ---- decode land
blk = uop_bytes.reshape(NB, 196)
hdr = blk[:, :4].copy().view('<u4').ravel()
cells = blk[:, 4:].reshape(NB, 64, 3)
tid = (cells[:, :, 0].astype(np.uint16) | (cells[:, :, 1].astype(np.uint16) << 8))
z = cells[:, :, 2].view(np.int8)
# block index = bx*BH + by ; cell = cy*8+cx
tid_g = tid.reshape(BW, BH, 8, 8).transpose(1, 2, 0, 3).reshape(H, W)
z_g = z.reshape(BW, BH, 8, 8).transpose(1, 2, 0, 3).reshape(H, W)
print('header unique', np.unique(hdr)[:10], len(np.unique(hdr)))
u, c = np.unique(tid_g, return_counts=True)
print('land unique ids', len(u), 'max id', u.max())
print('top land ids', list(zip(u[np.argsort(-c)][:15], np.sort(c)[::-1][:15])))
print('z min/max', z_g.min(), z_g.max())
dz_x = np.abs(np.diff(z_g.astype(np.int16), axis=1)); dz_y = np.abs(np.diff(z_g.astype(np.int16), axis=0))
print('|dz| x: mean %.3f p99 %d max %d' % (dz_x.mean(), np.percentile(dz_x, 99), dz_x.max()))
# NoDraw / void tiles
for t in (0x0002, 0x0244, 0x01AE, 0x01AF, 0x01B0, 0x01B1, 0x01B2, 0x01B3, 0x01B4, 0x01B5, 0x01B6, 0x01B7, 0x01B8, 0x01B9, 0x01BA, 0x01BB, 0x01BC, 0x01BD):
    n = int((tid_g == t).sum())
    if n: print('tile 0x%04X count %d' % (t, n))
# flat blocks
zb = z.reshape(NB, 64); flatblk = (zb.max(1) == zb.min(1)).sum()
tb = tid.reshape(NB, 64); uniblk = (tb.max(1) == tb.min(1)).sum()
print('blocks flat z', flatblk, 'blocks single tile', uniblk, 'both', int(((zb.max(1) == zb.min(1)) & (tb.max(1) == tb.min(1))).sum()))
# 64x64 chunk stats
cz = z_g.reshape(H // 64, 64, W // 64, 64)
print('64x64 chunks', cz.shape[0] * cz.shape[2])
# entropy-ish: unique per 64 chunk
ct = tid_g.reshape(H // 64, 64, W // 64, 64).transpose(0, 2, 1, 3).reshape(-1, 4096)
nu = np.array([len(np.unique(r)) for r in ct])
print('unique land ids per 64x64 chunk: mean %.1f max %d' % (nu.mean(), nu.max()))
np.save(os.path.join(os.path.dirname(__file__), 'tid.npy'), tid_g)
np.save(os.path.join(os.path.dirname(__file__), 'z.npy'), z_g)

# ---- statics
idx = np.fromfile(P('staidx0.mul'), dtype='<i4').reshape(-1, 3)
print('staidx entries', len(idx))
lk, ln = idx[:, 0], idx[:, 1]
valid = (lk >= 0) & (ln > 0) & (lk != -1)
print('blocks with statics', int(valid.sum()), 'total bytes', int(ln[valid].sum()), 'items', int(ln[valid].sum() // 7))
sdata = np.fromfile(P('statics0.mul'), dtype=np.uint8)
print('statics0.mul size', sdata.size, 'referenced', int(ln[valid].sum()), 'uniq lookups', len(np.unique(lk[valid])))
# also check uop statics?
dt = np.dtype([('id', '<u2'), ('x', 'u1'), ('y', 'u1'), ('z', 'i1'), ('hue', '<u2')])
items = []
bid = np.nonzero(valid)[0]
for b in bid:
    rec = np.frombuffer(sdata, dtype=dt, count=ln[b] // 7, offset=lk[b])
    items.append((b, rec))
cnt = np.array([len(r) for _, r in items])
print('statics per block: mean %.2f max %d' % (cnt.mean(), cnt.max()))
allr = np.concatenate([r for _, r in items])
su, sc = np.unique(allr['id'], return_counts=True)
print('static unique ids', len(su), 'max', su.max())
print('top static ids', [(hex(a), int(b)) for a, b in zip(su[np.argsort(-sc)][:20], np.sort(sc)[::-1][:20])])
print('hue nonzero', int((allr['hue'] != 0).sum()), 'unique hues', len(np.unique(allr['hue'])))
print('static z min/max', allr['z'].min(), allr['z'].max(), 'x/y max', allr['x'].max(), allr['y'].max())
np.save(os.path.join(os.path.dirname(__file__), 'sids.npy'), su)

# ---- tiledata (HS: 64-bit flags)
td = open(P('tiledata.mul'), 'rb').read()
print('tiledata size', len(td))
land = []
off = 0
for blkn in range(512):
    off += 4
    for j in range(32):
        fl, tex = struct.unpack_from('<QH', td, off); off += 30
        land.append((fl, tex))
stat = []
while off + 4 <= len(td):
    off += 4
    for j in range(32):
        if off + 41 > len(td): break
        fl, wt, q, mi, u2, qty, anim, u3, hue, u4, u5, hgt = struct.unpack_from('<QBBHBBHBBBBB', td, off)
        name = td[off + 21:off + 41].split(b'\0')[0]
        stat.append((fl, hgt, name)); off += 41
print('land entries', len(land), 'static entries', len(stat))
tex_used = set(land[t][1] for t in u)
print('land ids w/ texture', sum(1 for t in u if land[t][1] != 0), 'unique textures used', len(tex_used - {0}))
# flags of used statics
FL = {'Background': 1, 'Transparent': 4, 'Translucent': 8, 'Wall': 0x10, 'Impassable': 0x40, 'Wet': 0x80, 'Surface': 0x200, 'Bridge': 0x400, 'Window': 0x1000, 'Foliage': 0x20000, 'PartialHue': 0x40000, 'LightSource': 0x800000, 'Animation': 0x1000000, 'Roof': 0x10000000, 'Door': 0x20000000}
for k, v in FL.items():
    n = sum(1 for s in su if stat[s][0] & v)
    inst = int(sum(c for s, c in zip(su, sc) if stat[s][0] & v))
    print('static flag %-12s ids %5d instances %8d' % (k, n, inst))
print('static heights hist', np.bincount([stat[s][1] for s in su])[:40].tolist())

# ---- texidx
ti = np.fromfile(P('texidx.mul'), dtype='<i4').reshape(-1, 3)
ok = sum(1 for t in tex_used if t and t < len(ti) and ti[t, 0] >= 0 and ti[t, 1] > 0)
sizes = {}
for t in tex_used:
    if t and t < len(ti) and ti[t, 1] > 0:
        sizes[int(ti[t, 1])] = sizes.get(int(ti[t, 1]), 0) + 1
print('texidx entries', len(ti), 'used textures present', ok, 'size hist(bytes)', sizes)

# ---- art uop
fa, va, ea = uop_entries(P('artLegacyMUL.uop'))
print('art uop entries', len(ea), 'flags', set(e[3] for e in ea.values()))
present = sum(1 for s in su if hashlittle2(b'build/artlegacymul/%08d.tga' % (s + 0x4000)) in ea)
print('used statics present in art uop', present, '/', len(su))
dims = []
for s in su[:: max(1, len(su) // 400)]:
    h = hashlittle2(b'build/artlegacymul/%08d.tga' % (s + 0x4000))
    if h in ea:
        d = uop_read(fa, ea[h]); _, w, hh = struct.unpack_from('<Ihh', d, 0); dims.append((w, hh))
dims = np.array(dims)
print('sample static art dims: w mean %.1f max %d, h mean %.1f max %d, px sum est %.1f M' % (dims[:, 0].mean(), dims[:, 0].max(), dims[:, 1].mean(), dims[:, 1].max(), (dims[:, 0] * dims[:, 1]).mean() * len(su) / 1e6))
