"""Authenticate existing narrow caches; optional certified policy adapter."""
from io_utils import *
import sys
sys.path.insert(0,str(ROOT/'vendor'))
from common import check_payoffs

def validate_rows(d):
    """Validate the shared scientific fields, without aggregating outcomes."""
    if not len(d):return 0.
    if d[['game_id','chooser','t','y','month','speed','color']].isna().any().any():
        raise RuntimeError('Null identifier, timestamp, or category')
    if not d.y.isin([0,1]).all() or not d.color.isin(['white','black']).all():
        raise RuntimeError('Invalid outcome/color encoding')
    if not d.speed.isin(['ultrabullet','bullet','blitz','rapid','classical']).all():
        raise RuntimeError('Unknown speed')
    numeric=['t','cp','ply','rating','opp_rating','g','rd','opp_rd','rg','rc','ki','kj',
             'history_days','prior_starts','inactivity_days','opp_prior_starts']
    if not np.isfinite(d[numeric].to_numpy(float)).all():raise RuntimeError('Nonfinite required numeric value')
    if not (d.t.to_numpy()==d.t.to_numpy().astype(np.int64)).all():raise RuntimeError('t must be integer Unix milliseconds')
    if not (pd.to_datetime(d.t,unit='ms',utc=True).dt.strftime('%Y-%m').to_numpy()==d.month.astype(str).to_numpy()).all():
        raise RuntimeError('Timestamp/month mismatch')
    if np.max(abs(d.g-(d.opp_rating-d.rating)))>1e-8:raise RuntimeError('Gap/rating identity failed')
    if (d[['history_days','prior_starts','inactivity_days','opp_prior_starts']]<0).any().any():
        raise RuntimeError('Negative history')
    return check_payoffs(d)

def cache_tasks(project,work,memory_mb):
    ledger=pd.read_csv(ROOT/'authority/input_checksums.csv')
    found={}
    for row in ledger.to_dict('records'):
        path=str(row['path'])
        if '/mechanism_separation_v100_PRIVATE/analysis/' not in path or not path.endswith('.parquet'):continue
        month=Path(path).stem
        if month in found and found[month]['sha256']!=row['sha256']:raise RuntimeError('Contradictory source ledger')
        found[month]=row
    expected=[str(x) for x in pd.period_range('2023-11','2025-10',freq='M')]
    if sorted(found)!=expected:raise RuntimeError('Audited pre-policy monthly ledger incomplete')
    return [(str(remap(found[m]['path'],project)),found[m]['sha256'],m,str(work),memory_mb) for m in expected]

def prepare_month(task):
    source,expected,month,work,memory=task;work=Path(work)
    identity=auth(source,work,expected);p=work/'pre'/f'{month}.parquet'
    key=digest(dict(version=VERSION,source=identity,predicate='regular AND state=equal AND both RD<=110'))
    old=reusable(p,key)
    if old:return old
    c=connect(work/'tmp'/('prepare_'+month),1,memory)
    try:
        cols=set(pq.ParquetFile(source).schema_arrow.names)
        if not set(REQUIRED+('regular','state'))<=cols:raise RuntimeError('Unexpected mechanism schema: '+month)
        select=','.join('"'+x+'"' for x in REQUIRED)
        copy(c,f'SELECT {select} FROM {scan(source)} WHERE regular IS TRUE AND state=\'equal\' AND rd<=110 AND opp_rd<=110',p)
        n,u,grants,bad=c.execute(f'''SELECT count(*),count(DISTINCT game_id),coalesce(sum(y),0),count(*) FILTER(WHERE
          chooser IS NULL OR t IS NULL OR y NOT IN(0,1) OR color NOT IN('white','black') OR
          cp < -100 OR cp>=100 OR ply<=10 OR g < -575 OR g>=575 OR rd<=0 OR opp_rd<=0)
          FROM {scan(p)}''').fetchone()
        if n!=u or bad:raise RuntimeError('Invalid capped source rows: '+month)
        err=0.
        for batch in pq.ParquetFile(p).iter_batches(batch_size=100000):err=max(err,validate_rows(batch.to_pandas()))
        if stamp(source)!=identity['stamp']:raise RuntimeError('Source changed during capped projection: '+month)
        r=receipt(p,key,month=month,rows=n,grants=int(grants),payoff_error=err)
        log(f'{month}: reused upstream cache; {n:,} capped regular opportunities');return r
    finally:c.close()

def combine_pre(work,workers,memory_mb):
    work=Path(work);ps=sorted((work/'pre').glob('????-??.parquet'));p=work/'capped_training.parquet'
    key=digest([read(x.with_suffix('.json'))['output']['sha256'] for x in ps])
    if reusable(p,key):return p
    c=connect(work/'tmp/combine',workers,memory_mb)
    try:
        copy(c,f'SELECT * FROM {scan(ps)} ORDER BY chooser,t,game_id',p)
        n,g,u=c.execute(f'SELECT count(*),sum(y),count(DISTINCT chooser) FROM {scan(p)}').fetchone()
        if (n,int(g),u)!=(3236219,58298,778048):raise RuntimeError('Capped training counts differ from the repaired audit')
        receipt(p,key,rows=n,grants=int(g),accounts=u);return p
    finally:c.close()

def dependencies(project,work,explicit=None):
    """A bounded inventory. It does not construct or invent certifications."""
    project=Path(project);p=Path(explicit) if explicit else project/'derived/replication_36m/mechanism_color_inputs_v100/manifest.json'
    result=dict(manifest_path=str(p),exists=p.is_file(),actual_cohort_ready=False,
        missing=['Certified post-policy pool/observed-nonadjacency and fixed regular cohort',
                 'Actual capped-stratum calibration review','Source-supported censor timestamp'],
        note='Existing data availability is not sample certification. No all-source substitution.',cache_inventory=[])
    for m in ('2025-11','2025-12','2026-01'):
        dose=project/'derived/replication_36m/color_change_firstpass_v100/dose'/f'month={m}'/'opportunities.parquet'
        r=dict(month=m,dose_exists=dose.exists())
        if dose.exists():
            pf=pq.ParquetFile(dose);r.update(rows=pf.metadata.num_rows,columns=pf.schema_arrow.names)
        result['cache_inventory'].append(r)
    if p.exists():result['missing']=['Manifest exists; its evidence and scope have not yet passed the adapter']
    write(Path(work)/'dependency_inventory.json',result);return result

def policy_input(path,work,threads,memory_mb):
    """Accept an evidence-backed V1/V2 manifest; never manufacture one."""
    path=Path(path);m=read(path);version=m.get('format')
    if version not in ('MECHANISM_COLOR_INPUTS_V1','MECHANISM_COLOR_INPUTS_V2'):raise RuntimeError('Unrecognized policy manifest')
    for k in ('pool_and_previous_adjacency_certified','cohort_uses_only_preimplementation_information',
              'actual_stratum_calibration_reviewed','missing_clock_and_material_rules_aligned'):
        if m.get(k) is not True:raise RuntimeError('Unresolved policy evidence: '+k)
    # These explicit scope additions are required for either legacy V1 or V2.
    if m.get('calibration_rd_cap')!=110:raise RuntimeError('Calibration review must cover both-player RD<=110')
    if m.get('payoff_convention')!='anchored_novol_noreg_old_formula':
        raise RuntimeError('Policy payoffs must use the audited old-formula anchored convention')
    freeze=pd.Timestamp(m['cohort_information_cutoff_utc'])
    if freeze.tzinfo is None or int(freeze.timestamp()*1000)>IMPLEMENTED:
        raise RuntimeError('Cohort information cutoff must be timezone-aware and no later than implementation')
    def resolve(v):
        p=Path(v);return p if p.is_absolute() else path.parent/p
    evidence={}
    for k in ('producer_receipt','calibration_review','censor_source'):
        r=m[k];evidence[k]=auth(resolve(r['path']),work,r['sha256'])
    censor=int(pd.Timestamp(m['censor_utc']).timestamp()*1000)
    if censor<=IMPLEMENTED:raise RuntimeError('Censor precedes the policy')
    if pd.Timestamp(m['censor_utc']).tzinfo is None:raise RuntimeError('Censor needs an explicit timezone')
    through=str(m.get('chronology_through',''))
    if through<pd.to_datetime(censor-1,unit='ms',utc=True).strftime('%Y-%m'):raise RuntimeError('Chronology does not cover target censor')
    files=[];source_identities={}
    for r in m['files']:
        p=resolve(r['path']);source_identities[str(p)]=auth(p,work,r['sha256'],r['rows']);files.append(p)
        missing=set(REQUIRED+('fixed_regular_cohort','pool_main'))-set(pq.ParquetFile(p).schema_arrow.names)
        if missing:raise RuntimeError('Policy columns missing: '+','.join(sorted(missing)))
    if not files:raise RuntimeError('Empty policy manifest')
    coverage_start=m.get('coverage_start_utc')
    coverage_end=m.get('coverage_end_utc')
    if not coverage_start or not coverage_end:raise RuntimeError('Explicit source coverage_start_utc/coverage_end_utc required; do not infer complete weeks from observed events')
    if pd.Timestamp(coverage_start).tzinfo is None or pd.Timestamp(coverage_end).tzinfo is None:
        raise RuntimeError('Coverage bounds need explicit timezones')
    lo=int(pd.Timestamp(coverage_start).timestamp()*1000);hi=int(pd.Timestamp(coverage_end).timestamp()*1000)
    if lo>=IMPLEMENTED or hi<censor:raise RuntimeError('Policy coverage does not include complete requested interval')
    out=Path(work)/'actual_target.parquet';key=digest(dict(manifest=sha(path),evidence=evidence,censor=censor,version=VERSION))
    if not reusable(out,key):
        c=connect(Path(work)/'tmp/actual',threads,memory_mb)
        try:
            duplicate=c.execute(f'SELECT count(*)-count(DISTINCT game_id) FROM {scan(files)}').fetchone()[0]
            if duplicate:raise RuntimeError('Duplicate policy IDs across source files')
            copy(c,f'''SELECT {','.join('"'+x+'"' for x in REQUIRED)} FROM {scan(files)}
              WHERE fixed_regular_cohort IS TRUE AND pool_main IS TRUE AND cp>=-100 AND cp<100
              AND ply>10 AND g>=-575 AND g<575 AND rd<=110 AND opp_rd<=110 AND t>={lo} AND t<{censor}
              ORDER BY chooser,t,game_id''',out)
            if not pq.ParquetFile(out).metadata.num_rows:raise RuntimeError('Empty actual policy target')
            for batch in pq.ParquetFile(out).iter_batches(batch_size=100000):
                validate_rows(batch.to_pandas())
            for source in files:
                if stamp(source)!=source_identities[str(source)]['stamp']:raise RuntimeError('Policy source changed during projection')
            receipt(out,key,coverage_start_ms=lo,censor_ms=censor)
        finally:c.close()
    return dict(path=str(out),coverage_start_ms=lo,coverage_end_ms=censor,manifest_sha256=sha(path),
                actual_cohort_ready=True,evidence=evidence)
