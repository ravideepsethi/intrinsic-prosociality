"""Timing and region diagnostics on the new primary rows; never select the primary on B/C."""
from primary_common import *
import concurrent.futures as cf
import multiprocessing as mp

def score_job(job):
    frozen.r.threads_one();frozen.u.no_network()
    def build(tmp):
        chunks=[];fair=[]
        for rec in job['parts']:
            frozen.r.io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
            d=frozen.r.arrays(frozen.r.io.read(rec['path'],['j','i','t','y','arm','cell','fair']))
            clean=~np.isin(d['j'],job['authors'])&~np.isin(d['i'],job['authors'])
            f=clean&d['fair'].astype(bool);fair.append((d['j'][f],d['t'][f]))
            keep=clean&d['arm'].astype(bool)
            require(np.array_equal(d['fair'][keep].astype(bool),d['cell'][keep]//100>=2),'Donor region coding changed')
            chunks.append({x:d[x][keep] for x in ('j','i','t','y','cell')})
        h={x:np.concatenate([v[x] for v in chunks]) for x in chunks[0]};del chunks,d
        q=frozen.r.arrays(frozen.r.io.read(job['query']));q['frame']=np.zeros(len(q['row_id']),np.int8)
        ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        A,B,C,selected,diag,info=frozen.r9_scores.score(h,q,ref)
        oracle=frozen.r9_scores.oracle(h,q,ref,A,B,C,selected,diag)
        require(len(selected)==len(q['row_id']) and (A['n']>=5).all(),'Primary all-time support changed')
        out=dict(row_id=q['row_id'],**diag)
        for name,v in [('A',A),('B',B),('C',C)]:out.update({x+'_'+name:a for x,a in v.items()})
        audits=[]
        for label,mask in [('competitive',h['cell']//100>=2),('noncompetitive',h['cell']//100<2)]:
            hh={x:v[mask] for x,v in h.items()};values,_=inputs.alltime(hh,q,ref)
            out.update({x+'_'+label:a for x,a in values.items()})
            # Independent masks verify partition counts and exclusion, even with zero eligible donors.
            for ix in np.unique(np.linspace(0,len(q['row_id'])-1,min(12,len(q['row_id'])),dtype=int)):
                keep=(hh['j']==q['opponent_id'][ix])&(hh['i']!=q['recipient_id'][ix])
                require(values['n'][ix]==keep.sum(),'Region donor count oracle failed')
                require(values['counterparts'][ix]==len(np.unique(hh['i'][keep])),'Region donor breadth oracle failed')
                if keep.any():
                    sub={x:v[keep] for x,v in hh.items()};mapping,_=frozen.r9_scores.reference_map(ref,frozen.r9_scores.event_month(sub['t']))
                    fold=int(frozen.r.num.user_hash(np.array([q['recipient_id'][ix]]))[0]%np.uint64(4))
                    weights,_=frozen.r9_scores.donor_weights(sub,ref,fold,mapping)
                    require(abs(values['adjusted'][ix]-np.mean(sub['y']-weights))<2e-10,'Region donor-score oracle failed')
            audits.append(dict(score=label,eligible_donors=len(hh['j'])))
        pq.write_table(pa.table(out),tmp/'scores.parquet',compression='zstd')
        j=np.concatenate([x[0] for x in fair]);t=np.concatenate([x[1] for x in fair]);order=np.lexsort((t,j))
        first=np.r_[True,j[order][1:]!=j[order][:-1]] if len(j) else np.array([],bool)
        pq.write_table(pa.table(dict(person=j[order][first],first_fair_ms=t[order][first])),tmp/'first_fair_PRIVATE.parquet',compression='zstd')
        save(tmp/'audit.json',dict(queries=len(q['row_id']),oracle=oracle,regions=audits,**info))
        return dict(queries=len(q['row_id']),eligible_donors=len(h['j']),oracle=oracle)
    return frozen.r.stable_stage(Path(job['out']),job['conf'],build,[job['query'],job['reference']]+[x['path'] for x in job['parts']])[1]

def prepare(a,run,conf,b):
    root=run/'PRIVATE/scores';query=root/'query';query.mkdir(parents=True,exist_ok=True)
    source=b['primary'];qkey=key([conf,sha(source),'timing_queries'])
    c=db(root/'spill_queries',a.memory_gb-2)
    try:
        # Upstream hash shards, with start/anchor retained for B and C.
        if not cached(query/'queries.parquet',qkey):
            copy_query(c,'SELECT row_id,recipient_id,opponent_id,month_code,archive_start_ms,anchor_ms FROM '+parq([source])+' ORDER BY row_id',query/'queries.parquet');seal(query/'queries.parquet',qkey)
        qs=query/'queries.parquet'
        def split(tmp):
            table_schema=pq.ParquetFile(qs).schema_arrow
            writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',table_schema,compression='zstd') for s in range(16)]
            try:
                for batch in pq.ParquetFile(qs).iter_batches(batch_size=131072,use_threads=False):
                    t=pa.Table.from_batches([batch]);h=frozen.r.num.user_hash(frozen.r.io.arr(t,'opponent_id'))%np.uint64(16)
                    for s,w in enumerate(writers):
                        if (h==s).any():w.write_table(t.filter(pa.array(h==s)))
            finally:
                for w in writers:w.close()
            return dict(rows=EXPECTED_N)
        shards=frozen.r.stable_stage(query/'shards',conf,split,[qs])[0]
    finally:c.close()
    bound=b['bound'];jobs=[dict(parts=[p for p in bound['parts'] if p['shard']==s],query=str(shards/f'{s:02}.parquet'),
          reference=bound['reference'],authors=bound['binding']['author_ids'],out=str(root/'parts'/f'{s:02}'),conf=conf,memory_gb=4.5) for s in range(16)]
    frozen.runtime.mapped(score_job,jobs,min(a.workers,2),a.memory_gb,'Timing and donor-region scores on the rebuilt primary cohort',30,90)
    def combine(tmp):
        c=db(tmp/'spill',a.memory_gb-2)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+parq([Path(j['out'])/'scores.parquet' for j in jobs]));ensure_unique(c,'s',EXPECTED_N)
            c.execute('CREATE VIEW old AS SELECT * FROM '+parq([b['primary_scores']]))
            require(c.execute('SELECT count(*) FROM s JOIN old USING(row_id)').fetchone()[0]==EXPECTED_N,'Diagnostic score IDs differ')
            for field in ('n_A','counterparts_A','expected_A','adjusted_A'):
                error=c.execute(f'SELECT max(abs(s.{field}-old.{field})) FROM s JOIN old USING(row_id)').fetchone()[0]
                require(error is not None and error<2e-10,'New diagnostic Score A differs from R12: '+field)
            copy_query(c,'SELECT * FROM s ORDER BY row_id',tmp/'scores.parquet')
            c.execute('CREATE VIEW h AS SELECT * FROM '+parq([Path(j['out'])/'first_fair_PRIVATE.parquet' for j in jobs]))
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]))
            require(c.execute('SELECT count(*)-count(DISTINCT person) FROM h').fetchone()[0]==0,'Duplicate learning-history person')
            copy_query(c,'SELECT q.row_id,coalesce(h.first_fair_ms<q.archive_start_ms,FALSE) full_chronology,q.fair_90>0 flag_90d FROM q LEFT JOIN h ON q.recipient_id=h.person ORDER BY q.row_id',tmp/'learning_PRIVATE.parquet')
            vals=c.execute('SELECT count(*),sum(n_B>=5 AND isfinite(adjusted_B)),sum(n_C>=5 AND isfinite(adjusted_C)),sum(n_B>=5 AND n_C>=5 AND isfinite(adjusted_B) AND isfinite(adjusted_C)),median(n_A),avg(n_A),sum(n_A),sum(n_after_all) FROM s').fetchone()
            info=dict(primary_rows=vals[0],before_supported_rows=vals[1],after_supported_rows=vals[2],common_timing_rows=vals[3],median_all_time_donors=vals[4],mean_all_time_donors=vals[5],donor_query_links=vals[6],post_anchor_donor_query_links=vals[7],
                      primary_selection_uses_only_A=True,before_cutoff='strictly before exposure start; no buffer',after_cutoff='strictly after exposure anchor')
            save(tmp/'diagnostics.json',info);return info
        finally:c.close()
    folder,info=frozen.r.stable_stage(root/'combined',conf,combine,[source,b['primary_scores']]+[Path(j['out'])/'scores.parquet' for j in jobs]+[Path(j['out'])/'first_fair_PRIVATE.parquet' for j in jobs])
    save(run/'report/score_diagnostics.json',load(folder/'diagnostics.json'))
    save(run/'PRIVATE/DIAGNOSTIC_SCORES.json',dict(scores=str(folder/'scores.parquet'),flags=str(folder/'learning_PRIVATE.parquet')))
    return folder/'scores.parquet',folder/'learning_PRIVATE.parquet'
