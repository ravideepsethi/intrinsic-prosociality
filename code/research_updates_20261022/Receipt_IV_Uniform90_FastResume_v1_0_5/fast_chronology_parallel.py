"""Concurrent, checkpoint-compatible execution of independent chronology groups.

The frozen adjacency SQL and exact integer sums are unchanged. Existing leaf
receipts are reused before loading candidate data. For unfinished groups, read
candidate Parquet payloads into a spillable table once, then materialize each
bounded leaf once for the repeated adjacency/volume queries.
"""
from fast_bootstrap import *
import repair_chronology as old
from fast_digest_cache import install as install_digest_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import tempfile

MAX_MODULUS = 32768


def policy(memory=4., workers=None, budget=None, cores=None):
    workers = worker_limit() if workers is None else int(workers)
    budget = memory_budget() if budget is None else float(budget)
    cores = worker_limit() if cores is None else int(cores)
    sql_gb = min(float(memory), 3.5)
    require(sql_gb > 0 and workers > 0 and cores > 0, 'Invalid merge resource policy')
    # DuckDB uses decimal GB. Reserve additional Python/Arrow/SQL overhead and
    # shared coordinator memory, rather than granting the full budget per task.
    per_worker_gib = sql_gb * 10**9 / 2**30 + .75
    slots = min(4, workers, cores, max(1, int((budget - 1.) // per_worker_gib)))
    require(1. + slots * per_worker_gib <= budget, 'Memory allowance too small for merge')
    threads = max(1, min(4, cores // slots))
    return dict(workers=slots,threads_per_worker=threads,duckdb_memory_gb=sql_gb,
                estimated_reserved_gib=1. + slots*per_worker_gib,
                total_allowance_gib=budget)


def connection(root, resources):
    return db(Path(root)/'spill', resources['duckdb_memory_gb'],resources['threads_per_worker'])


def parallel_map(fn, items, workers, label):
    items = list(items)
    if not items:
        return []
    results = [None]*len(items)
    began = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(fn, item): i for i,item in enumerate(items)}
        try:
            for done,future in enumerate(as_completed(pending),1):
                results[pending[future]] = future.result()
                if done == len(items) or done % 8 == 0:
                    old.elapsed_message(label,done,len(items),began)
        except BaseException:
            for future in pending:
                future.cancel()
            raise
    return results


def resume_scans(jobs, workers):
    """Authenticate sealed scans in this process; run only missing scan jobs."""
    install_digest_cache(old.io)
    done = [j for j in jobs if (Path(j['output'])/'_DONE.json').is_file()]
    missing = [j for j in jobs if not (Path(j['output'])/'_DONE.json').is_file()]
    def reuse(job):
        require(old.io.sig(job['path']) == job['signature'], 'Chronology changed since authentication')
        def forbidden(tmp):
            raise RuntimeError('Completed chronology scan disappeared during verification')
        # Scan receipts use the chronology producer's stable_stage format;
        # unlike later merge leaves, they have no dependencies_PRIVATE.json.
        return chron.stable_stage(job['output'],job['conf'],forbidden,
                                 [job[k] for k in ('path','people','pairs','focal','roles')])[1]
    log(f'Chronology scan resume: {len(done)}/{len(jobs)} sealed scans; {len(missing)} scans require work')
    parallel_map(reuse,done,min(workers,4),'Authenticating saved chronology scans')
    if missing:
        mapped(chron.chronology_job,missing,min(workers,2),'Missing chronology scans')


def existing_nodes(root, buckets):
    result = {k:set() for k in range(buckets)}
    for p in (Path(root)/'classified').glob('*/_DONE.json'):
        match = re.fullmatch(r'(\d{5})_(\d{5})',p.parent.name)
        if not match:
            continue  # .partial directories are never candidates for reuse.
        modulus,residue = map(int,match.groups())
        require(modulus >= buckets and modulus <= MAX_MODULUS and modulus%buckets == 0
                and (modulus//buckets)&((modulus//buckets)-1) == 0 and 0 <= residue < modulus,
                'Invalid completed chronology leaf name: '+str(p.parent))
        result[residue%buckets].add((modulus,residue))
    return result


def query_ids(paths):
    arrays = []
    for p in paths:
        col = pq.ParquetFile(p).read(columns=['row_id'],use_threads=False)['row_id']
        require(col.null_count == 0, 'Missing chronology query row ID')
        values = col.to_numpy()
        require(np.issubdtype(values.dtype,np.integer) and (not len(values) or values.min()>=0),
                'Invalid chronology query row ID')
        arrays.append(values)
    return np.concatenate(arrays) if arrays else np.empty(0,np.int64)


def plan_bucket(job):
    """Reuse all sealed ancestors/descendants, including OOM-induced old splits."""
    root=Path(job['root']);nodes=job['nodes'];ids=query_ids(job['qp'])
    require(len(np.unique(ids)) == len(ids),'Duplicate chronology query row ID')
    require(not len(ids) or np.all(ids%job['buckets'] == job['bucket']), 'Wrong chronology query bucket')
    deps=job['qp']+job['cp']+job['pf'];leaves=[];pending=[]
    ancestors=set()
    for modulus,residue in nodes:
        while modulus>job['buckets']:
            modulus//=2;residue%=modulus;ancestors.add((modulus,residue))
    def visit(modulus,residue):
        qn=int(np.count_nonzero(ids%modulus == residue))
        if not qn:return
        if (modulus,residue) in nodes:
            def forbidden(tmp):raise RuntimeError('Sealed chronology leaf disappeared')
            out,info=stage(root/'classified'/f'{modulus:05}_{residue:05}',job['conf'],forbidden,deps)
            require(info['rows']==qn and pq.ParquetFile(out/'features.parquet').metadata.num_rows==qn,
                    'Completed chronology leaf row count differs')
            leaves.append(out/'features.parquet')
        elif (modulus,residue) in ancestors:
            visit(modulus*2,residue);visit(modulus*2,residue+modulus)
        else:pending.append((modulus,residue,qn))
    visit(job['buckets'],job['bucket'])
    return dict(job,ids=ids,leaves=leaves,pending=pending,reused_leaves=len(leaves))


def prepare_candidates(c, plan):
    predicate=' OR '.join(f'(sample_row%{m}={r})' for m,r,n in plan['pending'])
    # One Parquet payload scan, restricted to the unfinished portion of a bucket.
    c.execute('CREATE TEMP TABLE bucket_candidates AS SELECT * FROM '+parq(plan['cp'])+' WHERE '+predicate)
    return 'bucket_candidates'


def candidate_histogram(c, source):
    rows=c.execute(f'SELECT sample_row%{MAX_MODULUS} residue,count(*) n FROM '+source+' GROUP BY 1').fetchall()
    counts=np.zeros(MAX_MODULUS,dtype=np.int64)
    for residue,n in rows:
        require(residue is not None and 0<=residue<MAX_MODULUS,'Invalid candidate row ID')
        counts[int(residue)]=n
    return counts


def build_leaf(c, source, plan, modulus, residue, qn, cn, tmp):
    """Exact original joins/CASE and integer sums; no new scientific rule."""
    try:
        c.execute('CREATE OR REPLACE TEMP VIEW q AS SELECT * FROM '+parq(plan['qp'])+f' WHERE row_id%{modulus}={residue}')
        # Materialize once: frozen adjacency reads candidates twice, volume once.
        c.execute('CREATE TEMP TABLE candidates AS SELECT * FROM '+source+f' WHERE sample_row%{modulus}={residue}')
        c.execute('CREATE OR REPLACE TEMP VIEW focal AS SELECT row_id sample_row,recipient_id,opponent_id FROM q')
        c.execute('CREATE TEMP TABLE classifications AS '+old.previous.rebuild.adjacency_final_sql('candidates','focal'))
        c.execute('CREATE TEMP TABLE volume AS SELECT sample_row,sum(pre_games_30d)::BIGINT pre_games_30d FROM candidates WHERE role=0 GROUP BY sample_row')
        c.execute('CREATE TEMP TABLE pair_features AS SELECT * FROM '+parq(plan['pf'])+f' WHERE row_id%{modulus}={residue}')
        sql='''SELECT q.row_id,s.previous_classification_status,s.previous_classification_status='''+quote(old.previous.rebuild.NONADJ)+''' eligible_main,
          p.first_observed_pair,coalesce(v.pre_games_30d,0)::BIGINT pre_games_30d FROM q
          JOIN classifications s ON q.row_id=s.sample_row LEFT JOIN pair_features p USING(row_id) LEFT JOIN volume v ON q.row_id=v.sample_row'''
        copy_query(c,sql+' ORDER BY q.row_id',tmp/'features.parquet')
        c.execute('CREATE OR REPLACE TEMP VIEW result AS SELECT * FROM '+parq([tmp/'features.parquet']))
        ensure_unique(c,'result',qn)
        ensure(c,'SELECT count(*) FROM result WHERE first_observed_pair IS NULL OR pre_games_30d<0','Invalid bounded chronology feature')
        return dict(rows=qn,candidate_summary_rows=cn,modulus=modulus,residue=residue,
                    execution_version='1.0.5',candidate_table_materialized_once=True)
    finally:
        for table in ('classifications','volume','pair_features','candidates'):
            c.execute('DROP TABLE IF EXISTS '+table)


def classify_bucket(plan):
    resources=plan['resources'];root=Path(plan['root']);leaves=list(plan['leaves'])
    root.mkdir(parents=True,exist_ok=True)
    scratch=Path(tempfile.mkdtemp(prefix='merge105_scratch_',dir=root))
    c=None;built=0;began=time.monotonic();fallback=False
    deps=plan['qp']+plan['cp']+plan['pf']
    try:
        c=connection(scratch,resources)
        try:source=prepare_candidates(c,plan)
        except old.duckdb.OutOfMemoryException:
            # A large/skewed group may exceed the spillable-table reservation.
            # Fall back to bounded leaf reads; successful leaves still checkpoint.
            c.close();c=connection(scratch/'fallback',resources)
            source=parq(plan['cp']);fallback=True
            log(f'Group {plan["bucket"]+1}: using bounded leaf reads after materialization memory pressure')
        counts=candidate_histogram(c,source)
        def leaf(modulus,residue,qn=None):
            nonlocal built
            qn=int(np.count_nonzero(plan['ids']%modulus==residue)) if qn is None else qn
            if not qn:return
            cn=int(counts[residue::modulus].sum())
            def split():
                require(modulus<MAX_MODULUS,'Chronology leaf remains too large; stopped with saved partitions intact')
                leaf(modulus*2,residue);leaf(modulus*2,residue+modulus)
            if qn>plan['max_queries'] or cn>plan['max_candidates']:
                split();return
            target=root/'classified'/f'{modulus:05}_{residue:05}'
            try:
                out,_=stage(target,plan['conf'],lambda tmp:build_leaf(c,source,plan,modulus,residue,qn,cn,tmp),deps)
            except old.duckdb.OutOfMemoryException:
                log(f'Memory retry: splitting chronology group {residue}/{modulus}');split();return
            leaves.append(out/'features.parquet');built+=1
        for modulus,residue,qn in plan['pending']:leaf(modulus,residue,qn)
        return dict(leaves=leaves,reused_leaves=plan['reused_leaves'],new_leaves=built,
                    seconds=time.monotonic()-began,bucket=plan['bucket'],bounded_read_fallback=fallback)
    finally:
        if c is not None:c.close()
        # Only this invocation's unsealed SQL scratch. No user/checkpoint path.
        shutil.rmtree(scratch,ignore_errors=True)


def ordered_leaves(leaves, buckets):
    """Match v104 recursive left-before-right dependency order exactly."""
    def order(path):
        modulus,residue=map(int,Path(path).parent.name.split('_'))
        depth=(modulus//buckets).bit_length()-1
        branches=tuple(((residue//buckets)>>j)&1 for j in range(depth))
        return residue%buckets,branches
    return sorted(leaves,key=order)
