"""Combined G1/game and G2/block bootstrap with family-level Monte Carlo precision."""
from __future__ import annotations
import gc,pickle
from g_common import *
from g_outcome import fit_outcome,bootstrap_games,YearOutcome
from g_fe import *
from g_statistics import *

def fit_stores(stores,weights=None):return {m:s.fit(weights) for m,s in stores.items()}

def group_statistics(stores,fits,weights=None):
    weights=np.ones(BLOCKS) if weights is None else weights;out={}
    for g in range(4):
        select=np.zeros(BLOCKS);select[(g+1)*400:(g+2)*400]=weights[(g+1)*400:(g+2)*400];metrics={}
        for m,s in stores.items():
            H=np.einsum('b,bij->ij',select,s.forms['test'],optimize=True);n=float(select@s.counts[:,1])
            metrics[m]=dict(brier=quadratic(H,fits[m]['train']['beta'])/n if n>0 else np.nan)
        out.update({f'group{g}:{k}':v for k,v in statistics(metrics).items()})
        for m in ['MR','MRprime']:
            v=fits[m]['responses'][g];out[f'group{g}:{m}:proportional_response_per_0.10_index']=.1*float(v[:-2]@fits[m]['full']['beta']/v[-2]) if v[-2]>0 else np.nan
            out[f'group{g}:{m}:response_pp_per_0.10_index']=10*float(v[:-2]@fits[m]['full']['beta']/v[-1]) if v[-1]>0 else np.nan
    return out

def stage_statistics(stores,fits):
    out={}
    for m in ['MR','MU']:
        meta=load(stores[m].path/'META.json');names=meta['names'];fit=fits[m]
        for band in range(5):
            if band==2:out[f'{m}:stage{band}:coefficient_pp']=0.
            else:
                j=names.index('stage_'+str(band));q=np.eye(len(names))[j]
                out[f'{m}:stage{band}:coefficient_pp']=100*float(fit['full']['beta'][j]) if estimable(fit['full'],q) else np.nan
            row=fit['stages'][band];out[f'{m}:stage{band}:observed_oos_pp']=100*row[-2]/row[-1] if row[-1]>0 else np.nan
            out[f'{m}:stage{band}:predicted_oos_pp']=100*(row[:-3]@fit['train']['beta']+row[-3])/row[-1] if row[-1]>0 else np.nan
    return out

def extra_statistics(stores_by_variant,fits_by_variant,weights=None):
    out={}
    for variant,stores in stores_by_variant.items():
        fits=fits_by_variant[variant]
        if variant=='year2_groups':values=group_statistics(stores,fits,weights)
        elif variant=='roughly_equal':values=stage_statistics(stores,fits)
        else:values=statistics(fits)
        out.update({variant+':'+k:v for k,v in values.items()})
    return out

def update_reliability(folder,family):
    folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
    def callback(index,d,p):
        x=logit(np.clip(p[:,0],PROB_CLIP,1-PROB_CLIP));path=folder/f'b{index:03d}.npz'
        if path.exists():
            state=np.load(path);n=int(state['n']);mean=state['mean'];m2=state['m2'];last=int(state['family'])
            require(last<family,'Duplicate or out-of-order reliability family','RELIABILITY_CHECKPOINT_FAILURE')
        else:n=0;mean=np.zeros(len(x));m2=np.zeros(len(x))
        n+=1;delta=x-mean;mean+=delta/n;m2+=delta*(x-mean)
        tmp=path.with_name(path.stem+'.partial.npz');np.savez(tmp,n=n,mean=mean,m2=m2,family=family);os.replace(tmp,path)
    return callback

def bootstrap(a,run,paths,positions,g1,templates,merge,knots,point_stores,variant_point,point,key):
    work=run/'bootstrap';work.mkdir(exist_ok=True);d=pd.read_parquet(positions);records=[]
    for p in sorted((work/'draws').glob('draw_*.json')):records+=load(p)['records']
    completed_families=sorted({r['family'] for r in records});require(completed_families==list(range(len(completed_families))),'Noncontiguous bootstrap checkpoints')
    live=work/'reliability';backup=work/'reliability_previous'
    if backup.exists():
        interrupted=load(work/'CURRENT_FAMILY.json')['family']
        if not (work/'draws'/f'draw_{interrupted:04d}.json').exists():
            if live.exists():shutil.rmtree(live)
            shutil.copytree(backup,live)
        shutil.rmtree(backup)
    if (work/'COMPLETE.json').exists():
        state=load(work/'COMPLETE.json');require(state['key']==key,'Bootstrap configuration mismatch')
        cleaned=decode_records(records);exchange_info=exchange_summary(point,[r['statistics'] for r in cleaned],templates,work/'FIXED_EXCHANGE_WEIGHTS.json')
        mc,_=decision_endpoints(point,cleaned,exchange_info)
        return cleaned,exchange_info,mc,state['stopping_reason']
    immutable={m:point_stores[m] for m in ['M0','MU']};immutable_variants={v:{m:s[m] for m in ['M0','MU']} for v,s in variant_point.items()}
    timings=load(work/'TIMINGS.json') if (work/'TIMINGS.json').exists() else []
    stopping='maximum G1 draws reached';mc=[];exchange_info=None
    for family in range(len(completed_families),a.max_g1_draws):
        start=time.monotonic();seed=SEED+100000+family
        multiplicity=bootstrap_games(d,seed)
        model=fit_outcome(d,run/'g1/fit'/g1.kind,g1.kind,multiplicity=multiplicity,warm=g1)
        year_statistics={}
        for year in [1,2]:
            mask=((d.month_code<12) if year==1 else (d.month_code>=12)).to_numpy()&~d.test.to_numpy()
            year_model=model.models[year] if isinstance(model,YearOutcome) else fit_outcome(d,run/'g1/fit'/f'year{year}',g1.kind,multiplicity=multiplicity,train_mask=mask,warm=g1)
            for r in exchange(year_model,templates):
                for field in ['X_w','X_eq']:year_statistics[f'year{year}:{field}:{r["cell"]}:{r["rating_edge"]}:{r["f_to_move"]}']=r[field]
        # Reuse the point-estimate design file, but never its coefficients or probabilities.
        models_dir=work/'models';models_dir.mkdir(exist_ok=True)
        with (models_dir/f'g1_{family:04d}.pkl').open('wb') as f:pickle.dump(model,f,protocol=5)
        scratch=work/'current'
        if scratch.exists():shutil.rmtree(scratch)
        callback=update_reliability(work/'reliability',family)
        # Reliability checkpoints must be atomic at family level. Rebuild an interrupted family from the previous snapshot.
        live=work/'reliability';backup=work/'reliability_previous'
        if backup.exists():shutil.rmtree(backup)
        if live.exists():shutil.copytree(live,backup)
        save(work/'CURRENT_FAMILY.json',dict(family=family))
        try:
            generated=build_moments(paths,model,knots,scratch/'all',models=['MR','MRU','MRprime','MRUprime'],probability_store=callback)
            stores=dict(immutable,**generated);variant_stores={}
            for variant in variant_point:
                subset='all' if variant=='random_holdout' else variant
                current=build_moments(paths,model,knots,scratch/variant,models=['MR','MRU','MRprime','MRUprime'],subset=subset,random=variant=='random_holdout')
                variant_stores[variant]=dict(immutable_variants[variant],**current)
            chunk=[];g1_values=outcome_statistics(model,templates)
            for inner in range(10):
                weights=block_draw(SEED+family*100+inner);fits=fit_stores(stores,weights)
                values=vector_stats(fits,model,templates,knots,g1_values)
                values.update(partial_statistics(stores['MRU'],weights));values.update(year_statistics)
                variants_fits={v:fit_stores(s,weights) for v,s in variant_stores.items()};values.update(extra_statistics(variant_stores,variants_fits,weights))
                # Frozen v2.1: log loss for the first 100 combined replicates.
                if family<10:
                    losses=log_losses(paths,model,knots,fits,weights=weights)
                    mock={m:dict(brier=v) for m,v in losses.items()};values.update({'logloss:'+k:v for k,v in statistics(mock).items()});values.update({'logloss:'+m+':loss':v for m,v in losses.items()})
                chunk.append(dict(family=family,inner=inner,statistics=clean(values)))
            drawfile=work/'draws'/f'draw_{family:04d}.json';save(drawfile,dict(key=key,records=chunk));records+=chunk
        except BaseException:
            if live.exists():shutil.rmtree(live)
            if backup.exists():shutil.copytree(backup,live)
            raise
        finally:
            if backup.exists():shutil.rmtree(backup)
        timings.append(dict(family=family,combined_replicates=10,seconds=time.monotonic()-start));save(work/'TIMINGS.json',timings)
        del generated,stores,variant_stores,variants_fits;gc.collect();shutil.rmtree(scratch)
        if family==4:
            elapsed=sum(t['seconds'] for t in timings[:5]);save(run/'report/BOOTSTRAP_PILOT.json',dict(distinct_g1_draws=5,combined_replicates=50,seconds=elapsed,
                projected_hours_for_50_g1_draws=elapsed*10/3600,projected_hours_for_500_g1_draws=elapsed*100/3600,
                note='Five complete G1 rebuilds, each with ten block resamples. Includes the first fifty log-loss passes; later families can be faster.'))
            log('Five-draw pilot complete; measured runtime report saved.')
        if (family+1)%50==0:
            cleaned=decode_records(records);exchange_info=exchange_summary(point,[r['statistics'] for r in cleaned],templates,work/'FIXED_EXCHANGE_WEIGHTS.json')
            mc,resolved=decision_endpoints(point,cleaned,exchange_info)
            save(run/'report/BOOTSTRAP_PRECISION.json',dict(G1_draws=family+1,combined_replicates=len(records),endpoints=mc,all_resolved=resolved))
            package(run,a.desktop,'BOOTSTRAP_'+str(family+1),'IN_PROGRESS')
            if resolved:stopping='all decision-relevant endpoints exceed two Monte Carlo SEs from thresholds';break
    cleaned=decode_records(records)
    if exchange_info is None:
        exchange_info=exchange_summary(point,[r['statistics'] for r in cleaned],templates,work/'FIXED_EXCHANGE_WEIGHTS.json');mc,_=decision_endpoints(point,cleaned,exchange_info)
    save(work/'COMPLETE.json',dict(key=key,G1_draws=len({r['family'] for r in cleaned}),combined_replicates=len(cleaned),stopping_reason=stopping))
    return cleaned,exchange_info,mc,stopping

def decode_records(records):
    def val(x):
        if x in ('nan','inf','-inf') if isinstance(x,str) else False:return float(x)
        return x
    return [dict(r,statistics={k:val(v) for k,v in r['statistics'].items()}) for r in records]
