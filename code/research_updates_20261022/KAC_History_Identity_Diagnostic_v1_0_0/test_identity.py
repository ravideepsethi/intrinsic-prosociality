"""Synthetic end-to-end checks, including the parent failure and export boundary."""
from util import *
import tempfile,zipfile
import identity
import run as runner


def make_fixture(root):
    t=int(pd.Timestamp('2024-08-02',tz='UTC').timestamp()*1000)
    ids=['good0001','miss0002','user0003','time0004','sped0005','dupe0006','badk0007','ordi0008']
    f=pd.DataFrame(dict(game_id=ids,chooser=list(range(11,19)),t=[t+i*1000 for i in range(8)],
        ordinal=list(range(101,109)),speed_code=[1]*8))
    source=f.rename(columns={'chooser':'chooser_user_id','t':'utc_ms','ordinal':'archive_ordinal'}).copy()
    source['disconnected_user_id']=list(range(201,209));source['disconnected_color']='black'
    source['chooser_elo']=1600;source['disconnected_elo']=1601;source['api_speed']='bullet'
    source['private_unexported_field']='PRIVATE_SENTINEL_NOT_FOR_EXPORT'
    source_path=root/'source.parquet';source.to_parquet(source_path,index=False)
    focal_path=root/'focal.parquet';f.to_parquet(focal_path,index=False)
    raw=pd.DataFrame(dict(game_id=ids,white_id=list(range(11,19)),black_id=list(range(201,209)),
        utc_ms=f.t,archive_ordinal=f.ordinal,result_code=[1]*8))
    raw=raw.loc[raw.game_id!='miss0002'].copy()
    raw.loc[raw.game_id=='user0003',['white_id','black_id']]=[999,998]
    raw.loc[raw.game_id=='time0004','utc_ms']+=1000
    raw.loc[raw.game_id=='badk0007','game_id']=''
    raw.loc[raw.game_id=='ordi0008','archive_ordinal']=9999
    raw=pd.concat([raw,raw.loc[raw.game_id=='dupe0006']],ignore_index=True)
    records=[]
    for speed in (1,2):
        select=(raw.game_id=='sped0005') if speed==2 else (raw.game_id!='sped0005')
        p=root/f'raw{speed}.parquet';raw.loc[select].to_parquet(p,index=False)
        records.append(dict(path=str(p),speed_code=speed,speed=SPEEDS[speed],month='2024-08',
            rows=int(select.sum()),bytes=p.stat().st_size,stat=snapshot(p)))
    p=root/'neighbor.parquet'
    pd.DataFrame(dict(game_id=['miss0002'],white_id=[12],black_id=[202],utc_ms=[t+1000],archive_ordinal=[102])).to_parquet(p,index=False)
    neighbor=dict(path=str(p),speed_code=1,speed='bullet',month='2024-07',rows=1,bytes=p.stat().st_size,stat=snapshot(p))
    return source_path,focal_path,records,neighbor


def compare_test(root):
    source,focal,records,neighbor=make_fixture(root)
    baseline={str(p):sha(p) for p in [source,focal]+[Path(r['path']) for r in records+[neighbor]]}
    auth=checked(source);frec=dict(path=str(focal),sha256=sha(focal),stat=snapshot(focal),source=auth,
        month='2024-08',receipt_sha256='fixture')
    job=('2024-08',frec,records,str(root/'output'),'fixture_key',1,1)
    a=runner.month_job(job)
    assert a['focal_rows']==8 and a['failing_focal_rows']==6
    assert a['missing_game_keys']==2 and a['game_present_wrong_chooser']==1
    assert a['duplicated_chooser_game_pairs']==1 and a['time_or_speed_mismatches']==2
    assert a['replicated_parent_check']==[9,3,5]
    assert a['ordinal_mismatches_auxiliary_only']==1
    assert runner.month_job(job)['reused']
    deep=runner.deep_job(('2024-08',frec,records+[neighbor],str(root),str(root/'output'),'fixture_key',1,1))
    assert deep['canonical']['cached_projection_matches_certified_source']
    assert deep['candidates']['coherent_except_key_rows']==1
    assert deep['candidates']['same_key_wrong_players_rows']==1
    assert deep['candidates']['same_key_wrong_time_rows']==1
    assert deep['candidates']['same_key_wrong_speed_rows']==1
    assert deep['candidates']['history_candidate_key_shapes']['empty']==1
    assert deep['candidates']['exact_identity_rows']==3  # duplicate pair plus neighbor
    assert all(x['status']=='NO_PRODUCER_COMMAND' for x in deep['declared_upstream'])
    assert runner.deep_job(('2024-08',frec,records+[neighbor],str(root),str(root/'output'),'fixture_key',1,1))==deep
    assert all(sha(p)==h for p,h in baseline.items())
    # Strictly private keys/raw rows must not leak into the aggregate ZIP.
    report=root/'output/report';js(report/'CHECK.json',a);js(report/'PROBE.json',deep)
    path=runner.export(root/'output',root,'TEST')
    with zipfile.ZipFile(path) as z:
        assert all(not n.startswith('PRIVATE/') for n in z.namelist())
        data=b'\n'.join(z.read(n) for n in z.namelist())
        for literal in ['PRIVATE_SENTINEL_NOT_FOR_EXPORT','good0001','miss0002','user0003','badk0007']:
            assert literal.encode() not in data
        m=json.loads(z.read('report/REPORT_MANIFEST.json'))
        for row in m['files']:assert hashlib.sha256(z.read('report/'+row['path'])).hexdigest()==row['sha256']
    # Corrupt an already-completed diagnostic checkpoint; resume must fail.
    out=root/'output/PRIVATE/month_checks/2024-08'
    (out/'bad_focal.parquet').write_bytes(b'corrupt')
    try:runner.month_job(job)
    except RuntimeError:pass
    else:raise AssertionError('Damaged checkpoint accepted')


def exact_parent_failure(root):
    t=1724000000000
    f=pd.DataFrame(dict(game_id=['check001','lost0001','lost0002','lost0003'],
        chooser=[11,12,13,14],t=[t]*4,ordinal=[1,2,3,4],speed_code=[1]*4))
    p=root/'f.parquet';f.to_parquet(p,index=False)
    h=root/'h.parquet';pd.DataFrame(dict(game_id=['check001'],utc_ms=[t],archive_ordinal=[1],
        white_id=[11],black_id=[100])).to_parquet(h,index=False)
    c=db(root/'spill',1,1)
    try:a=identity.compare_month(c,p,[dict(path=str(h),speed_code=1)],root/'out')
    finally:c.close()
    assert a['replicated_parent_check']==[4,3,3] and a['failing_focal_rows']==3


def upstream_test(root):
    project=root/'project';base=project/'sorted';p=base/'events_replay_sorted_time/speed=bullet/month=2024-08/part-00000.parquet'
    p.parent.mkdir(parents=True);p.write_bytes(b'not-read')
    numeric=project/'numeric/events_numeric/month=2024-08/speed=bullet';numeric.mkdir(parents=True)
    pd.DataFrame(dict(game_id=['upkey001','other001'],archive_ordinal=[11,12],
        utc_ts=['2024-08-01 12:00:00','bad'])).to_parquet(numeric/'part.parquet',index=False)
    js(base/'command.json',dict(numeric_root=str(project/'numeric')))
    target=root/'targets.parquet';pd.DataFrame(dict(game_id=['upkey001'],ordinal=[11])).to_parquet(target,index=False)
    c=db(root/'spill',1,1)
    try:a=identity.upstream(c,target,[dict(path=str(p),speed='bullet',speed_code=1)],project,'2024-08',root/'out')
    finally:c.close()
    assert a[0]['candidate_rows']==1 and a[0]['exact_key_rows']==1


def spawn_test(root):
    # Exercise the same macOS-style spawned-worker entry path as the real scan.
    source,focal,records,_=make_fixture(root)
    frec=dict(path=str(focal),sha256=sha(focal),stat=snapshot(focal),source=checked(source),month='2024-08')
    tasks=[('2024-08',frec,records,str(root/f'out{i}'),'spawn_key',1,1) for i in range(2)]
    with runner.cf.ProcessPoolExecutor(max_workers=2,mp_context=runner.mp.get_context('spawn')) as ex:
        got=list(ex.map(runner.month_job,tasks))
    assert [x['failing_focal_rows'] for x in got]==[6,6]


def receipt_test(root):
    source,focal,records,_=make_fixture(root)
    parent=root/'parent';base=parent/'PRIVATE/focal/2024-08';base.mkdir(parents=True)
    shutil.copyfile(focal,base/'rows.parquet')
    original=checked(source);pk='parent_fixture'
    commit(base,digest([pk,original['sha256']]),source=original,rows=8)
    record=dict(month='2024-08',path=source,expected_sha256=original['sha256'],rows=8)
    got=runner.read_focal_receipt(parent,record,pk)
    assert got['sha256']==sha(focal) and got['source']['sha256']==sha(source)
    initial=parent/'PRIVATE/history/initial';initial.mkdir(parents=True)
    (initial/'fixture.txt').write_text('initial');commit(initial,pk)
    october=parent/'PRIVATE/history/2023-10';october.mkdir()
    (october/'fixture.txt').write_text('history');commit(october,digest([pk,'2023-10',sha(initial/'_DONE.json'),[]]),focal_rows=0)
    inv=runner.inventory(parent,records,pk)
    assert sum(x['completion_receipt_present'] for x in inv)==1
    (october/'fixture.txt').write_text('damaged size')
    try:runner.inventory(parent,records,pk)
    except RuntimeError as exc:assert str(exc)=='COMPLETED_HISTORY_FILE_MISSING_OR_RESIZED'
    else:raise AssertionError('Damaged history size accepted')


def main():
    with tempfile.TemporaryDirectory(prefix='kac_identity_test_') as tmp:
        root=Path(tmp)
        for name,fn in [('comparison',compare_test),('parent',exact_parent_failure),('upstream',upstream_test),('spawn',spawn_test),('receipt',receipt_test)]:
            p=root/name;p.mkdir();fn(p)
    print('IDENTITY_TEST_OK: missing keys vs players; time/speed/duplicates; exact parent tuple; neighbor and upstream probes; source preservation; resume integrity; private export exclusion; spawned workers.',flush=True)


if __name__=='__main__':main()
