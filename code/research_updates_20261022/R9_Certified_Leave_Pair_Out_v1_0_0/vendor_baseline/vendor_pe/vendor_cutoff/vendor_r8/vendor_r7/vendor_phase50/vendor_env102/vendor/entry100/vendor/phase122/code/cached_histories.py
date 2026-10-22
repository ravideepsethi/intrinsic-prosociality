"""Exact frozen scores, broad behavioral histories, main-panel future choices."""
from cached_common import *

def score_job(job):
    threads_one()
    def build(tmp):
        q=arrays(io.read(job['queries']));s=num.user_hash(q['opponent_id'])%np.uint64(16)==job['shard']
        q={k:v[s] for k,v in q.items()}
        h=arrays(pa.concat_tables([io.read(p,PROJECTION_COLS) for p in job['parts']]))
        arm=np.asarray(h['arm'],bool)
        old={k:v[arm] for k,v in h.items()}
        keep=arm&~authors.author_mask(h['j'],h['i'],job['authors'])
        clean={k:v[keep] for k,v in h.items()};del h
        refold=np.load(Path(job['reference'])/'original.npy',mmap_mode='r',allow_pickle=False)
        refclean=np.load(Path(job['reference'])/'clean.npy',mmap_mode='r',allow_pickle=False)
        result={'row_id':q['row_id']}
        for tag in ('','original_'):
            for k in SCORE_COLS:result[tag+k]=np.empty(len(q['row_id']),np.int64 if k.startswith(('n_','counterparts_')) else float)
        for month in np.unique(q['month_code']):
            ix=np.flatnonzero(q['month_code']==month);m=int(month)
            for tag,data,model in (('original_',old,refold),('',clean,refclean)):
                scores=num.score_month(data['j'],data['i'],data['t'],data['y'],data['cell'],
                    q['opponent_id'][ix],q['recipient_id'][ix],int(STARTS[m])-7*DAY,model[0,m])
                for name,value in scores.items():
                    col=name+'_7d'
                    if col in SCORE_COLS:result[tag+col][ix]=value
        new=~q['previous_frame'].astype(bool)
        if np.any(result['n_7d'][new]!=q['expected_n7'][new]):raise RuntimeError('Clean score count disagrees with local-first eligibility ledger')
        io.table(tmp/'scores.parquet',pa.table(result));return dict(rows=len(q['row_id']))
    return stable_stage(Path(job['output']),job['conf'],build,[job['queries']]+job['parts']+[str(Path(job['reference'])/n) for n in ('original.npy','clean.npy')])[1]

def history_month_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([job['queries']]))
            c.execute('CREATE VIEW h AS SELECT * FROM '+io.parq(job['parts']))
            ids=','.join(map(str,job['authors']))
            clean=f'j NOT IN ({ids}) AND i NOT IN ({ids})'
            for tag,condition in (('original','TRUE'),('clean',clean)):
                c.execute('CREATE OR REPLACE VIEW chosen AS SELECT * FROM h WHERE '+condition)
                c.execute('CREATE OR REPLACE TEMP TABLE events AS '+audit.history_sql('chosen','q'))
                for s in range(16):io.copy(c,'SELECT * EXCLUDE(bucket) FROM events WHERE bucket='+str(s),tmp/f'{tag}_{s:02}.parquet')
            return dict(month=job['month'])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['queries']]+job['parts'])[1]

def future_month_job(job):
    threads_one()
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'],1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([job['queries']]))
            c.execute('CREATE VIEW main AS SELECT * FROM '+io.parq([job['panel']]))
            # Certified main already applies pool/previous-nonadjacency selection.
            # Retain the producer's tournament-like exclusion too.
            fields='game_id gid,chooser_user_id::BIGINT j,disconnected_user_id::BIGINT i,api_last_move_at_ms::BIGINT t,utc_ms::BIGINT AS "start",archive_ordinal::BIGINT ord,kind_draw::BOOLEAN y'
            c.execute('CREATE TEMP TABLE events AS SELECT '+fields+' FROM main SEMI JOIN (SELECT DISTINCT recipient_id FROM q) q ON chooser_user_id=q.recipient_id WHERE fair_competitive AND NOT tournament_like_event')
            # An ordinary focal ending cannot simultaneously be an active opportunity.
            bad=c.execute('SELECT count(*) FROM main JOIN q USING(game_id)').fetchone()[0]
            if bad:raise RuntimeError('An ordinary focal game appears in the active-opportunity panel')
            for s in range(16):io.copy(c,'SELECT * FROM events WHERE j%16='+str(s),tmp/f'{s:02}.parquet')
            return dict(rows=c.execute('SELECT count(*) FROM events').fetchone()[0])
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(Path(job['output']),job['conf'],build,[job['queries'],job['panel']])[1]

def outcomes_job(job):
    threads_one()
    def build(tmp):
        q=arrays(io.read(job['queries']));use=q['recipient_id']%16==job['shard'];q={k:v[use] for k,v in q.items()}
        result={'row_id':q['row_id']}
        for tag in ('original','clean'):
            ev=arrays(pa.concat_tables([io.read(p) for p in job[tag+'_histories']]))
            counts=audit.window_counts(ev,q['recipient_id'],q['archive_start_ms']);del ev
            for k,v in counts.items():result[('original_' if tag=='original' else '')+k]=v
        h=arrays(pa.concat_tables([io.read(p) for p in job['futures']]))
        keep=~authors.author_mask(h['j'],h['i'],job['authors'])
        for prefix,data in (('original_',h),('',{k:v[keep] for k,v in h.items()})):
            out=audit.later_outcomes(data,q)
            for k,v in out.items():
                if k!='row_id':result[prefix+('y' if k=='observed_y' else k)]=v
        io.table(tmp/'outcomes.parquet',pa.table(result));return dict(rows=len(q['row_id']))
    return stable_stage(Path(job['output']),job['conf'],build,[job['queries']]+job['original_histories']+job['clean_histories']+job['futures'])[1]
