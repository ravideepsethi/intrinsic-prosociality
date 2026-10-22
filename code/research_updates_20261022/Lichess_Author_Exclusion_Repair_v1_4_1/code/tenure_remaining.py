"""Frozen tenure sample, factual account ages, rebuilt Patron histories and residuals."""
from remaining_common import *

def run_stage(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/tenure'))
    import prepare,tenure
    old=args.project/'output/tenure_responsibility_v100/c539ba215e708b22'
    selected=old/'PRIVATE/selected_accounts.parquet';checked_sidecar(selected)
    fetched=old/'PRIVATE/fetched_profile_dates.parquet';checked_sidecar(fetched)
    original_accounts=old/'PRIVATE/accounts.parquet';checked_sidecar(original_accounts)
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        c.execute('CREATE VIEW src AS SELECT * FROM '+scan([r['path'] for r in auth['month_records']]))
        # first_ms is a factual age anchor; it does not become later if an
        # early analytical encounter with the author is removed.
        c.execute('CREATE VIEW accounts AS SELECT a.* FROM '+scan(original_accounts)+' a SEMI JOIN (SELECT DISTINCT chooser_user_id chooser FROM src) b USING(chooser)')
        c.execute('CREATE VIEW selected AS SELECT a.* FROM '+scan(selected)+' a SEMI JOIN accounts USING(chooser)')
        paths=[]
        for r in auth['month_records']:
            path=out/'PRIVATE/panel'/(r['month']+'.parquet')
            query=prepare.project_query(r['path'])
            require(query.count('month::VARCHAR month')==1,'Tenure projection source changed')
            query=query.replace('month::VARCHAR month','month::VARCHAR AS "month"')
            copy(c,'SELECT p.*,s.draw_rank FROM ('+query+') p JOIN selected s USING(chooser)',path);paths.append(path)
        c.execute('CREATE VIEW panel AS SELECT * FROM '+scan(paths))
        prepare.cached_profiles(c,args.project,out)
        c.execute('CREATE VIEW profiles_fetch AS SELECT * FROM '+scan(fetched))
        prepare.attach_age(c)
        tenure.run_tenure(c,out)
    finally:c.close()
    estimates=[];contrasts=[];statuses=[]
    for p in sorted((out/'report').glob('*MODEL*.json')):
        d=read(p)
        if not isinstance(d,dict):continue
        statuses.append(dict(model=p.stem,status=d.get('status','UNKNOWN'),rows=d.get('n'),clusters=d.get('clusters')))
        for term,r in d.get('estimates',{}).items():
            estimates.append(dict(model=p.stem,term=term,**{k:v for k,v in r.items() if not isinstance(v,(dict,list))}))
        if 'fair_minus_losing_pp' in d:contrasts.append(dict(model=p.stem,contrast='fair_minus_losing',estimate_pp=d['fair_minus_losing_pp'],se_pp=d['contrast_se_pp']))
        if args.variant=='included':
            original=read(old/'report'/p.name)
            require(d['status']==original['status'],'Tenure baseline identification status differs: '+p.name)
            for term,r in d.get('estimates',{}).items():
                ref=original['estimates'][term];require(r['status']==ref['status'],'Tenure term identification differs')
                for col in ('coefficient_pp','se_pp'):
                    if col in r:require(np.isclose(r[col],ref[col],rtol=2e-7,atol=2e-8),'Tenure baseline does not reproduce: '+p.name+'/'+term+'/'+col)
    table(out/'report/model_estimates',estimates)
    table(out/'report/model_statuses',statuses);table(out/'report/patron_contrasts',contrasts)
    return dict(status='TENURE_AND_AGE_RESTRICTED_PATRON_REFITTED',frozen_sample=record(selected),new_profile_requests=0,new_account_sampling=False,factual_age_anchor_preserved=True)
