"""Certified S0 balance contrasts and first-stage ladder. IV units are explicit."""
import gc, sys
import pyarrow.parquet as pq
from local_common import *
sys.path.insert(0,str(ROOT/'vendor/r9b/code'))
import r9b_inputs as inputs, r9b_models as models, r9b_common as frozen

def bind(a,run):
    parent=a.r9_root or a.project/'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE/4028bf3e1857'
    with heartbeat('Authenticate certified R9 frames and donor histories'):b=inputs.bind(a.project,parent)
    require(pq.ParquetFile(b['s0']).metadata.num_rows==2682329,'S0 must contain 2682329 exposures')
    save(run/'PRIVATE/IV_BINDING.json',b);return b

def buffer(source,scores,balance=False):
    job=dict(name='R12',input=str(source),scores=str(scores),candidate='all',rich=True,
             level='X0_ENV_indicator',balance=balance,instruments=['A'])
    v,groups,actors,meta,targets,extra=models.buffer(job)
    require(v is not None,'IV sample is too small for the certified estimator')
    return v,groups,actors,meta,targets

def meat_for(actors):
    codes=frozen.r.stats.cmp.covariance_codes(actors['recipient_id'],actors['opponent_id'],actors['date'])
    return lambda s:frozen.shared_meat(s,codes,True)

def project_targets(work,groups,width):
    # The inherited routine expects at least one nuisance column. An identically
    # zero column makes its certified FE fallback usable for the FE-only ladder
    # without adding any fitted regressor; the continuous-control rank is zero.
    if work.shape[1]==width:
        expanded=np.empty((len(work),width+1),order='F');expanded[:,:width]=work;expanded[:,width]=0.;work=expanded
    return models.project(work,groups,width)

def iv_fit(source,scores,controls):
    v,groups,actors,meta,targets=buffer(source,scores)
    columns=targets+meta['controls'];take=['z_A','received','y']+list(controls)
    work=np.array(v[:,[columns.index(x) for x in take]],order='F',copy=True);del v
    with heartbeat('IV fixed-effect absorption'):res,rank,diag=project_targets(work,groups,3)
    del work,groups;z,D,y=res.T;meat=meat_for(actors)
    zz=float(z@z);zd=float(z@D);require(zz>0 and abs(zd)>1e-12,'No first stage')
    fs=float(z@D)/zz;rf=float(z@y)/zz;iv=float(z@y)/zd
    vf=float(meat(z*(D-fs*z)/zz)[0,0]);vr=float(meat(z*(y-rf*z)/zz)[0,0]);vi=float(meat(z*(y-iv*D)/zd)[0,0])
    f=inference(fs*100*SD,vf*(100*SD)**2);r=inference(rf*100*SD,vr*(100*SD)**2);i=inference(iv*100,vi*10000)
    out=dict(exposures=len(z),recipients=meta['recipients'],score_sd=SD,covariance='shared_account_OR_exposure_date_CR0',
             first_stage=f['estimate'],first_stage_se=f['se'],first_stage_p=f['p'],
             reduced_form=r['estimate'],reduced_form_se=r['se'],reduced_form_p=r['p'],
             iv=i['estimate'],iv_se=i['se'],iv_p=i['p'],ci_low=i['ci_low'],ci_high=i['ci_high'],
             first_stage_F=fs*fs/vf if vf>0 else None,status='ESTIMATED' if all(x['status']=='ESTIMATED' for x in [f,r,i]) else 'INVALID_VARIANCE',
             control_rank=rank,absorb_iterations=int(diag['iterations']))
    del res,actors;gc.collect();return out

def reproduce(row,column):
    level='X0' if column==3 else 'X0_ENV_indicator'
    ref=[r for r in load(ROOT/'vendor/r9b/evidence/A_receipt.json') if r['control_level']==level and r.get('cohort')=='full']
    for est,field,sefield in [('first_stage','first_stage','first_stage_se'),('reduced_form','reduced_form','reduced_form_se'),('2SLS','iv','iv_se')]:
        choices=[r for r in ref if r['estimator']==est and r.get('outcome') in ('received','y')]
        require(len(choices)==1,'Ambiguous frozen IV reference: '+est)
        old=choices[0]
        bf='iv_coefficient_pp' if est=='2SLS' else 'coefficient_pp';sf='iv_standard_error_pp' if est=='2SLS' else 'standard_error_pp'
        require(np.isclose(row[field],old[bf],atol=2e-7,rtol=1e-7),'Certified IV coefficient reproduction failed: '+field)
        require(np.isclose(row[sefield],old[sf],atol=2e-7,rtol=1e-7),'Certified IV SE reproduction failed: '+sefield)

def ladder(a,run,k,b):
    source=b['s0'];scores=Path(b['parent'])/'scores_combined/S0.parquet';rows=[]
    controls=[[],frozen.r.NH,frozen.r.X0,frozen.r.X0+frozen.r.ENV+['env_supported']]
    for j,names in enumerate(controls,1):
        path=run/'PRIVATE/iv'/f'ladder_{j}.json';ck=key([k,sha(source),sha(scores),j])
        if cached(path,ck):r=load(path)
        else:
            r=iv_fit(source,scores,names);save(path,r);seal(path,ck)
        if j in [3,4]:reproduce(r,j)
        rows.append(dict(column=j,**r));csv_out(run/'report/first_stage_ladder.csv',rows)
    save(run/'report/iv_ladder_model.json',dict(controls={str(j):x for j,x in enumerate(controls,1)},
         fixed_effects=['month x exact time control x 100-point mean rating bin','exposure date','hour of week'],
         rows=2682329,score_sd=SD,first_stage_reduced_form_units='percentage points per fixed primary score SD',iv_units='percentage points per receipt',author_accounts='excluded in both roles and donor histories'))

def balance(a,run,k,b):
    rows=[];src=b['s0'];scores=Path(b['parent'])/'scores_combined/S0.parquet'
    for label,traits,base in [('seven_recent',frozen.r.T30,frozen.r.X0+frozen.r.ENV+['env_supported']),
                              ('fifteen_no_history',frozen.r.T15,frozen.r.NH+frozen.r.ENV+['env_supported'])]:
        ck=key([k,sha(src),sha(scores),label]);path=run/'PRIVATE/iv'/('balance_'+label+'.json')
        if cached(path,ck):result=load(path)
        else:
            v,groups,actors,meta,targets=buffer(src,scores,True);columns=targets+meta['controls']
            # Traits are tested jointly, not partialled out with the nuisance controls.
            require(not set(traits)&set(base),'A tested trait is also a nuisance regressor')
            names=['received','y']+list(traits)+list(base)
            work=np.array(v[:,[columns.index(x) for x in names]],order='F',copy=True);del v
            with heartbeat('Balance contrast '+label):res,rank,diag=models.project(work,groups,2+len(traits))
            del work,groups;T=res[:,2:];gram=T.T@T
            require(np.linalg.matrix_rank(gram,tol=np.linalg.norm(gram,2)*1e-10)==len(traits),'Trait design rank deficient')
            bread=np.linalg.inv(gram);meat=meat_for(actors);result=[]
            for j,outcome in enumerate(['receipt','zero_coded_later_grant']):
                y=res[:,j];coef=bread@(T.T@y);err=y-T@coef;V=bread@meat(T*err[:,None])@bread
                partial=1-float(err@err)/float(y@y);test=wald(coef,V,len(traits))
                result.append(dict(specification=label,outcome=outcome,row_type='joint_test',term='all_traits',
                     **test,partial_R2=partial,exposures=len(y),units='chi-square'))
                for name,point,var in zip(traits,coef,np.diag(V)):
                    result.append(dict(specification=label,outcome=outcome,row_type='coefficient',term=name,
                         **inference(point*100,var*10000),partial_R2=partial,exposures=len(y),units='percentage points per full-sample trait SD'))
            save(path,result);seal(path,ck);del res,actors;gc.collect()
        rows+=result;csv_out(run/'report/balance_contrast.csv',rows)

def run(a,run,k):
    b=bind(a,run);ladder(a,run,k,b);balance(a,run,k,b)
