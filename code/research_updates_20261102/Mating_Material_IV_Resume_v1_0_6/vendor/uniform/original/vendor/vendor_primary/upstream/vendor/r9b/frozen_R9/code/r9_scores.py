"""One projected donor read; old-score replay and donor-month A/B/C together."""
from r9_common import *
from iv_history import AsOf
import ul_scores, pe_scores

def prepare_queries(paths,root,conf):
    def build(tmp):
        schema=pa.schema([('frame',pa.int8())]+list(ul_scores.QUERY_TYPES.items()))
        writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd') for s in range(16)]
        counts={}
        try:
            for sample,frame in FRAME.items():
                counts[sample]=0
                for batch in pq.ParquetFile(paths[sample]).iter_batches(batch_size=131072,columns=list(ul_scores.QUERY_TYPES)):
                    t=pa.Table.from_batches([batch]).select(list(ul_scores.QUERY_TYPES)).cast(pa.schema(ul_scores.QUERY_TYPES))
                    u.require(all(t[k].null_count==0 for k in ul_scores.QUERY_TYPES),'Null query field')
                    a=r.arrays(t);u.require(np.all(a['anchor_ms']>=a['archive_start_ms']),'Anchor before game start')
                    shards=r.num.user_hash(a['opponent_id'])%np.uint64(16)
                    t=t.add_column(0,'frame',pa.array(np.full(len(t),frame,np.int8)))
                    for s,w in enumerate(writers):
                        use=shards==s
                        if use.any():w.write_table(t.filter(pa.array(use)))
                    counts[sample]+=len(t)
        finally:
            for w in writers:w.close()
        return dict(rows=counts,ordinary_scanned_separately=False)
    return r.stable_stage(root,conf,build,[paths[k] for k in FRAME])[0]

def event_month(t):
    return (np.asarray(t,dtype='datetime64[ms]').astype('datetime64[M]').astype(np.int64)
            -np.datetime64('2023-11','M').astype(np.int64)).astype(np.int16)

def reference_map(reference,months):
    """A deterministic fallback per held-out pair of folds, independent of outcomes."""
    result={};audit=[]
    for month in np.unique(months):
        for jf in range(4):
            for rf in range(4):
                valid=np.flatnonzero(np.isfinite(reference[0,:,jf,rf,:]).all(axis=1))
                u.require(len(valid)>0,'No usable state model for a held-out pair of folds')
                previous=valid[valid<=month]
                chosen=int(previous[-1] if len(previous) else valid[0])
                result[(int(month),jf,rf)]=chosen
                if chosen!=month:audit.append(dict(donor_month_code=int(month),chooser_fold=jf,recipient_fold=rf,
                    fallback_model_month_code=chosen,policy=DEFINITION['reference_fallback']))
    return result,audit

def donor_weights(h,reference,rf,mapping):
    months=event_month(h['t']);jf=(r.num.user_hash(h['j'])%np.uint64(4)).astype(int)
    chosen=np.empty(len(months),np.int16)
    for mo in np.unique(months):
        for j in range(4):chosen[(months==mo)&(jf==j)]=mapping[(int(mo),j,int(rf))]
    weights=reference[0,chosen,jf,int(rf),h['cell']]
    u.require(np.isfinite(weights).all() and np.all((weights>=0)&(weights<=1)),'Invalid donor-month prediction')
    return weights,chosen!=months

def score(h,q,reference):
    n=len(q['row_id']);sel=np.flatnonzero(q['frame']==0);m=len(sel)
    # A, B on S0, and <= anchor on every frame (for donor timing diagnostics).
    pick=np.r_[np.arange(n),sel,np.arange(n)]
    cuts=np.r_[np.full(n,np.iinfo(np.int64).max,np.int64),q['archive_start_ms'][sel],q['anchor_ms']+1]
    j=q['opponent_id'][pick];i=q['recipient_id'][pick]
    ji=AsOf([h['j']],h['t'],[j],cuts);pi=AsOf([h['j'],h['i']],h['t'],[j,i],cuts)
    counts=ji.count-pi.count;wins=ji.sums(h['y'])-pi.sums(h['y'])
    first=pi.order[pi.starts]
    breadth=AsOf([h['j'][first]],h['t'][first],[j[:n+m]],cuts[:n+m]).count-(pi.count[:n+m]>0)
    # A counterpart is present after the anchor iff its last decision is later.
    last=pi.order[np.r_[pi.starts[1:]-1,len(pi.order)-1]] if len(pi.order) else np.array([],int)
    rev=AsOf([h['j'][last]],-h['t'][last],[q['opponent_id'][sel]],-q['anchor_ms'][sel]).count
    pair_after=pi.count[sel]-pi.count[n+m+sel]
    cbreadth=rev-(pair_after>0)
    mapping,fallback_map=reference_map(reference,event_month(h['t']))
    rf=(r.num.user_hash(i)%np.uint64(4)).astype(int)
    predicted=np.zeros(len(pick));fallback=np.zeros(len(pick),np.int64);affected_by_rf=[]
    for fold in np.unique(rf):
        weights,affected=donor_weights(h,reference,fold,mapping);use=rf==fold
        total=ji.sums(weights)-pi.sums(weights);predicted[use]=total[use]
        total=ji.sums(affected.astype(np.int64))-pi.sums(affected.astype(np.int64));fallback[use]=np.rint(total[use]).astype(np.int64)
        affected_by_rf.append(dict(recipient_fold=int(fold),unique_source_donors_affected=int(affected.sum())))
    def make(c,g,p,b):
        raw=np.divide(g,c,out=np.full(len(c),np.nan),where=c>0)
        expected=np.divide(p,c,out=np.full(len(c),np.nan),where=c>0)
        u.require(np.all((c>=0)&(b>=0)&(b<=c)&(g>=0)&(g<=c)),'Impossible donor totals')
        return dict(n=c,grants=g,counterparts=b,expected=expected,adjusted=raw-expected)
    A=make(counts[:n],wins[:n],predicted[:n],breadth[:n])
    B=make(counts[n:n+m],wins[n:n+m],predicted[n:n+m],breadth[n:n+m])
    nafter=counts[:n]-counts[n+m:]
    C=make(nafter[sel],wins[sel]-wins[n+m+sel],predicted[sel]-predicted[n+m+sel],cbreadth)
    del ji,pi,j,i,cuts,counts,wins,predicted
    hm=event_month(h['t']);zero=np.zeros(len(hm),np.int64);one=np.ones(n,np.int64)
    samej=AsOf([h['j'],hm],zero,[q['opponent_id'],q['month_code']],one).count
    samep=AsOf([h['j'],h['i'],hm],zero,[q['opponent_id'],q['recipient_id'],q['month_code']],one).count
    mismatch=A['n']-(samej-samep)
    return A,B,C,sel,dict(n_after_all=nafter,n_month_mismatch=mismatch,n_fallback=fallback[:n]),dict(
        fallback_model_map=fallback_map,fallback_unique_source_donors_by_recipient_fold=affected_by_rf)

def oracle(h,q,reference,A,B,C,sel,diag,limit=16):
    mapping,_=reference_map(reference,event_month(h['t']));where={int(k):l for l,k in enumerate(sel)}
    chosen=np.unique(np.linspace(0,len(q['row_id'])-1,min(limit,len(q['row_id'])),dtype=int)) if len(q['row_id']) else []
    error=0.
    for k in chosen:
        mask=(h['j']==q['opponent_id'][k])&(h['i']!=q['recipient_id'][k])
        hh={name:value[mask] for name,value in h.items()}
        rf=int(r.num.user_hash(np.array([q['recipient_id'][k]]))[0]%np.uint64(4))
        weights,fallback=donor_weights(hh,reference,rf,mapping)
        cases=[(A,k,np.ones(len(hh['t']),bool))]
        if k in where:cases += [(B,where[k],hh['t']<q['archive_start_ms'][k]),(C,where[k],hh['t']>q['anchor_ms'][k])]
        for got,ix,use in cases:
            u.require(got['n'][ix]==use.sum() and got['counterparts'][ix]==len(np.unique(hh['i'][use])),'Donor oracle count/breadth failed')
            if use.any():
                delta=abs(got['adjusted'][ix]-np.mean(hh['y'][use]-weights[use]));error=max(error,float(delta))
                u.require(delta<2e-10,'Donor-month residual oracle failed')
        u.require(diag['n_month_mismatch'][k]==np.sum(event_month(hh['t'])!=q['month_code'][k]),'Month mismatch oracle failed')
        u.require(diag['n_fallback'][k]==np.sum(fallback),'Fallback count oracle failed')
    return dict(queries_checked=len(chosen),maximum_absolute_difference=error)

def score_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        chunks=[];fair_chunks=[];source=0
        for rec in job['parts']:
            r.io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
            a=r.arrays(r.io.read(rec['path'],['j','i','t','y','arm','cell','fair']))
            u.require(len(a['j'])==rec['rows'],'Donor partition count changed');source+=len(a['j'])
            clean=~np.isin(a['j'],job['authors'])&~np.isin(a['i'],job['authors'])
            fair=clean&a['fair'].astype(bool)
            fair_chunks.append((a['j'][fair],a['t'][fair]))
            use=clean&a['arm'].astype(bool)
            chunks.append({k:a[k][use] for k in ('j','i','t','y','cell')})
        h={k:np.concatenate([a[k] for a in chunks]) for k in ('j','i','t','y','cell')};del chunks,a
        u.require(np.all(r.num.user_hash(h['j'])%np.uint64(16)==job['shard']),'Donor shard differs')
        u.require(np.isin(h['y'],[0,1]).all() and np.all((h['cell']>=0)&(h['cell']<500)),'Donor choice/cell invalid')
        fj=np.concatenate([a[0] for a in fair_chunks]);ft=np.concatenate([a[1] for a in fair_chunks]);del fair_chunks
        order=np.lexsort((ft,fj));first=np.r_[True,fj[order][1:]!=fj[order][:-1]] if len(order) else np.array([],bool)
        r.io.table(tmp/'first_fair_PRIVATE.parquet',pa.table(dict(person=fj[order][first],first_fair_ms=ft[order][first])))
        del fj,ft,order,first
        q=r.arrays(r.io.read(job['queries']));ref=np.load(job['reference'],allow_pickle=False,mmap_mode='r')
        # The exact prior algorithm is evaluated in this same decoded donor pass.
        prior,before,after,selected,gap=ul_scores.score(h,q,ref)
        replay=dict(frame=q['frame'],row_id=q['row_id'],**{k+'_all_time':v for k,v in prior.items()})
        for name,v in [('before',before),('after',after)]:
            for field in ('n','adjusted'):
                out=np.full(len(q['row_id']),-1 if field=='n' else np.nan,dtype=np.int64 if field=='n' else float)
                out[selected]=v[field];replay[field+'_'+name]=out
        out=np.full(len(q['row_id']),-1,np.int64);out[selected]=gap;replay['n_focal_interval']=out
        r.io.table(tmp/'replay.parquet',pa.table(replay))
        oldchecks=ul_scores.oracle_checks(h,q,ref,prior,before,after,selected)
        del before,after,gap,replay,out
        A,B,C,selected,diag,meta=score(h,q,ref)
        u.require(np.array_equal(A['n'],prior['n']) and np.array_equal(A['counterparts'],prior['counterparts']),
                  'Donor-month reindexing changed the all-time donor set')
        checks=oracle(h,q,ref,A,B,C,selected,diag)
        u.require(np.all(A['n']>=5) and np.isfinite(A['adjusted']).all(),'A donor support failed on frozen frame')
        output=dict(frame=q['frame'],row_id=q['row_id'],old_adjusted=prior['adjusted'],old_expected=prior['expected'],**diag)
        for variant,v in [('A',A),('B',B),('C',C)]:
            for field,value in v.items():
                if variant=='A':output[field+'_'+variant]=value
                else:
                    a=np.full(len(q['row_id']),-1 if field in ('n','counterparts') else np.nan,dtype=np.int64 if field in ('n','counterparts') else float)
                    a[selected]=value;output[field+'_'+variant]=a
        r.io.table(tmp/'scores.parquet',pa.table(output))
        info=dict(shard=job['shard'],source_rows=source,eligible_author_clean_donor_rows=len(h['j']),queries=len(q['row_id']),
            oracle=checks,baseline_oracle=oldchecks,**meta)
        r.io.js(tmp/'summary.json',info);return info
    return r.stable_stage(Path(job['output']),job['conf'],build,[v['path'] for v in job['parts']]+[job['queries'],job['reference']])[1]

def combine(jobs,paths,base,root,conf,memory):
    shards=[Path(j['output'])/'scores.parquet' for j in jobs];replays=[Path(j['output'])/'replay.parquet' for j in jobs]
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1);checks=[];diagnostics=[]
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(shards));c.execute('CREATE VIEW p AS SELECT * FROM '+u.parq(replays))
            for view in ('s','p'):u.require(c.execute(f'SELECT count(*)-count(DISTINCT (frame,row_id)) FROM {view}').fetchone()[0]==0,'Duplicate score identity')
            for sample,frame in FRAME.items():
                n=pq.ParquetFile(paths[sample]).metadata.num_rows
                c.execute('CREATE OR REPLACE VIEW q AS SELECT row_id FROM '+u.parq([paths[sample]]))
                u.require(c.execute(f'SELECT count(*),count(DISTINCT s.row_id) FROM s JOIN q USING(row_id) WHERE frame={frame}').fetchone()==(n,n),'Score/frame identity failed')
                u.require(c.execute(f'SELECT count(*) FROM s WHERE frame={frame}').fetchone()[0]==n,'Extra score rows')
                if sample=='S0':
                    previous=base/'scores_combined'/(sample+'.parquet');c.execute('CREATE OR REPLACE VIEW b AS SELECT * FROM '+u.parq([previous]))
                    schema=pq.ParquetFile(previous).schema_arrow
                    u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM b').fetchone()==(n,n),'Old score identity failed')
                    for field in schema:
                        if field.name=='row_id':continue
                        k=field.name
                        # Null timing diagnostics are retained, never converted to zero.
                        if pa.types.is_floating(field.type):
                            bad=f'(p."{k}" IS DISTINCT FROM b."{k}") AND NOT coalesce(abs(p."{k}"-b."{k}")<=2e-10,FALSE)'
                        else:bad=f'p."{k}" IS DISTINCT FROM b."{k}"'
                        count=c.execute(f'SELECT count(*) FROM p JOIN b USING(row_id) WHERE p.frame={frame} AND ({bad})').fetchone()[0]
                        u.require(count==0,'Step 0 saved-score replay failed: '+sample+'/'+k)
                        maximum=c.execute(f'SELECT max(abs(p."{k}"-b."{k}")) FROM p JOIN b USING(row_id) WHERE p.frame={frame}').fetchone()[0]
                        checks.append(dict(sample=sample,field=k,rows=n,passed=True,maximum_absolute_difference=maximum))
                r.io.copy(c,f'SELECT * EXCLUDE(frame) FROM s WHERE frame={frame} ORDER BY row_id',tmp/(sample+'.parquet'))
                row=c.execute(f'''SELECT count(*),median(n_A),avg(n_A),sum(n_A),sum(n_after_all),
                    avg(n_after_all*1.0/n_A),sum(n_month_mismatch),sum(n_fallback),sum(n_fallback>0),
                    corr(adjusted_A,old_adjusted),sum(n_B<5),sum(n_B>=5 AND n_C>=5)
                    FROM s WHERE frame={frame}''').fetchone()
                diagnostics.append(dict(sample=sample,rows=row[0],median_donors=row[1],mean_donors=row[2],
                    donor_query_links=row[3],donor_links_after_anchor=row[4],share_donor_links_after_anchor=row[4]/row[3],
                    mean_row_share_after_anchor=row[5],donor_links_other_month=row[6],share_donor_links_other_month=row[6]/row[3],
                    donor_links_with_fallback=row[7],queries_with_fallback=row[8],correlation_with_old_focal_month_score=row[9],
                    before_unsupported_rows=row[10] if sample=='S0' else None,timing_common_rows=row[11] if sample=='S0' else None))
            # The larger entry frame contains every old F50 game. Rebind old row IDs
            # by verified game identity instead of preparing 7.37 million duplicate queries.
            c.execute('CREATE VIEW expanded AS SELECT row_id,game_id FROM '+u.parq([paths['F']]))
            c.execute('CREATE VIEW oldframe AS SELECT row_id,game_id FROM '+u.parq([paths['F50']]))
            c.execute('CREATE VIEW f_replay AS SELECT oldframe.row_id,p.* EXCLUDE(frame,row_id) FROM p JOIN expanded USING(row_id) JOIN oldframe USING(game_id) WHERE p.frame=2')
            previous=base/'scores_combined/F50.parquet'
            c.execute('CREATE OR REPLACE VIEW b AS SELECT * FROM '+u.parq([previous]))
            fn=pq.ParquetFile(paths['F50']).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM f_replay').fetchone()==(fn,fn),'F50 replay membership differs')
            for field in pq.ParquetFile(previous).schema_arrow:
                k=field.name
                if k=='row_id':continue
                bad=f'p."{k}" IS DISTINCT FROM b."{k}"'
                if pa.types.is_floating(field.type):bad=f'({bad}) AND NOT coalesce(abs(p."{k}"-b."{k}")<=2e-10,FALSE)'
                u.require(c.execute('SELECT count(*) FROM f_replay p JOIN b USING(row_id) WHERE '+bad).fetchone()[0]==0,'Step 0 F50 score replay failed: '+k)
                maximum=c.execute(f'SELECT max(abs(p."{k}"-b."{k}")) FROM f_replay p JOIN b USING(row_id)').fetchone()[0]
                checks.append(dict(sample='F50',field=k,rows=fn,passed=True,maximum_absolute_difference=maximum,score_reused_from_larger_frame=True))
            r.io.js(tmp/'baseline_score_reproduction.json',checks);r.io.js(tmp/'diagnostics.json',diagnostics)
            return dict(baseline_scores_reproduced=True,baseline_checks=checks,diagnostics=diagnostics)
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,shards+replays+[paths[k] for k in ('S0','F','F50')]+[base/'scores_combined'/(k+'.parquet') for k in ('S0','F50')])
    return {k:folder/(k+'.parquet') for k in FRAME},public(info)

def ordinary(paths,scores,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            for name,path in [('e',paths['F']),('o',paths['O']),('s',scores)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
                u.require(c.execute(f'SELECT count(*)-count(DISTINCT row_id) FROM {name}').fetchone()[0]==0,'Duplicate comparison/score row IDs')
            n=pq.ParquetFile(paths['O']).metadata.num_rows
            u.require(c.execute('SELECT count(*) FROM o JOIN e USING(row_id) JOIN s USING(row_id)').fetchone()[0]==n,'Ordinary frame not an exact entry-frame subset')
            keys=['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code','n_7d','counterparts_7d','expected_7d','adjusted_7d']
            terms=' OR '.join('o.'+k+' IS DISTINCT FROM e.'+k for k in keys)
            u.require(c.execute('SELECT count(*) FROM o JOIN e USING(row_id) WHERE '+terms).fetchone()[0]==0,'Ordinary/entry score identity mismatch')
            u.require(c.execute('SELECT count(*) FROM o WHERE y IS NULL OR reached IS NULL OR NOT complete90').fetchone()[0]==0,'Ordinary follow-up is incomplete')
            r.io.copy(c,'SELECT s.* FROM s SEMI JOIN o USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            return dict(rows=n,verified_subset=True,entry_outcomes_not_required=True,ordinary_outcomes_from_authenticated_frame=True,extra_donor_scans=0)
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,[paths['F'],paths['O'],scores]);return folder/'scores.parquet',public(info)

def learning_flags(paths,jobs,root,conf,memory):
    first=[Path(j['output'])/'first_fair_PRIVATE.parquet' for j in jobs]
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW h AS SELECT * FROM '+u.parq(first));c.execute('CREATE VIEW q AS SELECT * FROM '+u.parq([paths['S0']]))
            u.require(c.execute('SELECT count(*)-count(DISTINCT person) FROM h').fetchone()[0]==0,'Chooser first-decision keys duplicated')
            sql='SELECT q.row_id,coalesce(h.first_fair_ms<q.archive_start_ms,FALSE) AS full_chronology,q.fair_90>0 AS flag_90d FROM q LEFT JOIN h ON q.recipient_id=h.person ORDER BY q.row_id'
            n=r.io.copy(c,sql,tmp/'flags_PRIVATE.parquet');u.require(n==pq.ParquetFile(paths['S0']).metadata.num_rows,'Learning attachment changed rows')
            counts=c.execute('SELECT full_chronology,flag_90d,count(*) FROM '+u.parq([tmp/'flags_PRIVATE.parquet'])+' GROUP BY ALL ORDER BY 1,2').fetchall()
            u.require(sum(k for full,recent,k in counts if recent and not full)==0,'90-day prior fair flag absent from full observed chronology')
            return dict(rows=n,counts=[dict(full_chronology=bool(a),flag_90d=bool(b),rows=n) for a,b,n in counts],
                full_chronology_definition='author-clean prior chooser fair event in all 24 donor partitions, before focal start; observed-panel history only',
                flag_90d_definition='frozen recipient fair_90 > 0; original R7 history cutoff',
                left_censored_at_observed_panel_start=True)
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,first+[paths['S0']]);return folder/'flags_PRIVATE.parquet',public(info)
