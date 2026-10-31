"""One donor pass shared by S0/F50; O50 is an identity-checked F50 subset."""
from ul_common import *
from iv_history import AsOf
import pe_scores

QUERY_TYPES = dict(row_id=pa.uint64(), opponent_id=pa.int64(), recipient_id=pa.int64(),
    archive_start_ms=pa.int64(), anchor_ms=pa.int64(), month_code=pa.int16(),
    n_7d=pa.int64(), counterparts_7d=pa.int64(), expected_7d=pa.float64(), adjusted_7d=pa.float64())

def prepare_queries(paths, root, conf):
    def build(tmp):
        schema = pa.schema([('frame',pa.int8())]+list(QUERY_TYPES.items()))
        writers = [pq.ParquetWriter(tmp/f'{s:02}.parquet', schema, compression='zstd') for s in range(16)]
        counts = {k:0 for k in FRAME}
        try:
            for sample, frame in FRAME.items():
                for batch in pq.ParquetFile(paths[sample]).iter_batches(batch_size=131072, columns=list(QUERY_TYPES)):
                    t = pa.Table.from_batches([batch]).select(list(QUERY_TYPES)).cast(pa.schema(QUERY_TYPES))
                    u.require(all(t[k].null_count==0 for k in QUERY_TYPES), 'Null query identity or archived score')
                    a = r.arrays(t)
                    u.require(np.all(a['anchor_ms'] >= a['archive_start_ms']), 'Focal anchor precedes game start')
                    shards = r.num.user_hash(a['opponent_id']) % np.uint64(16)
                    t = t.add_column(0,'frame',pa.array(np.full(len(t),frame,np.int8)))
                    for s, writer in enumerate(writers):
                        mask = shards == s
                        if mask.any():writer.write_table(t.filter(pa.array(mask)))
                    counts[sample] += len(t)
        finally:
            for writer in writers:writer.close()
        return dict(rows=counts, O50_donor_scans=0)
    return r.stable_stage(root, conf, build, [paths[k] for k in FRAME])[0]

def score(h, q, reference):
    """Full time totals; S0-only diagnostics before start / strictly after anchor.

    The primary score includes ties and decisions during the focal interval.
    Timing diagnostics exclude that interval and are never primary filters.
    Each query uses its original focal-month held-out state reference.
    """
    n = len(q['row_id']); selected = np.flatnonzero(q['frame']==FRAME['S0']); m = len(selected)
    u.require(np.all((q['month_code']>=0)&(q['month_code']<24)), 'Invalid reference month')
    pick = np.r_[np.arange(n), selected, selected]
    cuts = np.r_[np.full(n,np.iinfo(np.int64).max,np.int64),q['archive_start_ms'][selected],q['anchor_ms'][selected]+1]
    u.require(not len(h['t']) or np.max(h['t']) < np.iinfo(np.int64).max, 'Invalid donor timestamp')
    j=q['opponent_id'][pick];i=q['recipient_id'][pick];months=q['month_code'][pick]
    ji=AsOf([h['j']],h['t'],[j],cuts)
    pi=AsOf([h['j'],h['i']],h['t'],[j,i],cuts)
    count=ji.count-pi.count; grants=ji.sums(h['y'])-pi.sums(h['y'])
    # Distinct counterparts in the full donor period, minus the excluded pair.
    first=pi.order[pi.starts]
    breadth=AsOf([h['j'][first]],h['t'][first],[j[:n]],cuts[:n]).count-(pi.count[:n]>0)
    u.require(np.all((count>=0)&(grants>=0)&(grants<=count)) and np.all(breadth>=0), 'Impossible pair-excluded totals')
    jf=(r.num.user_hash(h['j'])%np.uint64(4)).astype(int)
    qjf=(r.num.user_hash(j)%np.uint64(4)).astype(int)
    rf=(r.num.user_hash(i)%np.uint64(4)).astype(int)
    predicted=np.full(len(pick),np.nan)
    for month in np.unique(months):
        for fold in np.unique(rf[months==month]):
            use=(months==month)&(rf==fold)
            model=reference[0,int(month),:,int(fold),:]
            valid=np.isfinite(model).all(axis=1)
            use &= valid[qjf]
            if not use.any():continue
            weights=np.where(valid[jf],model[jf,h['cell']],0.)
            value=ji.sums(weights)-pi.sums(weights)
            predicted[use]=value[use]
    def mean(g,p,c):
        raw=np.divide(g,c,out=np.full(len(c),np.nan),where=c>0)
        expected=np.divide(p,c,out=np.full(len(c),np.nan),where=c>0)
        return dict(n=c,grants=g,raw=raw,expected=expected,adjusted=raw-expected)
    full=mean(grants[:n],predicted[:n],count[:n]);full['counterparts']=breadth
    before=mean(grants[n:n+m],predicted[n:n+m],count[n:n+m])
    after=mean(grants[selected]-grants[n+m:],predicted[selected]-predicted[n+m:],count[selected]-count[n+m:])
    gap=count[selected]-before['n']-after['n']
    u.require(np.all(gap>=0), 'Timing partition has negative interval count')
    return full, before, after, selected, gap

def oracle_checks(h,q,reference,full,before,after,selected,limit=12):
    """Independent row masks verify actual production data, including unseen pairs."""
    chosen=np.unique(np.linspace(0,len(q['row_id'])-1,min(limit,len(q['row_id'])),dtype=int)) if len(q['row_id']) else []
    positions={int(k):v for v,k in enumerate(selected)}
    err=0.
    for k in chosen:
        j=q['opponent_id'][k];i=q['recipient_id'][k]
        use=(h['j']==j)&(h['i']!=i)
        model=reference[0,int(q['month_code'][k]),int(r.num.user_hash(np.array([j]))[0]%np.uint64(4)),
                        int(r.num.user_hash(np.array([i]))[0]%np.uint64(4))]
        cases=[(full,k,use)]
        if int(k) in positions:
            cases += [(before,positions[int(k)],use&(h['t']<q['archive_start_ms'][k])),
                      (after,positions[int(k)],use&(h['t']>q['anchor_ms'][k]))]
        for got,loc,mask in cases:
            u.require(got['n'][loc]==int(mask.sum()), 'Independent mask count mismatch')
            u.require(got['grants'][loc]==float(h['y'][mask].sum()), 'Independent grant total mismatch')
            if mask.any():
                want=float(np.mean(h['y'][mask]-model[h['cell'][mask]]))
                delta=abs(got['adjusted'][loc]-want)
                u.require(np.isfinite(want) and delta<2e-10, 'Independent residual score mismatch')
                err=max(err,delta)
        u.require(full['counterparts'][k]==len(np.unique(h['i'][use])), 'Independent breadth mismatch')
    return dict(queries_checked=len(chosen),maximum_absolute_score_error=err)

def score_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        chunks=[];source_rows=0
        for rec in job['parts']:
            r.io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
            a=r.arrays(r.io.read(rec['path'],['j','i','t','y','arm','cell']))
            u.require(len(a['j'])==rec['rows'],'Donor row count changed');source_rows+=len(a['j'])
            keep=a['arm'].astype(bool)&~np.isin(a['j'],job['authors'])&~np.isin(a['i'],job['authors'])
            chunks.append({k:v[keep] for k,v in a.items() if k!='arm'})
        h={k:np.concatenate([a[k] for a in chunks]) for k in ('j','i','t','y','cell')};del chunks
        u.require(np.all(r.num.user_hash(h['j'])%np.uint64(16)==job['shard']),'Wrong donor shard')
        u.require(np.isin(h['y'],[0,1]).all() and np.all((h['cell']>=0)&(h['cell']<500)),'Invalid donor choice/state')
        q=r.arrays(r.io.read(job['queries']));ref=np.load(job['reference'],allow_pickle=False,mmap_mode='r')
        full,before,after,selected,gap=score(h,q,ref)
        checks=oracle_checks(h,q,ref,full,before,after,selected)
        u.require(np.all(full['n']>=q['n_7d']) and np.all(full['n']>=5),'Full histories lost prior support')
        u.require(np.isfinite(full['adjusted']).all(),'Unavailable frozen state reference')
        result=dict(frame=q['frame'],row_id=q['row_id'])
        result.update({k+'_all_time':v for k,v in full.items()})
        for tag,values in [('before',before),('after',after)]:
            for k in ('n','adjusted'):
                a=np.full(len(q['row_id']),-1 if k=='n' else np.nan,dtype=np.int64 if k=='n' else float)
                a[selected]=values[k];result[k+'_'+tag]=a
        interval=np.full(len(q['row_id']),-1,np.int64);interval[selected]=gap;result['n_focal_interval']=interval
        r.io.table(tmp/'scores.parquet',pa.table(result))
        info=dict(shard=job['shard'],source_rows=source_rows,eligible_author_clean_donor_rows=len(h['j']),
            queries=len(q['row_id']),independent_oracle=checks,
            minimum_donor_time_ms=int(h['t'].min()) if len(h['t']) else None,
            maximum_donor_time_ms=int(h['t'].max()) if len(h['t']) else None)
        r.io.js(tmp/'summary.json',info);return info
    deps=[v['path'] for v in job['parts']]+[job['queries'],job['reference']]
    return r.stable_stage(Path(job['output']),job['conf'],build,deps)[1]

def combine(shards, sources, previous_scores, root, conf, memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1);info={}
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(shards))
            u.require(c.execute('SELECT count(*)-count(DISTINCT (frame,row_id)) FROM s').fetchone()[0]==0,
                      'Duplicate frame/row score identity')
            for sample,frame in FRAME.items():
                c.execute('CREATE OR REPLACE VIEW q AS SELECT row_id FROM '+u.parq([sources[sample]]))
                c.execute('CREATE OR REPLACE VIEW old AS SELECT row_id,n_24h,adjusted_24h FROM '+u.parq([previous_scores[sample]]))
                n=pq.ParquetFile(sources[sample]).metadata.num_rows
                for view in ('q','old'):
                    u.require(c.execute(f'SELECT count(*),count(DISTINCT row_id) FROM {view}').fetchone()==(n,n),
                              'Duplicate or unexpected archived frame/score rows')
                u.require(c.execute(f'SELECT count(*) FROM s JOIN q USING(row_id) JOIN old USING(row_id) WHERE frame={frame}').fetchone()[0]==n,
                          'Archived score or current row identities differ')
                u.require(c.execute(f'SELECT count(*) FROM s WHERE frame={frame}').fetchone()[0]==n,'Extra current scores')
                u.require(c.execute(f'SELECT count(*) FROM s JOIN old USING(row_id) WHERE frame={frame} AND n_all_time<n_24h').fetchone()[0]==0,
                          'Unrestricted history smaller than reviewed 24-hour history')
                r.io.copy(c,f'SELECT s.* EXCLUDE(frame) FROM s WHERE frame={frame} ORDER BY row_id',tmp/(sample+'.parquet'))
                row=c.execute(f'''SELECT count(*),median(n_all_time),median(n_24h),avg(n_all_time-n_24h),
                    corr(adjusted_all_time,adjusted_24h),sum(abs(adjusted_all_time-adjusted_24h)>2e-10)
                    FROM s JOIN old USING(row_id) WHERE frame={frame}''').fetchone()
                info[sample]=dict(rows=row[0],median_full_decisions=row[1],median_24h_decisions=row[2],
                    mean_added_decisions=row[3],correlation_full_24h=row[4],changed_scores=row[5])
            row=c.execute('''SELECT count(*),sum(n_before>=5 AND n_after>=5),
                corr(adjusted_before,adjusted_after) FILTER(WHERE n_before>=5 AND n_after>=5),
                avg(n_after*1.0/n_all_time),sum(n_focal_interval>0)
                FROM s WHERE frame=0''').fetchone()
            info['timing']=dict(S0_rows=row[0],common_supported_rows=row[1],before_after_score_correlation=row[2],
                mean_share_of_full_donors_after_anchor=row[3],rows_with_other_donor_event_in_focal_interval=row[4],
                common_rule='n_before>=5 AND n_after>=5 with finite scores; no primary rows removed')
            r.io.js(tmp/'summary.json',info);return info
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,shards+[sources[k] for k in FRAME]+[previous_scores[k] for k in FRAME])
    return {k:folder/(k+'.parquet') for k in FRAME}, public_stage(info)

def ordinary_scores(paths,scores,root,conf,memory):
    return pe_scores.subset_scores(paths['F50'],paths['O50'],scores,root,conf,memory)
