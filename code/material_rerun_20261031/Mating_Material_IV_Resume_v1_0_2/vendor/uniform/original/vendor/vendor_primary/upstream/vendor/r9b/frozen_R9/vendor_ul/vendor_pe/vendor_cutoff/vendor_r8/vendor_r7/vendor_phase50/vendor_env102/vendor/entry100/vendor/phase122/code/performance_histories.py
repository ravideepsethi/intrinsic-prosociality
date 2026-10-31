"""Phase-independent history indexes and exact query calculations."""
from cached_common import *
from performance_cache import feature_stage,BEHAVIOR_KEYS

def score_index_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            cut=[int(v)-7*DAY for v in STARTS]
            bucket='CASE '+' '.join(f'WHEN t<{v} THEN {k}' for k,v in enumerate(cut))+' ELSE 24 END'
            c.execute('CREATE TEMP TABLE aggregated AS SELECT j,i,cell,'+bucket+' AS bucket,count(*)::BIGINT n,sum(y::BIGINT)::BIGINT wins FROM '+io.parq(job['parts'])+f' WHERE arm AND t<{cut[-1]} GROUP BY j,i,cell,bucket')
            c.execute('CREATE TEMP TABLE people AS SELECT j,row_number() OVER(ORDER BY j)-1 AS j_index FROM (SELECT DISTINCT j FROM aggregated)')
            c.execute('CREATE TEMP TABLE pairs AS SELECT j,i,j_index,row_number() OVER(ORDER BY j,i)-1 AS pair_index FROM (SELECT DISTINCT j,i FROM aggregated) JOIN people USING(j)')
            io.copy(c,'SELECT j FROM people ORDER BY j_index',tmp/'people.parquet')
            io.copy(c,'SELECT j,i,j_index FROM pairs ORDER BY pair_index',tmp/'pairs.parquet')
            n=io.copy(c,'SELECT bucket,pair_index,j_index,cell,n,wins FROM aggregated JOIN pairs USING(j,i) ORDER BY bucket,pair_index,cell',tmp/'events.parquet')
            return dict(aggregated_rows=n,original_events=c.execute('SELECT coalesce(sum(n),0) FROM aggregated').fetchone()[0],phase_independent=True)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,job['parts'])[1]

class ScoreIndex:
    def __init__(self,path):
        path=Path(path);self.h=arrays(io.read(path/'events.parquet'))
        self.people=io.arr(io.read(path/'people.parquet'),'j')
        self.pairs=arrays(io.read(path/'pairs.parquet'))
        self.keys=np.empty(len(self.pairs['j']),dtype=[('v0','<i8'),('v1','<i8')])
        self.keys['v0']=self.pairs['j'];self.keys['v1']=self.pairs['i']
        self.folds=(num.user_hash(self.people)%np.uint64(4)).astype(int)

    def score(self,qj,qi,month,model,ids):
        stop=np.searchsorted(self.h['bucket'],month,side='right')
        h={k:v[:stop] for k,v in self.h.items()}
        allowed=~authors.author_mask(self.pairs['j'],self.pairs['i'],ids)
        use=allowed[h['pair_index']]
        j=h['j_index'][use];p=h['pair_index'][use];n=h['n'][use];wins=h['wins'][use];cell=h['cell'][use]
        njp=len(self.people);npp=len(self.keys)
        jn=np.bincount(j,weights=n,minlength=njp).astype(np.int64)
        pn=np.bincount(p,weights=n,minlength=npp).astype(np.int64)
        js=np.bincount(j,weights=wins,minlength=njp)
        ps=np.bincount(p,weights=wins,minlength=npp)
        qp=np.empty(len(qj),dtype=self.keys.dtype);qp['v0']=qj;qp['v1']=qi
        ij=num.lookup(self.people,qj);ip=num.lookup(self.keys,qp)
        count=num.take_zero(jn,ij)-num.take_zero(pn,ip)
        ys=num.take_zero(js,ij)-num.take_zero(ps,ip)
        breadth=np.bincount(self.pairs['j_index'],weights=(pn>0),minlength=njp).astype(np.int64)
        breadth=num.take_zero(breadth,ij)-(num.take_zero(pn,ip)>0)
        if np.any(count<0)|np.any(ys<0)|np.any(ys>count):raise RuntimeError('Invalid indexed pair-excluded score')
        raw=np.full(len(qj),np.nan);expected=raw.copy();good=count>0;raw[good]=ys[good]/count[good]
        qrf=(num.user_hash(qi)%np.uint64(4)).astype(int);qjf=(num.user_hash(qj)%np.uint64(4)).astype(int)
        for rf in range(4):
            rows=(qrf==rf)&good
            if not rows.any():continue
            valid=np.isfinite(model[:,rf,:]).all(axis=1)
            weight=np.where(valid[self.folds[j]],model[self.folds[j],rf,cell],0.)*n
            jm=np.bincount(j,weights=weight,minlength=njp);pm=np.bincount(p,weights=weight,minlength=npp)
            rows &= valid[qjf]
            expected[rows]=(num.take_zero(jm,ij)[rows]-num.take_zero(pm,ip)[rows])/count[rows]
        return dict(n_7d=count,counterparts_7d=breadth,expected_7d=expected,adjusted_7d=raw-expected)

def score_job(job):
    threads_one()
    def produce(query,tmp):
        q=arrays(io.read(query));old=np.asarray(q['previous_frame'],bool);nq=len(old)
        result={'row_id':q['row_id']}
        if nq and job.get('index_job'):score_index_job(job['index_job'])
        index=ScoreIndex(job['index']) if nq else None
        for tag,ids,select in [('',job['authors'],np.ones(nq,bool)),('original_',[],old)]:
            values={k:np.zeros(nq,np.int64) if k.startswith(('n_','counterparts_')) else np.full(nq,np.nan) for k in SCORE_COLS}
            model=np.load(Path(job['reference'])/('original.npy' if tag else 'clean.npy'),mmap_mode='r',allow_pickle=False)
            for m in np.unique(q['month_code'][select]):
                use=np.flatnonzero(select&(q['month_code']==m))
                sc=index.score(q['opponent_id'][use],q['recipient_id'][use],int(m),model[0,int(m)],ids)
                for k,v in sc.items():values[k][use]=v
            for k,v in values.items():result[tag+k]=pa.array(v,mask=~old if tag else None)
        path=tmp/'scores.parquet';io.table(path,pa.table(result));return path
    result=feature_stage(job,'scores.parquet',BEHAVIOR_KEYS,produce)
    # Verify the current ledger even when every feature was read from cache.
    q=arrays(io.read(job['queries'],['row_id','previous_frame','expected_n7']))
    out=arrays(io.read(Path(job['output'])/'scores.parquet',['row_id','n_7d']))
    loc=num.lookup(out['row_id'],q['row_id']);new=~q['previous_frame'].astype(bool)
    if np.any(loc<0) or np.any(out['n_7d'][loc][new]!=q['expected_n7'][new]):
        raise RuntimeError('Clean indexed score count disagrees with local-first eligibility ledger')
    return result

def history_index_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            ids=','.join(map(str,job['authors']));clean=f'j NOT IN ({ids}) AND i NOT IN ({ids})'
            c.execute('CREATE TEMP TABLE h AS SELECT j,i,t,fair,y,arm,('+clean+')::BIGINT clean FROM '+io.parq(job['parts']))
            sql='''WITH events AS (
                SELECT j person,t,fair::BIGINT fair,(fair AND y)::BIGINT kind,0::BIGINT disconnect,0::BIGINT receipt,0::BIGINT claim,clean FROM h WHERE fair
                UNION ALL SELECT i,t,0,0,1,y::BIGINT,(arm AND NOT y)::BIGINT,clean FROM h
              ) SELECT person,t,'''+','.join('sum('+k+')::BIGINT '+k+',sum('+k+'*clean)::BIGINT clean_'+k for k in audit.COUNTS)+' FROM events GROUP BY person,t'
            c.execute('CREATE TEMP TABLE events AS '+sql)
            for s in range(16):io.copy(c,'SELECT * FROM events WHERE person%16='+str(s)+' ORDER BY person,t',tmp/f'{s:02}.parquet')
            return dict(rows=c.execute('SELECT count(*) FROM events').fetchone()[0],phase_independent=True)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,job['parts'])[1]

def main_index_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE TEMP TABLE main AS SELECT game_id,chooser_user_id::BIGINT j,disconnected_user_id::BIGINT i,api_last_move_at_ms::BIGINT t,utc_ms::BIGINT start_ms,archive_ordinal::BIGINT ord,kind_draw::BOOLEAN y,fair_competitive,tournament_like_event,timeout_chooser_win FROM '+io.parq([job['panel']]))
            io.copy(c,'SELECT game_id,i,j,fair_competitive,y AS kind_draw,timeout_chooser_win FROM main ORDER BY game_id',tmp/'keys.parquet')
            for s in range(16):
                io.copy(c,'SELECT game_id gid,j,i,t,start_ms AS "start",ord,y FROM main WHERE fair_competitive AND NOT tournament_like_event AND j%16='+str(s)+' ORDER BY j,t,ord,gid',tmp/f'{s:02}.parquet')
            return dict(rows=c.execute('SELECT count(*) FROM main').fetchone()[0],phase_independent=True)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,[job['panel']])[1]

def role_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([job['queries']]))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq([job['keys']]))
            if c.execute('SELECT count(*) FROM q JOIN m USING(game_id) WHERE q.ordinary_narrow').fetchone()[0]:
                raise RuntimeError('Ordinary focal game occurs in active-opportunity main panel')
            n=io.copy(c,'SELECT q.row_id,q.game_id,q.recipient_id,q.opponent_id,m.* EXCLUDE(game_id) FROM q JOIN m USING(game_id)',tmp/'roles.parquet')
            return dict(rows=n)
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(job['output'],job['conf'],build,[job['queries'],job['keys']])[1]

def sorted_later_outcomes(h,q):
    """Frozen search, with the input already sorted by j,t,ord,gid."""
    n=len(q['row_id']);keys=audit.moments(h['j'],h['t'])
    at=np.searchsorted(keys,audit.moments(q['recipient_id'],q['anchor_ms']),'right')
    end=np.searchsorted(keys,audit.moments(q['recipient_id'],q['anchor_ms']+90*DAY),'right')
    out=dict(y=np.zeros(n,bool),reached=np.zeros(n,bool),outcome_gid=np.full(n,'',dtype='U8'),
        outcome_t=np.full(n,-1,np.int64),outcome_start=np.full(n,-1,np.int64),outcome_opponent=np.full(n,-1,np.int64))
    active=np.flatnonzero(at<end)
    while len(active):
        ix=at[active];valid=(h['start'][ix]>q['anchor_ms'][active])&(h['i'][ix]!=q['opponent_id'][active])&(h['gid'][ix]!=q['game_id'][active])
        hit=active[valid];hi=ix[valid];out['reached'][hit]=True;out['y'][hit]=h['y'][hi]
        for name,key in [('outcome_gid','gid'),('outcome_t','t'),('outcome_start','start'),('outcome_opponent','i')]:out[name][hit]=h[key][hi]
        active=active[~valid];at[active]+=1;active=active[at[active]<end[active]]
    return out

def outcome_job(job):
    threads_one()
    def produce(query,tmp):
        q=arrays(io.read(query));nq=len(q['row_id']);old=np.asarray(q['previous_frame'],bool)
        result={'row_id':q['row_id']};c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([query]))
            if nq:
                begin=int(q['archive_start_ms'].min())-97*DAY;end=int(q['archive_start_ms'].max())-7*DAY
                sql='SELECT e.* FROM '+io.parq(job['histories'])+f' e SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON e.person=q.recipient_id WHERE e.t>={begin} AND e.t<{end} ORDER BY person,t'
                ev=arrays(c.execute(sql).to_arrow_table())
            else:ev={k:np.empty(0,np.int64) for k in ['person','t']+list(audit.COUNTS)+['clean_'+v for v in audit.COUNTS]}
            keys=audit.moments(ev['person'],ev['t'])
            end=q['archive_start_ms']-7*DAY
            hi=np.searchsorted(keys,audit.moments(q['recipient_id'],end),'left')
            lows={days:np.searchsorted(keys,audit.moments(q['recipient_id'],end-days*DAY),'left') for days in (30,90)}
            for prefix,source,select in [('', 'clean_',np.ones(nq,bool)),('original_','',old)]:
                for name in audit.COUNTS:
                    if select.any():
                        cumulative=np.r_[np.int64(0),np.cumsum(ev[source+name],dtype=np.int64)]
                        for days,lo in lows.items():
                            vals=np.zeros(nq,np.int64);vals[select]=cumulative[hi[select]]-cumulative[lo[select]]
                            result[prefix+f'{name}_{days}']=pa.array(vals,mask=~select)
                    else:
                        for days in lows:result[prefix+f'{name}_{days}']=pa.nulls(nq,pa.int64())
                result[prefix+'history_window_complete']=pa.array(q['archive_start_ms']-97*DAY>=int(STARTS[0]),mask=~select)
            del ev
            if nq:
                lower=int(q['anchor_ms'].min());upper=int(q['anchor_ms'].max())+90*DAY
                sql='SELECT h.* FROM '+io.parq(job['futures'])+f' h SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON h.j=q.recipient_id WHERE h.t>{lower} AND h.t<={upper} ORDER BY j,t,ord,gid'
                h=arrays(c.execute(sql).to_arrow_table())
            else:h={k:np.empty(0,'U8' if k=='gid' else bool if k=='y' else np.int64) for k in ('gid','j','i','t','start','ord','y')}
            clean=~authors.author_mask(h['j'],h['i'],job['authors'])
            for prefix,events,select in [('',{k:v[clean] for k,v in h.items()},np.ones(nq,bool)),('original_',h,old)]:
                out=sorted_later_outcomes(events,{k:v[select] for k,v in q.items()})
                for name,v in out.items():
                    values=np.zeros(nq,v.dtype);values[select]=v
                    result[prefix+name]=pa.array(values,mask=~select)
            path=tmp/'outcomes.parquet';io.table(path,pa.table(result));return path
        finally:finish_connection(c,tmp/'spill')
    return feature_stage(job,'outcomes.parquet',BEHAVIOR_KEYS,produce)
