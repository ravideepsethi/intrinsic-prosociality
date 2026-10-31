"""Prediction and descriptive fixed-effect regressions, with explicit inference."""
import math
from core import *

def absorb(a,groups,tol=1e-9,max_iter=1000):
    a=np.asarray(a,float).copy();codes=[np.unique(g,return_inverse=True)[1] for g in groups];ns=[np.bincount(g).astype(float) for g in codes]
    scale=max(1.,float(np.max(abs(a))))
    for it in range(max_iter):
        largest=0.
        for g,n in zip(codes,ns):
            for k in range(a.shape[1]):
                mu=np.bincount(g,weights=a[:,k],minlength=len(n))/n;largest=max(largest,float(np.max(abs(mu))));a[:,k]-=mu[g]
        if largest<tol*scale:return a,it+1
    raise RuntimeError('Fixed effects did not converge')

def factor(*cols):
    a=np.empty(len(cols[0]),dtype=[('x'+str(k),'<i8') for k in range(len(cols))])
    for k,v in enumerate(cols):a['x'+str(k)]=v
    return np.unique(a,return_inverse=True)[1]
def meat(s,key):
    key=np.unique(key,return_inverse=True)[1]
    sums=np.column_stack([np.bincount(key,weights=s[:,k]) for k in range(s.shape[1])]);return sums.T@sums
def fit_fe(y,target,controls,groups,j,i,date,names):
    n=len(y);base=dict(n=n,grants=int(np.sum(y)),chooser_accounts=len(np.unique(j)),causal=False)
    if n<2000 or min(np.sum(y),n-np.sum(y))<20:return dict(**base,supported=False,reason='Insufficient rows or grants'),[]
    raw=np.column_stack([*controls,*target,y]);z,it=absorb(raw,groups);del raw
    kc=len(controls);kt=len(target);x=z[:,:kc];v=z[:,kc:]
    if kc:v=v-x@(np.linalg.pinv(x.T@x,rcond=1e-11)@(x.T@v))
    x=v[:,:kt];yy=v[:,-1];gram=x.T@x
    if np.linalg.matrix_rank(gram,tol=max(1.,np.linalg.norm(gram,2))*1e-10)<kt:
        return dict(**base,supported=False,reason='No identifying target variation',absorb_iterations=it),[]
    bread=np.linalg.inv(gram);b=bread@(x.T@yy);s=x*(yy-x@b)[:,None]
    # Chooser-only CR1 for comparison to manuscript; shared-account/date CR0 sensitivity.
    g=len(np.unique(j));chooser=bread@meat(s,j)@bread*(g/(g-1) if g>1 else np.nan)
    pair=pairs(j,i);both=np.r_[s,s];allids=np.r_[j,i]
    shared=meat(both,allids)-meat(s,pair)+meat(s,date)-meat(both,factor(allids,np.r_[date,date]))+meat(s,factor(pair.astype(np.int64),date))
    shared=bread@shared@bread
    rows=[]
    for covname,V in [('chooser_CR1',chooser),('shared_account_OR_date_CR0',shared)]:
        psd=bool(np.linalg.eigvalsh(V).min()>=-1e-10*max(1e-30,float(np.max(abs(V)))))
        for k,name in enumerate(names):
            row=dict(contrast=name,coefficient_pp=100*b[k],covariance=covname,covariance_psd=psd,n=n)
            if psd and V[k,k]>0:
                se=math.sqrt(V[k,k]);row.update(supported=True,se_pp=100*se,ci95_low_pp=100*(b[k]-1.959964*se),ci95_high_pp=100*(b[k]+1.959964*se),p=math.erfc(abs(b[k]/se)/math.sqrt(2)))
            else:row.update(supported=False,reason='Unsupported covariance; not repaired')
            rows.append(row)
    return dict(**base,supported=True,absorb_iterations=it,control_columns=kc),rows

def logistic_fit(x,y,penalty=1e-5):
    n,k=x.shape;b=np.zeros(k);p0=(float(y.sum())+.5)/(n+1);b[0]=math.log(p0/(1-p0));reg=np.eye(k)*penalty;reg[0,0]=0
    def loss(v):
        z=x@v;return float(np.mean(np.logaddexp(0,z)-y*z)+v@reg@v/2)
    old=loss(b)
    for it in range(80):
        p=1/(1+np.exp(-np.clip(x@b,-35,35)));g=x.T@(p-y)/n+reg@b
        if np.max(abs(g))<1e-8:return b,it+1
        H=(x.T*(p*(1-p)))@x/n+reg;step=np.linalg.solve(H+np.eye(k)*1e-12,g);rate=1.
        while rate>1e-7:
            candidate=b-rate*step;new=loss(candidate)
            if new<=old:break
            rate/=2
        if rate<=1e-7:raise RuntimeError('Prediction optimizer line search failed')
        b=candidate;old=new
        if np.max(abs(rate*step))<1e-7:return b,it+1
    raise RuntimeError('Prediction optimizer did not converge')

def prediction_raw(d):
    gap=d['opp_rating']-d['rating'];v=[np.ones(len(gap)),d['rating']/1000,d['opp_rating']/1000,abs(gap)/1000,
        np.log1p(d['jvolume']),np.log1p(d['ivolume']),d['jslot']/np.maximum(d['jvolume'],1),d['islot']/np.maximum(d['ivolume'],1),
        np.log1p(d['prior30']),np.log1p(d['prior90']),d['repeat'].astype(float),
        np.log1p(d['previous_hour_pool_games']),np.log1p(d['base']),np.log1p(d['inc'])]
    names=['intercept','giver_rating_1000','recipient_rating_1000','absolute_rating_gap_1000','log_giver_volume30','log_recipient_volume30',
        'giver_same_4h_share30','recipient_same_4h_share30','log_prior_pair30','log_prior_pair90','previous_meeting','log_platform_speed_games_previous_hour','log_base','log_increment']
    for s in range(1,5):v.append((d['speed']==s).astype(float));names.append('speed_'+SPEEDS[s])
    slot=(d['start']//14400000)%6
    for h in range(1,6):v.append((slot==h).astype(float));names.append('utc_slot_'+str(h))
    return np.column_stack(v),names
