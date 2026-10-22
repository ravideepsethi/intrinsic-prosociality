"""One original donor scan; certified old scores and reusable author-clean events."""
from r9_common import *
from iv_history import AsOf

QUERY_TYPES = ul_scores.QUERY_TYPES

def prepare_queries(paths,root,conf):
    def build(tmp):
        schema=pa.schema([('frame',pa.int8())]+list(QUERY_TYPES.items()))
        writers=[pq.ParquetWriter(tmp/f'{s:02}.parquet',schema,compression='zstd') for s in range(16)]
        counts={}
        try:
            for frame,key in enumerate(('S0','F50','F')):
                counts[key]=0
                for batch in pq.ParquetFile(paths[key]).iter_batches(columns=list(QUERY_TYPES),batch_size=131072):
                    t=pa.Table.from_batches([batch]).cast(pa.schema(QUERY_TYPES))
                    u.require(all(t[k].null_count==0 for k in QUERY_TYPES),'Missing query fields')
                    a=r.arrays(t);u.require(np.all(a['anchor_ms']>=a['archive_start_ms']),'Anchor before start')
                    shard=r.num.user_hash(a['opponent_id'])%np.uint64(16)
                    t=t.add_column(0,'frame',pa.array(np.full(len(t),frame,np.int8)))
                    for s,w in enumerate(writers):
                        if (shard==s).any():w.write_table(t.filter(pa.array(shard==s)))
                    counts[key]+=len(t)
        finally:
            for w in writers:w.close()
        return dict(rows=counts)
    return r.stable_stage(root,conf,build,[paths[k] for k in ('S0','F50','F')])[0]

def scan_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        chunks=[];learning_chunks=[];original=0
        for v in job['parts']:
            r.io.checked(v['path'],v['sha256'],v.get('bytes'))
            a=r.arrays(r.io.read(v['path'],['j','i','t','y','arm','fair','cell']))
            u.require(len(a['j'])==v['rows'],'Donor source row count changed')
            original+=len(a['j'])
            clean=~np.isin(a['j'],job['authors'])&~np.isin(a['i'],job['authors'])
            # Learning uses the same competitive-history flag as frozen fair_90,
            # independently of the all-position donor arm eligibility flag.
            learning=clean&a['fair'].astype(bool)
            learning_chunks.append((a['j'][learning],a['t'][learning]))
            keep=a['arm'].astype(bool)&clean
            chunks.append({k:x[keep] for k,x in a.items() if k!='arm'})
        h={k:np.concatenate([v[k] for v in chunks]) for k in chunks[0]};del chunks
        u.require(np.all(r.num.user_hash(h['j'])%np.uint64(16)==job['shard']),'Wrong chooser shard')
        u.require(np.isin(h['y'],[0,1]).all() and ((h['cell']>=0)&(h['cell']<500)).all(),'Invalid donor outcomes/state')
        r.io.table(tmp/'events_PRIVATE.parquet',pa.table(h))
        # The only scan of the original 384 donor files also produces full chronology learning flags.
        lp=np.concatenate([v[0] for v in learning_chunks]);lt=np.concatenate([v[1] for v in learning_chunks]);del learning_chunks
        people,inv=np.unique(lp,return_inverse=True)
        first=np.full(len(people),np.iinfo(np.int64).max,np.int64);np.minimum.at(first,inv,lt)
        del lp,lt,inv
        r.io.table(tmp/'first_competitive_PRIVATE.parquet',pa.table(dict(person=people,first_competitive_ms=first)))
        q=r.arrays(r.io.read(job['queries']));ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        full,before,after,sel,gap=ul_scores.score(h,q,ref)
        check=ul_scores.oracle_checks(h,q,ref,full,before,after,sel)
        out=dict(frame=q['frame'],row_id=q['row_id'],**{k+'_all_time':v for k,v in full.items()})
        for tag,data in [('before',before),('after',after)]:
            for k in ('n','adjusted'):
                value=np.full(len(q['row_id']),-1 if k=='n' else np.nan,dtype=np.int64 if k=='n' else float)
                value[sel]=data[k];out[k+'_'+tag]=value
        value=np.full(len(q['row_id']),-1,np.int64);value[sel]=gap;out['n_focal_interval']=value
        r.io.table(tmp/'baseline_scores_PRIVATE.parquet',pa.table(out))
        return dict(source_rows=original,eligible_donors=len(h['j']),queries=len(q['row_id']),oracle=check)
    return r.stable_stage(Path(job['output']),job['conf'],build,
        [v['path'] for v in job['parts']]+[job['queries'],job['reference']])[1]

def donor_month(t):
    return (np.asarray(t,dtype='datetime64[ms]').astype('datetime64[M]').astype(np.int64)-np.datetime64('2023-11','M').astype(np.int64)).astype(np.int16)

def model_map(reference, months):
    out={};fallback=[]
    for m in np.unique(months):
        for jf in range(4):
            for rf in range(4):
                valid=np.flatnonzero(np.isfinite(reference[0,:,jf,rf,:]).all(axis=1))
                valid=valid[valid<=m]
                used=int(valid[-1]) if len(valid) else -1
                out[int(m),jf,rf]=used
                if used!=m:fallback.append(dict(donor_month_code=int(m),chooser_fold=jf,recipient_fold=rf,
                    model_month_code=used,rule='no_state_adjustment_p_hat_zero' if used<0 else 'last_available_prior_month'))
    return out,fallback

def weights_for(h,ref,rf,mapping):
    jf=(r.num.user_hash(h['j'])%np.uint64(4)).astype(int);dm=donor_month(h['t'])
    w=np.zeros(len(dm));fallback=np.zeros(len(dm),np.int8)
    for m in np.unique(dm):
        for jfold in range(4):
            ix=(dm==m)&(jf==jfold);used=mapping[int(m),jfold,int(rf)]
            if used>=0:w[ix]=ref[0,used,jfold,int(rf),h['cell'][ix]]
            fallback[ix]=used!=m
    u.require(np.isfinite(w).all() and ((w>=0)&(w<=1)).all(),'Invalid state predictions')
    return w,fallback

def score(h,q,ref):
    n=len(q['row_id']);sel=np.flatnonzero(q['frame']==0);ns=len(sel)
    pick=np.r_[np.arange(n),sel,sel];j=q['opponent_id'][pick];i=q['recipient_id'][pick]
    cuts=np.r_[np.full(n,np.iinfo(np.int64).max,np.int64),q['archive_start_ms'][sel],q['anchor_ms'][sel]+1]
    ji=AsOf([h['j']],h['t'],[j],cuts);pi=AsOf([h['j'],h['i']],h['t'],[j,i],cuts)
    count=ji.count-pi.count;grants=ji.sums(h['y'])-pi.sums(h['y'])
    first=pi.order[pi.starts]
    breadth=AsOf([h['j'][first]],h['t'][first],[j],cuts).count-(pi.count>0)
    ends=pi.order[np.r_[pi.starts[1:]-1,len(pi.order)-1]] if len(pi.order) else np.array([],int)
    after_breadth=AsOf([h['j'][ends]],-h['t'][ends],[q['opponent_id'][sel]],-q['anchor_ms'][sel]).count
    after_pair=AsOf([h['j'],h['i']],-h['t'],[q['opponent_id'][sel],q['recipient_id'][sel]],-q['anchor_ms'][sel]).count
    after_breadth-=after_pair>0
    mapping,fallbacks=model_map(ref,donor_month(h['t']))
    rf=(r.num.user_hash(i)%np.uint64(4)).astype(int);pred=np.zeros(len(pick));affected=np.zeros(len(pick))
    for f in np.unique(rf):
        w,fb=weights_for(h,ref,f,mapping);use=rf==f
        v=ji.sums(w)-pi.sums(w);pred[use]=v[use]
        v=ji.sums(fb)-pi.sums(fb);affected[use]=v[use]
    dm=donor_month(h['t']);same=np.zeros(n)
    for m in np.unique(q['month_code']):
        weights=(dm==m).astype(np.int8);v=ji.sums(weights)-pi.sums(weights);use=q['month_code']==m
        same[use]=v[:n][use]
    after_n=count[sel]-count[n+ns:]
    # F queries also need after-anchor diagnostics, without constructing additional instruments.
    aj=AsOf([h['j']],h['t'],[q['opponent_id']],q['anchor_ms']+1)
    ap=AsOf([h['j'],h['i']],h['t'],[q['opponent_id'],q['recipient_id']],q['anchor_ms']+1)
    out=dict(frame=q['frame'],row_id=q['row_id'],cross_month_donors=count[:n]-same,
        donors_after_anchor=count[:n]-(aj.count-ap.count))
    def put(tag,c,g,p,b,fb,indices):
        for k,v in dict(n=c,grants=g,counterparts=b,fallback_donors=fb,
                expected=np.divide(p,c,out=np.full(len(c),np.nan),where=c>0),
                adjusted=np.divide(g-p,c,out=np.full(len(c),np.nan),where=c>0)).items():
            if indices is None:out[k+'_'+tag]=v
            else:
                result=np.full(n,-1 if k in ('n','counterparts') else np.nan,dtype=np.int64 if k in ('n','counterparts') else float)
                result[indices]=v;out[k+'_'+tag]=result
    put('A',count[:n],grants[:n],pred[:n],breadth[:n],affected[:n],None)
    put('B',count[n:n+ns],grants[n:n+ns],pred[n:n+ns],breadth[n:n+ns],affected[n:n+ns],sel)
    put('C',after_n,grants[sel]-grants[n+ns:],pred[sel]-pred[n+ns:],after_breadth,affected[sel]-affected[n+ns:],sel)
    u.require(np.all(out['n_A']>=5),'Unsupported all-time score; no rows removed')
    u.require(np.all(out['counterparts_A']>=1),'No pair-excluded counterpart')
    return out,fallbacks

def oracle(h,q,ref,out,limit=18):
    mapping,_=model_map(ref,donor_month(h['t']));err=0.
    chosen=np.unique(np.linspace(0,len(q['row_id'])-1,min(limit,len(q['row_id'])),dtype=int))
    for k in chosen:
        use=(h['j']==q['opponent_id'][k])&(h['i']!=q['recipient_id'][k])
        rf=int(r.num.user_hash(q['recipient_id'][k:k+1])[0]%np.uint64(4));w,fb=weights_for(h,ref,rf,mapping)
        for tag,mask in [('A',use),('B',use&(h['t']<q['archive_start_ms'][k])),('C',use&(h['t']>q['anchor_ms'][k]))]:
            if tag!='A' and q['frame'][k]!=0:continue
            u.require(out['n_'+tag][k]==mask.sum(),'Donor oracle count mismatch')
            u.require(out['counterparts_'+tag][k]==len(np.unique(h['i'][mask])),'Donor oracle breadth mismatch')
            u.require(out['fallback_donors_'+tag][k]==fb[mask].sum(),'Fallback accounting mismatch')
            if mask.any():
                want=np.mean(h['y'][mask]-w[mask]);delta=abs(out['adjusted_'+tag][k]-want)
                u.require(delta<2e-10,'Donor-month independent score mismatch');err=max(err,float(delta))
        u.require(out['cross_month_donors'][k]==(use&(donor_month(h['t'])!=q['month_code'][k])).sum(),'Month accounting mismatch')
        u.require(out['donors_after_anchor'][k]==(use&(h['t']>q['anchor_ms'][k])).sum(),'After-anchor accounting mismatch')
    return dict(checked_queries=len(chosen),maximum_absolute_score_error=err)

def new_score_job(job):
    r.threads_one();u.no_network()
    def build(tmp):
        h=r.arrays(r.io.read(job['events']));q=r.arrays(r.io.read(job['queries']))
        ref=np.load(job['reference'],mmap_mode='r',allow_pickle=False)
        out,fallbacks=score(h,q,ref);checks=oracle(h,q,ref,out)
        dm=donor_month(h['t']);jf=(r.num.user_hash(h['j'])%np.uint64(4)).astype(int)
        for entry in fallbacks:
            entry['eligible_source_donor_rows_for_fold']=int(((dm==entry['donor_month_code'])&(jf==entry['chooser_fold'])).sum())
        r.io.table(tmp/'scores_PRIVATE.parquet',pa.table(out))
        return dict(queries=len(q['row_id']),oracle=checks,fallback_models=fallbacks,
            unique_donors_by_month=[dict(month_code=int(m),donors=int((donor_month(h['t'])==m).sum())) for m in np.unique(donor_month(h['t']))])
    return r.stable_stage(Path(job['output']),job['conf'],build,[job['events'],job['queries'],job['reference']])[1]

def combine(shards,paths,root,conf,memory,new=False,archived=None):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1);checks=[]
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(shards))
            u.require(c.execute('SELECT count(*)-count(DISTINCT (frame,row_id)) FROM s').fetchone()[0]==0,'Duplicate scores')
            for frame,key in enumerate(('S0','F50','F')):
                c.execute('CREATE OR REPLACE VIEW q AS SELECT row_id FROM '+u.parq([paths[key]]));n=pq.ParquetFile(paths[key]).metadata.num_rows
                u.require(c.execute(f'SELECT count(*),count(DISTINCT row_id) FROM s JOIN q USING(row_id) WHERE frame={frame}').fetchone()==(n,n),'Score frame mismatch')
                u.require(c.execute(f'SELECT count(*) FROM s WHERE frame={frame}').fetchone()[0]==n,'Extra scores')
                r.io.copy(c,f'SELECT * EXCLUDE(frame) FROM s WHERE frame={frame} ORDER BY row_id',tmp/(key+'.parquet'))
                if archived and key in archived:
                    c.execute('CREATE OR REPLACE VIEW oldscore AS SELECT * FROM '+u.parq([archived[key]]))
                    u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM oldscore').fetchone()==(n,n),'Archived score count/identity not unique')
                    u.require(c.execute(f'SELECT count(*) FROM s JOIN oldscore USING(row_id) WHERE frame={frame}').fetchone()[0]==n,'Archived score IDs differ')
                    fields=pq.ParquetFile(archived[key]).schema_arrow.names
                    for k in fields:
                        if k=='row_id':continue
                        sql=f'''SELECT count(*),max(abs(s."{k}"-o."{k}")) FROM s JOIN oldscore o USING(row_id)
                            WHERE s.frame={frame} AND NOT (s."{k}" IS NOT DISTINCT FROM o."{k}" OR abs(s."{k}"-o."{k}")<=2e-10)'''
                        bad,delta=c.execute(sql).fetchone();u.require(bad==0,'Saved baseline score differs: '+key+'/'+k)
                        checks.append(dict(sample=key,field=k,passed=True))
        finally:r.finish_connection(c,tmp/'spill')
        return dict(baseline_score_checks=checks)
    deps=shards+[paths[k] for k in ('S0','F50','F')]+list((archived or {}).values())
    folder,info=r.stable_stage(root,conf,build,deps)
    return {k:folder/(k+'.parquet') for k in ('S0','F50','F')},info
