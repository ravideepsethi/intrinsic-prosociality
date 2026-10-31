"""Candidate stream rebuilt before support, spacing and observation cuts."""
from bootstrap import *
import audit_logic

def first_pair_job(job):
    def build(tmp):
        q=pq.read_table(job['query']);keys=q['pair_key'].to_numpy();out=np.full(len(keys),np.iinfo(np.int64).max,np.int64)
        r=job['record'];p=Path(r['path']);require(c.frozen.r.io.sig(p)==r['signature'],'Chronology signature changed')
        f=pq.ParquetFile(p);idx=f.schema_arrow.get_field_index('utc_ms')
        for g in range(f.metadata.num_row_groups):
            stats=f.metadata.row_group(g).column(idx).statistics
            if stats and stats.has_min_max and stats.min>job['cutoff']:continue
            for b in f.iter_batches(row_groups=[g],columns=['utc_ms','white_id','black_id'],batch_size=262144,use_threads=False):
                t,w,z=[b.column(k).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for k in range(3)]
                good=(t>0)&(t<=job['cutoff'])&(w>=0)&(z>=0)&(w<2**32)&(z<2**32)&(w!=z)
                t,w,z=t[good],w[good],z[good]
                pk=(np.minimum(w,z).astype(np.uint64)<<np.uint64(32))|np.maximum(w,z).astype(np.uint64)
                ix=np.searchsorted(keys,pk);good=ix<len(keys);good[good]&=keys[ix[good]]==pk[good]
                np.minimum.at(out,ix[good],t[good])
        require(c.frozen.r.io.sig(p)==r['signature'],'Chronology changed during first-pair scan')
        np.save(tmp/'minima.npy',out,allow_pickle=False);return dict(pairs=len(keys),found=int((out<np.iinfo(np.int64).max).sum()))
    return stage(job['out'],c.key([job['conf'],job['record']]),build,[job['query']])[1]

def build(a,run,conf,auth,b):
    root=run/'PRIVATE/exposures';main=[r['path'] for r in auth['material']['records']]
    original=auth['legacy']['raw'];oldparts=[r['path'] for r in auth['legacy']['bound']['parts']]
    def candidates(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            # Hive inference is disabled everywhere; month is supplied explicitly
            # only when the frozen full-width file does not carry that field.
            tables=[]
            for r in auth['material']['records']:
                extra='' if 'month' in c.columns(r['path']) else ','+c.quote(r['month'])+' AS month'
                tables.append('SELECT *'+extra+' FROM '+c.parq([r['path']]))
            db.execute('CREATE VIEW m AS '+' UNION ALL '.join(tables))
            view(db,'old',original);view(db,'h',oldparts)
            copy(db,audit_logic.exposure_sql('m'),tmp/'all_competitive.parquet')
            view(db,'q',tmp/'all_competitive.parquet')
            # Frozen analysis is the complete real-time, arm-eligible first-pair
            # stream before all-time support/window cuts. Reclassification can
            # introduce previously ineligible arm rows; these receive fresh
            # factual first-pair queries. Retained old arm rows keep only the
            # factual first-pair answer, never their previous eligibility.
            c.ensure(db,'''SELECT count(*) FROM old o JOIN q USING(game_id) WHERE
                o.recipient_id<>q.recipient_id OR o.opponent_id<>q.opponent_id
                OR o.archive_start_ms<>q.archive_start_ms OR o.anchor_ms<>q.anchor_ms''','Exposure factual bridge differs')
            copy(db,'''SELECT q.*,o.row_id AS legacy_row_id,h.y AS original_grant,
              (h.y OR m.timeout_chooser_win) AS original_arm,
              o.row_id IS NOT NULL AS cached_first_pair
              FROM q JOIN m USING(game_id) JOIN h ON q.game_id=h.gid LEFT JOIN old o USING(game_id)
              WHERE q.arm_eligible AND '''+audit_logic.realtime_sql().replace('speed IN','q.speed IN').replace('tc_base_s>','q.tc_base_s>')+
              ' ORDER BY q.row_id',tmp/'candidates.parquet')
            view(db,'candidate',tmp/'candidates.parquet')
            c.ensure(db,'SELECT count(*) FROM candidate WHERE cached_first_pair AND NOT original_arm','Old first-pair row was not an eligible arm')
            copy(db,'''SELECT pair_key,min(archive_start_ms)::BIGINT cutoff FROM candidate
              WHERE NOT original_arm AND NOT cached_first_pair GROUP BY pair_key ORDER BY pair_key''',tmp/'new_pair_queries.parquet')
            return dict(candidates=rows(tmp/'candidates.parquet'),new_pairs=rows(tmp/'new_pair_queries.parquet'))
        finally:db.close()
    prep,info=stage(root/'candidates',conf,candidates,main+[original]+oldparts)
    query=prep/'new_pair_queries.parquet';n=rows(query);pairpath=root/'pair_result'
    jobs=[]
    if n:
        cutoff=int(pq.read_table(query,columns=['cutoff'])['cutoff'].to_numpy().max())
        log(f'{n:,} newly eligible pairs need factual first-meeting dates; scanning only three cached chronology columns.')
        for k,r in enumerate(b['bound']['binding']['source']['chron']):
            if r.get('minimum') is not None and r['minimum']>cutoff:continue
            jobs.append(dict(query=str(query),record=r,cutoff=cutoff,conf=conf,out=str(root/'pair_files'/f'{k:04}')))
        c.mapped(first_pair_job,jobs,min(a.workers,4),'First-pair facts for newly eligible arms')
    def combine(tmp):
        q=pq.read_table(query);mins=np.full(n,np.iinfo(np.int64).max,np.int64)
        for j in jobs:np.minimum(mins,np.load(Path(j['out'])/'minima.npy'),out=mins)
        require(np.all(mins<=q['cutoff'].to_numpy()),'A new exposure has no factual pair history')
        pq.write_table(pa.table(dict(pair_key=q['pair_key'],first_pair_ms=mins)),tmp/'pairs.parquet',compression='zstd')
        return dict(queried=n)
    pr,_=stage(pairpath,conf,combine,[query]+[Path(j['out'])/'minima.npy' for j in jobs])
    def finish(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'q',prep/'candidates.parquet');view(db,'p',pr/'pairs.parquet')
            copy(db,f'''SELECT q.*,
              archive_start_ms-{97*DAY}>={int(c.phase_inputs.core.STARTS[0])} history_window_complete,
              archive_start_ms-{90*DAY}>={int(c.phase_inputs.core.STARTS[0])} history90_complete,
              FALSE previous_frame
              FROM q LEFT JOIN p USING(pair_key)
              WHERE cached_first_pair OR (NOT original_arm AND first_pair_ms=archive_start_ms)
              ORDER BY row_id''',tmp/'raw.parquet')
            view(db,'raw',tmp/'raw.parquet');c.ensure_unique(db,'raw')
            require(db.execute('SELECT count(*),count(DISTINCT game_id) FROM raw').fetchone()[0]==rows(tmp/'raw.parquet'),'Raw exposure count differs')
            return dict(raw_exposures=rows(tmp/'raw.parquet'),fresh_pair_queries=n,first_recipient_recomputed_before_arm=True)
        finally:db.close()
    out,result=stage(root/'raw',conf,finish,[prep/'candidates.parquet',pr/'pairs.parquet'])
    save(run/'report/EXPOSURE_REBUILD.json',result)
    return out/'raw.parquet'

def score_job(job):
    def build(tmp):
        chunks=[]
        for r in job['parts']:
            t=pq.read_table(r['path'],columns=['j','i','t','y','arm','cell']);h={k:t[k].to_numpy() for k in t.column_names}
            mask=h.pop('arm').astype(bool);chunks.append({k:v[mask] for k,v in h.items()})
        h={k:np.concatenate([x[k] for x in chunks]) for k in chunks[0]};del chunks
        t=pq.read_table(job['query']);q={k:t[k].to_numpy() for k in t.column_names};ref=np.load(job['reference'],mmap_mode='r')
        out=dict(row_id=q['row_id']);audit={}
        if len(q['row_id']):
            q['frame']=np.zeros(len(q['row_id']),np.int8)
            A,B,C,sel,diag,_=c.frozen.r9_scores.score(h,q,ref)
            c.frozen.r9_scores.oracle(h,q,ref,A,B,C,sel,diag)
            for label,s in [('A',A),('B',B),('C',C)]:out.update({k+'_'+label:v for k,v in s.items() if k!='grants'})
            for label,mask in [('competitive',h['cell']//100>=2),('noncompetitive',h['cell']//100<2)]:
                sub={k:v[mask] for k,v in h.items()};s,_=c.inputs.alltime(sub,q,ref)
                out.update({k+'_'+label:v for k,v in s.items()})
            audit=dict(queries=len(q['row_id']),donors=len(h['j']),oracle=True)
        else:
            for label in ('A','B','C','competitive','noncompetitive'):
                for k in ('n','counterparts','expected','adjusted'):out[k+'_'+label]=np.empty(0,np.int64 if k in ('n','counterparts') else float)
        pq.write_table(pa.table(out),tmp/'scores.parquet',compression='zstd');return audit
    return stage(job['out'],job['conf'],build,[job['query'],job['reference']]+[r['path'] for r in job['parts']])[1]

def scores(a,run,conf,b,raw):
    root=run/'PRIVATE/receipt_scores'
    def split(tmp):
        cols=['row_id','recipient_id','opponent_id','month_code','archive_start_ms','anchor_ms']
        pf=pq.ParquetFile(raw);schema=pa.schema([pf.schema_arrow.field(k) for k in cols])
        writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd') for s in range(16)]
        try:
            for batch in pf.iter_batches(columns=cols,batch_size=131072,use_threads=False):
                t=pa.Table.from_batches([batch]);sh=c.frozen.r.num.user_hash(t['opponent_id'].to_numpy())%np.uint64(16)
                for s,w in enumerate(writers):w.write_table(t.filter(pa.array(sh==s)))
        finally:
            for w in writers:w.close()
        return dict(rows=rows(raw))
    q,_=stage(root/'queries',conf,split,[raw]);jobs=[]
    for s in range(16):jobs.append(dict(query=str(q/f'{s:02}.parquet'),reference=b['bound']['reference'],parts=[r for r in b['bound']['parts'] if r['shard']==s],conf=conf,out=str(root/'parts'/f'{s:02}')))
    c.mapped(score_job,jobs,min(2,a.workers),'All-time, earlier, later and state-specific scores')
    paths=[Path(j['out'])/'scores.parquet' for j in jobs]
    def join(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'s',paths);view(db,'q',raw);c.assert_coverage(db,'q','s')
            copy(db,'SELECT * FROM s ORDER BY row_id',tmp/'scores.parquet');return dict(rows=rows(raw))
        finally:db.close()
    out,_=stage(root/'combined',conf,join,paths+[raw]);return out/'scores.parquet'

def selection(a,run,conf,raw,scores):
    def build(tmp):
        db=connect(tmp,a.memory_gb-2)
        try:
            view(db,'r',raw);view(db,'s',scores)
            d=db.execute('SELECT r.row_id,r.recipient_id,r.archive_start_ms,r.anchor_ms,r.complete90,r.history_window_complete,r.history90_complete,s.n_A,s.adjusted_A,s.expected_A FROM r JOIN s USING(row_id) ORDER BY recipient_id,archive_start_ms,row_id').fetchnumpy()
            finite=np.isfinite(d['adjusted_A'])&np.isfinite(d['expected_A']);out={'row_id':d['row_id']}
            for minimum in (3,5,10,20):
                ok=(d['n_A']>=minimum)&finite
                for days in ((30,90) if minimum==5 else (90,)):
                    out[f'spaced{days}_n{minimum}']=audit_logic.spaced(d['recipient_id'],d['archive_start_ms'],d['anchor_ms'],ok,days)
            out['supported']=(d['n_A']>=5)&finite
            out['uniform_keep']=out['supported']&d['complete90'].astype(bool)&d['history90_complete'].astype(bool)
            out['legacy_windows']=d['complete90'].astype(bool)&d['history_window_complete'].astype(bool)
            db.register('f',pa.table(out));copy(db,'SELECT * FROM f ORDER BY row_id',tmp/'flags.parquet')
            copy(db,'''SELECT r.*,f.* EXCLUDE(row_id),spaced90_n5 AND legacy_windows AS legacy_primary,
              spaced90_n5 AS spaced90,spaced30_n5 AS spaced30
              FROM r JOIN f USING(row_id) WHERE uniform_keep OR (safely_three)
              ORDER BY row_id'''.replace('(safely_three)','(r.complete90 AND r.history90_complete AND f.spaced90_n3)'),tmp/'source.parquet')
            copy(db,'SELECT s.* FROM s JOIN '+c.parq([tmp/'source.parquet'])+' q USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            return dict(pre_support=rows(raw),primary=int(out['uniform_keep'].sum()),spaced_legacy=int((out['spaced90_n5']&out['legacy_windows']).sum()))
        finally:db.close()
    out,result=stage(run/'PRIVATE/selection90',conf,build,[raw,scores]);save(run/'report/SELECTION.json',result);return out/'source.parquet',out/'scores.parquet'
