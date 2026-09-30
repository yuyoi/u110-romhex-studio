import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageDraw, ImageFont
W,H=128,64; PAD=500
base=Image.open('../art/girl_redraw2.png').convert('L')
def mk(img):
    img=img.copy(); ImageDraw.Draw(img).rectangle((485,345,540,372),fill=255)   # drop the collarbone dash: a fat square at 128x64
    return ImageOps.expand(img,PAD,fill=255)
srcN=mk(base)
blk=base.copy(); d=ImageDraw.Draw(blk)
for (ex,ey) in [(407,208),(519,208)]:           # blink: eyes become a thin closed line
    d.ellipse((ex-24,ey-24,ex+24,ey+24),fill=255); d.line((ex-18,ey+2,ex+18,ey+2),fill=0,width=4)
srcB=mk(Image.open('../art/girl_closed.png').convert('L'))   # the user's own closed-eye drawing
hlf=base.copy(); d=ImageDraw.Draw(hlf)
for (ex,ey) in [(407,208),(519,208)]:
    d.ellipse((ex-24,ey-24,ex+24,ey+24),fill=255); d.ellipse((ex-17,ey-6,ex+17,ey+8),fill=0)
srcH=mk(hlf)
FAR=(640,300,1280); NEAR=(350,218,720)            # centre x, y, width (source px)
def cam(t):
    e=t*t*(3-2*t); w=FAR[2]*(NEAR[2]/FAR[2])**e
    return FAR[0]+(NEAR[0]-FAR[0])*e, FAR[1]+(NEAR[1]-FAR[1])*e, w, e
def crop(src,cx,cy,w):
    h=w/2; x0=cx-w/2+PAD; y0=cy-h/2+PAD
    return src.crop((int(x0),int(y0),int(x0+w),int(y0+h)))
def mD(c):
    g=c.resize((W,H),Image.LANCZOS).filter(ImageFilter.UnsharpMask(1.2,250,0)); return np.asarray(g.convert('1'))==0
def mE(c):
    g=ImageOps.autocontrast(c.resize((W,H),Image.LANCZOS),cutoff=3); return np.asarray(g)<170
font=lambda s:ImageFont.truetype(r'C:\Windows\Fonts\consolab.ttf',int(s))
def logo(size,x,y,n=4,cursor=False):
    im=Image.new('L',(W,H),0); d=ImageDraw.Draw(im); f=font(size); s='U110'[:n]
    d.text((x,y),s,font=f,fill=255)
    full=d.textlength('U110',font=f); cw=d.textlength(s,font=f)
    if cursor: d.rectangle((x+cw+1,y+size*0.15,x+cw+size*0.3,y+size*0.85),fill=255)
    return np.asarray(im)>128,(int(x)-1,int(y)-1,int(x+full)+2,int(y+size*1.1)+1)
def overlay(a,size,x,y):
    a=a.copy(); x0=max(0,int(x)-1); a[0:36,x0:x0+46]=False
    ptext(a,'U110',x,1,2,1); ptext(a,'HEX',x,19,1,1); ptext(a,'WIZARD',x,28,1,1)
    return a
FPS=15; frames=[]
def emit(a,shift=0):
    if shift: a=np.roll(a,shift,axis=0)
    frames.append(a.copy())
rnd=np.random.RandomState(3); mask=rnd.rand(H,W)
GL={
 'U':["X...X","X...X","X...X","X...X","X...X","X...X",".XXX."],
 '1':["..X..",".XX..","..X..","..X..","..X..","..X..",".XXX."],
 '0':[".XXX.","X...X","X..XX","X.X.X","XX..X","X...X",".XXX."],
 'H':["X...X","X...X","X...X","XXXXX","X...X","X...X","X...X"],
 'E':["XXXXX","X....","X....","XXXX.","X....","X....","XXXXX"],
 'X':["X...X","X...X",".X.X.","..X..",".X.X.","X...X","X...X"],
 'W':["X...X","X...X","X...X","X.X.X","X.X.X","XX.XX","X...X"],
 'I':[".XXX.","..X..","..X..","..X..","..X..","..X..",".XXX."],
 'Z':["XXXXX","....X","...X.","..X..",".X...","X....","XXXXX"],
 'A':[".XXX.","X...X","X...X","XXXXX","X...X","X...X","X...X"],
 'R':["XXXX.","X...X","X...X","XXXX.","X.X..","X..X.","X...X"],
 'D':["XXXX.","X...X","X...X","X...X","X...X","X...X","XXXX."],
 ' ':["     "]*7}
def tw(t,sc,sp): return len(t)*5*sc+max(0,len(t)-1)*sp
def ptext(img,t,x,y,sc,sp):
    cx=int(x)
    for ch in t:
        for r,row in enumerate(GL[ch]):
            for c,v in enumerate(row):
                if v=='X':
                    for dy in range(sc):
                        for dx in range(sc):
                            px=cx+c*sc+dx; py=int(y)+r*sc+dy
                            if 0<=px<W and 0<=py<H: img[py,px]=True
        cx+=5*sc+sp
    return img
def typed(n1,n2,cur):
    im=np.zeros((H,W),bool); t1='U110'[:n1]; t2='HEX WIZARD'[:n2]
    x1=(W-tw('U110',4,4))//2; x2=(W-tw('HEX WIZARD',2,2))//2
    ptext(im,t1,x1,2,4,4); ptext(im,t2,x2,40,2,2)
    if cur:
        if n2>0: cx=x2+tw(t2,2,2)+2; im[40:54,cx:cx+8]=True
        else: cx=x1+tw(t1,4,4)+4; im[2:30,cx:cx+10]=True if cx+10<=W else True
    return im
for i in range(4): emit(np.zeros((H,W),bool))
for n in range(1,5):
    for k in range(4): emit(typed(n,0,k%2==0))
for n in range(1,11):
    for k in range(2): emit(typed(4,n,k%2==0))
for k in range(10): emit(typed(4,10,(k//2)%2==0))
cx,cy,w,e=cam(0); far=mD(crop(srcN,cx,cy,w)); txt=typed(4,10,False)
for k in range(1,7): emit(np.where(mask<k/6,far,txt))
for k in range(12): emit(mD(crop(srcN,cx,cy,w)))
Z=26
for k in range(Z+1):
    cx,cy,w,e=cam(k/Z); c=crop(srcN,cx,cy,w)
    p=np.clip((e-0.3)/0.5,0,1)
    a=np.where(mask<p,mE(c),mD(c))
    q=np.clip((e-0.2)/0.5,0,1); q=q*q*(3-2*q); lx=-40+42*q
    emit(overlay(a,18,lx,1) if q>0 else a)
cx,cy,w,e=cam(1)
idle=overlay(mE(crop(srcN,cx,cy,w)),18,2,1); blink=overlay(mE(crop(srcB,cx,cy,w)),18,2,1); half=overlay(mE(crop(srcH,cx,cy,w)),18,2,1)
for k in range(FPS*8):
    ph=k%45
    a=(half if ph in (38,42) else blink if ph in (39,40,41) else idle).copy()
    if (k%38) in (34,35):
        r0=int(24+(k*7)%30); a[r0:r0+4]=np.roll(a[r0:r0+4],3 if k%2 else -3,axis=1)   # below the logo, never on it
    emit(a)
S=6; imgs=[Image.fromarray((a*255).astype(np.uint8)).resize((W*S,H*S),Image.NEAREST).convert('P') for a in frames]
imgs[0].save('../art/u110_intro_preview.gif',save_all=True,append_images=imgs[1:],duration=int(1000/FPS),loop=0,optimize=True)
def still(a,n): Image.fromarray((a*255).astype(np.uint8)).resize((W*S,H*S),Image.NEAREST).save(n)
still(idle,'v3_final.png'); still(blink,'v3_blink.png'); still(half,'v3_half.png')
print(len(frames))

# ---- firmware header: unique 128x64 XBM frames + intro sequence
nIntro=len(frames)-FPS*8
uniq=[]; idx={}
def fid(a):
    key=np.packbits(a.astype(np.uint8),axis=1,bitorder='little').tobytes()
    if key not in idx: idx[key]=len(uniq); uniq.append(key)
    return idx[key]
seq=[fid(a) for a in frames[:nIntro]]
IDLE,HALF,CLOSED=fid(idle),fid(half),fid(blink)
with open('../firmware/sst_programmer/splash.h','w') as f:
    f.write('// generated by oled_anim/anim3.py: 128x64 XBM frames (ink = lit), intro sequence, idle/blink frames\n#pragma once\n')
    f.write('#define SPL_W 128\n#define SPL_H 64\n#define SPL_FRAME_MS %d\n'%int(1000/FPS))
    f.write('#define SPL_IDLE %d\n#define SPL_HALF %d\n#define SPL_CLOSED %d\n'%(IDLE,HALF,CLOSED))
    f.write('#define SPL_NFRAMES %d\n#define SPL_NSEQ %d\n'%(len(uniq),len(seq)))
    f.write('static const uint8_t SPL_FRAMES[SPL_NFRAMES][1024] PROGMEM = {\n')
    for k in uniq: f.write('{'+','.join('0x%02x'%b for b in k)+'},\n')
    f.write('};\nstatic const uint8_t SPL_SEQ[SPL_NSEQ] PROGMEM = {'+','.join(str(i) for i in seq)+'};\n')
print('unique frames',len(uniq),'intro',len(seq))
