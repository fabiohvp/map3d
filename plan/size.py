import sys,os,struct,zlib,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from uo import *
try:
  import brotli; C=lambda b: brotli.compress(b,quality=9); cn='brotli9'
except ImportError:
  C=lambda b: zlib.compress(b,9); cn='zlib9'
d=os.path.dirname(os.path.abspath(__file__))
tid=np.load(d+'/tid.npy'); z=np.load(d+'/z.npy')
VOID={0x2,0x1DB,0x244}|set(range(0x1AE,0x1B6))
voidm=np.isin(tid,list(VOID))
zp=np.pad(z,((0,1),(0,1)),mode='edge')
raw=comp=n=0; rawst=compst=0; ninst=0
idx=np.fromfile(P('staidx0.mul'),'<i4').reshape(-1,3); sd=np.fromfile(P('statics0.mul'),np.uint8)
dt=np.dtype([('id','<u2'),('x','u1'),('y','u1'),('z','i1'),('hue','<u2')])
td=open(P('tiledata.mul'),'rb').read(); off=512*(4+32*30); fl=[]
while off+4<=len(td):
  off+=4
  for j in range(32):
    if off+41>len(td): break
    fl.append((struct.unpack_from('<Q',td,off)[0],td[off+20])); off+=41
wet=np.array([(f&0x80)!=0 and h==0 for f,h in fl])
for cy in range(64):
  for cx in range(112):
    t=tid[cy*64:cy*64+64,cx*64:cx*64+64]
    if voidm[cy*64:cy*64+64,cx*64:cx*64+64].all(): continue
    h=zp[cy*64:cy*64+65,cx*64:cx*64+65].astype(np.int8)
    tt=np.where(voidm[cy*64:cy*64+64,cx*64:cx*64+64],0xFFFF,t).astype('<u2')
    b=h.tobytes()+tt.tobytes()+bytes(512)
    raw+=len(b); comp+=len(C(b)); n+=1
    # statics of chunk: 8 blocks x 8 blocks
    recs=[]
    for bx in range(cx*8,cx*8+8):
      for by in range(cy*8,cy*8+8):
        i=bx*512+by; lk,ln,_=idx[i]
        if lk<0 or ln<=0: continue
        r=np.frombuffer(sd,dt,ln//7,lk)
        r=r[~wet[r['id']]]
        if len(r)==0: continue
        a=np.zeros(len(r),dtype=[('x','u1'),('y','u1'),('z','i1'),('f','u1'),('id','<u2'),('hue','<u2')])
        a['x']=(bx-cx*8)*8+r['x']; a['y']=(by-cy*8)*8+r['y']; a['z']=r['z']; a['id']=r['id']; a['hue']=r['hue']
        recs.append(a)
    if recs:
      a=np.concatenate(recs); a=a[np.lexsort((a['z'],a['x'].astype(int)+a['y']))]
      # SoA for better compression
      b=b''.join(a[k].tobytes() for k in a.dtype.names)
      rawst+=len(b); compst+=len(C(b)); ninst+=len(a)
print(cn,'terrain chunks',n,'raw %.1fMB comp %.1fMB avg %.1fKB'%(raw/1e6,comp/1e6,comp/n/1e3))
print('statics inst',ninst,'raw %.1fMB comp %.1fMB'%(rawst/1e6,compst/1e6))
