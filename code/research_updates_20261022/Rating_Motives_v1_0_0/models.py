"""Frozen model registry and deterministic design columns; no outcome-tuned specification."""
from itertools import product
import numpy as np
from scipy import sparse
from fe_core import onehot

def registry(history_available, threshold_ok=True):
    variants={
      'T1':['primary','recipient_rd','inactivity','performance'],
      'T2':['primary','rd110','inactivity','chooser_speed','cubic','performance_peak','display_equal'],
      'T3':['primary','lookback15','lookback60','tau200','tau800','common15','common60','common200','common800','interaction'],
      'T4':['primary','band10','band40','quadratic','rd110','history365','recent_peak','rounded','matching','buffer1','distance_profile'],
      'T5':['primary','band05','band15','quadratic','rd110','donut','break65','break70','break80','break85','profile']}
    models=[];pending=[]
    for test,vs in variants.items():
        if (test!='T5' and not history_available) or (test=='T5' and not threshold_ok):
            pending.append(dict(test=test,status='UNSUPPORTED_INPUT',reason=('Authenticated prior completed-game history unavailable' if test!='T5' else 'Effective E disagrees with pre-state Glicko check')))
            if test in ['T1','T2']:
                vs=['diagnostic_no_prior_count']
            else:continue
        for variant in vs:
            for state in ['competitive','losing']:
                models.append(dict(test=test,variant=variant,state=state,key=f'{test}__{variant}__{state}',
                                   fe='chooser_speed' if variant=='chooser_speed' else 'chooser'))
            if variant=='primary':
                models.append(dict(test=test,variant=variant,state='difference',key=f'{test}__primary__difference',fe='chooser_state'))
    return models,pending

def poly(arrays,degree):
    vals=[];names=[]
    for d in range(1,degree+1):
        for powers in product(range(d+1),repeat=len(arrays)):
            if sum(powers)!=d:continue
            z=np.ones(len(arrays[0]))
            for a,p in zip(arrays,powers):z*=a**p
            vals.append(z);names.append('_'.join(map(str,powers)))
    return vals,names

def distance_code(d):return np.where(d<=0,0,np.where(d<=5,1,np.where(d<=10,2,np.where(d<=20,3,np.where(d<=40,4,5)))))

def keep_rows(f,m):
    t,v,s=m['test'],m['variant'],m['state'];n=len(f['y'])
    keep=np.ones(n,bool) if s=='difference' else f['state']==(1 if s=='competitive' else 0)
    keep &= np.isfinite(f['k'])&(f['k']>0)&np.isfinite(f['e'])&np.isfinite(f['age_days'])&(f['age_days']>=365)
    if t in ['T1','T2'] and v!='diagnostic_no_prior_count':keep &= np.isfinite(f['opp_prior_count'])&(f['opp_prior_count']>=0)
    if t=='T1':
        key='opp_rd' if v=='recipient_rd' else 'opp_stake';keep &= np.isfinite(f[key])&(f[key]>0)
    if t=='T2':
        keep &= f['rating']==f['opp_rating']
        if v!='display_equal':keep &= np.abs(f['rg'])<=1e-9
    hist=(t in ['T3','T4']) or v in ['performance','performance_peak']
    if hist:
        keep &= (f['prior_count']>=30)&np.isfinite(f['peak'])
        if t!='T3':keep &= np.isfinite(f['dperf'])
    if t=='T3':
        key={'lookback15':'dperf15','lookback60':'dperf60','tau200':'dperf200','tau800':'dperf800',
             'common15':'dperf15','common60':'dperf60','common200':'dperf200','common800':'dperf800'}.get(v,'dperf')
        keep &= np.isfinite(f[key])
        if v.startswith('common'):keep &= np.isfinite(f['dperf'])
    if t=='T4':
        peak=f['peak365'] if v=='recent_peak' else f['peak'];d=peak-f['rating']
        keep &= np.isfinite(peak)
        if v!='distance_profile':keep &= (d>0)&(d<=({'band10':10,'band40':40}.get(v,20)))
        if v=='history365':keep &= f['history_days']>=365
        if v=='buffer1':keep &= (np.abs(f['rc']-d)>1)&(np.abs(f['rg']-d)>1)
    if v=='rd110':keep &= (f['rd']>0)&(f['rd']<=110)&(f['opp_rd']>0)&(f['opp_rd']<=110)
    if v=='inactivity':keep &= np.isfinite(f['prior_count'])&((f['prior_count']==0)|np.isfinite(f['inactivity_days']))
    if t=='T5':
        if v=='profile':keep &= (f['e']>=.50)&(f['e']<=.95)
        else:
            brk=float(v[-2:])/100 if v.startswith('break') else .75
            band={'band05':.05,'band15':.15}.get(v,.10);d=np.abs(f['e']-brk)
            keep &= (d<=band+1e-12)&(d>(.005 if v=='donut' else 1e-12))
    return keep

def subgroup(f,fe):
    ids=f['chooser']
    if fe=='chooser':keys=ids[:,None]
    else:keys=np.column_stack([ids,f['state'] if fe=='chooser_state' else f['speed']])
    _,inv,count=np.unique(keys,axis=0,return_inverse=True,return_counts=True)
    A=sparse.csr_matrix((np.ones(len(ids)),(inv,np.arange(len(ids)))),shape=(len(count),len(ids)))
    return inv,count,A

def sample(f,m):
    keep=keep_rows(f,m);d={k:v[keep] for k,v in f.items()}
    selected=len(d['y'])
    if not selected:return None,selected
    g,n,A=subgroup(d,m['fe']);use=n[g]>=2
    if not use.any():return None,selected
    return {k:v[use] for k,v in d.items()},selected

def build(f,m):
    t,v=m['test'],m['variant'];n=len(f['y']);cols=[];names=[]
    def scalar(name,x):cols.append(sparse.csr_matrix(np.asarray(x,float).reshape(-1,1)));names.append(name)
    def cats(name,codes,levels,ref=0):
        use=[i for i in range(levels) if i!=ref];cols.append(onehot(np.asarray(codes,int),levels)[:,use]);names.extend(f'{name}_{i}' for i in use)
    cats('month',f['month_idx'],24);cats('speed',f['speed'],6)
    cats('board',np.where(f['board']>=300,2,np.where(f['board']>100,1,0)),3)
    cats('stage',np.digitize(f['ply'],[5,11,21,41,81]),6)
    cats('rating_tier',np.digitize(f['rating'],[1600,2000,2400]),4)
    scalar('rating_400',f['rating']/400);scalar('rating_400_sq',(f['rating']/400)**2)
    if t!='T5':
        gap=f['opp_rating']-f['rating'];codes=np.select([gap<-400,gap<-200,gap<-50,gap<=50,gap<=200,gap<=400],[0,1,2,3,4,5],default=6)
        cats('gap',codes,7,3)
    for c in ['clock','opp_clock']:
        missing=~np.isfinite(f[c])|(f[c]<0)
        scalar(c+'_log',np.log1p(np.where(missing,0,f[c])));scalar(c+'_missing',missing)
    scalar('log_age',np.log(f['age_days']))
    lk=np.log(f['k']);e=f['e']
    if t in ['T1','T3']:
        vals,nn=poly([lk,e-.5],3)
        for x,name in zip(vals,nn):scalar('Q_'+name,x)
    if t in ['T1','T2'] and v!='diagnostic_no_prior_count':scalar('log_opp_prior',np.log1p(f['opp_prior_count']))
    if v=='inactivity':
        scalar('no_own_prior',f['prior_count']==0);scalar('log_inactivity',np.log1p(np.where(f['prior_count']==0,0,f['inactivity_days'])))
    peak=f['peak365'] if t=='T4' and v=='recent_peak' else f['peak'];dist=peak-f['rating']
    W=(f['rc']>dist).astype(float)-(f['rg']>dist).astype(float)
    if v=='performance':scalar('performance_gap',f['dperf']/100)
    if v=='performance_peak':scalar('performance_gap',f['dperf']/100);scalar('win_only_crossing',W)
    target=[];labels=[];weights=[]
    def target_column(name,x):
        target.append(len(names));scalar(name,x)
    if t=='T1':target_column('recipient_rd_100' if v=='recipient_rd' else 'recipient_stake_10',f['opp_rd']/100 if v=='recipient_rd' else f['opp_stake']/10)
    if t=='T2':
        target_column('log_k',lk)
        if v=='cubic':
            target_column('log_k_sq',lk**2);target_column('log_k_cube',lk**3)
    if t=='T3':
        cats('distance',distance_code(dist),6,3);scalar('win_only_crossing',W)
        key={'lookback15':'dperf15','lookback60':'dperf60','tau200':'dperf200','tau800':'dperf800'}.get(v,'dperf')
        x=f[key]/100;target_column('performance_gap_100',x)
        if v=='interaction':target_column('performance_by_log_k',x*lk)
    if t=='T4':
        if v=='distance_profile':
            vals,nn=poly([lk,e-.5],3)
            for x,name in zip(vals,nn):scalar('Q_'+name,x)
            scalar('performance_gap',f['dperf']/100);scalar('win_only_crossing',W)
            dc=distance_code(dist)
            for i in [0,1,2,4,5]:target_column('distance_'+str(i),(dc==i).astype(float))
        else:
            vals,nn=poly([dist/10,f['rg']/10,f['premium']/10],2 if v=='quadratic' else 3)
            for x,name in zip(vals,nn):scalar('peak_basis_'+name,x)
            scalar('performance_gap',f['dperf']/100)
            if v=='rounded':
                W=(np.floor(f['rating']+f['rc']+.5)>peak).astype(float)-(np.floor(f['rating']+f['rg']+.5)>peak).astype(float)
            if v=='matching':W=(f['rc']>=dist).astype(float)-(f['rg']>=dist).astype(float)
            target_column('win_only_crossing',W)
    if t=='T5':
        for i in range(1,4):scalar('log_k_'+str(i),lk**i)
        if v=='profile':
            code=np.minimum(8,np.floor((e-.5+1e-12)/.05)).astype(int)
            for i in [0,1,2,3,5,6,7,8]:target_column('e_bin_'+str(i),(code==i).astype(float))
        else:
            brk=float(v[-2:])/100 if v.startswith('break') else .75
            tt=e-brk;H=(e>brk).astype(float);scalar('left_slope',tt);scalar('slope_change',tt*H)
            if v=='quadratic':scalar('left_curvature',tt**2);scalar('curvature_change',tt**2*H)
            target_column('threshold_jump',H)
    X=sparse.hstack(cols,format='csr');p=X.shape[1]
    C=np.zeros((len(target),p));C[np.arange(len(target)),target]=1
    if t=='T2' and v=='cubic':
        C=np.zeros((3,p))
        for j,base in enumerate([10,20,40]):C[j,target]=[np.log(2*base)**i-np.log(base)**i for i in [1,2,3]]
        labels=['K_10_to_20','K_20_to_40','K_40_to_80']
    else:labels=[names[j] for j in target]
    # Average interaction contrast is finalized using the exact estimation-sample mean log K.
    if t=='T3' and v=='interaction':C=C[:1];labels=['average_performance_gap_100']
    target_raw=np.asarray(X[:,target[0]].toarray()).ravel()
    if m['state']=='difference':
        c=f['state']==1;l=~c
        X=sparse.hstack([X.multiply(c[:,None]),X.multiply(l[:,None])],format='csr')
        cc=C[0];C=np.vstack([np.r_[cc,np.zeros(p)],np.r_[np.zeros(p),cc],np.r_[cc,-cc]])
        names=['competitive:'+s for s in names]+['losing:'+s for s in names]
        labels=['competitive','losing','competitive_minus_losing']
    if not np.isfinite(X.data).all():raise RuntimeError('Nonfinite design matrix: '+m['key'])
    return X,names,C,labels,target_raw,target
