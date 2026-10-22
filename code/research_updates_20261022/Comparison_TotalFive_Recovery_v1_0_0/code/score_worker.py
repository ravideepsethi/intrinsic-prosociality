"""Frozen all-time score producer, with independent pair-exclusion checks."""
import sys
from pathlib import Path
import recovery_util as u
sys.path.insert(0,str(u.PACKAGE/'vendor_primary'))
import primary_common as pc
import primary_inputs as pi
np,pa,pq=pc.np,pc.pa,pc.pq

def score_job(job):
    pc.frozen.r.threads_one();pc.frozen.u.no_network()
    def build(tmp):
        chunks=[]
        for r in job['parts']:
            pc.frozen.r.io.checked(r['path'],r['sha256'],r.get('bytes'))
            d=pc.frozen.r.arrays(pc.frozen.r.io.read(r['path'],['j','i','t','y','arm','cell','fair']))
            keep=d['arm'].astype(bool)&~np.isin(d['i'],job['authors'])&~np.isin(d['j'],job['authors'])
            u.require(np.array_equal(d['fair'][keep],d['cell'][keep]//100>=2),'Donor classification changed')
            chunks.append({k:d[k][keep] for k in ('j','i','t','y','cell')})
        h={k:np.concatenate([r[k] for r in chunks]) for k in chunks[0]};del chunks,d
        q=pc.frozen.r.arrays(pc.frozen.r.io.read(job['query']))
        ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        scores,fallback=pc.inputs.alltime(h,q,ref);err=0.;checks=0
        for ix in np.unique(np.linspace(0,len(q['row_id'])-1,min(12,len(q['row_id'])),dtype=int)):
            mask=(h['j']==q['opponent_id'][ix])&(h['i']!=q['recipient_id'][ix]);sub={k:v[mask] for k,v in h.items()}
            u.require(scores['n'][ix]==mask.sum() and scores['counterparts'][ix]==len(np.unique(sub['i'])),'Pair-exclusion count oracle failed')
            if mask.any():
                mapping,_=pc.frozen.r9_scores.reference_map(ref,pc.frozen.r9_scores.event_month(sub['t']))
                fold=int(pc.frozen.r.num.user_hash(np.array([q['recipient_id'][ix]]))[0]%np.uint64(4))
                prediction,_=pc.frozen.r9_scores.donor_weights(sub,ref,fold,mapping)
                err=max(err,abs(scores['expected'][ix]-float(np.mean(prediction))),abs(scores['adjusted'][ix]-float(np.mean(sub['y']-prediction))))
                u.require(err<2e-10,'Direct donor-month oracle failed')
            checks+=1
        pq.write_table(pa.table(dict(row_id=q['row_id'],**{k+'_A':v for k,v in scores.items()})),tmp/'scores.parquet',compression='zstd')
        u.save(tmp/'audit.json',dict(queries=len(q['row_id']),oracle_checks=checks,oracle_max_error=err,fallback=fallback))
        return dict(queries=len(q['row_id']),oracle_checks=checks,oracle_max_error=err)
    return pc.frozen.r.stable_stage(Path(job['out']),job['conf'],build,[job['query'],job['reference']]+[r['path'] for r in job['parts']])[1]

def run(a):
    pc.frozen.u.no_network();a.r9_root=None;a.r12_root=a.project/'derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3'
    b=pi.bind(a,a.run,a.conf);old=u.parent(a)
    selected=old/'PRIVATE/wider/selection.parquet'
    sk=pc.key([u.PARENT_CONF,'selection',pc.sha(b['raw']),[pc.sha(p) for p in b['all_scores']]])
    pc.verified_receipt(selected,sk)
    streamkey=pc.key([u.PARENT_CONF,pc.sha(b['raw']),pc.sha(selected),'full_pre_window_stream'])
    stream=old/'PRIVATE/full_selected_stream90.parquet';pc.verified_receipt(stream,streamkey)
    pc.verified_receipt(old/'PRIVATE/selection_universe.parquet',streamkey)
    u.require(pq.ParquetFile(stream).metadata.num_rows==4226388,'Full pre-window receipt stream count differs')
    audit=old/'PRIVATE/comparison_audit';ledgers=[]
    for row in u.load(u.PACKAGE/'evidence/comparison_full_denominator.json'):
        folder=audit/row['month'];pc.frozen.r.io.complete(folder,u.PARENT_CONF)
        u.require(u.load(folder/'summary.json')['totals']==row,'Audited month counts differ')
        ledgers.append(folder/'new_count_supported_PRIVATE.parquet')
    root=a.run/'PRIVATE/score';root.mkdir(exist_ok=True)
    def queries(tmp):
        c=pc.db(tmp/'spill',a.memory_gb-2)
        try:
            # Row IDs are local to this new frame; game_id is the future cross-frame key.
            pc.copy_query(c,'SELECT row_number() OVER(ORDER BY month,game_id)::BIGINT row_id,* FROM '+pc.parq(ledgers),tmp/'candidates.parquet')
            u.require(pq.ParquetFile(tmp/'candidates.parquet').metadata.num_rows==9654945,'Newly count-supported universe changed')
            # Deterministic validation rows, disjoint negative IDs, from accepted R12.
            pc.copy_query(c,'SELECT -p.row_id-1 row_id,p.recipient_id,p.opponent_id,s.n_A,s.counterparts_A,s.expected_A,s.adjusted_A FROM '+pc.parq([b['primary']])+' p JOIN '+pc.parq([b['primary_scores']])+' s USING(row_id) ORDER BY hash(p.row_id),p.row_id LIMIT 4096',tmp/'validation.parquet')
            pc.copy_query(c,'SELECT row_id,recipient_id,opponent_id FROM '+pc.parq([tmp/'candidates.parquet'])+' UNION ALL SELECT row_id,recipient_id,opponent_id FROM '+pc.parq([tmp/'validation.parquet']),tmp/'queries.parquet')
        finally:c.close()
        schema=pq.ParquetFile(tmp/'queries.parquet').schema_arrow
        writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd') for s in range(16)]
        try:
            for batch in pq.ParquetFile(tmp/'queries.parquet').iter_batches(batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([batch]);shard=pc.frozen.r.num.user_hash(pc.frozen.r.io.arr(t,'opponent_id'))%np.uint64(16)
                for s,w in enumerate(writers):
                    if (shard==s).any():w.write_table(t.filter(pa.array(shard==s)))
        finally:
            for w in writers:w.close()
        return dict(candidates=9654945,validation_rows=4096)
    qp,_=pc.frozen.r.stable_stage(root/'queries',a.conf,queries,ledgers+[b['primary'],b['primary_scores']])
    bound=b['bound'];jobs=[dict(parts=[r for r in bound['parts'] if r['shard']==s],query=str(qp/f'{s:02}.parquet'),reference=bound['reference'],authors=bound['binding']['author_ids'],out=str(root/'parts'/f'{s:02}'),conf=a.conf,memory_gb=4.5) for s in range(16)]
    pc.frozen.runtime.mapped(score_job,jobs,min(2,a.workers),a.memory_gb,'All-time pair-excluded Score A',30,90)
    def combine(tmp):
        c=pc.db(tmp/'spill',a.memory_gb-2)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+pc.parq([Path(j['out'])/'scores.parquet' for j in jobs]))
            pc.ensure_unique(c,'s',9654945+4096)
            c.execute('CREATE VIEW v AS SELECT * FROM '+pc.parq([qp/'validation.parquet']))
            u.require(c.execute('SELECT count(*) FROM v JOIN s USING(row_id)').fetchone()[0]==4096,'R12 score validation row set differs')
            errors={}
            for field in ('n_A','counterparts_A','expected_A','adjusted_A'):
                error=c.execute(f'SELECT max(abs(s.{field}-v.{field})) FROM s JOIN v USING(row_id)').fetchone()[0]
                u.require(error is not None and error<2e-10,'R12 score bridge failed: '+field);errors[field]=error
            c.execute('CREATE VIEW q AS SELECT * FROM '+pc.parq([qp/'candidates.parquet']))
            u.require(c.execute('SELECT count(*) FROM q JOIN s USING(row_id) WHERE s.n_A<>q.total_pair_excluded_decisions').fetchone()[0]==0,'Finite-score count and full-frame count differ')
            pc.copy_query(c,'SELECT q.*,s.* EXCLUDE(row_id),isfinite(s.adjusted_A) AND isfinite(s.expected_A) AND s.n_A>=5 AS finite_A FROM q JOIN s USING(row_id)',tmp/'candidates.parquet')
            n=c.execute('SELECT count(*) FROM '+pc.parq([tmp/'candidates.parquet'])+' WHERE finite_A').fetchone()[0]
            return dict(count_supported_candidates=9654945,finite_score_candidates=n,R12_validation_rows=4096,R12_max_errors=errors)
        finally:c.close()
    folder,info=pc.frozen.r.stable_stage(root/'combined',a.conf,combine,[qp/'candidates.parquet']+[Path(j['out'])/'scores.parquet' for j in jobs])
    u.save(a.run/'report/score_support.json',{k:info[k] for k in ('count_supported_candidates','finite_score_candidates','R12_validation_rows','R12_max_errors')})
    u.save(a.run/'PRIVATE/SCORE_PATHS.json',dict(candidates=str(folder/'candidates.parquet'),stream=str(stream)))
if __name__=='__main__':
    with u.pulse('Score authentication and construction'):run(u.parser().parse_args())
