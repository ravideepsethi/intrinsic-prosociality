"""Prepare original pair-excluded instruments without estimating behavior."""
import shutil,sys,time
from common import *
sys.path.insert(0,str(PACKAGE/'vendor'))
import iv_numerics as num

def score_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    key=digest(dict(code=job['code'],shard=job['shard'],inputs=job['inputs']))
    def build(tmp):
        started=time.monotonic();c=connection(tmp/'spill',1,job['memory_mb'])
        try:
            c.execute('CREATE VIEW h AS SELECT * FROM '+scan(job['paths']))
            ht=c.execute('SELECT j,i,t,y,cell FROM h WHERE arm').to_arrow_table()
            h={n:arr(ht,n) for n in ht.column_names};del ht
            model=np.load(job['reference'],allow_pickle=False)
            if model.shape!=(2,32,4,4,500):raise RuntimeError('Extended reference model shape differs')
            counts=[]
            for m,month in enumerate(MONTHS):
                lo=int(STARTS[m]);hi=int(STARTS[m+1]) if m+1<len(STARTS) else int(dt.datetime(2026,5,1,tzinfo=dt.timezone.utc).timestamp()*1000)
                qt=c.execute(f'''SELECT gid game_id,j chooser_user_id,i recipient_id,t anchor_ms,start archive_start_ms,
                    ord archive_ordinal FROM h WHERE fair AND rt AND arm AND start>={lo} AND start<{hi}
                    ORDER BY gid''').to_arrow_table()
                q={n:arr(qt,n) for n in qt.column_names}
                result={**q,'month':np.full(len(qt),month,dtype='U7')}
                for ix,lag in enumerate((7,30)):
                    r=num.score_month(h['j'],h['i'],h['t'],h['y'],h['cell'],q['chooser_user_id'],q['recipient_id'],
                        int(STARTS[m]-lag*DAY),model[ix,m],4)
                    for name,value in r.items():result[f'{name}_{lag}d']=value
                    support5=(r['n']>=5)&np.isfinite(r['adjusted'])&np.isfinite(r['expected'])
                    support10=(r['n']>=10)&np.isfinite(r['adjusted'])&np.isfinite(r['expected'])
                    result[f'support5_{lag}d']=support5;result[f'common5_10_{lag}d']=support10
                    if np.any(support10 & ~support5):raise RuntimeError('Common support is not nested')
                out=tmp/('month='+month)/'scores_PRIVATE.parquet';out.parent.mkdir(parents=True)
                pq.write_table(pa.table(result),out,compression='zstd',row_group_size=131072)
                counts.append(dict(month=month,rows=len(qt)))
            return dict(shard=job['shard'],rows=sum(r['rows'] for r in counts),counts=counts,
                history_arm_rows=len(h['j']),elapsed_seconds=time.monotonic()-started)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    root,done=stage(Path(job['work'])/'scores'/f'shard-{job["shard"]:02d}'/key,key,job['inputs'],build,job['auth'])
    return dict(root=str(root),receipt=receipt(root/'_DONE.json'),result=done['result'])

def summarize(products,membership_root,work,auth,code,threads,memory_mb,inputs):
    key=digest(dict(code=code,inputs=inputs))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            roots=[Path(r['root']) for r in products]
            paths=[p for root in roots for p in sorted(root.glob('month=*/scores_PRIVATE.parquet'))]
            c.execute('CREATE VIEW s AS SELECT * FROM '+scan(paths))
            manifest=load(Path(membership_root)/'MAIN_INPUT_MANIFEST_PRIVATE.json')
            pp=[Path(membership_root)/r['path'] for r in manifest['months']]
            c.execute('CREATE VIEW main AS SELECT * FROM '+scan(pp))
            c.execute('''CREATE VIEW qualified AS SELECT game_id,month FROM main WHERE fair_competitive
                AND NOT tournament_like_event AND arm_eligible AND tc_base_s>0
                AND speed IN ('ultrabullet','bullet','blitz','rapid','classical')''')
            if c.execute('SELECT count(*) FROM qualified ANTI JOIN s USING(game_id)').fetchone()[0]:
                raise RuntimeError('A known-main scoring candidate lacks an all-source score record')
            if c.execute('SELECT count(*) FROM (SELECT game_id FROM s GROUP BY 1 HAVING count(*)>1)').fetchone()[0]:
                raise RuntimeError('Duplicate score record across history shards')
            summaries=[]
            for lag in (7,30):
                for scope,query in [('all_source_candidates','SELECT * FROM s'),
                        ('known_main_candidates','SELECT s.* FROM s SEMI JOIN qualified USING(game_id)')]:
                    rows=c.execute(f'''SELECT month,count(*) AS rows,count(*) FILTER(WHERE support5_{lag}d) support5,
                        count(*) FILTER(WHERE common5_10_{lag}d) common5_10,
                        stddev_samp(adjusted_{lag}d) FILTER(WHERE common5_10_{lag}d) score_sd_common,
                        count(*) FILTER(WHERE archive_start_ms-{97*DAY}>={int(STARTS[0])} AND common5_10_{lag}d) common_with_97day_history
                        FROM ({query}) GROUP BY month ORDER BY month''').fetchall()
                    summaries += [dict(scope=scope,lag_days=lag,month=r[0],candidate_rows=r[1],support5=r[2],
                        common5_10=r[3],score_sd_common=r[4],common_with_97day_history=r[5]) for r in rows]
            known=copy(c,'''SELECT s.* FROM s SEMI JOIN qualified USING(game_id)''',tmp/'known_main_candidate_scores_PRIVATE.parquet')
            write_json(tmp/'SCORE_INPUT_MANIFEST_PRIVATE.json',dict(paths=[str(p) for p in paths],
                known_main_scores='known_main_candidate_scores_PRIVATE.parquet',history_boundary='2023-09-01T00:00:00Z',
                cutoff='strictly before exposure month start minus lag; 7 and 30 days',pair_exclusion='all prior decisions between the focal pair removed',
                threshold_comparison='Minimum history floors 5 and 10; common sample is finite score with n>=10. Both use all qualifying prior decisions.',
                first_observed_pair_filter_applied=False,spacing_applied=False,mechanics_censor=None,
                complete90_outcome_cohort_built=False,final_iv_eligible_n=None))
            return dict(support=summaries,known_main_candidate_score_rows=known,
                score_scope='Candidate decisions before first-pair, spacing and complete-follow-up restrictions',
                historical_IV_reestimated=False,new_behavioral_coefficients=False)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(Path(work)/'support'/key,key,inputs,build,auth)
