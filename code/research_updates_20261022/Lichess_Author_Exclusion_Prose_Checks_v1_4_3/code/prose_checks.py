"""Small, explicit follow-up for manuscript results missed by family-level coverage."""
from engine import *
import argparse, ast, fcntl, platform, zipfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(ROOT/'vendor'))
from activity_original import features, adjustment, statistics

PARENT = read(ROOT/'PARENT.json')
REVIEWED = read(ROOT/'REVIEWED_PARENT.json')
V100 = read(ROOT/'V100_AUTHORITY.json')
VARIANTS = ('included', 'excluded')
KEYS = {
 'rating_activity_summary.csv':['scope'],
 'rating_distribution_by_activity.csv':['activity','rating_band'],
 'time_control_composition.csv':['activity','modal_speed','modal_time_control'],
 'joint_cell_support.csv':['rating_band','modal_speed','modal_time_control'],
 'within_rating_time_control_rates.csv':['rating_band','modal_speed','modal_time_control','scope'],
 'common_support_flow.csv':['scope'],
 'standardized_state_rates.csv':['scope','method'],
 'standardized_rate_covariance_pct2.csv':['scope','row_method','row_rate','column_method','column_rate'],
 'standardization_weights.csv':['scope','method','rating_band','modal_speed','modal_time_control'],
 'standardization_target.csv':['rating_band','modal_speed','modal_time_control'],
 'standardized_activity_comparisons.csv':['method','comparison'],
 'paired_adjustment_changes.csv':['method','comparison'],
 'equal_weight_estimates.csv':['scope','estimator'],
 'equal_weight_differences.csv':['scope','comparison'],
 'equal_weight_covariance.csv':['row_estimator','column_estimator'],
 'material_screen.csv':['variant'],
 'patron_bounds.csv':['sample'],
 'patron_bounds_by_cell.csv':['match_cell'],
 'patron_flow.csv':['stage','is_kind_role'],
}

def verify_package():
    for line in (ROOT/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        expected, rel = line.split('  ',1); p=(ROOT/rel).resolve()
        require(ROOT.resolve() in p.parents and p.is_file() and sha(p)==expected,'Package changed: '+rel)

def verify_report(root, expected):
    require(sha(root/'report/REPORT_HASHES.json')==expected,'Reviewed report manifest changed')
    for r in read(root/'report/REPORT_HASHES.json'):
        rel=Path(r['file']); require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe report path')
        p=root/'report'/rel
        require(p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Reviewed report changed: '+str(rel))

def authenticate(project, workers):
    parent=project/'derived/replication/author_exclusion_persistence_v142_PRIVATE'/REVIEWED['run_id']
    require(digest(read(parent/'PRIVATE/CONFIG.json'))[:16]==parent.name,'v142 configuration changed')
    verify_report(parent,REVIEWED['report_manifest_sha256'])
    old=project/'derived/replication/author_exclusion_repair_v141_PRIVATE'/PARENT['run_id']
    cfg=read(old/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==old.name and cfg['code']==PARENT['code'],'v141 configuration changed')
    auths={v:read(old/'PRIVATE/inputs'/(v+'_AUTH.json')) for v in VARIANTS}
    for v,a in auths.items():
        require(a['variant']==v and a['author_policy']==POLICY,'Paired input policy changed')
        rr=a['month_records'];require([r['month'] for r in rr]==MONTHS,'Panel months differ')
        require(a['fingerprint']==PARENT['sample_fingerprints'][v] and
                digest([v,POLICY,[{k:x for k,x in r.items() if k!='verified_signature'} for r in rr]])==a['fingerprint'],
                'Paired input fingerprint changed')
        require(sha(a['success_path'])==a['success_sha256'],'Input certification changed')
    records={str(Path(r['path']).resolve()):r for a in auths.values() for r in a['month_records']}
    def check(item):
        p,r=item
        require(Path(p).stat().st_size==r['size_bytes'] and sha(p)==r['expected_sha256'],'Panel checksum changed')
        return p,signature(p)
    with ThreadPoolExecutor(max_workers=min(4,workers)) as pool,heartbeat('Authenticate existing Parquets'):
        stamps=dict(pool.map(check,records.items()))
    return parent,auths,stamps

def material_counts(paths, temp, workers, memory):
    c=db(temp,memory,workers)
    try:
        pair=names_pair(paths[0]); source=scan(paths)
        missing=' OR '.join('coalesce(trim(s.'+ident(n)+"),'')=''" for n in pair)
        f='timeout_draw_no_mating_material'; fair='engine_eval_cp_disconnected>=-100'; lost='engine_eval_cp_disconnected<=-300'
        return {k:int(v) for k,v in c.execute(f'''SELECT count(*) AS opportunities,
          sum(outcome_kind_draw)::BIGINT AS grants,
          count(*) FILTER(WHERE {missing}) AS missing_id,
          count(*) FILTER(WHERE {author_sql(pair)}) AS author_games,
          count(*) FILTER(WHERE {f} IS NULL) AS missing_flag,
          count(*) FILTER(WHERE {f}) AS flagged,
          count(*) FILTER(WHERE {f} AND NOT ({fair})) AS flagged_outside_competitive,
          count(*) FILTER(WHERE {f} AND outcome_kind_draw<>0) AS flagged_grants,
          count(*) FILTER(WHERE NOT {f}) AS sensitivity_opportunities,
          count(*) FILTER(WHERE {fair}) AS competitive,
          sum(outcome_kind_draw) FILTER(WHERE {fair})::BIGINT AS competitive_grants,
          count(*) FILTER(WHERE {fair} AND NOT {f}) AS sensitivity_competitive,
          count(*) FILTER(WHERE {lost}) AS clearly_worse,
          sum(outcome_kind_draw) FILTER(WHERE {lost})::BIGINT AS clearly_worse_grants
          FROM {source} s''').fetchdf().iloc[0].to_dict().items()}
    finally:c.close()

def original_function(path,name):
    tree=ast.parse(Path(path).read_text())
    selected=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==name]
    require(len(selected)==1,'Original producer function missing')
    namespace={'np':np,'pd':pd}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(path),'exec'),namespace)
    return namespace[name]

def reproduce(actual, expected, keys, label, tolerance=2e-8):
    require(set(actual.columns)==set(expected.columns),'Reproduction columns changed: '+label)
    a=actual.set_index(keys).sort_index();b=expected.set_index(keys).sort_index()
    require(not a.index.duplicated().any() and a.index.equals(b.index),'Reproduction keys changed: '+label)
    checks=[]
    for col in b.columns:
        if pd.api.types.is_numeric_dtype(b[col]):
            exact=pd.api.types.is_integer_dtype(b[col]) or pd.api.types.is_bool_dtype(b[col])
            ok=np.array_equal(a[col],b[col],equal_nan=True) if exact else np.allclose(a[col],b[col],rtol=tolerance,atol=tolerance,equal_nan=True)
        else:ok=a[col].fillna('<missing>').equals(b[col].fillna('<missing>'))
        checks.append({'file':label,'column':col,'status':'REPRODUCED' if ok else 'MISMATCH'})
    require(all(x['status']=='REPRODUCED' for x in checks),'Original result failed to reproduce: '+label)
    return checks

def activity_stage(auth,out,workers,memory):
    private=out/'PRIVATE';public=out/'report';private.mkdir(parents=True,exist_ok=True);public.mkdir(exist_ok=True)
    key=digest([auth['fingerprint'],sha(ROOT/'vendor/activity_original/features.py'),sha(ROOT/'vendor/activity_original/adjustment.py')])
    # Four independent monthly scans, then a ten-thread merge; no nested worker pools.
    with heartbeat('Original activity/rating aggregation'):
        feature,receipt,monthly=features.build_features(auth,private,key,min(4,workers),workers,'1.5GB',f'{max(2,memory-3)}GB')
    frame=pd.read_parquet(feature)
    require(not frame.chooser.duplicated().any() and not frame.chooser.isna().any(),'Invalid activity chooser identities')
    require(int(frame.f.sum())==auth['census']['competitive'] and int(frame.a.sum())==auth['census']['competitive_grants'], 'Activity competitive totals differ')
    require(int(frame.l.sum())==auth['census']['clearly_worse'] and int(frame.b.sum())==auth['census']['clearly_worse_grants'], 'Activity losing totals differ')
    frame=frame.loc[(frame.f>0)&(frame.l>0)].copy()
    n,both,w,inv,d=statistics.inputs(frame)
    estimates,differences,cov=statistics.estimate(d,np.column_stack((w[both],inv[both],np.ones(len(d)))))
    with heartbeat('Original common-support standardization'):
        tables=adjustment.analyze_adjustment(frame)
    del frame
    checks=[]
    if auth['variant']=='included':
        for name,t in tables.items():
            expected=pd.read_csv(ROOT/'evidence/activity_original'/name)
            # Original cell IDs are stable for the included reproduction.
            keys=KEYS[name] if name!='standardization_weights.csv' else ['scope','method','cell']
            checks+=reproduce(t,expected,keys,name)
        checks+=reproduce(estimates,pd.read_csv(ROOT/'evidence/activity_upstream/UPSTREAM_estimates.csv'),KEYS['equal_weight_estimates.csv'],'equal_weight_estimates.csv')
        contrast=differences.set_index('comparison').loc['equal_chooser_minus_original_FE']
        require(f"{contrast.estimate_pp:.3f}"=='0.646' and f"{contrast.se_pp:.3f}"=='0.009' and f"{contrast.ci_low_pp:.3f}"=='0.628' and f"{contrast.ci_high_pp:.3f}"=='0.664','Manuscript equal-weight joint contrast not reproduced')
    # Cell integers are internal ordering labels. Compare their semantic dimensions.
    cell_info=tables['joint_cell_support.csv'][['cell','rating_band','modal_speed','modal_time_control']]
    tables['standardization_weights.csv']=tables['standardization_weights.csv'].merge(cell_info,on='cell',validate='many_to_one')
    tables.update({'equal_weight_estimates.csv':estimates,'equal_weight_differences.csv':differences,
      'equal_weight_covariance.csv':pd.DataFrame([dict(row_estimator=a,column_estimator=b,covariance_pp2=float(cov[i,j]*10000)) for i,a in enumerate(statistics.LABELS) for j,b in enumerate(statistics.LABELS)])})
    for name,t in tables.items():
        require(not {'chooser','username','username_norm','game_id'}.intersection(t.columns),'Private identity in activity export')
        table(public/Path(name).stem,t.drop(columns=['cell'],errors='ignore'))
    write(public/'REPRODUCTION.json',checks)
    write(private/'SOURCE.json',{'features':record(feature),'monthly':monthly,'fingerprint':auth['fingerprint']})
    return len(checks)

def patron_stage(project,parent,variant,auth,output,workers,memory):
    root=project/'derived/replication/author_exclusion_reestimate_v100_PRIVATE'/V100['run_id']
    cfg=read(root/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==root.name and cfg['code']==V100['v100_code'] and cfg['upstream_manifest']==V100['v100_upstream'],'Original Patron configuration changed')
    stage=read(root/'PRIVATE/STAGES.json')[variant+'/patron'];require(stage['status']=='COMPLETE','Original Patron stage incomplete')
    receipt=read(verify(stage['receipt']))
    require(receipt['sample_fingerprint']==auth['fingerprint'],'Patron sample differs')
    require(receipt==read(parent/'report/stage_summaries'/variant/'patron.json'),'Patron completion receipt differs from reviewed result')
    for f in stage['aggregate_files']:verify(f)
    source=root/'PRIVATE/results'/variant/'patron'
    design=verify(read(source/'PRIVATE/design/DESIGN_DONE.json')['cache'])
    snapshot=project/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    require(sha(snapshot)=='f42f28a6540a65c0a83f0da488663b4adddf60d1001daeed556f1ffbb961e238','August profile snapshot changed')
    c=db(output/'PRIVATE/spill',memory,workers)
    try:
        missing="coalesce(trim(d.username_norm),'')='' OR coalesce(trim(d.matched_kind_chooser_id),'')=''"
        author=author_sql(('username_norm','matched_kind_chooser_id'),'d')
        n,miss,hits=c.execute(f'SELECT count(*),count(*) FILTER(WHERE {missing}),count(*) FILTER(WHERE {author}) FROM {scan(design)} d').fetchone()
        require(miss==0 and (variant=='included' or hits==0),'Author/missing identity in Patron roster')
        # Same fields and left-join semantics as the original load_frames function;
        # avoid loading unrelated design covariates merely to recompute bounds.
        frame=c.execute(f'''SELECT d.group_ever_kind_fair,d.is_kind_role,d.match_cell,d.matched_kind_chooser_id,
          coalesce(s.returned,false) AS returned,s.patron,
          CASE WHEN s.username_norm IS NULL THEN 'not_planned_in_august' WHEN NOT s.returned THEN 'queried_nonreturn' ELSE 'observed_outcome' END AS outcome_status
          FROM {scan(design)} d LEFT JOIN {scan(snapshot)} s USING(username_norm)''').fetchdf()
        require(len(frame)==n,'Patron snapshot join duplicated rows')
    finally:c.close()
    producer=original_function(ROOT/'vendor/patron/runner/run.py','missing_outcome_bounds')
    bounds=producer(frame)
    previous=read(source/'report/missing_outcome_bounds.json')
    require(digest(bounds)==digest(previous),'Recomputed Patron bounds differ from completed producer')
    primary=frame.loc[frame.group_ever_kind_fair.astype(bool)].copy()
    returned_focals=set(primary.loc[primary.is_kind_role.astype(bool)&primary.returned,'matched_kind_chooser_id'])
    primary['analysis']=primary.returned & primary.matched_kind_chooser_id.isin(returned_focals)
    rows=[]
    for label,mask in [('target',np.ones(len(primary),bool)),('missing',~primary.returned),('observed',primary.returned),('analysis',primary.analysis),('observed_excluded_group',primary.returned&~primary.analysis)]:
        for role in [0,1]:
            sub=primary.loc[mask&(primary.is_kind_role.astype(int)==role)]
            rows.append(dict(stage=label,is_kind_role=role,accounts=len(sub),observed_patrons=int(sub.patron.fillna(0).sum())))
    flow=pd.DataFrame(rows)
    expected=receipt['result']['primary']
    require(int(flow.query("stage=='analysis' and is_kind_role==1").accounts.iloc[0])==expected['primary_kind_accounts'] and int(flow.query("stage=='analysis' and is_kind_role==0").accounts.iloc[0])==expected['primary_control_accounts'],'Recomputed Patron flow differs')
    public=output/'report';public.mkdir(parents=True,exist_ok=True)
    write(public/'patron_bounds.json',bounds)
    table(public/'patron_bounds',[{'sample':'fixed_primary_target',**{k:v for k,v in bounds.items() if k!='by_cell'}}])
    table(public/'patron_bounds_by_cell',bounds['by_cell']);table(public/'patron_flow',flow)
    write(public/'PATRON_REPRODUCTION.json',dict(status='EXACT_COMPLETED_BOUNDS_REPRODUCED',fits_rerun=0,author_roster_hits=hits,missing_identity_rows=miss))
    write(output/'PRIVATE/SOURCE.json',{'design':record(design),'snapshot':record(snapshot),'original_bounds':record(source/'report/missing_outcome_bounds.json')})

def semantic_comparison(a,b,keys,name,family):
    require(set(a.columns)==set(b.columns),'Comparison columns differ: '+name)
    a=a.copy();b=b.copy()
    for k in keys:a[k]=a[k].astype('string').fillna('<missing>');b[k]=b[k].astype('string').fillna('<missing>')
    require(not a.duplicated(keys).any() and not b.duplicated(keys).any(),'Duplicate comparison keys: '+name)
    m=a.merge(b,on=keys,how='outer',suffixes=('_included','_excluded'),indicator=True,validate='one_to_one')
    result=[]
    pairs={'estimate_pp':'se_pp','absolute_gap_difference_pp':'absolute_difference_se_pp','gap_difference_change_pp':'gap_difference_change_se_pp',
           'log_ratio_of_risk_ratios':'log_ratio_se','log_ror_change':'log_ror_change_se'}
    for metric in a.columns:
        if metric.endswith('_rate_pct'):pairs[metric]=metric.replace('_pct','_se_pct')
    pairs['gap_pp']='gap_se_pp'
    for _,r in m.iterrows():
        key=json.dumps({k:str(r[k]) for k in keys},sort_keys=True)
        if r['_merge']!='both':
            result.append(dict(family=family,file=name,key=key,metric='ROW_MEMBERSHIP',status=str(r['_merge'])));continue
        for col in set(a.columns)-set(keys):
            x=r[col+'_included'];y=r[col+'_excluded']
            if isinstance(x,(str,bool,np.bool_)) or isinstance(y,(str,bool,np.bool_)):
                if str(x)!=str(y):result.append(dict(family=family,file=name,key=key,metric=col,status='TEXT_OR_SUPPORT_CHANGED',included_text=str(x),excluded_text=str(y)))
                continue
            if pd.isna(x) or pd.isna(y):
                if pd.isna(x)!=pd.isna(y):result.append(dict(family=family,file=name,key=key,metric=col,status='FINITE_SUPPORT_CHANGED'))
                continue
            row=dict(family=family,file=name,key=key,metric=col,status='MATCHED',included=float(x),excluded=float(y),change=float(y-x))
            se=pairs.get(col)
            if se and se in a.columns:
                sx=r[se+'_included'];sy=r[se+'_excluded']
                row.update(included_se=float(sx),excluded_se=float(sy),sign_changed=bool(x*y<0))
                if np.isfinite(sx) and sx>0:row['absolute_change_in_included_se_units']=abs(y-x)/sx
                if np.isfinite(sx) and np.isfinite(sy):row['crosses_approx_95pct_zero_boundary']=bool((abs(x)>1.96*sx)!=(abs(y)>1.96*sy))
            result.append(row)
    return result

def checkpoint(run,destination,percent,start,eta):
    write(run/'report/RUNTIME_ESTIMATE.json',dict(percent=percent,elapsed_minutes=(time.monotonic()-start)/60,remaining_minutes=eta))
    rows=[dict(file=str(p.relative_to(run/'report')),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted((run/'report').rglob('*')) if p.is_file() and p!=run/'report/REPORT_HASHES.json']
    write(run/'report/REPORT_HASHES.json',rows);destination.mkdir(parents=True,exist_ok=True)
    target=destination/f'AUTHOR_EXCLUSION_PROSE_{run.name}_{percent:03d}.zip';tmp=target.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((run/'report').rglob('*')):
            if p.is_file():z.write(p,'report/'+str(p.relative_to(run/'report')))
    tmp.replace(target);target.with_suffix('.zip.sha256').write_text(sha(target)+'  '+target.name+'\n')
    log(f'CHECKPOINT {percent}%: {target}; expected remaining {eta[0]}–{eta[1]} minutes')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--result-dir',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    p.add_argument('--estimate-only',action='store_true');a=p.parse_args()
    if a.estimate_only:print('Planning ETA 5–15 minutes (slower external drives may take 20–30). Four scan workers, ten merge threads; existing 20 analysis families retained.');return 0
    verify_package();a.project=a.project.expanduser().resolve()
    require(a.project.is_dir() and 1<=a.workers<=10 and a.memory_gb>=8,'Use available project, 1–10 workers and at least 8 GiB')
    require(shutil.disk_usage(a.project).free>=6*2**30,'At least 6 GiB free for aggregate Parquets and spill')
    config=dict(version='1.4.3',parent=REVIEWED,package_sha256=sha(ROOT/'PACKAGE_MANIFEST.sha256'),versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__))
    run=a.project/'derived/replication/author_exclusion_prose_v143_PRIVATE'/digest(config)[:16]
    (run/'PRIVATE').mkdir(parents=True,exist_ok=True);(run/'report').mkdir(exist_ok=True)
    lock=(run/'RUNNING.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    locks=[];start=time.monotonic()
    try:
        for family,runid in [('author_exclusion_persistence_v142_PRIVATE',REVIEWED['run_id']),('author_exclusion_repair_v141_PRIVATE',PARENT['run_id']),('author_exclusion_reestimate_v100_PRIVATE',V100['run_id'])]:
            f=(a.project/'derived/replication'/family/runid/'RUNNING.lock').open('a+');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);locks.append(f)
        write(run/'PRIVATE/CONFIG.json',config)
        write(run/'report/CLAIM_STATUS.json',dict(all_analyses_excluded=False,no_substantive_difference_established=False,status='PROSE_CHECKS_PENDING'))
        checkpoint(run,a.result_dir,0,start,[5,15])
        parent,auths,stamps=authenticate(a.project,a.workers)
        shutil.copytree(parent/'report',run/'report/retained_v142',dirs_exist_ok=True)
        checkpoint(run,a.result_dir,25,start,[3,12])
        for v,percent in [('included',50),('excluded',75)]:
            out=run/'PRIVATE/results'/v;receipt=out/'DONE.json'
            key=digest([config,auths[v]['fingerprint']])
            if receipt.exists():
                saved=read(receipt);require(saved['key']==key,'Prose checkpoint contract changed')
                for f in saved['files']:verify(f)
                log('Verified completed prose checks retained: '+v)
            else:
                out.mkdir(parents=True,exist_ok=True)
                log(v+': material count, activity standardization and bounds; expected 1–5 minutes')
                m=material_counts([r['path'] for r in auths[v]['month_records']],out/'PRIVATE/material_spill',a.workers,max(2,a.memory_gb-3))
                require(m['missing_id']==m['missing_flag']==m['flagged_grants']==m['flagged_outside_competitive']==0,'Material-screen identity/definition audit failed')
                require(m['author_games']==(42 if v=='included' else 0),'Unexpected author-game count')
                require(m['opportunities']==auths[v]['census']['opportunities'] and m['grants']==auths[v]['census']['grants'],'Material census differs')
                if v=='included':require(m['flagged']==20902 and m['sensitivity_opportunities']==41513429 and m['sensitivity_competitive']==15186521,'Published material-screen counts not reproduced')
                m.update(competitive_rate_pct=100*m['competitive_grants']/m['sensitivity_competitive'],worse_rate_pct=100*m['clearly_worse_grants']/m['clearly_worse'])
                m.update(raw_gap_pp=m['competitive_rate_pct']-m['worse_rate_pct'],risk_ratio=m['competitive_rate_pct']/m['worse_rate_pct'])
                table(out/'report/material_screen',[m])
                checks=activity_stage(auths[v],out/'activity_adjustment',a.workers,a.memory_gb)
                patron_stage(a.project,parent,v,auths[v],out/'patron_bounds',a.workers,max(2,a.memory_gb-3))
                files=[record(f) for f in out.rglob('*') if f.is_file() and 'report' in f.relative_to(out).parts]
                write(receipt,{'key':key,'files':files,'activity_reproduction_checks':checks})
            dest=run/'report/new_tables'/v
            for f in out.rglob('*'):
                if f.is_file() and 'report' in f.relative_to(out).parts:
                    target=dest/f.relative_to(out);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f,target)
            checkpoint(run,a.result_dir,percent,start,[2,8] if v=='included' else [0,2])
        for path,stamp in stamps.items():require(signature(path)==stamp,'Panel changed during prose checks')
        rows=[]
        for file in sorted((run/'report/new_tables/included').rglob('*.csv')):
            rel=file.relative_to(run/'report/new_tables/included');b=run/'report/new_tables/excluded'/rel
            keys=KEYS[file.name] if file.name!='material_screen.csv' else []
            x=pd.read_csv(file);y=pd.read_csv(b)
            if not keys:x=x.assign(sample='material_screen');y=y.assign(sample='material_screen');keys=['sample']
            rows+=semantic_comparison(x,y,keys,str(rel),str(rel.parts[0]))
        fresh=pd.DataFrame(rows);fresh.to_parquet(run/'report/prose_before_after.parquet',index=False,compression='zstd')
        old=pd.read_parquet(parent/'report/before_after.parquet')
        combined=pd.concat([old,fresh],ignore_index=True);combined.to_parquet(run/'report/combined_before_after.parquet',index=False,compression='zstd')
        review=dict(status='COMPLETED_REVIEW_REQUIRED',original_families_retained=20,regression_fits_rerun=0,
            new_checks=['material_screen','activity_rating_standardization','equal_weight_joint_contrasts','patron_missing_outcome_bounds'],
            new_numeric_metrics=int((fresh.status=='MATCHED').sum()),new_support_or_status_changes=int((fresh.status!='MATCHED').sum()),
            combined_maximum_se_change=float(combined.absolute_change_in_included_se_units.max()),
            combined_sign_changes=int(combined.sign_changed.fillna(False).astype(bool).sum()),
            combined_approx95_boundary_changes=int(combined.crosses_approx_95pct_zero_boundary.fillna(False).astype(bool).sum()),
            elapsed_minutes=(time.monotonic()-start)/60)
        write(run/'report/EXECUTION_STATUS.json',review)
        write(run/'report/CLAIM_STATUS.json',dict(all_requested_prose_checks_finished=True,original_twenty_families_retained=True,
            all_analyses_excluded=False,no_substantive_difference_established=False,manuscript_numerical_reconciliation_complete=False,
            review_required=True,reason='Review these exact prose-level checks and finish manuscript reconciliation; the v142 family-level boolean was too broad.'))
        checkpoint(run,a.result_dir,100,start,[0,0]);return 0
    except BaseException as e:
        import traceback
        write(run/'report/EXECUTION_STATUS.json',dict(status='BLOCKED',error=str(e),traceback=traceback.format_exc(),elapsed_minutes=(time.monotonic()-start)/60))
        write(run/'report/CLAIM_STATUS.json',dict(all_analyses_excluded=False,status='BLOCKED',review_required=True))
        checkpoint(run,a.result_dir,0,start,[0,0]);raise
    finally:
        for f in locks:f.close()
        lock.close()

if __name__=='__main__':sys.exit(main())
