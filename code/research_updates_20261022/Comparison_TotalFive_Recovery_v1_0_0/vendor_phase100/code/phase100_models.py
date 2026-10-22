"""Projected reads, checked FE calculation and phase-independent score caches."""
from phase100_common import *
import env_numerics
import bounded_absorption, bounded_primary, bounded_secondary, bounded_entry
import checkpoint_secondary as secondary
import checkpoint_reporting as old_report
import entry_common
import entry_models
import phase100_report as reporting
import performance_cache as cache
from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
import multiprocessing as mp
from performance_runtime import invoke

PRIMARY_COLUMNS=list(dict.fromkeys(entry_common.MODEL_COLUMNS+['y','reached','complete90','outcome_gid']))
SECONDARY_COLUMNS=list(dict.fromkeys([x for x in entry_common.MODEL_COLUMNS if x not in ENTRY_COLUMNS]+entry_common.COMP_COLUMNS+['y','reached']))

@contextlib.contextmanager
def checked_solver(audit_path=None, owned=False):
    """Adapt the validated solver without changing vendored sources or cache hashes."""
    original=num.absorb;audits=[]
    def checked(matrix,groups,tol=1e-10,max_iter=1000):
        def emit(row):
            if audit_path is not None:io.js(Path(audit_path),row)
        solver=bounded_absorption if owned else env_numerics
        a,diag=solver.absorb(matrix,groups,tol,max_iter,publish=emit)
        audits.append(diag)
        return a,diag['iterations']
    num.absorb=checked
    try:yield audits
    finally:num.absorb=original


def primary_job(job):
    threads_one();path=Path(job['output'])
    def build(tmp):
        names=pq.ParquetFile(job['sample']).schema_arrow.names
        columns=[k for k in PRIMARY_COLUMNS if k in names]
        d=arrays(io.read(job['sample'],columns));spec=SPECS[job['family']]
        with checked_solver(path.parent.parent/'numerical_progress'/(path.name+'.json'),owned=True) as audits:
            r=bounded_primary.estimate(d,spec)
        r.update(cohort=job['cohort'],sample_accounting=stats.describe(d),numerics=audits)
        for row in r['estimates']:
            row.update(cohort=job['cohort'],phase_percent=75,interim_only=True,abstract_gate_cleared=False)
        io.js(tmp/'result.json',r);return dict(rows=len(d['row_id']))
    return stable_stage(path,job['conf'],build,[job['sample']])[1]


def competitive_prepare(split,scores,root,conf,memory,family):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1);support=[]
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scores))
            if c.execute('SELECT count(*)-count(DISTINCT row_id) FROM s').fetchone()[0]:raise RuntimeError('Duplicate competitive scores')
            for cohort in COHORTS:
                src=split/(family+'_'+cohort+'.parquet');c.execute('CREATE OR REPLACE VIEW d AS SELECT * FROM '+io.parq([src]))
                total=c.execute('SELECT count(*) FROM d').fetchone()[0]
                if c.execute('SELECT count(*) FROM d JOIN s USING(row_id)').fetchone()[0]!=total:raise RuntimeError('Missing competitive scores')
                good='comp_n_7d>=5 AND isfinite(comp_adjusted_7d) AND isfinite(comp_expected_7d)'
                # Keep a narrow, deterministic physical model table; factual caches are unchanged.
                cols=[k for k in entry_common.MODEL_COLUMNS if k not in ENTRY_COLUMNS or family=='entry']
                if family=='ordinary':cols+=['y','reached']
                fields=','.join('d.'+x for x in cols)+',s.* EXCLUDE(row_id)'
                n=io.copy(c,'SELECT '+fields+' FROM d JOIN s USING(row_id) WHERE '+good+' ORDER BY d.row_id',tmp/(cohort+'.parquet'))
                support.append(dict(cohort=cohort,input_rows=total,competitive_supported_n=n,excluded=total-n))
            cutoff=io.load(ENTRY/'evidence/secondary_scale.json')['upper_5pct_raw_competitive_cutoff']
            io.js(tmp/'support.json',support)
            io.js(tmp/'scale.json',dict(comp_reference_SD=secondary.COMP_REFERENCE_SD,pooled_reference_SD=stats.REFERENCE_SD,
                upper_5pct_raw_competitive_cutoff=cutoff,cutoff_fitted_on='completed 25% ordinary cohort; fixed before 50% and 75% estimation',
                trimming_rule='retain score <= frozen cutoff; ties retained; refit controls',scores_author_clean=True))
            return dict(support=support,tail_cutoff=cutoff)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,scores+[split/(family+'_'+s+'.parquet') for s in COHORTS]+[ENTRY/'evidence/secondary_scale.json'])


def secondary_job(job):
    threads_one();path=Path(job['output'])
    def build(tmp):
        d=arrays(io.read(job['input'],SECONDARY_COLUMNS))
        if job['tail']=='exclude_above_95pct':
            use=d['comp_adjusted_7d']<=job['cutoff'];d={k:v[use] for k,v in d.items()}
        with checked_solver(path.parent.parent/'numerical_progress'/(path.name+'.json'),owned=True) as audits:
            rows=bounded_secondary.estimate(d,job['family'],job['cohort'],job['tail'])
        io.js(tmp/'result.json',dict(estimates=rows,numerics=audits));return dict(rows=len(d['row_id']))
    return stable_stage(path,job['conf'],build,[job['input']])[1]


def entry_comp_job(job):
    threads_one();path=Path(job['output'])
    def build(tmp):
        d=arrays(io.read(job['input'],entry_common.MODEL_COLUMNS+entry_common.COMP_COLUMNS))
        with checked_solver(path.parent.parent/'numerical_progress'/(path.name+'.json'),owned=True) as audits:
            result=bounded_entry.estimate(d,job['cohort'],'competitive_supported',job['cutoff'])
        result['numerics']=audits
        # Earlier row IDs are rebound in 75%, so compare counts and estimates after the feature bridge.
        if job['cohort'] in ('new_phase50','old_author_clean'):
            targets=io.load(RELEASE/'evidence/completed50/competitive_entry_estimates.json')
            bridges=[]
            for t in targets:
                if t.get('cohort')!=job['cohort'] or t.get('sample')!='competitive_supported':continue
                got=next(r for r in result['estimates'] if all(r.get(k)==t.get(k) for k in ('instrument','control_level','outcome')))
                for k in ('n','events','supported'):
                    if got.get(k)!=t.get(k):raise RuntimeError('Earlier competitive entry counts changed: '+k)
                if t.get('supported'):
                    for k in ('coefficient_pp','standard_error_pp'):
                        if not np.isclose(got[k],t[k],rtol=2e-7,atol=2e-9):raise RuntimeError('Earlier competitive entry estimate changed: '+k)
                bridges.append(dict(instrument=t['instrument'],control_level=t['control_level'],outcome=t['outcome'],reproduced=True))
            if not bridges:raise RuntimeError('No earlier competitive entry targets')
            result['bridge']=bridges
        io.js(tmp/'result.json',result);return dict(rows=len(d['row_id']))
    return stable_stage(path,job['conf'],build,[job['input'],RELEASE/'evidence/completed50/competitive_entry_estimates.json'])[1]


def fit_map(fn,jobs,runtime,workers,memory,label,report):
    # Small physical model tables and contiguous FE arrays avoid loading the wide feature tables.
    jobs=sorted(jobs,key=lambda j:j['memory_estimate_gb'],reverse=True);budget=memory-1.5
    if jobs and max(j['memory_estimate_gb'] for j in jobs)>budget:
        need=max(j['memory_estimate_gb'] for j in jobs)+1.5
        raise RuntimeError(f'{label} needs an estimated {need:.1f} GiB total budget. Current budget {memory:g}; checkpoints retained. Increase --memory-gb only if physical RAM allows.')
    start=time.monotonic();pending={};metrics=[];error=None;fresh_weight=0.
    # Each completed large fit releases its process/allocator before the next.
    # Python >=3.11 supports this; the launcher requires it for this release.
    with ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn'),max_tasks_per_child=1) as pool:
        while jobs or pending:
            used=sum(j['memory_estimate_gb'] for j in pending.values())
            while jobs and len(pending)<workers:
                k=next((k for k,j in enumerate(jobs) if used+j['memory_estimate_gb']<=budget),None)
                if k is None:break
                job=jobs.pop(k);pending[pool.submit(invoke,fn,job)]=job;used+=job['memory_estimate_gb']
            done,_=wait(pending,timeout=30,return_when=FIRST_COMPLETED)
            for f in done:
                done_job=pending.pop(f)
                try:
                    _,metric=f.result();metrics.append(metric)
                    if not metric['reused_checkpoint']:fresh_weight+=max(.01,done_job['memory_estimate_gb']-.8)
                except Exception as exc:
                    if error is None:error=exc
                    jobs=[]
                report()
            remaining=sum(max(.01,j['memory_estimate_gb']-.8) for j in jobs+list(pending.values()))
            eta=f'{remaining*(time.monotonic()-start)/fresh_weight/3600:.2f} h' if fresh_weight and len(metrics)>=2 else 'measuring / reusing checkpoints'
            if not jobs and not pending:eta='0.00 h'
            io.log(f'{label}: {len(metrics)} completed; {len(pending)} active; {len(jobs)} queued; stage ETA {eta}; reserved {sum(j["memory_estimate_gb"] for j in pending.values()):.1f} GiB')
    runtime.save(dict(stage=label,kind='memory_weighted_models',seconds=time.monotonic()-start,completed_jobs=len(metrics),workers=workers,
        max_worker_lifetime_peak_rss_gib=max((x['worker_lifetime_peak_rss_gib'] for x in metrics),default=0)))
    if error:raise error


def score_queries(split,root,conf,family):
    def build(tmp):
        cols=list(dict.fromkeys(['row_id']+cache.BEHAVIOR_KEYS+SCORE_COLS))
        q=io.read(split/(family+'_pooled.parquet'),cols);shard=num.user_hash(io.arr(q,'opponent_id'))%np.uint64(16)
        for s in range(16):io.table(tmp/f'{s:02}.parquet',q.filter(pa.array(shard==s)))
        return dict(rows=len(q))
    return stable_stage(root,conf,build,[split/(family+'_pooled.parquet')])


def score_family(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime,family):
    prefix='secondary' if family=='ordinary' else 'entry_comp'
    q,_=score_queries(split,root/(prefix+'_queries'),conf,family)
    definition=cache.definition('competitive_history_author_clean_v1',dict(pooled_definition=pooled_definition,cp_cutoff=-100,minimum_decisions=5),[Path(secondary.__file__)])
    jobs=[]
    for s in range(16):
        j=dict(queries=str(q/f'{s:02}.parquet'),index=index_jobs[s]['output'],index_job=index_jobs[s],reference=str(reference),authors=ids,
               memory=max(.5,(memory-2)/workers),conf=conf,output=str(root/(prefix+'_scores')/f'{s:02}'))
        jobs.append(cache.attach(j,shared,'competitive_scores',definition,s))
    runtime.mapped(secondary.score_job,jobs,workers,'Reuse competitive scores; compute missing '+family+' scores')
    return competitive_prepare(split,[str(Path(j['output'])/'scores.parquet') for j in jobs],root/(prefix+'_prepared'),conf,memory,family)


def run_secondary(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime,report):
    prepared,info=score_family(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime,'ordinary')
    jobs=[]
    for cohort in COHORTS:
        src=prepared/(cohort+'.parquet');n=pq.ParquetFile(src).metadata.num_rows
        for family in ('X0','XC'):
            for tail in ('all_supported','exclude_above_95pct'):
                jobs.append(dict(input=str(src),cohort=cohort,family=family,tail=tail,cutoff=info['tail_cutoff'],conf=conf,
                    memory_estimate_gb=memory_estimate(n,'secondary'),output=str(root/'secondary_models'/(cohort+'_'+family+'_'+tail))))
    fit_map(secondary_job,jobs,runtime,workers,memory,'Competitive ordinary-comparison fits',report)


def run_entry_competitive(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime,report):
    prepared,info=score_family(root,split,shared,index_jobs,reference,ids,pooled_definition,conf,memory,workers,runtime,'entry')
    jobs=[]
    for cohort in COHORTS:
        src=prepared/(cohort+'.parquet');n=pq.ParquetFile(src).metadata.num_rows
        jobs.append(dict(input=str(src),cohort=cohort,cutoff=info['tail_cutoff'],conf=conf,
            memory_estimate_gb=memory_estimate(n,'competitive_entry'),output=str(root/'entry_comp_models'/cohort)))
    fit_map(entry_comp_job,jobs,runtime,workers,memory,'Competitive entry control ladder',report)


def memory_estimate(n,kind):
    # Allocation audit + synthetic RSS scaling; GiB, including input/cluster codes.
    per_row={'primary':800,'secondary':850,'competitive_entry':1000}[kind]
    return .8+n*per_row/1024**3
