import sys,os,struct,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from uo import *
d=os.path.dirname(os.path.abspath(__file__))
tid=np.load(d+'/tid.npy'); z=np.load(d+'/z.npy')
td=open(P('tiledata.mul'),'rb').read()
land=[];off=0
for b in range(512):
  off+=4
  for j in range(32): fl,tex=struct.unpack_from('<QH',td,off); land.append((fl,tex,td[off+10:off+30].split(b'\0')[0])); off+=30
stat=[]
while off+4<=len(td):
  off+=4
  for j in range(32):
    if off+41>len(td): break
    fl=struct.unpack_from('<Q',td,off)[0]; hgt=td[off+20]; stat.append((fl,hgt,td[off+21:off+41].split(b'\0')[0])); off+=41
notex=np.array([land[i][1]==0 for i in range(16384)])
print('land cells w/o texture',int(notex[tid].sum()), 'ids', sorted(set(np.unique(tid[notex[tid]]).tolist()))[:30])
wetland=np.array([bool(land[i][0]&0x80) for i in range(16384)])
print('land cells wet',int(wetland[tid].sum()))
print('0x244 name',land[0x244][2],'0x1AE',land[0x1AE][2],'0x2',land[2][2])
# statics again
idx=np.fromfile(P('staidx0.mul'),'<i4').reshape(-1,3); sd=np.fromfile(P('statics0.mul'),np.uint8)
dt=np.dtype([('id','<u2'),('x','u1'),('y','u1'),('z','i1'),('hue','<u2')])
v=np.nonzero((idx[:,0]>=0)&(idx[:,1]>0))[0]
recs=[];bids=[]
for b in v:
  r=np.frombuffer(sd,dt,idx[b,1]//7,idx[b,0]); recs.append(r); bids.append(np.full(len(r),b,np.int32))
r=np.concatenate(recs); b=np.concatenate(bids)
gx=(b//512)*8+r['x']; gy=(b%512)*8+r['y']
fl=np.array([s[0] for s in stat],np.uint64); hg=np.array([s[1] for s in stat])
F=fl[r['id']]
wet=(F&0x80)!=0; h0=hg[r['id']]==0
print('wet statics',int(wet.sum()),'wet & height0',int((wet&h0).sum()))
lz=z[gy,gx]
flatwater=wet&h0&(r['z']<=lz+0)
print('wet h0 at/below land z',int(flatwater.sum()))
# duplicates
key=(gx.astype(np.int64)<<32)|(gy.astype(np.int64)<<16)|((r['z'].astype(np.int64)+128)<<8)
k2=key*65536+r['id']
print('exact dup (same id,x,y,z)',len(k2)-len(np.unique(k2)))
# per 64x64 chunk instance counts
cid=(gy//64)*(7168//64)+(gx//64)
c=np.bincount(cid,minlength=7168)
print('statics per 64x64 chunk: mean %.0f p50 %d p95 %d max %d nonempty %d'%(c.mean(),np.median(c),np.percentile(c,95),c.max(),(c>0).sum()))
c32=np.bincount((gy//32)*(7168//32)+(gx//32),minlength=224*128)
print('per 32x32: p95 %d max %d'%(np.percentile(c32,95),c32.max()))
# land chunk z range
zz=z.reshape(64,64,112,64).transpose(0,2,1,3).reshape(-1,4096)
print('land 64-chunk all-0x244 (void)',int((tid.reshape(64,64,112,64).transpose(0,2,1,3).reshape(-1,4096)==0x244).all(1).sum()))
# animated / light
print('anim instances',int(((F&0x1000000)!=0).sum()),'light',int(((F&0x800000)!=0).sum()))
