"""Additional G1 refits with their own combined uncertainty, including account-overlap sensitivity."""
from __future__ import annotations
import gc,pickle
from g_common import *
from g_outcome import *
from g_fe import *
from g_statistics import *
from g_bootstrap import fit_stores

class MonthlyOutcome:
    def __init__(self,models,kind):self.models=models;self.kind='adjacent_'+kind
    def predict(self,d):
        out=np.zeros((len(d),3));months=d.month_code.to_numpy()
        for m in np.unique(months):
            require(int(m) in self.models,'No adjacent-month G1 model for opportunity month','ROBUSTNESS_MONTH_UNSUPPORTED')
            ix=np.flatnonzero(months==m);out[ix]=self.models[int(m)].predict(d.iloc[ix])
        return out

def overlap(a,run,paths,positions):
    c=db(run/'g1/overlap_spill',max(1,a.memory_gb-2))
    try:
        c.execute('CREATE TEMP TABLE choosers AS SELECT DISTINCT chooser_name FROM '+parq(paths))
        c.execute('CREATE TEMP TABLE players AS SELECT white AS "name" FROM '+parq([positions])+' UNION SELECT black AS "name" FROM '+parq([positions]))
        N,n=c.execute('SELECT count(*),count(*) FILTER(WHERE p.name IS NOT NULL) FROM choosers c LEFT JOIN players p ON c.chooser_name=p.name').fetchone()
        d=pd.read_parquet(positions);c.register('sampled',d)
        surviving=c.execute('SELECT s.* FROM sampled s WHERE NOT EXISTS(SELECT 1 FROM choosers c WHERE c.chooser_name=s.white OR c.chooser_name=s.black)').fetchdf()
        p=run/'g1/overlap_excluded.parquet';atomic_parquet(surviving,p)
        result=dict(G2_choosers=int(N),overlapping=int(n),share=float(n/N),G1_games=len(d),G1_games_without_G2_choosers=len(surviving),
            interpretation='Exclusion sensitivity changes G1 training population; it does not repair independent-stage resampling dependence')
        save(run/'report/ACCOUNT_OVERLAP.json',result);return result,p
    finally:c.close()

def sensitivity_fit(d,work,kind,merge,case,multiplicity=None,warm=None):
    if case!='adjacent_months':
        model=fit_outcome(d,work,kind,multiplicity=multiplicity,warm=warm)
        if multiplicity is None:
            cal,passed=calibration(model,d,d.test.to_numpy(),merge,case)
            require(passed,'Sensitivity G1 failed held-out calibration','ROBUSTNESS_CALIBRATION_FAILED')
        return model
    models={}
    for month in range(24):
        if warm is not None and month not in warm.models:continue
        mask=np.abs(d.month_code.to_numpy()-month)<=1
        if mask.sum()<5000:continue
        piece=d.loc[mask].reset_index(drop=True);count=None if multiplicity is None else multiplicity[mask]
        model=fit_outcome(piece,Path(work)/f'm{month:02d}',kind,multiplicity=count,warm=None if warm is None else warm.models.get(month))
        if multiplicity is None:
            _,passed=calibration(model,piece,piece.test.to_numpy(),merge,f'adjacent_{month}')
            if not passed:continue
        models[month]=model
    require(models,'No adjacent-month model passes calibration','ROBUSTNESS_CALIBRATION_FAILED')
    return MonthlyOutcome(models,kind)

def case_exchange(model,templates):
    if not isinstance(model,MonthlyOutcome):return {f'X_w:{r["cell"]}':r['X_w'] for r in exchange(model,templates) if r['rating_edge']==100 and r['f_to_move']==0}
    values={}
    for month,m in model.models.items():
        for r in exchange(m,templates):
            if r['rating_edge']==100 and r['f_to_move']==0:values[f'month{month}:X_w:{r["cell"]}']=r['X_w']
    return values

def run_robustness(a,run,paths,positions,g1,templates,merge,main_point):
    from g_reports import default_meta
    report=run/'report';over,p_excluded=overlap(a,run,paths,positions);original=pd.read_parquet(positions)
    cases=['secondary_model','adjacent_months','annotated_games','verified_endings']+(['exclude_overlapping_accounts'] if over['share']>.10 else [])
    summary=[];family_details=[]
    for case in cases:
        work=run/'robustness'/case;work.mkdir(parents=True,exist_ok=True);status=work/'STATUS.json'
        if status.exists() and load(status).get('finished'):
            summary+=load(status)['rows'];continue
        d=original.copy();kind='sequential' if g1.kind=='multinomial' else 'multinomial' if case=='secondary_model' else g1.kind
        if case!='secondary_model':kind=g1.kind
        if case=='verified_endings':d=d.loc[d.ending_basis=='verified'].reset_index(drop=True)
        elif case=='exclude_overlapping_accounts':d=pd.read_parquet(p_excluded)
        elif case=='annotated_games':
            d=d.loc[d.annotated&(d.annotation_cp.notna()|d.annotation_mate.notna())].copy();d['vf']=d.annotation_cp.fillna(0.);d['mate']=d.annotation_mate.fillna(0.);d=d.reset_index(drop=True)
        try:
            require(len(d)>=5000,'Fewer than 5,000 sensitivity games remain; no calibrated sensitivity claimed','ROBUSTNESS_INSUFFICIENT_SAMPLE')
            model=sensitivity_fit(d,work/'fit',kind,merge,case,warm=g1 if isinstance(g1,YearOutcome) and case!='adjacent_months' else None)
            subpaths=paths
            if isinstance(model,MonthlyOutcome):
                folder=work/'opportunities';folder.mkdir(exist_ok=True);subpaths=[]
                for i,p in enumerate(paths):
                    z=pd.read_parquet(p);z=z.loc[z.month_code.isin(model.models)].copy()
                    if len(z):q=folder/f'bucket_{i:03d}.parquet';atomic_parquet(z,q);subpaths.append(q)
            private_positions=work/'positions.parquet';atomic_parquet(d,private_positions)
            knots=init_knots(subpaths,model,work)
            stores=build_moments(subpaths,model,knots,work/'point');fits=fit_stores(stores);point=statistics(fits);point.update(case_exchange(model,templates))
            for k,v in list(point.items()):
                if k.startswith('X_w:'):
                    cell=k.split(':')[1];point['shift:'+k]=v-main_point.get(f'X_w:{cell}:100:0',np.nan)
            fixed={m:stores[m] for m in ['M0','MU']};rows=[];families=[];precision=[]
            for family in range(a.max_g1_draws):
                output=work/'draws'/f'f{family:04d}.json'
                if output.exists():vals=[{k:float(v) for k,v in x.items()} for x in load(output)]
                else:
                    master_counts=bootstrap_games(original,SEED+100000+family)
                    master_index=pd.Index(original.game_id).get_indexer(d.game_id);require((master_index>=0).all(),'Sensitivity games not in the original G1 sample')
                    fitted=sensitivity_fit(d,work/'fit',kind,merge,case,master_counts[master_index],warm=model)
                    scratch=work/'current'
                    if scratch.exists():shutil.rmtree(scratch)
                    changing=build_moments(subpaths,fitted,knots,scratch,models=['MR','MRU','MRprime','MRUprime']);current=dict(fixed,**changing);xw=case_exchange(fitted,templates);vals=[]
                    # Main G1 draws with the same family index give a paired shift benchmark when available.
                    mainfile=run/'bootstrap/draws'/f'draw_{family:04d}.json';main_draws=load(mainfile)['records'] if mainfile.exists() else None
                    main_xw=None
                    if main_draws is None:
                        main_model=fit_outcome(original,run/'g1/fit'/g1.kind,g1.kind,multiplicity=master_counts,warm=g1)
                        main_xw=case_exchange(main_model,templates)
                    for inner in range(10):
                        ff=fit_stores(current,block_draw(SEED+100*family+inner));v=statistics(ff);v.update(xw)
                        for k,value in xw.items():
                            if k.startswith('X_w:'):
                                cell=k.split(':')[1];baseline=float(main_draws[inner]['statistics'].get(f'X_w:{cell}:100:0',np.nan)) if main_draws else main_xw.get(k,np.nan);v['shift:'+k]=value-baseline
                        vals.append(v)
                    save(output,vals);del changing,current;gc.collect();shutil.rmtree(scratch)
                rows+=vals;families.extend([family]*10)
                if (family+1)%50==0:
                    precision=[]
                    for name in ['MRU:gain','D10','D25']:
                        values=[v[name] for v in rows];ci=interval(values);se=monte_carlo_endpoints(values,families)
                        precision.append(dict(statistic=name,ci=ci,mcse=se,resolved=all(np.isfinite(t) and abs(t)>2*s for t,s in zip(ci,se))))
                    if all(r['resolved'] for r in precision):break
            case_rows=[]
            for name,value in point.items():
                lo,hi=interval([v.get(name,np.nan) for v in rows]);case_rows.append(dict(case=case,statistic=name,estimate=value,ci_low=lo,ci_high=hi,G1_games=len(d),combined_replicates=len(rows),status='ESTIMATED',simulation_resolved=all(r['resolved'] for r in precision)))
            save(work/'STATUS.json',dict(finished=True,rows=case_rows,precision=precision));summary+=case_rows
            table(report,'tabG_robustness_'+case,case_rows,dict(default_meta(run,int(fits['M0']['counts'][2])),G1_games=len(d),source_months=[MONTHS[i] for i in sorted(d.month_code.unique())]))
        except GateError as e:
            row=dict(case=case,status=e.code,reason=str(e),G1_games=len(d));summary.append(row);save(work/'STATUS.json',dict(finished=True,rows=[row]));log('Sensitivity '+case+': '+e.code)
    old=pd.read_csv(report/'tabG_robustness.csv',comment='#') if (report/'tabG_robustness.csv').exists() else pd.DataFrame()
    table(report,'tabG_robustness',pd.concat([old,pd.DataFrame(summary)],ignore_index=True),default_meta(run))
    return summary
