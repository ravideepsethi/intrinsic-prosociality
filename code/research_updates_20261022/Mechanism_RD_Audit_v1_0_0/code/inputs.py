"""Read the completed mechanism cache; never rebuild history or rating states."""
from common import *
from model_utils import FOLDS

COHORTS=('original','rd110')
STATES=('equal','losing')
def eligibility(state,cohort):
    return "regular IS TRUE AND state="+q(state)+( " AND rd<=110 AND opp_rd<=110" if cohort=='rd110' else '')

def authenticate_source(source,work,reference):
    source,work=Path(source),Path(work)
    identity=read(source/'RUN_IDENTITY.json')
    if identity.get('package_sha256')!=reference['source_package_sha256']:
        raise RuntimeError('Completed mechanism cache has a different package identity')
    paths=[];ledger=[]
    for month in MONTHS:
        p=source/'analysis'/(month+'.parquet');r=read(p.with_suffix('.json'))
        a=auth(p,work,r['output']['sha256'],size=r['output']['size'])
        ledger.append(dict(path=str(p),sha256=a['sha256'],bytes=p.stat().st_size));paths.append(p)
    missing={'game_id','chooser','opponent','t','month','state','regular','y','rd','opp_rd','ki','kj','rg','rc','g','history_days','prior_starts','inactivity_days','opp_prior_starts'}-cols(paths[0])
    if missing:raise RuntimeError('Prepared cache schema missing: '+str(sorted(missing)))
    return paths,ledger

def rd_bin(field):
    return f"CASE WHEN {field}<45.01 THEN 'floor' WHEN {field}<60 THEN '45.01_to_60' WHEN {field}<=110 THEN '60_to_110' WHEN {field}<200 THEN '110_to_200' ELSE '200_plus' END"

def prepare_state(paths,state,work,report,key,threads=8,memory_mb=6144):
    work,report=Path(work),Path(report);base=work/'prepared'/state
    receipt=base/'PREPARED.json'
    if receipt.exists():
        r=read(receipt)
        if r['key']!=key:raise RuntimeError('Prepared audit inputs changed')
        for f in r['files']:auth(f['path'],work,f['sha256'],size=f['bytes'])
        log(state+': reusing prepared conditional histories and validation groups')
        return r
    base.mkdir(parents=True,exist_ok=True)
    c=connect(work/'tmp'/state,threads,memory_mb)
    result=dict(key=key,state=state,cohorts={},files=[])
    def export(sql,name):
        p=base/(name+'.parquet');copy(c,sql,p)
        result['files'].append(dict(path=str(p),sha256=sha(p),bytes=p.stat().st_size))
        return str(p)
    support=[];monthly=[];rdrows=[];gaprows=[];costsupport=[]
    try:
        for cohort in COHORTS:
            c.execute(f'CREATE OR REPLACE VIEW d AS SELECT * FROM {scan(paths)} WHERE {eligibility(state,cohort)}')
            row=c.execute('SELECT count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) accounts,count(DISTINCT game_id) games FROM d').fetchdf().iloc[0]
            if row.n!=row.games:raise RuntimeError('Duplicate game keys in '+state+'/'+cohort)
            if row.n==0:raise RuntimeError('No eligible rows for '+state+'/'+cohort)
            meta=dict(n=int(row.n),grants=int(row.grants or 0),accounts=int(row.accounts))
            bad=c.execute("SELECT count(*) FROM d WHERE y IS NULL OR y NOT IN (0,1) OR rd IS NULL OR opp_rd IS NULL OR NOT isfinite(rd+opp_rd+ki+kj+rg+rc) OR rd<45 OR opp_rd<45 OR ki<=0 OR kj<=0 OR abs(g-(opp_rating-rating))>1e-8").fetchone()[0]
            if bad:raise RuntimeError('Invalid cached analysis rows')
            summary=c.execute("""SELECT count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,
                avg(y)*100 base_rate_pp,avg((rd<45.01)::INTEGER) own_rd_floor_share,
                quantile_cont(ki,[.01,.1,.25,.5,.75,.9,.95,.99,.999]) ki_quantiles,
                max(ki) ki_max,max(abs(rg)) abs_rg_max,max(rd) own_rd_max,max(opp_rd) opponent_rd_max
                FROM d""").fetchdf().iloc[0].to_dict()
            summary.update(state=state,cohort=cohort);support.append(summary)
            for sql,collection in [
              ("SELECT month,count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers FROM d GROUP BY month ORDER BY month",monthly),
              (f"SELECT {rd_bin('rd')} own_rd_bin,{rd_bin('opp_rd')} opponent_rd_bin,count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,avg(ki) mean_ki,quantile_cont(ki,.99) p99_ki,max(ki) max_ki,avg(abs(rg)) mean_abs_rg,max(abs(rg)) max_abs_rg FROM d GROUP BY ALL",rdrows),
              ("SELECT floor((g+25)/50)*50 gap_bin,count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers FROM d GROUP BY gap_bin ORDER BY gap_bin",gaprows)]:
                x=c.execute(sql).fetchdf();x['state']=state;x['cohort']=cohort;collection.extend(x.to_dict('records'))
            for window,where in [('exact_tie','g=0'),('near_tie_25','abs(g)<=25')]:
                x=c.execute(f"""WITH z AS (SELECT * FROM d WHERE {where}),
                    v AS (SELECT *,count(*) OVER(PARTITION BY chooser) ct FROM z)
                    SELECT count(*) n,sum(y)::BIGINT grants,count(DISTINCT chooser) choosers,
                      quantile_cont(ki,.25) ki_q25,quantile_cont(ki,.5) ki_median,quantile_cont(ki,.75) ki_q75,
                      quantile_cont(kj,.25) kj_q25,quantile_cont(kj,.5) kj_median,quantile_cont(kj,.75) kj_q75
                    FROM v WHERE ct>=2""").fetchdf().iloc[0].to_dict()
                x.update(state=state,cohort=cohort,window=window,frame='Repeated choosers within this near-tie window');costsupport.append(x)
            cohortdata=dict(meta=meta,folds=[])
            clause='QUALIFY sum(y) OVER(PARTITION BY chooser)>0 AND sum(y) OVER(PARTITION BY chooser)<count(*) OVER(PARTITION BY chooser)'
            cohortdata['fit_full']=export(f'SELECT * FROM d {clause} ORDER BY chooser,t,game_id',cohort+'_fit_full')
            for fold,(end,start,stop) in enumerate(FOLDS):
                train=c.execute(f'SELECT count(*) n,count(DISTINCT chooser) accounts,sum(y)::BIGINT grants FROM d WHERE month<={q(end)}').fetchdf().iloc[0].to_dict()
                train_path=export(f'SELECT * FROM d WHERE month<={q(end)} {clause} ORDER BY chooser,t,game_id',cohort+f'_fit_fold{fold}')
                testwhere=f'month>={q(start)} AND month<={q(stop)}'
                testmeta=c.execute(f"""WITH g AS (SELECT month,chooser,count(*) n,sum(y) sy FROM d WHERE {testwhere} GROUP BY month,chooser)
                    SELECT month,sum(n)::BIGINT AS "rows",sum(sy)::BIGINT grants,count(*) chooser_months,
                      sum((sy>0 AND sy<n)::INTEGER)::BIGINT informative_groups,
                      sum(CASE WHEN sy>0 AND sy<n THEN n ELSE 0 END)::BIGINT informative_rows
                    FROM g GROUP BY month ORDER BY month""").fetchdf().to_dict('records')
                test_path=export(f'''SELECT * FROM d WHERE {testwhere}
                    QUALIFY sum(y) OVER(PARTITION BY chooser,month)>0
                      AND sum(y) OVER(PARTITION BY chooser,month)<count(*) OVER(PARTITION BY chooser,month)
                    ORDER BY chooser,month,t,game_id''',cohort+f'_test_fold{fold}')
                cohortdata['folds'].append(dict(fold=fold,train_end=end,test_start=start,test_end=stop,
                    train_path=train_path,test_path=test_path,train_meta=train,test_meta=testmeta))
            if cohort=='rd110':
                cohortdata['standardization']=export('SELECT * FROM d ORDER BY hash(game_id),game_id LIMIT 100000','common_rd110_standardization')
            result['cohorts'][cohort]=cohortdata
        # Quantify how trimming changes the identifying account population.
        x=c.execute(f'''WITH a AS (SELECT chooser,count(*) n,sum(y) sy,
            count(*) FILTER(WHERE rd<=110 AND opp_rd<=110) retained_n,
            coalesce(sum(y) FILTER(WHERE rd<=110 AND opp_rd<=110),0) retained_grants
            FROM {scan(paths)} WHERE {eligibility(state,'original')} GROUP BY chooser)
            SELECT count(*) choosers,
              sum((retained_n>0 AND retained_n<n)::INTEGER) choosers_with_retained_and_removed_rows,
              sum((sy>0 AND sy<n)::INTEGER) original_switchers,
              sum((retained_grants>0 AND retained_grants<retained_n)::INTEGER) retained_switchers,
              sum((sy>0 AND sy<n AND NOT(retained_grants>0 AND retained_grants<retained_n))::INTEGER) lost_switchers
            FROM a''').fetchdf()
        x['state']=state;table(x,report/(state+'_account_retention.parquet'))
        for name,rows in [('support',support),('monthly_counts',monthly),('RD_cells',rdrows),('gap_support',gaprows),('near_tie_normalization_support',costsupport)]:
            table(rows,report/(state+'_'+name+'.parquet'))
        write(receipt,result);log(state+': cached rows prepared; no upstream stage run')
        return result
    finally:c.close()
