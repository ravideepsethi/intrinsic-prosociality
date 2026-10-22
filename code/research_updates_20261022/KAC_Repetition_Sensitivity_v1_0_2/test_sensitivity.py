import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
from util import *
import tempfile
from fixtures import focal_frame,history_test,quick
import repetition as r

def prefix_test(root):
    from history import prefix_job
    from uncertainty import valid_prefix_sql
    run=root/'prefix_run';private=run/'PRIVATE';target=private/'uncertain_prefix'
    target.mkdir(parents=True)
    pd.DataFrame({'chooser':[1]}).to_parquet(private/'needed.parquet',index=False)
    stamp=int(pd.Timestamp('2023-06-15',tz='UTC').timestamp()*1000)
    d=pd.DataFrame(dict(game_id=['valid001','','valid003',None],utc_ms=[stamp,0,stamp+1000,None],
        white_id=[1,1,5,7],black_id=[2,3,1,8],archive_ordinal=[10,11,12,13]))
    path=root/'raw.parquet';d.to_parquet(path,index=False)
    d.iloc[[1]].to_parquet(target/'target.parquet',index=False)
    pd.DataFrame({'chooser':[1]}).to_parquet(target/'choosers.parquet',index=False)
    auth=checked(path);commit(target,'testtarget',source=auth)
    record=dict(path=str(path),stat=snapshot(path),speed='bullet',speed_code=1,month='2023-06',rows=len(d))
    out=prefix_job((record,run,'prefixkey'));got=pd.read_parquet(out)
    assert len(got)==1 and got.iloc[0]['n']==2 and got.iloc[0]['last_t']==stamp+1000
    assert sha(path)==auth['sha256'] and pd.read_parquet(path).iloc[1].utc_ms==0
    assert prefix_job((record,run,'prefixkey'))==out
    # The exception is a single exact tuple. Another invalid relevant row survives
    # SQL filtering and is therefore rejected by the unchanged positive-time gate.
    extra=d.iloc[[1]].copy();extra['archive_ordinal']=14
    altered=root/'extra.parquet';pd.concat([d,extra]).to_parquet(altered,index=False)
    c=db(root/'testspill',1,1)
    try:
        c.execute('CREATE VIEW needed AS SELECT 1::BIGINT chooser')
        x=c.execute(valid_prefix_sql(altered,'needed',run,True)).fetchdf()
        assert len(x)==3 and int((x.utc_ms==0).sum())==1
    finally:c.close()
    # Tampering cannot silently reuse the uncertain-record selection.
    (target/'target.parquet').write_bytes(b'bad')
    from uncertainty import source_is_uncertain
    try:source_is_uncertain(run,path)
    except RuntimeError:pass
    else:raise AssertionError('Damaged target accepted')

def estimates_test(root):
    models=[s for s in r.specs() if s['base_name']=='binary_primary']
    d=focal_frame(2500)
    d['prefix_count_uncertain']=((d.chooser==22)&(d.speed_code==1)).astype(int)
    rows=[];expected=[]
    for s in models:
        a,X,names,p=r.design(d,s);W,y,starts=r.within(a,X)
        fit=r.solve(W.T@W,W.T@y)
        D=pd.get_dummies(a.chooser,dtype=float).to_numpy()
        b=np.linalg.lstsq(np.column_stack([D,X]),100*a.y.to_numpy(),rcond=1e-10)[0][D.shape[1]:]
        assert np.allclose(fit['beta'][:p],b[:p],atol=1e-7)
        score=np.add.reduceat(W*(y-W@fit['beta'])[:,None],starts,axis=0)
        expected.append((W.T@W,W.T@y,score.T@score,len(a),len(starts),fit))
        rows.append(a[['chooser','game_id']])
    assert rows[0].equals(rows[1])
    chunks=[]
    for j in range(3):
        f=root/f'shard{j}.parquet';d.loc[d.chooser%3==j].to_parquet(f,index=False);chunks.append(f)
    outputs=[r.worker(([p],root/f'pass1_{j}',f'p1_{j}',1,models,[])) for j,p in enumerate(chunks)]
    first=r.reduce(outputs);fits=[]
    for j,e in enumerate(expected):
        assert np.allclose(first[f'{j}_xx'],e[0],atol=1e-7)
        assert np.allclose(first[f'{j}_xy'],e[1],atol=1e-7)
        assert int(first[f'{j}_n'])==e[3] and int(first[f'{j}_g'])==e[4]==50
        fits.append(r.solve(first[f'{j}_xx'],first[f'{j}_xy']))
    second=r.reduce([r.worker(([p],root/f'pass2_{j}',f'p2_{j}',2,models,fits)) for j,p in enumerate(chunks)])
    for j,e in enumerate(expected):assert np.allclose(second[f'{j}_meat'],e[2],atol=1e-5)
    # Both scenarios' SEs must use their own coefficient vector, not copied scores.
    assert not np.array_equal(second['0_meat'],second['1_meat'])
    assert r.worker(([chunks[0]],root/'pass1_0','p1_0',1,models,[]))==outputs[0]

def integration(root):
    d=focal_frame(3000);d['prefix_count_uncertain']=((d.chooser==22)&(d.speed_code==1)).astype(int)
    files=[]
    for j,m in enumerate(MONTHS):
        f=root/'PRIVATE/history'/m/'focal_history.parquet';f.parent.mkdir(parents=True)
        d.loc[d.month_code==j].to_parquet(f,index=False);files.append(str(f))
    for j,m in enumerate(['2023-10']+MONTHS):
        f=root/'PRIVATE/history'/m/'sessions30.parquet';f.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(dict(chooser=[1,2,22],start30=[1699000000000+j*100000000]*3,
            observed_session_length=[2,3,18],left_censored=[False]*3,
            last_t=[1699003000000+j*100000000]*3)).to_parquet(f,index=False)
    result=r.run(files,root,'testdriver',2,3)
    assert result['status']=='SENSITIVITY_ESTIMATED_NOT_TIMESTAMP_REPAIR'
    coeff=pd.read_csv(root/'report/repetition/coefficients.csv')
    compare=pd.read_csv(root/'report/repetition/count_scenario_comparison.csv')
    assert len(coeff)==200 and len(compare)==100
    assert all(len(v)==4 for v in load(root/'report/repetition/primary_families.json').values())
    assert load(root/'report/repetition/COUNT_SCENARIO_SUMMARY.json')['scenario_sample_sizes_identical']
    before=sha(root/'report/repetition/coefficients.csv')
    r.run(files,root,'testdriver',2,3)
    assert before==sha(root/'report/repetition/coefficients.csv')
    print('INTEGRATION_OK: twenty models; independent scenario covariance; 200 contrasts; identical samples; resumable output.',flush=True)

def main(full=False):
    quick()
    reserve=process_reservations('5 /a/python /other/lichess/run.py --worker-budget 7',99,'/mine')
    assert reserve[0]['workers']==7
    with tempfile.TemporaryDirectory(prefix='kac_repetition_test_') as temp:
        root=Path(temp);prefix_test(root);estimates_test(root);history_test(root)
        if full:integration(root/'integration')
    print('SELF_TEST_OK: exact-row handling; unchanged sources; full account retention; explicit-dummy parity; separate covariance; cross-month sessions; count/tie rules; cache integrity.',flush=True)

if __name__=='__main__':
    import sys,multiprocessing
    multiprocessing.set_start_method('spawn')
    main('--integration' in sys.argv)
