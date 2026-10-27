import sys,os,numpy as np
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from uo import *
NB=458752
raw=np.fromfile(P('map0.mul'),np.uint8).reshape(NB,196)
rx=np.fromfile(P('map0x.mul'),np.uint8).reshape(NB,196)
f,v,e=uop_entries(P('map0LegacyMUL.uop'))
u=np.frombuffer(b''.join(uop_read(f,e[hashlittle2(b'build/map0legacymul/%08d.dat'%i)]) for i in range(113))[:NB*196],np.uint8).reshape(NB,196)
for n,a,b in (('mul/uop',raw,u),('mulx/uop',rx,u),('mul/mulx',raw,rx)):
  hd=(a[:,:4]!=b[:,:4]).any(1).sum(); cd=(a[:,4:]!=b[:,4:]).any(1)
  print(n,'hdr-diff blocks',hd,'cell-diff blocks',cd.sum())
  ids=np.nonzero(cd)[0]; bx=ids//512; by=ids%512
  if len(ids): print('  cell-diff bbox tiles x',bx.min()*8,bx.max()*8+7,'y',by.min()*8,by.max()*8+7)
print('uop hdr sample',u[:3,:4].tolist(),'mul hdr',raw[:3,:4].tolist())
