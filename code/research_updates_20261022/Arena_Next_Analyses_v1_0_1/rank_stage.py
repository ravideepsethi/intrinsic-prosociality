"""Targeted numerical repair; original variables and source-derived cache definitions."""
from pathlib import Path
import numpy as np
from next_common import *

def within_gram(mod,c,table,filt,terms,tag):
    raw=c.execute(mod.raw_cross_query(table,filt,terms)).fetchdf().iloc[0].to_dict()
    temp='rank_audit_'+tag;mod.make_cluster_sums(c,table,filt,terms,temp)
    cor=c.execute(mod.correction_query(temp,terms)).fetchdf().iloc[0].to_dict();c.execute('DROP TABLE '+temp)
    names=[n for n,_ in terms];p=len(names);gram=np.zeros((p,p))
    for i,a in enumerate(names):
        for j,b in enumerate(names[i:],i):
            gram[i,j]=gram[j,i]=float(raw.get(f's_{a}__{b}') or 0)-float(cor.get(f'c_{a}__{b}') or 0)
    return gram,int(raw['n']),int(cor['clusters'])

def run(sample,root,args):
    work=Path(root)/'private/rank_repair';public=Path(root)/'public/rank_repair'
    if work.exists():work.rename(work.with_name('rank_repair.incomplete.'+str(time.time_ns())))
    work.mkdir(parents=True);public.mkdir(parents=True,exist_ok=True)
    krd=load(ROOT/'source/structural/rating_gap_krd_decomposition.py','arena_rank_krd')
    mod=load(ROOT/'source/structural/rating_gap_nonparametric_closure_parallel.py','arena_rank_closure')
    c=db(work/'spill',args.memory,args.threads)
    try:
        cache=work/'krd.parquet';krd.schema_gate(c,parq(sample['panels']))
        krd.create_cache(c,parq(sample['panels']),cache)
        qa=krd.mechanical_validation(c,parq(cache)).iloc[0].to_dict()
        require(qa['n']==sample['authority']['rows'] and qa['max_abs_error']<=1e-8,'Rebuilt K/RD identity failed')
        mod.SOURCE_CACHE=cache
        base,cache_receipt=mod.build_private_cache(c,work)
        months,speeds=mod.categories(c,base);plan=mod.build_model_plan(months,speeds,cache_receipt)
        old={r['model_id']:r for r in read(ROOT/'authority/V102_RANK_FLAGS.json')};receipts=[];coefficients=[]
        for item in plan:
            name=item['model_id']
            if name not in old:continue
            log('Numerical repair: '+name);table=mod.table_for_band(base,item['eb'])
            filt='('+mod.stage_filter(item['stage'])+') AND ('+item['extra_filter']+')';terms=item['terms']
            dropped_baseline=None
            if name.startswith('year2__'):
                active=[r[0] for r in c.execute(f'SELECT DISTINCT month FROM {table} WHERE {filt} ORDER BY 1').fetchall()]
                require(len(active)==12,'Year-two repair requires all 12 active months')
                dropped_baseline='m_'+active[0].replace('-','_')
                terms=[t for t in terms if t[0]!=dropped_baseline]
            gram,n,g=within_gram(mod,c,table,filt,terms,str(len(receipts)))
            require(n==old[name]['rows'] and g==old[name]['clusters'],'Targeted refit changed the original model sample')
            scale=np.sqrt(np.maximum(np.diag(gram),0.));valid=scale>max(1e-9,scale.max()*1e-9)
            small=gram[np.ix_(valid,valid)]/scale[valid,None]/scale[None,valid]
            ev=np.linalg.eigvalsh((small+small.T)/2);rank=int((ev>max(1e-9,ev[-1]*1e-10)).sum())
            receipt={'model_id':name,'rows':n,'clusters':g,'within_dimension_ceiling':n-g,
              'original_rank':old[name]['rank'],'original_kept_terms':old[name]['terms_kept'],
              'scaled_rank':rank,'varying_terms':int(valid.sum()),'dropped_active_month_baseline':dropped_baseline,
              'same_sample_as_v102':True,'nuisance_span_preserved':True}
            if rank<int(valid.sum()) or n-g<int(valid.sum()):
                receipt.update(status='UNSUPPORTED_FULL_SPECIFICATION',reason='Insufficient within-chooser rank; no reduced substantive model substituted.')
            else:
                adjusted=[(name,f'({expr})/({s:.17g})') for (name,expr),s,ok in zip(terms,scale,valid) if ok]
                fits,r=mod.fit_fe_targeted(c,table,filt,adjusted,item['key_terms'],name)
                require(r['rank']==r['terms_kept'],'Rescaled targeted fit remains singular')
                smap={n:s for (n,_),s in zip(terms,scale)}
                fits['coef_pp']=fits.apply(lambda x:x['coef_pp']/smap[x['term']],axis=1)
                fits['se_pp']=fits.apply(lambda x:x['se_pp']/smap[x['term']],axis=1)
                fits['status']='ESTIMATED_REBASED_MONTHS_AND_SCALED';coefficients.extend(fits.to_dict(orient='records'))
                receipt.update(status='ESTIMATED_REBASED_MONTHS_AND_SCALED',new_fit=r)
            receipts.append(receipt)
        require(len(receipts)==4,'Not all four flagged curves were accounted for')
        js(public/'TARGETED_REPAIR.json',receipts);csvout(public/'repaired_coefficients.csv',coefficients)
        js(public/'REBUILT_CACHE_QA.json',qa)
    finally:c.close()
    return {'status':'COMPLETE','flagged_models':4,'reestimated':sum(r['status'].startswith('ESTIMATED') for r in receipts),
      'unsupported':sum(r['status'].startswith('UNSUPPORTED') for r in receipts),
      'previous_files_modified':False,'reconstructed_cache_from_authenticated_arena_panel':True}
