"""Refresh only histories needed by Run 3, preserving the frozen exposure rows."""
from __future__ import annotations
from common import *
import concurrent.futures as cf
import iv_numerics as num
import audit_logic as audit

def author_mask(j,i,ids): return np.isin(j,ids)|np.isin(i,ids)

def checked_record(record):
    return io.checked(record['path'],record['sha256'],record.get('bytes'))

def resolve_authors(project, prior):
    identity=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'identity'
    check=identity/'report/dictionary_check.json'
    digest=next(r['sha256'] for r in prior['comparison_public_files'] if r['file']=='dictionary_check.json')
    io.checked(check,digest);column=io.load(check)['selected_explicit_ID_column']
    receipt=io.load(identity/'_COMPLETE.json')
    if receipt['config_sha256']!=prior['comparison_config_sha256']:raise RuntimeError('Wrong historical identity receipt')
    entry=next(r for r in receipt['files'] if r['path']=='dictionary_binding_PRIVATE.json')
    binding=identity/'dictionary_binding_PRIVATE.json';io.checked(binding,entry['sha256'],entry['bytes'])
    records=io.load(binding)['files']; found={}
    dictionary=project/'derived/glicko2_replay/user_dictionary_v1/user_dictionary_buckets'
    for name in AUTHORS:
        bucket=hashlib.md5(name.encode()).hexdigest()[:2]
        candidates=[]
        for r in records:
            p=relocate(project,r['path'])
            if dictionary.resolve() in p.resolve().parents and 'bucket='+bucket in p.parts and p.suffix=='.parquet':
                io.checked(p,r['sha256'],r['bytes']); candidates.append(p)
        if not candidates:raise RuntimeError('No verified dictionary bucket for author '+name)
        values=[]
        for p in candidates:
            t=arrays(io.read(p,['username_norm',column]))
            names=np.char.lower(np.char.strip(np.asarray(t['username_norm'],dtype=str)))
            values.extend(np.asarray(t[column],np.int64)[names==name].tolist())
        if len(values)!=1:raise RuntimeError('Author identity is absent or ambiguous: '+name)
        found[name]=int(values[0])
    if len(set(found.values()))!=2:raise RuntimeError('Author IDs unexpectedly coincide')
    return found

def authenticate(project, workers):
    prior=io.load(ROOT/'evidence/prior_authority.json')
    source=project/EXPANDED_REL
    if io.cfgsha(io.load(source/'config.json'))!=EXPANDED_CONF:raise RuntimeError('Expanded IV configuration differs')
    io.checked(source/'analysis/spaced90.parquet',SPACED_SHA,295180899)
    if pq.ParquetFile(source/'analysis/spaced90.parquet').metadata.num_rows!=2682330:raise RuntimeError('Wrong frozen IV cohort')
    lineage=project/'derived/replication/comparison_tests_v110_PRIVATE'/prior['comparison_run']/'lineage_PRIVATE.json'
    io.checked(lineage,prior['comparison_lineage_sha256']);line=io.load(lineage)
    parts=[]
    for shard,entries in enumerate(line['projections']):
        for r in entries:parts.append(dict(r,path=str(relocate(project,r['path'])),shard=shard))
    if len(parts)!=384 or {(p['month'],p['shard']) for p in parts}!={(m,s) for m in MONTHS for s in range(16)} or sum(p['rows'] for p in parts)!=47587020:
        raise RuntimeError('Opportunity history coverage differs')
    with io.heartbeat('Checking cached history file hashes'),cf.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(checked_record,parts))
    pilot=project/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/prior['iv_run']
    success=io.load(pilot/'_SUCCESS.json')
    if success['config_sha256']!=prior['iv_config_sha256'] or success['report_zip_sha256']!=prior['iv_report_sha256']:
        raise RuntimeError('Historical reference authority changed')
    deltas=[]
    for month in MONTHS:
        folder=pilot/'projection'/('month='+month);r=io.load(folder/'_COMPLETE.json')
        if r['config_sha256']!=prior['iv_config_sha256']:raise RuntimeError('Reference configuration differs')
        entry=next(e for e in r['files'] if e['path']=='reference_deltas.npz')
        p=folder/entry['path'];io.checked(p,entry['sha256'],entry['bytes']);deltas.append(str(p))
    ids=resolve_authors(project,prior)
    return dict(spaced=str(source/'analysis/spaced90.parquet'),parts=parts,deltas=deltas,author_ids=ids,
                source_sample_sha256=SPACED_SHA,lineage_sha256=prior['comparison_lineage_sha256'])

def extract_author_month(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def produce(tmp):
        c=io.conn(tmp/'spill',1,1)
        try:
            ids=','.join(str(int(v)) for v in job['ids'])
            n=io.copy(c,'SELECT '+','.join(PROJECTION_COLS)+' FROM '+io.parq(job['parts'])+
                      f' WHERE j IN ({ids}) OR i IN ({ids})',tmp/'removed.parquet')
        finally:c.close()
        return dict(removed_rows=n)
    return io.stage(Path(job['output']),job['conf'],produce)[1]

def reference_removal(h, shape):
    """Same first-eligible-month rule as run_iv_pilot.project_month, including ties."""
    dn=np.zeros(shape,np.int64);ds=np.zeros(shape,np.int64)
    use=np.asarray(h['arm'],bool)
    j=np.asarray(h['j'])[use];i=np.asarray(h['i'])[use];t=np.asarray(h['t'])[use]
    jf=(num.user_hash(j)%np.uint64(4)).astype(int);rf=(num.user_hash(i)%np.uint64(4)).astype(int)
    cell=np.asarray(h['cell'])[use];y=np.asarray(h['y'],np.int64)[use]
    for k,lag in enumerate((7,30)):
        eligible=np.searchsorted(STARTS,t+lag*DAY,side='right')
        flat=(((eligible*4+jf)*4+rf)*500+cell).astype(np.int64)
        dn[k]=np.bincount(flat,minlength=int(np.prod(shape[1:]))).reshape(shape[1:])
        ds[k]=np.bincount(flat,weights=y,minlength=int(np.prod(shape[1:]))).reshape(shape[1:]).astype(np.int64)
    return dn,ds

def removed_events(h):
    n=len(h['j']);fair=np.asarray(h['fair'],np.int64);y=np.asarray(h['y'],np.int64)
    zero=np.zeros(n,np.int64)
    return dict(person=np.r_[h['j'],h['i']],t=np.r_[h['t'],h['t']],
                fair=np.r_[fair,zero],kind=np.r_[fair*y,zero],disconnect=np.r_[zero,np.ones(n,np.int64)],
                receipt=np.r_[zero,y],claim=np.r_[zero,np.asarray(h['arm'],np.int64)*(1-y)])

def prepare_reference(inputs, removed_paths, root, conf):
    def produce(tmp):
        n=s=None
        for path in inputs['deltas']:
            with np.load(path,allow_pickle=False) as z:
                if n is None:n=z['n'].copy();s=z['s'].copy()
                else:n+=z['n'];s+=z['s']
        if n.shape!=(2,25,4,4,500):raise RuntimeError('Unexpected reference shape')
        h=arrays(pa.concat_tables([io.read(p,PROJECTION_COLS) for p in removed_paths]))
        dn,ds=reference_removal(h,n.shape)
        if np.any(n<dn) or np.any(s<ds) or np.any(n-dn<s-ds):raise RuntimeError('Author reference subtraction is inconsistent')
        np.save(tmp/'original.npy',num.expanding_reference(n[:,:24],s[:,:24]),allow_pickle=False)
        np.save(tmp/'clean.npy',num.expanding_reference((n-dn)[:,:24],(s-ds)[:,:24]),allow_pickle=False)
        io.table(tmp/'removed_events.parquet',pa.table(removed_events(h)))
        return dict(removed_history_games=len(h['j']),removed_reference_games=int(np.asarray(h['arm']).sum()))
    return io.stage(root,conf,produce)

def score_shard(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def produce(tmp):
        q=arrays(io.read(job['query']))
        original=np.load(job['reference']+'/original.npy',mmap_mode='r',allow_pickle=False)
        clean=np.load(job['reference']+'/clean.npy',mmap_mode='r',allow_pickle=False)
        tables=[io.read(p,PROJECTION_COLS) for p in job['parts']]
        h=arrays(pa.concat_tables(tables));del tables
        if np.any(num.user_hash(h['j'])%np.uint64(16)!=job['shard']):raise RuntimeError('Wrong chooser history shard')
        arm=np.asarray(h['arm'],bool)
        oldh={k:v[arm] for k,v in h.items()}
        keep=arm&~author_mask(h['j'],h['i'],job['ids'])
        newh={k:v[keep] for k,v in h.items()};del h
        result={k:np.asarray(q[k]).copy() for k in QUERY_COLS};max_error=0.
        for month in np.unique(q['month_code']):
            ix=np.flatnonzero(q['month_code']==month);m=int(month)
            for data,model,checking in ((oldh,original,True),(newh,clean,False)):
                sc=num.score_month(data['j'],data['i'],data['t'],data['y'],data['cell'],
                                   q['opponent_id'][ix],q['recipient_id'][ix],int(STARTS[m])-7*DAY,model[0,m])
                for name,value in sc.items():
                    col=name+'_7d'
                    if col not in SCORE_COLS:continue
                    if checking:
                        saved=q[col][ix]
                        if not np.allclose(saved,value,rtol=1e-10,atol=2e-11,equal_nan=True):
                            raise RuntimeError('Original cached score not reproduced: '+col+' month '+str(m))
                        finite=np.isfinite(saved)&np.isfinite(value)
                        if finite.any():max_error=max(max_error,float(np.max(abs(saved[finite]-value[finite]))))
                    else:result[col][ix]=value
        io.table(tmp/'scores.parquet',pa.table({k:result[k] for k in ['row_id']+SCORE_COLS}))
        return dict(rows=len(q['row_id']),original_score_max_abs_error=max_error)
    return io.stage(Path(job['output']),job['conf'],produce)[1]

def build_clean_sample(inputs, root, conf, workers):
    stage=root/'histories'
    jobs=[dict(parts=[p['path'] for p in inputs['parts'] if p['month']==m],ids=list(inputs['author_ids'].values()),
               output=str(stage/'removed'/m),conf=conf) for m in MONTHS]
    io.mapped(extract_author_month,jobs,workers,'Author history scan')
    removed=[Path(j['output'])/'removed.parquet' for j in jobs]
    reference,refinfo=prepare_reference(inputs,removed,stage/'reference',conf)
    def query_build(tmp):
        q=io.read(inputs['spaced'],QUERY_COLS);shards=num.user_hash(io.arr(q,'opponent_id'))%np.uint64(16)
        for s in range(16):io.table(tmp/f'{s:02}.parquet',q.filter(pa.array(shards==s)))
    queries,_=io.stage(stage/'queries',conf,query_build)
    jobs=[dict(parts=[p['path'] for p in inputs['parts'] if p['shard']==s],query=str(queries/f'{s:02}.parquet'),
               reference=str(reference),ids=list(inputs['author_ids'].values()),shard=s,
               output=str(stage/'scores'/f'{s:02}'),conf=conf) for s in range(16)]
    io.mapped(score_shard,jobs,workers,'Verify old scores and refresh without authors')
    def assemble(tmp):
        t=io.read(inputs['spaced'],MODEL_COLS);d=arrays(t)
        scores=arrays(pa.concat_tables([io.read(Path(j['output'])/'scores.parquet') for j in jobs]))
        order=np.argsort(scores['row_id']);scores={k:v[order] for k,v in scores.items()}
        loc=num.lookup(scores['row_id'],d['row_id'])
        if len(np.unique(scores['row_id']))!=len(t) or np.any(loc<0):raise RuntimeError('Refreshed score join is not one-to-one')
        change=abs(scores['adjusted_7d'][loc]-d['adjusted_7d'])
        max_change=float(np.nanmax(change)) if np.isfinite(change).any() else None
        for col in ('n_7d','adjusted_7d','expected_7d','counterparts_7d'):d[col]=scores[col][loc]
        events=arrays(io.read(reference/'removed_events.parquet'))
        removed_counts=audit.window_counts(events,d['recipient_id'],d['archive_start_ms'])
        for col in COUNT_COLS:
            d[col]=np.asarray(d[col],np.int64)-removed_counts[col]
            if np.any(d[col]<0):raise RuntimeError('Negative author-clean history count: '+col)
        involved=author_mask(d['opponent_id'],d['recipient_id'],list(inputs['author_ids'].values()))
        supported=(d['n_7d']>=5)&np.isfinite(d['adjusted_7d'])&np.isfinite(d['expected_7d'])
        keep=~involved&supported
        io.table(tmp/'sample.parquet',pa.table({k:v[keep] for k,v in d.items()}))
        return dict(original_rows=len(t),author_exposures_removed=int(involved.sum()),
                    additional_rows_losing_score_support=int((~involved&~supported).sum()),rows=int(keep.sum()),
                    largest_score_change=max_change,author_history_games_removed=refinfo['removed_history_games'],
                    author_reference_games_removed=refinfo['removed_reference_games'],
                    original_spacing_preserved=True,factual_all_game_activity_preserved=True,
                    future_outcomes_loaded=False)
    return io.stage(root/'clean_sample',conf,assemble)
