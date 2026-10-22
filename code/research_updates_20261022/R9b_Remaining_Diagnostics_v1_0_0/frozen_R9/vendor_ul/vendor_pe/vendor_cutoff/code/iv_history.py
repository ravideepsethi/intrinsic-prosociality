"""Exact event-time as-of scores, cumulative recorded history, full pair exclusion."""
from iv_common import *

def segmented_cumsum(values,groups,block=512):
    """Bound cancellation to small blocks, not the entire multi-million-row shard."""
    n=len(values)
    if not n:return np.array([],float)
    out=np.empty(n,float)
    full=n//block
    if full:out[:full*block]=np.cumsum(np.asarray(values[:full*block],float).reshape(full,block),axis=1).ravel()
    if full*block<n:out[full*block:]=np.cumsum(values[full*block:],dtype=float)
    starts=np.maximum.accumulate(np.where(np.r_[True,groups[1:]!=groups[:-1]],np.arange(n),0))
    block_starts=np.arange(n)//block*block
    local=np.maximum(starts,block_starts)
    base=np.where(local>block_starts,out[np.maximum(local-1,0)],0.)
    out-=base
    if n>block:
        ends=np.r_[np.arange(block-1,n,block),n-1]
        if len(ends)>1 and ends[-1]==ends[-2]:ends=ends[:-1]
        tails=segmented_cumsum(out[ends],groups[ends],block)
        b=np.arange(n)//block
        continuing=(b>0)&(groups==groups[np.maximum(block_starts-1,0)])
        out[continuing]+=tails[b[continuing]-1]
    return out

class AsOf:
    def __init__(self,groups,times,queries,cutoffs):
        n=len(times);width=len(groups)
        dtype=[('g'+str(k),'<i8') for k in range(width)]+[('t','<i8')]
        key=np.empty(n,dtype=dtype);q=np.empty(len(cutoffs),dtype=dtype)
        for k,(v,w) in enumerate(zip(groups,queries)):
            key['g'+str(k)]=v;q['g'+str(k)]=w
        key['t']=times;q['t']=cutoffs
        self.order=np.argsort(key,kind='stable');key=key[self.order]
        change=np.ones(n,bool)
        if n>1:
            change[1:]=False
            for k in range(width):change[1:] |= key['g'+str(k)][1:]!=key['g'+str(k)][:-1]
        self.groups=np.cumsum(change)-1
        self.starts=np.flatnonzero(change)
        self.at=np.searchsorted(key,q,side='left')-1
        self.ok=self.at>=0
        self.at=np.maximum(self.at,0)
        if n:
            for k in range(width):self.ok &= key['g'+str(k)][self.at]==q['g'+str(k)]
            counts=np.arange(n)-np.repeat(self.starts,np.diff(np.r_[self.starts,n]))+1
            self.count=np.where(self.ok,counts[self.at],0)
        else:self.count=np.zeros(len(q),np.int64)

    def sums(self,weights):
        if not len(self.order):return np.zeros(len(self.at))
        prefix=segmented_cumsum(np.asarray(weights)[self.order],self.groups)
        return np.where(self.ok,prefix[self.at],0.)

def score(h,q,reference):
    """Return both old and new cutoffs on exactly the same query rows."""
    n=len(q['row_id']);m=np.asarray(q['month_code'],int)
    u.require(np.all((m>=0)&(m<24)),'Query month out of bounds')
    old=np.asarray(STARTS,np.int64)[m]-7*DAY
    new=q['archive_start_ms']-DAY
    u.require(np.all(new>=old),'New cutoff precedes old cutoff')
    j=np.tile(q['opponent_id'],2);i=np.tile(q['recipient_id'],2)
    cuts=np.r_[old,new];months=np.tile(m,2)
    ji=AsOf([h['j']],h['t'],[j],cuts)
    pi=AsOf([h['j'],h['i']],h['t'],[j,i],cuts)
    first=pi.order[pi.starts]
    breadth=AsOf([h['j'][first]],h['t'][first],[j],cuts).count-(pi.count>0)
    count=ji.count-pi.count;wins=ji.sums(h['y'])-pi.sums(h['y'])
    u.require(np.all((count>=0)&(wins>=0)&(wins<=count)&(breadth>=0)),'Impossible pair-excluded totals')
    jf=(r.num.user_hash(h['j'])%np.uint64(4)).astype(int)
    qjf=(r.num.user_hash(j)%np.uint64(4)).astype(int)
    rf=(r.num.user_hash(i)%np.uint64(4)).astype(int)
    expected=np.full(2*n,np.nan)
    for month in np.unique(months):
        for fold in np.unique(rf[months==month]):
            use=(months==month)&(rf==fold)&(count>0)
            model=reference[0,int(month),:,int(fold),:]
            valid=np.isfinite(model).all(axis=1)
            use &= valid[qjf]
            if not use.any():continue
            weights=np.where(valid[jf],model[jf,h['cell']],0.)
            total=ji.sums(weights)-pi.sums(weights)
            expected[use]=total[use]/count[use]
    raw=np.divide(wins,count,out=np.full(2*n,np.nan),where=count>0)
    return {tag:dict(n=count[sl],counterparts=breadth[sl],expected=expected[sl],adjusted=(raw-expected)[sl])
            for tag,sl in [('7d',slice(0,n)),('24h',slice(n,2*n))]}

def score_job(job):
    r.threads_one();u.no_network()
    paths=[v['path'] for v in job['parts']]
    def build(tmp):
        chunks=[];source_rows=0
        for record in job['parts']:
            r.io.checked(record['path'],record['sha256'],record.get('bytes'))
            t=r.io.read(record['path'],['j','i','t','y','arm','cell'])
            u.require(len(t)==record['rows'],'Donor row count differs')
            a=r.arrays(t);source_rows+=len(t)
            keep=a['arm'].astype(bool)&~np.isin(a['j'],job['authors'])&~np.isin(a['i'],job['authors'])
            chunks.append({k:v[keep] for k,v in a.items() if k!='arm'})
        h={k:np.concatenate([a[k] for a in chunks]) for k in ('j','i','t','y','cell')};del chunks
        u.require(np.all(r.num.user_hash(h['j'])%np.uint64(16)==job['shard']),'Donor shard assignment differs')
        u.require(np.isin(h['y'],[0,1]).all() and np.all((h['cell']>=0)&(h['cell']<500)),'Invalid donor outcome or state')
        q=r.arrays(r.io.read(job['queries']));reference=np.load(job['reference'],allow_pickle=False,mmap_mode='r')
        values=score(h,q,reference);checks={}
        for k,v in values['7d'].items():
            want=q[k+'_7d'];delta=np.abs(v-want)
            exact=np.array_equal(v,want) if k in ('n','counterparts') else np.allclose(v,want,rtol=0,atol=2e-10,equal_nan=True)
            u.require(exact,'Old-cutoff replay failed: '+k)
            checks[k]=float(np.nanmax(delta)) if len(delta) else 0.
        u.require(np.all(values['24h']['n']>=values['7d']['n']),'Cumulative history shrank')
        u.require(np.all(values['24h']['n']>=5) and np.isfinite(values['24h']['adjusted']).all(),'Unsupported new scores on old-supported rows')
        result={'row_id':q['row_id']}
        for tag,data in values.items():
            result.update({k+'_'+tag:v for k,v in data.items()})
        r.io.table(tmp/'scores.parquet',pa.table(result))
        changed=values['24h']['adjusted']-values['7d']['adjusted']
        info=dict(shard=job['shard'],queries=len(q['row_id']),source_rows=source_rows,
            eligible_author_clean_donor_rows=len(h['j']),old_replay_max_absolute_difference=checks,
            score_changed_rows=int(np.sum(np.abs(changed)>2e-10)),
            added_decisions=int(np.sum(values['24h']['n']-values['7d']['n'])))
        r.io.js(tmp/'summary.json',info);return info
    return r.stable_stage(Path(job['output']),job['conf'],build,paths+[job['queries'],job['reference']])[1]

def prepare_queries(source,root,conf):
    def build(tmp):
        names=['row_id','opponent_id','recipient_id','archive_start_ms','month_code','n_7d','counterparts_7d','expected_7d','adjusted_7d']
        table=r.io.read(source,names);a=r.arrays(table)
        shards=r.num.user_hash(a['opponent_id'])%np.uint64(16)
        for s in range(16):r.io.table(tmp/f'{s:02}.parquet',table.filter(pa.array(shards==s)))
        return dict(rows=len(table))
    return r.stable_stage(root,conf,build,[source])[0]

def combine(paths,source,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW s AS SELECT * FROM '+u.parq(paths))
            c.execute('CREATE VIEW q AS SELECT row_id FROM '+u.parq([source]))
            match=c.execute('SELECT count(*),count(DISTINCT s.row_id) FROM s JOIN q USING(row_id)').fetchone()
            n=pq.ParquetFile(source).metadata.num_rows
            u.require(match==(n,n) and c.execute('SELECT count(*) FROM s').fetchone()[0]==n,'Combined score identities differ')
            r.io.copy(c,'SELECT * FROM s ORDER BY row_id',tmp/'scores.parquet')
            return dict(rows=n)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,paths+[source])[0]/'scores.parquet'
