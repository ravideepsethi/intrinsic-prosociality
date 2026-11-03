"""Fresh donor/reference/history/future streams; original factual clocks retained."""
from bootstrap import *

def project_job(job):
    def build(tmp):
        db=connect(tmp,job['memory'])
        try:
            view(db,'m',job['material']);view(db,'o',[p['path'] for p in job['old']])
            require(db.execute('SELECT count(*),count(DISTINCT game_id) FROM m').fetchone()==(job['rows'],job['rows']),'Duplicate corrected game')
            c.ensure(db,'SELECT count(*) FROM m LEFT JOIN o ON m.game_id=o.gid WHERE o.gid IS NULL','Corrected donor absent from original projection')
            c.ensure(db,'''SELECT count(*) FROM m JOIN o ON m.game_id=o.gid WHERE
                m.chooser_user_id<>o.j OR m.disconnected_user_id<>o.i OR m.api_last_move_at_ms<>o.t
                OR m.utc_ms<>o.start OR m.archive_ordinal<>o.ord OR m.fair_competitive<>o.fair''','Original factual donor bridge differs')
            ids=','.join(map(str,job['authors']))
            c.ensure(db,f'SELECT count(*) FROM m WHERE chooser_user_id IN ({ids}) OR disconnected_user_id IN ({ids})','Author in material donor source')
            # Retain the frozen cell/real-time fields, recalculate the arm after
            # recoding the grant. Nonfinite boards and gaps retain prior exclusion.
            db.execute('''CREATE TEMP TABLE h AS SELECT o.* EXCLUDE(y,arm),m.kind_draw::BOOLEAN y,
              ((m.kind_draw OR m.timeout_chooser_win) AND isfinite(m.engine_eval_cp_disconnected)
              AND isfinite(m.ply_count) AND isfinite(m.disconnected_elo-m.chooser_elo) AND o.rt)::BOOLEAN arm
              FROM m JOIN o ON m.game_id=o.gid''')
            copy(db,'''SELECT o.gid,o.j,o.i,o.t,o.start,o.y,o.arm FROM o ANTI JOIN m ON o.gid=m.game_id
                WHERE o.j NOT IN ('''+ids+') AND o.i NOT IN ('+ids+')',tmp/'removed.parquet')
            copy(db,'''SELECT o.gid,o.y old_y,m.kind_draw new_y,o.arm old_arm,h.arm new_arm
              FROM o JOIN m ON o.gid=m.game_id JOIN h USING(gid) WHERE o.y<>m.kind_draw OR o.arm<>h.arm''',tmp/'relabeled.parquet')
            # Shard with exactly the original SplitMix hash, not ID modulo 16.
            t=db.execute('SELECT * FROM h ORDER BY gid').fetch_arrow_table()
            shard=c.frozen.r.num.user_hash(t['j'].to_numpy())%np.uint64(16)
            for s in range(16):pq.write_table(t.filter(pa.array(shard==s)),tmp/f'{s:02}.parquet',compression='zstd')
            h={k:t[k].to_numpy() for k in ('j','i','t','y','arm','cell')}
            import author_history
            n,y=author_history.reference_removal(h,(2,25,4,4,500))
            np.savez_compressed(tmp/'reference_delta.npz',n=n,s=y)
            return dict(rows=len(t),grants=int(np.sum(h['y'])),arms=int(np.sum(h['arm'])),removed=rows(tmp/'removed.parquet'),relabeled=rows(tmp/'relabeled.parquet'))
        finally:db.close()
    return stage(job['out'],job['conf'],build,[job['material']]+[p['path'] for p in job['old']])[1]

def build(a,run,conf,auth):
    old=auth['legacy']['bound'];root=run/'PRIVATE/decision_inputs';jobs=[]
    for r in auth['donors']:
        jobs.append(dict(material=r['path'],rows=r['rows'],old=[p for p in old['parts'] if p['month']==r['month']],
            authors=old['binding']['author_ids'],out=str(root/'donors'/r['month']),memory=3.,conf=conf))
    c.mapped(project_job,jobs,min(a.workers,2),'Corrected monthly donor inputs')
    parts=[]
    for j in jobs:
        for s in range(16):
            p=Path(j['out'])/f'{s:02}.parquet'
            parts.append(dict(path=str(p),month=Path(j['out']).name,shard=s,rows=rows(p),bytes=p.stat().st_size,sha256=sha(p)))
    def reference(tmp):
        n=np.zeros((2,25,4,4,500),np.int64);y=np.zeros_like(n)
        for j in jobs:
            with np.load(Path(j['out'])/'reference_delta.npz') as z:n+=z['n'];y+=z['s']
        require(np.all((n>=y)&(y>=0)),'Impossible reference counts')
        ref=c.frozen.r.num.expanding_reference(n[:,:24],y[:,:24])
        np.save(tmp/'reference.npy',ref,allow_pickle=False)
        np.savez_compressed(tmp/'counts.npz',n=n,s=y)
        return dict(eligible_donors=int(n[0].sum()),grants=int(y[0].sum()),held_out_both_roles=True)
    rr,_=stage(root/'reference',conf,reference,[Path(j['out'])/'reference_delta.npz' for j in jobs])
    history=[];futures=[];alljobs=[]
    for r in auth['donors']:
        p=root/'history'/r['month'];history.append(str(p))
        alljobs.append(dict(parts=[x['path'] for x in parts if x['month']==r['month']],authors=old['binding']['author_ids'],memory=3.,conf=conf,output=str(p)))
    c.mapped(c.fast.history_index_job,alljobs,min(a.workers,2),'Rebuilding behavioral histories')
    mainjobs=[]
    for r in auth['material']['records']:
        p=root/'futures'/r['month'];futures.append(str(p));mainjobs.append(dict(panel=r['path'],memory=3.,conf=conf,output=str(p)))
    c.mapped(c.fast.main_index_job,mainjobs,min(a.workers,2),'Rebuilding first later choices and roles')
    bound=dict(old,parts=parts,reference=str(rr/'reference.npy'),features=dict(old['features'],histories=history,futures=futures,history_conf=conf,main_conf=conf))
    result=dict(auth['legacy'],bound=bound)
    save(run/'PRIVATE/MATERIAL_BOUND.json',result)
    c.csv_out(run/'report/DONOR_REBUILD.csv',[dict(month=Path(j['out']).name,**{k:v for k,v in c.load(Path(j['out'])/'_DONE.json').items() if k in ('rows','grants','arms','removed','relabeled')}) for j in jobs])
    return result
