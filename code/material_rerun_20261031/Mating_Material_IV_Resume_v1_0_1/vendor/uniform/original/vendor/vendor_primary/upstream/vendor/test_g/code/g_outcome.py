"""G1 multinomial / sequential models, symmetry, held-out calibration, and exchange rates."""
from __future__ import annotations
import pickle
from scipy.optimize import minimize,brentq
from scipy.special import logsumexp
from sklearn.ensemble import HistGradientBoostingClassifier
from threadpoolctl import threadpool_limits
from g_common import *
from g_design import *

class OutcomeModel:
    def __init__(self,kind='multinomial'):self.kind=kind;self.beta=None;self.names=None;self.a=None;self.b=None
    def raw_predict(self,d):
        if self.kind=='multinomial':
            X,names,_=raw_features(d,intercept=True);require(names==self.names,'G1 feature-map mismatch')
            logits=np.column_stack([X@self.beta,np.zeros(len(d))]);return np.exp(logits-logsumexp(logits,axis=1)[:,None])
        X=self.boost_features(d);a=self.a.predict_proba(X)[:,1];b=self.b.predict_proba(X)[:,1]
        return np.column_stack([a*b,a*(1-b),1-a])
    def predict(self,d):
        # Chunk externally for full panels. Reversing twice must give the original features.
        p=self.raw_predict(d);q=self.raw_predict(opposite(d))[:,[2,1,0]];z=.5*(p+q)
        require(np.isfinite(z).all() and (z>=0).all() and np.max(np.abs(z.sum(axis=1)-1))<1e-10,'Incoherent G1 probabilities')
        return z
    @staticmethod
    def boost_features(d):
        vf=np.where(d.mate!=0,np.sign(d.mate)*1500,np.clip(d.vf,-1500,1500))
        return np.column_stack([vf,np.clip(d.dr,-600,600),d.mean_r,np.log1p(d.clock_f),np.log1p(d.clock_g),d.clock_f/d.base,
            d.base,d.inc,d.speed,d.ply,d.stm,np.sign(d.mate),np.abs(d.mate)])

class YearOutcome:
    def __init__(self,models,kind):self.models=models;self.kind=kind;self.beta=None
    def predict(self,d):
        if 'year2_share' in d:
            w=d.year2_share.to_numpy(float)[:,None];return (1-w)*self.models[1].predict(d)+w*self.models[2].predict(d)
        result=np.zeros((len(d),3));year=np.where(d.month_code.to_numpy()<12,1,2)
        for y in [1,2]:
            ix=np.flatnonzero(year==y)
            if len(ix):result[ix]=self.models[y].predict(d.iloc[ix])
        return result

def fit_outcome(d,work,kind='multinomial',multiplicity=None,train_mask=None,warm=None,maxiter=1000):
    work=Path(work);work.mkdir(parents=True,exist_ok=True)
    if isinstance(warm,YearOutcome) and train_mask is None:
        models={}
        for year in [1,2]:
            mask=((d.month_code<12) if year==1 else (d.month_code>=12)).to_numpy()&~d.test.to_numpy()
            models[year]=fit_outcome(d,work/f'year{year}',kind,multiplicity=multiplicity,train_mask=mask,warm=warm.models[year],maxiter=maxiter)
        return YearOutcome(models,kind)
    train=(~d.test.to_numpy(bool)) if train_mask is None else np.asarray(train_mask,bool)
    weights=d.weight.to_numpy(float).copy()
    if multiplicity is not None:weights*=multiplicity
    weights*=train;require(weights.sum()>0,'Empty G1 training data')
    model=OutcomeModel(kind)
    if kind=='sequential':
        t=d.loc[weights>0].copy();w=np.tile(weights[weights>0],2);t=pd.concat([t,opposite(t)],ignore_index=True)
        X=model.boost_features(t);y=t.outcome.to_numpy();mon=[1,-1]+[0]*(X.shape[1]-2)
        kwargs=dict(max_iter=250,max_leaf_nodes=31,learning_rate=.06,min_samples_leaf=100,l2_regularization=1.,monotonic_cst=mon,
            categorical_features=[8],early_stopping=False,random_state=SEED)
        with threadpool_limits(limits=1):
            model.a=HistGradientBoostingClassifier(**kwargs).fit(X,(y!=2).astype(int),sample_weight=w)
            model.b=HistGradientBoostingClassifier(**kwargs).fit(X[y!=2],(y[y!=2]==0).astype(int),sample_weight=w[y!=2])
        return model
    X0,names,_=raw_features(d.iloc[:1],intercept=True);p=X0.shape[1];n=len(d);model.names=names
    path=work/'g1_design.f64';shape=(2*n,p)
    # Guard against same-size changed inputs, especially a new source fallback.
    if d.attrs.get('_g_design_owner')!=id(d):
        columns=['game_id','vf','mate','dr','mean_r','clock_f','clock_g','base','inc','stm','ply','speed','weight']
        h=pd.util.hash_pandas_object(d[columns],index=False).to_numpy().tobytes()
        d.attrs['_g_design_hash']=hashlib.sha256(h).hexdigest();d.attrs['_g_design_owner']=id(d)
    signature=digest([d.attrs['_g_design_hash'],np.packbits(train).tobytes().hex(),names])
    source_receipt=work/'DESIGN_SIGNATURE.json'
    if source_receipt.exists() and load(source_receipt)['signature']!=signature:
        for obsolete in [path,work/'WHITENING.npy',work/'g1_whitened.f64']:obsolete.unlink(missing_ok=True)
    save(source_receipt,dict(signature=signature))
    # This is a deterministic, private design cache; no opportunity-level export.
    if not path.exists() or path.stat().st_size!=2*n*p*8:
        X=np.memmap(path,dtype='float64',mode='w+',shape=shape)
        for start in range(0,n,8192):
            end=min(n,start+8192);piece=d.iloc[start:end]
            X[start:end]=raw_features(piece,intercept=True)[0];X[n+start:n+end]=raw_features(opposite(piece),intercept=True)[0]
        X.flush();del X
    X=np.memmap(path,dtype='float64',mode='r',shape=shape);y=np.r_[d.outcome.to_numpy(int),2-d.outcome.to_numpy(int)];w=np.tile(weights,2);total=w.sum()
    transform_path=work/'WHITENING.npy';white_path=work/'g1_whitened.f64'
    # Fixed, unpenalized reparameterization, computed using training covariates only.
    # It removes exact aliases and avoids thousands of ill-conditioned L-BFGS iterations.
    if not transform_path.exists() or not white_path.exists():
        base_weights=np.tile(d.weight.to_numpy(float)*train,2);gram=np.zeros((p,p))
        for start in range(0,2*n,8192):
            end=min(2*n,start+8192);xx=X[start:end];gram+=xx.T@(xx*base_weights[start:end,None])
        gram/=base_weights.sum();scale=np.sqrt(np.maximum(np.diag(gram),0));active=scale>max(1e-14,scale.max()*1e-12);scale=np.where(active,scale,1.);cor=gram/scale[:,None]/scale[None,:]
        values,Q=np.linalg.eigh((cor+cor.T)/2);keep=values>max(1e-10,values.max()*1e-10)
        transform=Q[:,keep]/np.sqrt(values[keep])[None,:]/scale[:,None];transform[~active,:]=0.
        white=np.memmap(white_path,dtype='float64',mode='w+',shape=(2*n,keep.sum()))
        for start in range(0,2*n,8192):white[start:start+8192]=X[start:start+8192]@transform
        white.flush();del white;np.save(transform_path,transform)
    transform=np.load(transform_path);r=transform.shape[1];X=np.memmap(white_path,dtype='float64',mode='r',shape=(2*n,r))
    def objective(theta):
        B=theta.reshape(r,2);loss=0.;gradient=np.zeros((r,2))
        for start in range(0,2*n,16384):
            end=min(2*n,start+16384);wt=w[start:end];use=wt>0
            if not use.any():continue
            xx=X[start:end][use];yy=y[start:end][use];wt=wt[use]
            logits=np.column_stack([xx@B,np.zeros(len(xx))]);lse=logsumexp(logits,axis=1)
            loss+=np.sum(wt*(lse-logits[np.arange(len(xx)),yy]));pred=np.exp(logits-lse[:,None])[:,:2]
            pred[:,0]-=yy==0;pred[:,1]-=yy==1;gradient+=xx.T@(pred*wt[:,None])
        return loss/total,(gradient/total).ravel()
    initial=np.zeros((r,2)) if warm is None or warm.kind!='multinomial' or warm.beta is None else np.linalg.lstsq(transform,warm.beta,rcond=1e-10)[0]
    with threadpool_limits(limits=1),heartbeat('G1 multinomial fit'):
        result=minimize(objective,initial.ravel(),jac=True,method='L-BFGS-B',options=dict(maxiter=maxiter,ftol=1e-11,gtol=2e-7,maxcor=30,maxls=40))
    save(work/'OPTIMIZER_DIAGNOSTIC.json',dict(success=bool(result.success),iterations=int(result.nit),gradient_max=float(np.max(np.abs(result.jac))),message=str(result.message),objective=float(result.fun),rank=r))
    require(result.success or np.max(np.abs(result.jac))<2e-6,'G1 multinomial did not converge: '+str(result.message)+'; gradient='+str(float(np.max(np.abs(result.jac)))),'G1_NONCONVERGENCE')
    model.beta=transform@result.x.reshape(r,2);model.fit_info=dict(success=bool(result.success),rank=r,iterations=int(result.nit),gradient_max=float(np.max(np.abs(result.jac))),objective=float(result.fun))
    return model

def predict_chunks(model,d):
    return np.concatenate([model.predict(d.iloc[i:i+8192]) for i in range(0,len(d),8192)],axis=0) if len(d) else np.empty((0,3))

def calibration(model,d,mask,merge_ultra,label):
    t=d.loc[mask].copy();require(len(t)>0,'Empty calibration set','G1_CALIBRATION_NO_SUPPORT')
    t=pd.concat([t,opposite(t)],ignore_index=True);p=predict_chunks(model,t);cell=context(t,merge_ultra);rows=[];ece={};pass_all=True
    for cls,field in [(0,'win'),(2,'loss')]:
        weighted_error=0.;total_weight=0.
        for cc in np.unique(cell):
            for stm in [0,1]:
                ix=np.flatnonzero((cell==cc)&(t.stm.to_numpy()==stm));ix=ix[np.argsort(p[ix,cls],kind='stable')]
                for dec,indices in enumerate(np.array_split(ix,10),1):
                    if not len(indices):continue
                    w=t.weight.to_numpy()[indices];pred=float(np.average(p[indices,cls],weights=w));actual=float(np.average(t.outcome.to_numpy()[indices]==cls,weights=w));error=abs(pred-actual)
                    # Each side-to-move cell contains one orientation per game: no double-counted CI.
                    effective=w.sum()**2/np.sum(w*w);den=1+1.96**2/effective;center=(actual+1.96**2/(2*effective))/den
                    half=1.96*np.sqrt(actual*(1-actual)/effective+1.96**2/(4*effective**2))/den
                    rows.append(dict(model=label,outcome=field,cell=int(cc),f_to_move=stm,decile=dec,N=len(indices),predicted=pred,observed=actual,
                        observed_ci_low=max(0,center-half),observed_ci_high=min(1,center+half),absolute_error=error,ci_method='Wilson with sampling-weight effective N'))
                    weighted_error+=w.sum()*error;total_weight+=w.sum()
                    if len(indices)>=1000 and error>.03:pass_all=False
        ece[field]=weighted_error/total_weight
        if ece[field]>.01:pass_all=False
        rows.append(dict(model=label,outcome=field,cell='overall',N=len(t),ece=ece[field],passed=pass_all))
    return rows,pass_all
def math_sqrt(x):return float(np.sqrt(x))

def bootstrap_games(d,seed):
    rng=np.random.default_rng(seed);counts=np.zeros(len(d),dtype=np.int32)
    for _,ix in d.groupby(['speed','ply_bin'],sort=True).indices.items():
        counts[ix]=rng.multinomial(len(ix),np.full(len(ix),1/len(ix)))
    return counts

def solve_curve(fn,limit=600,tolerance=1e-8):
    """Signed root with monotonicity, endpoint and multiple-crossing checks."""
    grid=np.linspace(-limit,limit,481);v=np.asarray(fn(grid),float)
    if not np.isfinite(v).all():return np.nan,'nonfinite'
    diff=np.diff(v);increasing=np.all(diff>=-tolerance);decreasing=np.all(diff<=tolerance)
    if not (increasing or decreasing):return np.nan,'nonmonotone'
    if np.ptp(v)<=tolerance:return np.nan,'flat_or_unidentified'
    if v.min()>0 or v.max()<0:return np.nan,'no_root_in_range'
    zeros=np.flatnonzero(np.abs(v)<=tolerance)
    if len(zeros)>1 and grid[zeros[-1]]-grid[zeros[0]]>2.5:return np.nan,'flat_root_interval'
    # Monotone generalized inverse also supports discontinuous boosted probabilities.
    direction=1 if increasing else -1;lo=-limit;hi=limit
    for _ in range(36):
        mid=(lo+hi)/2;value=float(np.asarray(fn(np.array([mid])))[0])*direction
        if value>=0:hi=mid
        else:lo=mid
    return (lo+hi)/2,'resolved'

def exchange(model,templates):
    rows=[]
    for r in templates.to_dict('records'):
        for stm in [0,1,'average']:
            for gap in [100,200]:
                def probs(x,g):
                    d=pd.DataFrame([r]*len(x));d['vf']=x;d['mate']=0.;d['dr']=g
                    def mixed(z):
                        p=model.predict(z);share=float(r.get('ultrabullet_share',0))
                        if share>0:
                            ultra=z.copy();ultra['speed']=0;p=(1-share)*p+share*model.predict(ultra)
                        return p
                    if stm=='average':
                        d['stm']=0;p=mixed(d);d['stm']=1;return .5*(p+mixed(d))
                    d['stm']=stm;return mixed(d)
                target=probs(np.array([0.]),0)[0,0]
                xw,sw=solve_curve(lambda x:probs(x,gap)[:,0]-target)
                xe,se=solve_curve(lambda x:probs(x,gap)[:,0]-probs(x,gap)[:,2])
                rows.append(dict(cell=int(r['cell']),rating_edge=gap,f_to_move=stm,X_w=xw,X_w_status=sw,X_eq=xe,X_eq_status=se,N=int(r.get('N',0))))
    return rows

def make_templates(a,run,paths,d):
    c=db(run/'g1/cell_spill',max(1,a.memory_gb-2))
    try:
        c.execute('CREATE VIEW p AS SELECT *, CASE WHEN mean_r<1200 THEN 0 WHEN mean_r<1600 THEN 1 WHEN mean_r<2000 THEN 2 ELSE 3 END rb, CASE WHEN ply<=20 THEN 0 WHEN ply<=40 THEN 1 WHEN ply<=80 THEN 2 WHEN ply<=120 THEN 3 ELSE 4 END pb FROM '+parq(paths)+' WHERE ply>10')
        grants=c.execute('SELECT speed*20+rb*5+pb cell,sum(y) grants FROM p GROUP BY cell').fetchdf().set_index('cell').grants.to_dict()
        counts=pd.Series(context(d,False)).value_counts().to_dict()
        merge=any(counts.get(k,0)<50000 or grants.get(k,0)<2000 for k in range(20))
        expression='(CASE WHEN speed=0 THEN 1 ELSE speed END)' if merge else 'speed'
        q=f'''SELECT {expression}*20+rb*5+pb cell,min({expression}) speed,count(*) N,sum(y) grants,
          median(mean_r) mean_r,median(ply) ply,median((clock_f+clock_g)/2) equal_clock,
          median(base) base,median(inc) inc,median(premium) premium,median(rd_c) rd_c,median(rd_d) rd_d,
          avg((speed=0)::INTEGER) ultrabullet_share,avg((month_code>=12)::INTEGER) year2_share
          FROM p GROUP BY cell'''
        t=c.execute(q).fetchdf();t['clock_f']=t.equal_clock;t['clock_g']=t.equal_clock;t['vf']=0.;t['mate']=0.;t['dr']=0.;t['stm']=0;t['month_code']=0
        if not merge:t['ultrabullet_share']=0.
        require(not merge or not (t.speed==0).any(),'Context merge failed')
        save(run/'report/CONTEXT_CELL_POLICY.json',dict(merge_ultrabullet_into_bullet=merge,model_speed_levels=SPEEDS,
             reason='Any ultra cell below 50,000 G1 games or 2,000 grants',equal_clock='Median across opportunities of (chooser_clock + opponent_clock)/2',
             merged_cell_evaluation='Observed-opportunity-weighted mixture of the separate ultrabullet and bullet predictions; all model speed levels remain separate.'))
        atomic_parquet(t,run/'g1/templates.parquet');return t,merge
    finally:c.close()

def train_primary(a,run,positions,paths,key):
    work=run/'g1/fit';work.mkdir(parents=True,exist_ok=True);k=digest([key,sha(positions),'outcome-fit'])
    if done(work,k):
        with (work/'model.pkl').open('rb') as f:model=pickle.load(f)
        return model,pd.read_parquet(run/'g1/templates.parquet'),load(work/'META.json')['merge_ultra']
    d=pd.read_parquet(positions);templates,merge=make_templates(a,run,paths,d);meta=dict(N=len(d),sample='Completed games; one position, both orientations; game holdout',source_months=[MONTHS[x] for x in sorted(d.month_code.unique())],ending_status_coverage=d.ending_basis.value_counts().to_dict(),share_games_both_flag_statuses_known=float(d.flags_known.mean()))
    calrows=[];models={};passed={}
    for kind in ['multinomial','sequential']:
        model=fit_outcome(d,work/kind,kind);models[kind]=model
        rows,passed[kind]=calibration(model,d,d.test.to_numpy(),merge,kind);calrows+=rows
        with (work/(kind+'.pkl')).open('wb') as f:pickle.dump(model,f,protocol=5)
    table(run/'report','tabG1_calibration',calrows,meta)
    selected='multinomial' if passed['multinomial'] else 'sequential' if passed['sequential'] else None
    require(selected is not None,'Both G1 outcome models failed held-out calibration.','G1_CALIBRATION_FAILED')
    model=models[selected];stability=[];allstable=True;year_models={}
    for year in [1,2]:
        source=(d.month_code<12).to_numpy() if year==1 else (d.month_code>=12).to_numpy()
        trained=fit_outcome(d,work/f'year{year}',selected,train_mask=source&~d.test.to_numpy(),warm=model)
        year_models[year]=trained
        rows,ok=calibration(trained,d,~source,merge,f'train_P{year}_test_P{3-year}');stability+=rows;allstable &= ok
        er=exchange(trained,templates)
        for r in er:r['training_year']=year
        table(run/'report',f'tabG1_exchange_rate_year{year}',er,meta)
    table(run/'report','tabG1_stability',stability,meta)
    if not allstable:
        require(len(d.month_code.unique())==24,'Cross-year calibration failed. Missing-month streaming downloads require approval before the prespecified year-specific refit.','G1_STABILITY_REQUIRES_SOURCE_FALLBACK')
        within_rows=[]
        for year in [1,2]:
            mask=((d.month_code<12) if year==1 else (d.month_code>=12)).to_numpy()&d.test.to_numpy()
            rows,ok=calibration(year_models[year],d,mask,merge,f'year_specific_P{year}');within_rows+=rows
            require(ok,'Full-source year-specific G1 fails its own held-out calibration','G1_YEAR_SPECIFIC_CALIBRATION_FAILED')
        table(run/'report','tabG1_year_specific_calibration',within_rows,meta);model=YearOutcome(year_models,selected)
    with (work/'model.pkl').open('wb') as f:pickle.dump(model,f,protocol=5)
    save(work/'META.json',dict(selected=selected,by_year=isinstance(model,YearOutcome),merge_ultra=merge,calibration=passed,meta=meta))
    table(run/'report','tabG1_exchange_rate',exchange(model,templates),meta)
    checkpoint(work,k,[positions],[work/'model.pkl',work/'META.json',work/'multinomial.pkl',work/'sequential.pkl',run/'g1/templates.parquet'])
    return model,templates,merge
