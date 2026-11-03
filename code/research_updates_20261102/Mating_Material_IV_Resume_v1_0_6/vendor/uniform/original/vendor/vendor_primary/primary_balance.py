"""R12 joint-trait contrast estimator, rebound explicitly to the new cohort."""
from primary_common import *
from local_common import wald

def balance(src,scores,run,k):
    rows=[]
    for label,traits,base in [('seven_recent',frozen.r.T30,frozen.r.X0+frozen.r.ENV+['env_supported']),
                              ('fifteen_no_history',frozen.r.T15,frozen.r.NH+frozen.r.ENV+['env_supported'])]:
        ck=key([k,sha(src),sha(scores),label]);path=run/'PRIVATE/iv'/('balance_'+label+'.json')
        if cached(path,ck):result=load(path)
        else:
            v,groups,actors,meta,targets=iv.buffer(src,scores,True);columns=targets+meta['controls']
            # Traits are tested jointly, not partialled out with the nuisance controls.
            require(not set(traits)&set(base),'A tested trait is also a nuisance regressor')
            names=['received','y']+list(traits)+list(base)
            work=np.array(v[:,[columns.index(x) for x in names]],order='F',copy=True);del v
            with heartbeat('Balance contrast '+label):res,rank,diag=models.project(work,groups,2+len(traits))
            del work,groups;T=res[:,2:];gram=T.T@T
            require(np.linalg.matrix_rank(gram,tol=np.linalg.norm(gram,2)*1e-10)==len(traits),'Trait design rank deficient')
            bread=np.linalg.inv(gram);meat=iv.meat_for(actors);result=[]
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
