"""Whole-account FE fits, exact unbounded LPM test quadratic, and chooser CR1."""
from __future__ import annotations
from scipy.stats import chi2
from g_common import *
from g_design import *
from g_inputs import load_bucket
from g_outcome import predict_chunks

MODELS=['M0','MR','MU','MRU','MRprime','MRUprime']
BLOCKS=2000

def solve(H):
    xx=H[:-1,:-1];xy=H[:-1,-1];scale=np.sqrt(np.maximum(np.diag(xx),0))
    active=scale>max(1e-14,float(scale.max(initial=0))*1e-12);scale=np.where(active,scale,1.)
    z=xx/scale[:,None]/scale[None,:];values,Q=np.linalg.eigh((z+z.T)/2)
    use=values>max(1e-10,float(values.max(initial=0))*1e-10)
    inverse=(Q[:,use]/values[use])@Q[:,use].T/scale[:,None]/scale[None,:]
    inverse[~active,:]=0.;inverse[:,~active]=0.
    b=inverse@xy;return dict(beta=b,inverse=inverse,rank=int(use.sum()),null=Q[:,~use],scale=scale,
      sse=float(H[-1,-1]-2*b@xy+b@xx@b),sst=float(H[-1,-1]))
def estimable(fit,q,tol=1e-7):
    q=np.asarray(q)/fit['scale'];return np.linalg.norm(fit['null'].T@q)<=tol*max(1,np.linalg.norm(q))
def quadratic(H,b):
    q=np.r_[-b,1.];return float(q@H@q)
def account_layout(d):
    ids=d.chooser.to_numpy();start=np.r_[0,np.flatnonzero(ids[1:]!=ids[:-1])+1];count=np.diff(np.r_[start,len(d)]);index=np.repeat(np.arange(len(start)),count)
    groups=d.group.to_numpy()[start];block=np.array([(int(g)+1)*400+hash64(int(u),'account-blocks')%400 for u,g in zip(ids[start],groups)],int)
    # group -1 -> 0..399; 0 -> 400..799; ..., 3 -> 1600..1999.
    return start,count,index,block

def within_forms(d,X):
    start,count,index,blocks=account_layout(d);y=d.y.to_numpy(float);train=d.train.to_numpy(bool)
    Z=np.column_stack([X,y]);ntrain=np.add.reduceat(train.astype(float),start)
    require((ntrain>0).all(),'A test account lacks a training history','HOLDOUT_FE_FAILURE')
    mean_train=np.add.reduceat(Z*train[:,None],start,axis=0)/ntrain[:,None]
    mean_all=np.add.reduceat(Z,start,axis=0)/count[:,None]
    return Z-mean_train[index],Z-mean_all[index],train,blocks[index],(start,count,index,blocks)

def add_block_cross(destination,Z,ids):
    order=np.argsort(ids,kind='stable');z=Z[order];b=ids[order]
    starts=np.r_[0,np.flatnonzero(b[1:]!=b[:-1])+1] if len(b) else []
    for i,lo in enumerate(starts):
        hi=starts[i+1] if i+1<len(starts) else len(b);destination[b[lo]]+=z[lo:hi].T@z[lo:hi]

class MomentStore:
    def __init__(self,path,p,create=False):
        self.path=Path(path);self.path.mkdir(parents=True,exist_ok=True);self.p=p;mode='w+' if create else 'r'
        self.forms={name:np.lib.format.open_memmap(self.path/(name+'.npy'),mode=mode,dtype='float64',shape=(BLOCKS,p+1,p+1)) for name in ['train','full','test']}
        self.counts=np.lib.format.open_memmap(self.path/'counts.npy',mode=mode,dtype='float64',shape=(BLOCKS,4))
        # Four contrasts: gap in C, gap in L, clock doubling in C, evaluation +100 in C/nonmate.
        self.contrasts=np.lib.format.open_memmap(self.path/'contrasts.npy',mode=mode,dtype='float64',shape=(BLOCKS,4,p+1))
        self.stages=np.lib.format.open_memmap(self.path/'stages.npy',mode=mode,dtype='float64',shape=(BLOCKS,5,p+3))
        self.responses=np.lib.format.open_memmap(self.path/'responses.npy',mode=mode,dtype='float64',shape=(BLOCKS,4,p+2))
        if create:
            for x in self.forms.values():x[:]=0
            self.counts[:]=0;self.contrasts[:]=0;self.stages[:]=0;self.responses[:]=0
    def flush(self):
        for x in list(self.forms.values())+[self.counts,self.contrasts,self.stages,self.responses]:x.flush()
    def fit(self,weights=None):
        weights=np.ones(BLOCKS) if weights is None else np.asarray(weights,float)
        H={n:np.einsum('b,bij->ij',weights,m,optimize=True) for n,m in self.forms.items()}
        counts=weights@self.counts;train=solve(H['train']);full=solve(H['full'])
        require(counts[1]>0,'No test opportunities','NO_OOS_SUPPORT')
        return dict(train=train,full=full,brier=quadratic(H['test'],train['beta'])/counts[1],
            within_r2=1-full['sse']/full['sst'] if full['sst']>0 else np.nan,counts=counts,
            contrast=np.einsum('b,bkp->kp',weights,self.contrasts,optimize=True),
            stages=np.einsum('b,bkp->kp',weights,self.stages,optimize=True),
            responses=np.einsum('b,bkp->kp',weights,self.responses,optimize=True))

def init_knots(paths,g1,run):
    target=run/'g2/KNOTS.json'
    if target.exists():return load(target)
    # Exact training-row quantiles, disk-backed: no test outcomes or test covariates set the knots.
    parts=[];folder=run/'g2/quantiles';folder.mkdir(exist_ok=True,parents=True)
    for i,p in enumerate(paths):
        d=load_bucket(p);d=d.loc[d.train];prob=predict_chunks(g1,d)
        q=folder/f'p{i:03d}.parquet';atomic_parquet(pd.DataFrame({'omega':prob[:,0],'score':prob[:,0]+.5*prob[:,1]}),q);parts.append(q)
    c=db(folder/'spill',4)
    try:
        q=c.execute("SELECT quantile_cont(ln(greatest(1e-6,least(1-1e-6,omega))/(1-greatest(1e-6,least(1-1e-6,omega)))),[.1,.25,.5,.75,.9]), quantile_cont(ln(greatest(1e-6,least(1-1e-6,score))/(1-greatest(1e-6,least(1-1e-6,score)))),[.1,.25,.5,.75,.9]) FROM "+parq(parts)).fetchone()
    finally:c.close()
    value=dict(knots=[float(logit(PROB_CLIP))]+q[0]+[float(logit(1-PROB_CLIP))],score_knots=[float(logit(PROB_CLIP))]+q[1]+[float(logit(1-PROB_CLIP))],probability_clip=PROB_CLIP,source='Temporal training opportunities, exact quantiles of point-estimate logits')
    require(np.all(np.diff(value['knots'])>0) and np.all(np.diff(value['score_knots'])>0),'Insufficient variation for frozen index knots','INSUFFICIENT_INDEX_SUPPORT')
    save(target,value);shutil.rmtree(folder);return value

def build_moments(paths,g1,knots,folder,models=MODELS,subset='all',random=False,probability_store=None):
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True);stores={};metadata={};nrows=0
    for ip,path in enumerate(paths):
        d=load_bucket(path,random=random,subset=subset)
        if not len(d):continue
        p=predict_chunks(g1,d) if set(models)-{'M0','MU'} else None;omega=p[:,0] if p is not None else None;score=p[:,0]+.5*p[:,1] if p is not None else None
        if probability_store is not None and p is not None:probability_store(ip,d,p)
        changed={}
        for kind in ['gap100','double_clock','eval100']:
            z=counterfactual(d,kind);q=predict_chunks(g1,z) if p is not None else None
            changed[kind]=(z,q)
        for model in models:
            X,names,blocks=g2_design(d,model,omega,score,knots['knots'],knots['score_knots'],group_specific=subset=='year2_groups')
            if model not in stores:
                stores[model]=MomentStore(folder/model,X.shape[1],True);metadata[model]=dict(names=names,blocks=blocks,p=X.shape[1],subset=subset,random_holdout=random)
            store=stores[model];zt,zf,train,block,layout=within_forms(d,X)
            add_block_cross(store.forms['train'],zt[train],block[train]);add_block_cross(store.forms['test'],zt[~train],block[~train]);add_block_cross(store.forms['full'],zf,block)
            for j,mask in enumerate([train,~train,np.ones(len(d),bool)]):store.counts[:,j]+=np.bincount(block[mask],minlength=BLOCKS)
            store.counts[:,3]+=np.bincount(layout[3],minlength=BLOCKS)
            for band in range(5):
                mask=(~train)&(ply_band(d.ply.to_numpy())==band)
                for j in range(X.shape[1]):store.stages[:,band,j]+=np.bincount(block[mask],weights=zt[mask,j],minlength=BLOCKS)
                store.stages[:,band,-3]+=np.bincount(block[mask],weights=d.y.to_numpy()[mask]-zt[mask,-1],minlength=BLOCKS)
                store.stages[:,band,-2]+=np.bincount(block[mask],weights=d.y.to_numpy()[mask],minlength=BLOCKS)
                store.stages[:,band,-1]+=np.bincount(block[mask],minlength=BLOCKS)
            if subset=='year2_groups' and model in ('MR','MRU','MRprime','MRUprime'):
                index=score if 'prime' in model else omega;up=np.clip(index+1e-5,PROB_CLIP,1-PROB_CLIP);down=np.clip(index-1e-5,PROB_CLIP,1-PROB_CLIP)
                def xd(v):return g2_design(d,model,v if 'prime' not in model else omega,v if 'prime' in model else score,knots['knots'],knots['score_knots'],True)[0]
                derivative=(xd(up)-xd(down))/np.maximum(1e-12,up-down)[:,None]
                for g in range(4):
                    mask=d.group.to_numpy()==g
                    for j in range(X.shape[1]):store.responses[:,g,j]+=np.bincount(block[mask],weights=derivative[mask,j],minlength=BLOCKS)
                    store.responses[:,g,-2]+=np.bincount(block[mask],weights=d.y.to_numpy()[mask],minlength=BLOCKS)
                    store.responses[:,g,-1]+=np.bincount(block[mask],minlength=BLOCKS)
            for k,(kind,mask) in enumerate([('gap100',d.board.to_numpy()>=-100),('gap100',d.board.to_numpy()<=-300),('double_clock',d.board.to_numpy()>=-100),('eval100',(d.board.to_numpy()>=-100)&(d.mate.to_numpy()==0))]):
                z,q=changed[kind];Xnew=g2_design(z,model,None if q is None else q[:,0],None if q is None else q[:,0]+.5*q[:,1],knots['knots'],knots['score_knots'],group_specific=subset=='year2_groups')[0]
                diff=Xnew-X
                for j in range(X.shape[1]):store.contrasts[:,k,j]+=np.bincount(block[mask],weights=diff[mask,j],minlength=BLOCKS)
                store.contrasts[:,k,-1]+=np.bincount(block[mask],minlength=BLOCKS)
            del X,zt,zf
        nrows+=len(d)
        if ip%8==0:log(f'FE moment pass: {ip+1}/{len(paths)} account partitions, {nrows:,} rows')
    require(stores,'No model data','NO_G2_SAMPLE')
    for model,store in stores.items():store.flush();save(folder/model/'META.json',metadata[model])
    return stores

def read_stores(folder,models=MODELS):
    return {m:MomentStore(Path(folder)/m,load(Path(folder)/m/'META.json')['p']) for m in models}
def block_draw(seed):
    rng=np.random.default_rng(seed);w=np.zeros(BLOCKS,dtype=int)
    for g in range(5):w[g*400:(g+1)*400]=rng.multinomial(400,np.full(400,1/400))
    return w
def statistics(fits,metric='brier'):
    v={m:f[metric] for m,f in fits.items()};gain={m:(v['M0']-v[m] if metric=='brier' else v[m]-v['M0']) for m in v};out={m+':gain':g for m,g in gain.items()}
    for suffix,index,enc in [('', 'MR','MRU'),('prime','MRprime','MRUprime')]:
        raw=gain[enc]-gain[index];aw=gain[enc]-gain['MU'];den=gain[enc]
        out.update({suffix+'A_raw':raw,suffix+'A_omega':aw,suffix+'D10':raw-.10*den,suffix+'D25':raw-.25*den,
            suffix+'S_R':gain[index]/den if den!=0 else np.nan,suffix+'S':gain[index]/gain['MU'] if gain['MU']!=0 else np.nan})
    return out

def log_losses(paths,g1,knots,fits,subset='all',random=False,weights=None):
    weights=np.ones(BLOCKS) if weights is None else weights;tot={m:0. for m in fits};N=0.
    for path in paths:
        d=load_bucket(path,random=random,subset=subset)
        if not len(d):continue
        p=predict_chunks(g1,d)
        for m in fits:
            X=g2_design(d,m,p[:,0],p[:,0]+.5*p[:,1],knots['knots'],knots['score_knots'],group_specific=subset=='year2_groups')[0]
            zt,_,train,block,_=within_forms(d,X);ix=~train
            # y - demeaned_y restores training-mean y; X residual uses training mean X.
            b=fits[m]['train']['beta'];pred=np.clip(d.y.to_numpy()[ix]-zt[ix,-1]+zt[ix,:-1]@b,.0005,.9995)
            y=d.y.to_numpy()[ix];w=weights[block[ix]];tot[m]+=float(np.sum(w*(-y*np.log(pred)-(1-y)*np.log1p(-pred))))
            if m=='M0':N+=w.sum()
    return {m:v/N for m,v in tot.items()}

def chooser_wald(paths,g1,knots,fit,metadata):
    p=len(fit['beta']);meat=np.zeros((p,p));G=0
    for path in paths:
        d=load_bucket(path);prob=predict_chunks(g1,d);X=g2_design(d,'MRU',prob[:,0],prob[:,0]+.5*prob[:,1],knots['knots'],knots['score_knots'])[0]
        _,z,_,_,layout=within_forms(d,X);e=z[:,-1]-z[:,:-1]@fit['beta'];scores=np.add.reduceat(z[:,:-1]*e[:,None],layout[0],axis=0)
        meat+=scores.T@scores;G+=len(scores)
    cov=fit['inverse']@meat@fit['inverse']*G/max(1,G-1)
    names=metadata['names'];raw=sorted(set(j for js in metadata['blocks'].values() for j in js));q=np.eye(p)[raw]
    identified=[i for i in range(len(q)) if estimable(fit,q[i])];q=q[identified]
    V=q@cov@q.T;b=q@fit['beta'];rank=np.linalg.matrix_rank(V);stat=float(b@np.linalg.pinv(V,rcond=1e-10)@b)
    return dict(statistic=stat,df=rank,p_value=float(chi2.sf(stat,rank)) if rank else np.nan,chooser_clusters=G,correction=G/max(1,G-1),status='Descriptive Wald only; not a decision rule'),cov
