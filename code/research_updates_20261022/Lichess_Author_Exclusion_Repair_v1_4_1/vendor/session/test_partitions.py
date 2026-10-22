"""Independent annotation parity, partition resume, recent-checkpoint reuse, no wait."""
from util import *
import tempfile
import pyarrow.compute as pc
from partition_annotation import annotate,equal_columns,worker,write_arrow


def random_table(n_accounts=21,n_per=80):
    rng=np.random.default_rng(929);rows=[];expected=[]
    for a in range(n_accounts):
        t=1700000000000+a*100000000;prev=None if a%3==0 else t-1000
        carries={g:int(rng.integers(0,20)) for g in (15,30,60)}
        cens={g:bool(a%2) for g in (15,30,60)}
        sid={g:0 for g in (15,30,60)};pos=carries.copy()
        start_carry=None if a%4==0 else t-500000;start=start_carry
        for j in range(n_per):
            t+=int(rng.choice([0,1000,899999,900000,1799999,1800000,3599999,3600000]))
            row=dict(chooser=a+1,t=t,ordinal=j,game_id=f'g{a:04d}_{j:04d}',prev_t=prev,
                result=j%3-1,rating_diff=None if j%13==0 else float(j%7),tie_n=1,speed_code=j%5)
            want=dict(chooser=a+1,t=t,ordinal=j,game_id=row['game_id'])
            for g in (15,30,60):
                new=prev is None or t-prev>=g*60000
                if new:sid[g]+=1;pos[g]=0
                pos[g]+=1
                row.update({f'sid{g}':sid[g],f'carry{g}':carries[g],f'carry_cens{g}':cens[g]})
                want.update({f'pos{g}':pos[g],f'cens{g}':sid[g]==0 and cens[g]})
                if g==30 and (new or j==0 and start is None):start=t
            row['carry_start30']=start_carry;want['start30']=start
            rows.append(row);expected.append(want);prev=t
    order=rng.permutation(len(rows))
    return pa.Table.from_pylist([rows[int(j)] for j in order]),pa.Table.from_pylist(expected)


def annotation_parity(root,large=False):
    t,expected=random_table(128 if large else 21,3000 if large else 80)
    original,actual,latest,summary=annotate(t)
    equal_columns(actual,expected,expected.column_names)
    c=db(root/'spill',.2 if large else 1,2)
    try:
        if large:c.execute('SET debug_force_external=true')
        c.register('sessions',t)
        cols=[]
        for g in (15,30,60):
            cols += [f'row_number() OVER(PARTITION BY chooser,sid{g} ORDER BY t,ordinal,game_id)+CASE WHEN sid{g}=0 THEN carry{g} ELSE 0 END AS pos{g}',
                f'(sid{g}=0 AND carry_cens{g}) AS cens{g}']
        cols.append('CASE WHEN sid30=0 THEN coalesce(carry_start30,min(t) OVER(PARTITION BY chooser,sid30)) ELSE min(t) OVER(PARTITION BY chooser,sid30) END AS start30')
        sql=c.execute('SELECT *, '+','.join(cols)+' FROM sessions ORDER BY chooser,t,ordinal,game_id').fetch_arrow_table()
        equal_columns(actual,sql,actual.column_names)
        c.register('got',actual)
        x=c.execute('SELECT chooser,start30,max(pos30)::BIGINT observed_session_length,bool_or(cens30) left_censored,max(t) last_t FROM got GROUP BY chooser,start30 ORDER BY chooser,start30').fetch_arrow_table()
        equal_columns(summary,x,summary.column_names)
    finally:c.close()
    # Wrong sessions or predecessors must fail before producing accepted outputs.
    for col in ('sid30','prev_t'):
        values=t[col].to_pylist();values[3]=(values[3] or 0)+123456
        broken=t.set_column(t.column_names.index(col),col,pa.array(values,type=t[col].type))
        try:annotate(broken)
        except RuntimeError:pass
        else:raise AssertionError('Invalid annotation dependency accepted: '+col)
    tasks=[]
    for bucket in range(3):
        mask=pa.array(np.asarray(t['chooser'])%3==bucket);p=root/f'input{bucket}.parquet'
        write_arrow(t.filter(mask),p)
        tasks.append(([p],str(root/f'output{bucket}'),f'test{bucket}',bucket,3,t.column_names))
    from history import parallel_jobs
    paths=parallel_jobs(worker,tasks,2,'Synthetic annotation partitions')
    assert sum(load(Path(p)/'CHECKS.json')['rows'] for p in paths)==t.num_rows
    before=sha(Path(tasks[0][1])/'_DONE.json');stamp=snapshot(Path(tasks[0][1])/'_DONE.json')
    worker(tasks[0]);assert before==sha(Path(tasks[0][1])/'_DONE.json') and stamp==snapshot(Path(tasks[0][1])/'_DONE.json')
    (Path(tasks[0][1])/'annotated.parquet').write_bytes(b'bad')
    try:worker(tasks[0])
    except RuntimeError:pass
    else:raise AssertionError('Damaged annotated cache accepted')
    print(f'ANNOTATION_PARITY_OK: {t.num_rows:,} events; independent loop and previous SQL; partition writes; damage gates.',flush=True)


def interrupted_month(root):
    import history
    run=root/'run';private=run/'PRIVATE';private.mkdir(parents=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(private/'needed.parquet',index=False)
    t=int(pd.Timestamp('2023-10-02',tz='UTC').timestamp()*1000)
    prefix=root/'prefix.parquet';pd.DataFrame(dict(chooser=[1,2,3],speed_code=[1]*3,n=[1]*3,last_t=[t-HOUR]*3)).to_parquet(prefix,index=False)
    previous=history.initial_state(run,[prefix],'resume_test',1,1)
    raw=root/'raw.parquet';pd.DataFrame(dict(game_id=['a','b','c'],utc_ms=[t,t+1000,t+2000],archive_ordinal=[0,1,2],
        white_id=[1,2,3],black_id=[2,3,1],result_code=[0,1,2],white_rating_diff=[1.,2.,3.],black_rating_diff=[-1.,-2.,-3.])).to_parquet(raw,index=False)
    records=[dict(path=str(raw),speed_code=1,stat=snapshot(raw))]
    old_parallel=history.parallel_jobs;proof={}
    def interrupt(fn,tasks,workers,label):
        fn(tasks[0]);p=Path(tasks[0][1])/'_DONE.json'
        proof['shard']=(p,sha(p),snapshot(p));p=private/'history_work/2023-10/inputs/_DONE.json'
        proof['input']=(p,sha(p),snapshot(p))
        raise RuntimeError('simulated interruption after first committed partition')
    try:
        history.parallel_jobs=interrupt
        try:history.month_history('2023-10',records,run,previous,'resume_test',2,4)
        except RuntimeError as exc:assert 'simulated interruption' in str(exc)
        else:raise AssertionError('Interruption not exercised')
        assert not (private/'history/2023-10/_DONE.json').exists()
        def resume(fn,tasks,workers,label):
            for p,h,s in proof.values():assert sha(p)==h and snapshot(p)==s
            fn(tasks[0]);p,h,s=proof['shard'];assert sha(p)==h and snapshot(p)==s
            return old_parallel(fn,tasks,workers,label)
        history.parallel_jobs=resume
        out=history.month_history('2023-10',records,run,previous,'resume_test',2,4)
        assert load(out/'_DONE.json')['history_rows']==6
        assert not (private/'history_work/2023-10').exists()
        assert load(run/'report/history_integrity/2023-10.json')['status']=='PASS'
    finally:history.parallel_jobs=old_parallel
    print('PARTITION_RESUME_OK: input and completed shard receipts reused; commit precedes disposable-file cleanup.',flush=True)


def recent_reuse(root):
    import handoff
    from test_resume import reuse_fixture
    f=reuse_fixture(root);prior_root=handoff.ROOT
    try:
        handoff.ROOT=f['authority'];project=f['project'];vkey='v101_fixture_key'
        vrun=project/'output/kac_repetition_sensitivity_v101/v101_fixture'
        js(vrun/'report/CONFIG.json',dict(project=str(project)))
        previous=handoff.prepare(f['cat'],vrun,vkey,2,1,1)
        ref=f['authority']/'authority/december_failure/history_integrity'
        js(f['authority']/'authority/v101_run.json',dict(run=vrun.name,key=vkey,partial_zip_sha256='fixture'))
        for month in ('2024-08','2024-09','2024-10','2024-11'):
            out=vrun/'PRIVATE/history'/month;out.mkdir()
            pd.DataFrame({'chooser':[1,2,3]}).to_parquet(out/'carry.parquet',index=False)
            records=[r for r in f['cat']['chronology'] if r['month']==month]
            k=digest([vkey,month,sha(previous/'_DONE.json'),[r['stat'] for r in records]])
            commit(out,k,sources=[checked(r['path']) for r in records],focal_rows=3)
            report=dict(status='PASS',focal_rows=3,written_original_focal_multiset_differences=0)
            js(ref/(month+'.json'),report);js(vrun/'report/history_integrity'/(month+'.json'),report)
            previous=out
        originals={str(p):(sha(p),snapshot(p)) for d in (f['parent'],vrun) for p in d.rglob('*') if p.is_file()}
        final=handoff.prepare_latest(f['cat'],f['run'],f['key'],2,1,1)
        assert final.name=='2024-11'
        assert all(sha(p)==h and snapshot(p)==s for p,(h,s) in originals.items())
        report=load(f['run']/'report/CHECKPOINT_REUSE.json')
        assert len(report['history_months'])==14 and report['first_month_to_build']=='2024-12'
        h=sha(final/'_DONE.json');handoff.prepare_latest(f['cat'],f['run'],f['key'],2,1,1)
        assert sha(final/'_DONE.json')==h
        (vrun/'PRIVATE/history/2024-10/carry.parquet').write_bytes(b'damaged')
        try:handoff.prepare_latest(f['cat'],f['run'],f['key'],2,1,1)
        except RuntimeError:pass
        else:raise AssertionError('Damaged newly reused history accepted')
    finally:handoff.ROOT=prior_root
    print('FOURTEEN_MONTH_REUSE_OK: dependency keys, reviewed PASS reports, unchanged files, resume and damaged-output rejection.',flush=True)


def no_wait():
    import util
    original=util.reservations
    def forbidden():raise AssertionError('Worker-capacity check was called')
    try:
        util.reservations=forbidden
        assert util.slots(10,10)==(10,[]) and util.slots(2,10)==(2,[])
    finally:util.reservations=original


def main(large=False):
    no_wait()
    with tempfile.TemporaryDirectory(prefix='kac_partitions_test_') as tmp:
        root=Path(tmp)
        for name,fn in [('annotation',lambda p:annotation_parity(p,large)),('interruption',interrupted_month),('recent',recent_reuse)]:
            p=root/name;p.mkdir();fn(p)
    print('PARTITION_TEST_OK: whole-account annotation, within-month recovery, fourteen-month reuse, no capacity wait.',flush=True)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.set_start_method('spawn')
    main('--large' in sys.argv)
