import numpy as np, itertools
E24=[1.0,1.2,1.5,1.8,2.2,2.7,3.3,3.9,4.7,5.6,6.8,8.2]   # E12: the common values
vals=np.array(sorted({round(m*d,1) for d in (100,1e3,1e4) for m in E24 if 100<=m*d<=47000}))
VCC=3.3
def level(rpu,rb,ri):                    # node voltage with a button leg of ri closed
    par=(rb*ri)/(rb+ri) if rb else ri
    return VCC*par/(rpu+par)
best=None
Rb_choices=np.concatenate([[0],vals[(vals>=2000)&(vals<=47000)]])   # 0 = no bias resistor
for rpu in vals[(vals>=2000)&(vals<=47000)]:
  for rb in Rb_choices:
    idle = VCC if rb==0 else VCC*rb/(rpu+rb)
    if idle>2.40: continue
    L=np.array([level(rpu,rb,ri) for ri in vals])
    ok=(L>=0.30)&(L<=idle-0.25)
    idx=np.where(ok)[0]
    if len(idx)<3: continue
    # choose three levels maximising the smallest gap (including to idle and to 0.30 floor)
    Ls=L[idx]
    for a,b,c in itertools.combinations(range(len(idx)),3):
        t=sorted([Ls[a],Ls[b],Ls[c]])
        gap=min(t[0]-0.0, t[1]-t[0], t[2]-t[1], idle-t[2])
        if best is None or gap>best[0]:
            best=(gap,rpu,rb,[vals[idx[a]],vals[idx[b]],vals[idx[c]]],t,idle)
g,rpu,rb,ris,t,idle=best
print('min gap %.3f V'%g,'Rpu',rpu,'Rbias',rb,'Ri',sorted(ris),'levels',[round(x,3) for x in t],'idle',round(idle,3))
# worst case: 1% resistors, +-50 mV ADC error
import random
worst=1
for _ in range(20000):
    r=lambda x:x*(1+random.uniform(-.01,.01))
    L=sorted(level(r(rpu),r(rb) if rb else 0,r(ri)) for ri in ris)
    ids=VCC*r(rb)/(r(rpu)+r(rb)) if rb else VCC
    worst=min(worst,min(L[0],L[1]-L[0],L[2]-L[1],ids-L[2]))
print('worst-case gap with 1%% resistors: %.3f V (leaves %.0f mV each side after +-50 mV ADC error)'%(worst,(worst-0.1)/2*1000))
