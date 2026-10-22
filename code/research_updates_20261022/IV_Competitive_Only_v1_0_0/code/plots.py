"""Small dependency-free PNG plots from aggregate data. No SciPy/matplotlib."""
from common import *
import struct,zlib
# Original compact bitmap lettering; plotting depends only on NumPy/stdlib.
FONT={
'A':'01110 10001 10001 11111 10001 10001 10001','B':'11110 10001 10001 11110 10001 10001 11110',
'C':'01111 10000 10000 10000 10000 10000 01111','D':'11110 10001 10001 10001 10001 10001 11110',
'E':'11111 10000 10000 11110 10000 10000 11111','F':'11111 10000 10000 11110 10000 10000 10000',
'G':'01111 10000 10000 10111 10001 10001 01111','H':'10001 10001 10001 11111 10001 10001 10001',
'I':'11111 00100 00100 00100 00100 00100 11111','J':'00111 00010 00010 00010 10010 10010 01100',
'K':'10001 10010 10100 11000 10100 10010 10001','L':'10000 10000 10000 10000 10000 10000 11111',
'M':'10001 11011 10101 10101 10001 10001 10001','N':'10001 11001 10101 10011 10001 10001 10001',
'O':'01110 10001 10001 10001 10001 10001 01110','P':'11110 10001 10001 11110 10000 10000 10000',
'Q':'01110 10001 10001 10001 10101 10010 01101','R':'11110 10001 10001 11110 10100 10010 10001',
'S':'01111 10000 10000 01110 00001 00001 11110','T':'11111 00100 00100 00100 00100 00100 00100',
'U':'10001 10001 10001 10001 10001 10001 01110','V':'10001 10001 10001 10001 10001 01010 00100',
'W':'10001 10001 10001 10101 10101 10101 01010','X':'10001 10001 01010 00100 01010 10001 10001',
'Y':'10001 10001 01010 00100 00100 00100 00100','Z':'11111 00001 00010 00100 01000 10000 11111',
'0':'01110 10001 10011 10101 11001 10001 01110','1':'00100 01100 00100 00100 00100 00100 01110',
'2':'01110 10001 00001 00010 00100 01000 11111','3':'11110 00001 00001 01110 00001 00001 11110',
'4':'00010 00110 01010 10010 11111 00010 00010','5':'11111 10000 10000 11110 00001 00001 11110',
'6':'01110 10000 10000 11110 10001 10001 01110','7':'11111 00001 00010 00100 01000 01000 01000',
'8':'01110 10001 10001 01110 10001 10001 01110','9':'01110 10001 10001 01111 00001 00001 01110',
'.':'00000 00000 00000 00000 00000 00100 00100','-':'00000 00000 00000 11111 00000 00000 00000',
'+':'00000 00100 00100 11111 00100 00100 00000',':':'00000 00100 00100 00000 00100 00100 00000',
'/':'00001 00010 00010 00100 01000 01000 10000','%':'11001 11010 00100 01000 10110 00110 00000',
'(':'00010 00100 01000 01000 01000 00100 00010',')':'01000 00100 00010 00010 00010 00100 01000',
'=':'00000 11111 00000 11111 00000 00000 00000',',':'00000 00000 00000 00000 00100 00100 01000'}

class Canvas:
    def __init__(self):self.a=np.full((620,1100,3),255,np.uint8)
    def text(self,x,y,t,size=2,color=(35,45,55)):
        for char in str(t).upper():
            pat=FONT.get(char)
            if pat:
                for r,row in enumerate(pat.split()):
                    for c,v in enumerate(row):
                        if v=='1':self.a[y+r*size:y+(r+1)*size,x+c*size:x+(c+1)*size]=color
            x+=6*size
    def line(self,x0,y0,x1,y1,color=(40,55,70),width=1):
        n=max(abs(int(x1-x0)),abs(int(y1-y0)),1)+1
        for x,y in zip(np.linspace(x0,x1,n).astype(int),np.linspace(y0,y1,n).astype(int)):
            self.a[max(0,y-width):min(620,y+width+1),max(0,x-width):min(1100,x+width+1)]=color
    def save(self,p):
        h,w,_=self.a.shape
        def chunk(name,data):return struct.pack('!I',len(data))+name+data+struct.pack('!I',zlib.crc32(name+data)&0xffffffff)
        raw=b''.join(b'\x00'+row.tobytes() for row in self.a)
        Path(p).write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw,6))+chunk(b'IEND',b''))

def axes(title,xlo,xhi,ylo,yhi,xlabel,ylabel):
    c=Canvas();c.text(60,24,title);c.text(60,54,ylabel)
    if xhi<=xlo:xhi=xlo+1
    if yhi<=ylo:yhi=ylo+1
    X=lambda x:100+(x-xlo)/(xhi-xlo)*930
    Y=lambda y:515-(y-ylo)/(yhi-ylo)*405
    for y in np.linspace(ylo,yhi,6):
        py=int(Y(y));c.line(100,py,1030,py,(225,230,235),0);c.text(5,py-6,f'{y:.3g}')
    for x in np.linspace(xlo,xhi,5):c.text(max(100,int(X(x))-30),533,f'{x:.3g}')
    c.line(100,110,100,515);c.line(100,515,1030,515);c.text(170,568,xlabel)
    return c,X,Y

def histogram(path,counts,edges,title):
    c,X,Y=axes(title,edges[0],edges[-1],0,max(counts)*1.1 if len(counts) else 1,'RAW RESIDUAL SCORE','EXPOSURE COUNT')
    for n,lo,hi in zip(counts,edges[:-1],edges[1:]):
        x0=max(100,int(X(lo))+1);x1=min(1030,int(X(hi)));top=max(110,int(Y(n)))
        c.a[top:515,x0:x1]=(50,120,160)
    c.save(path)

def binned(path,rows,slope,title):
    rows=[r for r in rows if r.get('supported')]
    if not rows:return
    xx=[r['mean_residual_score'] for r in rows];lo=min(r['ci_low'] for r in rows);hi=max(r['ci_high'] for r in rows)
    span=max(hi-lo,.01);c,X,Y=axes(title,min(xx),max(xx),lo-.05*span,hi+.05*span,'RESIDUALIZED SCORE','RESIDUAL RECEIPT - PP')
    for r in rows:
        x=int(X(r['mean_residual_score']));yl=int(Y(r['ci_low']));yh=int(Y(r['ci_high']));ym=int(Y(r['estimate']))
        c.line(x,yl,x,yh,(50,120,160));c.line(x-4,yl,x+4,yl,(50,120,160));c.line(x-4,yh,x+4,yh,(50,120,160))
        c.a[ym-4:ym+5,x-4:x+5]=(50,120,160)
    # Clip the fitted line to the plot's vertical range.
    xs=np.linspace(min(xx),max(xx),500);ys=xs*slope;valid=(ys>=lo-.05*span)&(ys<=hi+.05*span)
    if valid.any():c.line(X(xs[valid][0]),Y(ys[valid][0]),X(xs[valid][-1]),Y(ys[valid][-1]),(190,90,45),1)
    c.text(600,77,'LINE: LINEAR FIRST STAGE',1);c.save(path)

