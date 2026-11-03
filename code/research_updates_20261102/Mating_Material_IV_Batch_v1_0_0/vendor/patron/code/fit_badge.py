"""Exact Model 5 design; weighted FE/FWL and shared-account-OR-date CR0."""
from common5 import *
sys.path.insert(0,str(ROOT/'vendor_badge/code'))
from patron_models import weighted_absorb
import gc,math

def weights_for(path,kind):
    n=pq.ParquetFile(path).metadata.num_rows
    if kind=='unit':return np.ones(n)
    p=np.asarray(cert.c.frozen.col(path,'sampling_fraction'),float)
    require(np.isfinite(p).all() and (p>0).all() and (p<=1).all(),'Invalid original acquisition fraction')
    w=1./p
    if kind=='recipient_ipw':
        ni=np.asarray(cert.c.frozen.col(path,'model5_exposures_per_recipient'),float)
        require(np.isfinite(ni).all() and (ni>=1).all(),'Invalid full-frame recipient row counts');w/=ni
    else:require(kind=='ipw','Unknown weight rule')
    return w

def weighted_project(v,groups,w,width,root):
    if np.all(w==w[0]):return model.project(v,groups,width,root)
    v,diag=weighted_absorb(v,groups,w,publish=lambda d:log('Weighted FE iteration '+str(d.get('iteration',d.get('iterations')))))
    n,p=v.shape;k=p-width;gram=np.zeros((k,k));cross=np.zeros((k,width))
    for lo in range(0,n,65536):
        hi=min(n,lo+65536);sw=np.sqrt(w[lo:hi]);x=np.asarray(v[lo:hi,width:])*sw[:,None];y=np.asarray(v[lo:hi,:width])*sw[:,None]
        gram+=x.T@x;cross+=x.T@y
    beta=np.linalg.pinv(gram,rcond=1e-12)@cross
    rank=int(np.linalg.matrix_rank(gram,tol=max(float(np.linalg.norm(gram,2)),1.)*1e-12))
    result=model.disk.disk_matrix(Path(root)/'weighted_residual.dat',n,width)
    for lo in range(0,n,65536):result[lo:lo+65536]=v[lo:lo+65536,:width]-v[lo:lo+65536,width:]@beta
    model.disk.release_pages(result);return result,rank,diag

def residual_terms(res,w,outcomes,iv_outcome):
    z=res[:,0];zz=float(np.dot(w*z,z));require(zz>1e-14,'No residual instrument variation')
    terms=[]
    for k,name in enumerate(outcomes,1):
        terms.append(dict(term='first_stage' if name=='received' else 'rf_'+name,outcome=name,beta=float(np.dot(w*z,res[:,k]))/zz,den=zz,error_y=k,error_x=0,scale=100*SD,units='percentage points per fixed reference Score A SD'))
    if iv_outcome:
        kd=1+outcomes.index('received');ky=1+outcomes.index(iv_outcome);zd=float(np.dot(w*z,res[:,kd]))
        require(abs(zd)>1e-12,'Zero first stage on the Patron estimation sample')
        terms.append(dict(term='iv_'+iv_outcome,outcome=iv_outcome,beta=float(np.dot(w*z,res[:,ky]))/zd,den=zd,error_y=ky,error_x=kd,scale=100.,units='percentage points per receipt'))
    return terms,math.sqrt(zz/w.sum())

def fit(job):
    def build(tmp):
        v,groups,actors,targets,meta,events=model.build_buffer(job,tmp)
        names=list(c.frozen.r.X0);names=[x.replace('log_volume_30','log_volume_90') for x in names]+c.frozen.r.ENV+['env_supported']
        require(meta['controls']==names and 'log_volume_90' in names,'Model 5 control list changed')
        raw=weights_for(job['input'],job['weight']);w=raw/raw.mean();n=len(w)
        weight_info=dict(weight_rule=job['weight'],sum_raw_weights=float(raw.sum()),maximum_raw_weight=float(raw.max()),kish_effective_rows=float(raw.sum()**2/np.dot(raw,raw)))
        del raw
        for name in job['outcomes']:
            y=np.asarray(c.frozen.col(job['input'],name),float);events[name]['mean_pp']=float(100*np.dot(w,y)/w.sum())
        extra={}
        if 'patron' in job['outcomes']:
            patron=np.asarray(c.frozen.col(job['input'],'patron'),bool)
            extra['unique_patrons']=int(len(np.unique(actors['recipient_id'][patron])))
            extra['unique_nonpatrons']=meta['recipients']-extra['unique_patrons'];del patron
        del y
        res,rank,diag=weighted_project(v,groups,w,len(targets),tmp);del v,groups;gc.collect()
        terms,native=residual_terms(res,w,job['outcomes'],job.get('iv_outcome'))
        influence=tmp/'influence_PRIVATE.parquet';writer=None
        try:
            for lo in range(0,n,65536):
                hi=min(n,lo+65536);data={k:val[lo:hi] for k,val in actors.items()}
                for term in terms:
                    data[term['term']]=w[lo:hi]*res[lo:hi,0]*(res[lo:hi,term['error_y']]-term['beta']*res[lo:hi,term['error_x']])/term['den']
                block=pa.table(data)
                if writer is None:writer=pq.ParquetWriter(influence,block.schema,compression='zstd')
                writer.write_table(block)
        finally:
            if writer:writer.close()
        del actors,res,w;gc.collect()
        for path in ('design.dat','residual.dat','weighted_residual.dat'):(tmp/path).unlink(missing_ok=True)
        # Force bounded covariance so its allocations do not depend on free-RAM
        # fluctuations from another research process on the laptop.
        buckets=min(128,max(8,2**int(np.ceil(np.log2(max(1,n/1000000))))))
        V=model.covariance(influence,[t['term'] for t in terms],Path(job['work']),memory=3.,buckets=buckets)
        rows=[]
        for k,t in enumerate(terms):
            row=dict(meta,**extra,**weight_info,term=t['term'],outcome=t['outcome'],units=t['units'],
                **model.inference90(t['beta'],float(V[k,k]),t['scale']),**events[t['outcome']],
                control_rank=rank,native_residual_score_sd=native,absorb_iterations=diag['iterations'],
                profile_snapshot='August 2026' if 'patron' in job['outcomes'] else None,
                target=job['target'],generated_scores_treated_as_fixed=True)
            if t['term']=='first_stage':row['wald_F']=t['beta']**2/V[k,k] if V[k,k]>0 else None
            if t['outcome']=='patron' and min(extra['unique_patrons'],extra['unique_nonpatrons'])<10:row.update(supported=False,reason='FEWER_THAN_TEN_DISTINCT_PATRONS_OR_NONPATRONS')
            rows.append(row)
        save(tmp/'result.json',dict(estimates=rows,covariance_terms=[t['term'] for t in terms],native_covariance=V.tolist(),projection=diag))
        return dict(rows=n,recipients=meta['recipients'])
    folder,_=stage(job['output'],job['conf'],build,[job['input'],job['scores']])
    return load(folder/'result.json')['estimates']

def subset(a,paths,name,where):
    def build(tmp):
        con=c.conn(tmp/'spill',a.memory_gb-2)
        try:
            c.view(con,'q',paths['linked']);c.view(con,'s',paths['scores'])
            c.copy_query(con,'SELECT * FROM q WHERE '+where+' ORDER BY row_id',tmp/'source.parquet')
            c.copy_query(con,'SELECT s.* FROM s JOIN q USING(row_id) WHERE '+where+' ORDER BY s.row_id',tmp/'scores.parquet')
            n=pq.ParquetFile(tmp/'source.parquet').metadata.num_rows
            require(n==pq.ParquetFile(tmp/'scores.parquet').metadata.num_rows,'Subset score join changed rows')
            return dict(rows=n)
        finally:con.close()
    folder,info=stage(a.run/'PRIVATE/subsets'/name,a.conf,build,[paths['linked'],paths['scores']]);return folder,info

def make_job(a,name,source,scores,outcomes,weight='unit',iv=None,target=''):
    return dict(name=name,input=str(source),scores=str(scores),outcomes=outcomes,weight=weight,iv_outcome=iv,
        level='X0_ENV_indicator',conf=a.conf,output=str(a.run/'PRIVATE/fits'/name),work=str(a.run/'PRIVATE/covariance'/name),target=target)

def baseline(a):
    binding=load(a.run/'PRIVATE/BINDING.json')
    job=make_job(a,'model5_reproduction',binding['source'],binding['scores'],['received','y','reached'],iv='y',target='Full accepted Model 5 exposure frame')
    rows=fit(job);reference={r['term']:r for r in load(binding['baseline'])['estimates']};checks=[]
    for r in rows:
        old=reference[r['term']]
        for field in ('n','recipients','row_set_sha256','controls','history','fixed_effects'):require(r[field]==old[field],'Model 5 metadata mismatch: '+field)
        for field in ('coefficient','standard_error','native_residual_score_sd'):
            delta=abs(r[field]-old[field]);tol=2e-7+2e-7*abs(old[field]);checks.append(dict(term=r['term'],field=field,actual=r[field],expected=old[field],difference=delta,tolerance=tol,passed=delta<=tol))
    table(a.run/'report/model5_reproduction',checks);require(all(r['passed'] for r in checks),'Model 5 numerical reproduction failed')
    table(a.run/'report/model5_reference_estimates',rows)

def primary(a):
    paths=load(a.run/'PRIVATE/BADGE_PATHS.json');observed,info=subset(a,paths,'observed','profile_returned')
    require(info['rows']>=2000,'Fewer than 2,000 observed Model 5 exposure rows')
    job=make_job(a,'patron_exposure_ipw',observed/'source.parquet',observed/'scores.parquet',['received','patron'],weight='ipw',iv='patron',target='Exposure-weighted Model 5 population within original positive acquisition support; inverse original sampling fractions; no nonresponse adjustment')
    table(a.run/'report/Patron_primary_estimates',fit(job))
    job=make_job(a,'profile_selection',paths['linked'],paths['scores'],['in_original_chooser_universe','positive_support','profile_returned'],target='Full Model 5 exposure frame')
    table(a.run/'report/selection_diagnostics',fit(job))

def sensitivities(a):
    paths=load(a.run/'PRIVATE/BADGE_PATHS.json');observed=a.run/'PRIVATE/subsets/observed';jobs=[]
    jobs.append(make_job(a,'patron_observed_unweighted',observed/'source.parquet',observed/'scores.parquet',['received','patron'],iv='patron',target='Observed August profiles; equal exposure weights'))
    jobs.append(make_job(a,'patron_recipient_ipw',observed/'source.parquet',observed/'scores.parquet',['received','patron'],weight='recipient_ipw',iv='patron',target='Each full-frame recipient has total base weight one, then inverse original acquisition fraction; positive-support population'))
    prior=load(a.run/'report/prior_chooser_support.json')
    if prior['zero_support_exposures']==0 and prior['observed_exposures']>=2000:
        folder,_=subset(a,paths,'prior_chooser','profile_returned AND fair_90>0')
        jobs.append(make_job(a,'patron_prior_chooser_ipw',folder/'source.parquet',folder/'scores.parquet',['received','patron'],weight='ipw',iv='patron',target='Pre-exposure chooser history fair_90>0, verified universal positive acquisition support; exposure weights with original acquisition correction'))
    else:save(a.run/'report/prior_chooser_fit_status.json',dict(status='NOT_FIT',reason='Insufficient rows or pre-exposure chooser subset lacks universal positive acquisition support'))
    rows=[]
    for job in jobs:
        rows+=fit(job);table(a.run/'report/Patron_sensitivity_estimates',rows)

if __name__=='__main__':
    a=parser().parse_args();c.frozen.u.no_network();os.environ['UNIFORM90_MEMORY_GIB']=str(a.memory_gb);os.environ['UNIFORM90_WORKERS']=str(a.workers)
    with cert.heartbeat('Patron Model 5 '+a.mode):
        if a.mode=='baseline':baseline(a)
        elif a.mode=='primary':primary(a)
        elif a.mode=='sensitivities':sensitivities(a)
        else:raise ValueError(a.mode)
