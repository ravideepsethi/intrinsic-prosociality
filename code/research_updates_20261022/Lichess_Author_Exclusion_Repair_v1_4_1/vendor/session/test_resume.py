"""Independent old/new parity, strict failure, and checkpoint-reuse tests."""
from util import *
import tempfile
import handoff


def history_parity(root):
    import history,fixtures
    reference=module('reference_history',ROOT/'test_reference/history_v100.py')
    assert sha(ROOT/'test_reference/history_v100.py')=='7730acc425994aa9c0ddea6233717bf1bf2711cfa3a7131beac7f1840637016d'
    actual=sys.modules['history']
    try:
        for name,mod in [('old',reference),('new',history)]:
            p=root/name;p.mkdir();sys.modules['history']=mod;fixtures.history_test(p)
    finally:sys.modules['history']=actual
    for month in ('2023-10','2023-11'):
        for name in ('carry.parquet','counts.parquet','sessions30.parquet')+(
                ('focal_history.parquet',) if month=='2023-11' else ()):
            dfs=[]
            for side in ('old','new'):
                d=pd.read_parquet(root/side/'history_run/PRIVATE/history'/month/name)
                d=d.sort_values(list(d.columns),na_position='first').reset_index(drop=True)
                dfs.append(d)
            pd.testing.assert_frame_equal(*dfs)


def strict_failure(root):
    from history_checks import Checks
    run=root/'run';p=run/'PRIVATE/focal/2023-11/rows.parquet';p.parent.mkdir(parents=True)
    pd.DataFrame(dict(game_id=['missing1'],chooser=[1],t=[1],ordinal=[1],speed_code=[1])).to_parquet(p,index=False)
    c=db(root/'spill',1,1)
    try:
        c.execute('CREATE TEMP TABLE needed AS SELECT 1::BIGINT chooser')
        tracker=Checks(c,run,'2023-11',root/'out')
        c.execute('CREATE TEMP TABLE absent AS SELECT NULL::VARCHAR game_id,1::BIGINT chooser,1::BIGINT t,1::INTEGER speed_code WHERE false')
        try:tracker._identity('absent','fixture')
        except RuntimeError:pass
        else:raise AssertionError('Missing focal identity accepted')
        assert load(run/'report/history_integrity/2023-11.json')['status']=='BLOCKED_FOCAL_IDENTITY'
    finally:c.close()
    c=db(root/'spill2',1,1)
    try:
        tracker=Checks(c,run,'2023-10',root/'out2')
        tracker.report['expected_player_events']=2
        c.execute("CREATE TEMP TABLE events AS SELECT i::BIGINT chooser,'g'||i game_id,i::BIGINT t,i::BIGINT ordinal,1 speed_code FROM range(2) q(i)")
        tracker.stage('events');c.execute('CREATE TEMP TABLE ordered AS SELECT * FROM events WHERE chooser=0')
        try:tracker.stage('ordered')
        except RuntimeError:pass
        else:raise AssertionError('Intermediate row loss accepted')
    finally:c.close()


def reuse_fixture(root):
    project=root/'project';parent=project/'output/kac_repetition_sensitivity_v100/fixture_parent'
    run=project/'output/new';run.mkdir(parents=True);parent.mkdir(parents=True)
    local_authority=root/'package';(local_authority/'authority/diagnostic').mkdir(parents=True)
    ref=local_authority/'authority/identity_diagnostic';ref.mkdir()
    old_key='fixture_old';key='fixture_new'
    js(local_authority/'authority/repetition_parent.json',dict(parent_run='fixture_parent',parent_key=old_key))
    js(run/'report/CONFIG.json',dict(project=str(project)))
    js(ref/'STATUS.json',dict(status='DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED',failing_focal_rows=0,
        months_checked=15,focal_rows_checked=26073431))
    records=[];main=[]
    for j,month in enumerate(['2023-06','2023-10']+MONTHS):
        raw=project/f'source_{month}.parquet';pd.DataFrame({'data':[j]}).to_parquet(raw,index=False)
        r=dict(path=str(raw),month=month,speed='bullet',speed_code=1,rows=1,bytes=raw.stat().st_size,stat=snapshot(raw))
        records.append(r)
        if month in MONTHS:
            focal=parent/'PRIVATE/focal'/month;focal.mkdir(parents=True)
            pd.DataFrame({'chooser':[1,2,3]}).to_parquet(focal/'rows.parquet',index=False)
            source=checked(raw);source_sha=source['sha256']
            commit(focal,digest([old_key,source_sha]),source=source,rows=3)
            main.append(dict(path=raw,month=month,expected_sha256=source_sha,rows=3))
    (parent/'PRIVATE').mkdir(exist_ok=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(parent/'PRIVATE/needed.parquet',index=False)
    uncertain=parent/'PRIVATE/uncertain_prefix';uncertain.mkdir()
    pd.DataFrame({'chooser':[1]}).to_parquet(uncertain/'choosers.parquet',index=False)
    pd.DataFrame({'game_id':['']}).to_parquet(uncertain/'target.parquet',index=False)
    auth=checked(records[0]['path']);commit(uncertain,digest([old_key,auth['sha256']]),source=auth)
    js(local_authority/'authority/diagnostic/KEY_AND_TIME.json',dict(source_sha256=auth['sha256']))
    prefix=parent/'PRIVATE/prefix/bullet_2023-06';prefix.mkdir(parents=True)
    commit(prefix,digest([old_key,records[0],sha(uncertain/'_DONE.json'),'valid_timestamp_history']),source=auth)
    js(parent/'report/UNCERTAINTY.json',dict(status='READY_FOR_SENSITIVITY_TIMESTAMP_STILL_UNRESOLVED'))
    js(parent/'report/TIMESTAMP_AUDIT.json',dict(status='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP'))
    previous=parent/'PRIVATE/history/initial';previous.mkdir(parents=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(previous/'carry.parquet',index=False);commit(previous,old_key)
    inv=[]
    for month in ['2023-10']+[m for m in MONTHS if m<='2024-07']:
        h=parent/'PRIVATE/history'/month;h.mkdir()
        pd.DataFrame({'chooser':[1,2,3]}).to_parquet(h/'carry.parquet',index=False)
        recs=[r for r in records if r['month']==month]
        k=digest([old_key,month,sha(previous/'_DONE.json'),[r['stat'] for r in recs]])
        commit(h,k,sources=[checked(r['path']) for r in recs],focal_rows=0)
        inv.append(dict(month=month,completion_receipt_present=True,receipt_sha256=sha(h/'_DONE.json')));previous=h
    js(ref/'PARENT_CHECKPOINTS.json',dict(months=inv))
    return dict(project=project,parent=parent,run=run,key=key,authority=local_authority,
        cat=dict(main=dict(month_records=main,authority=dict(choosers=3)),chronology=records))


def reuse_test(root):
    f=reuse_fixture(root);saved_root=handoff.ROOT
    try:
        handoff.ROOT=f['authority']
        originals={str(p):(sha(p),snapshot(p)) for p in f['parent'].rglob('*') if p.is_file()}
        final=handoff.prepare(f['cat'],f['run'],f['key'],2,1,1)
        assert final.name=='2024-07'
        assert all(sha(p)==s[0] and snapshot(p)==s[1] for p,s in originals.items())
        report=load(f['run']/'report/CHECKPOINT_REUSE.json')
        assert len(report['history_months'])==10 and report['focal_months']==24
        assert (final/'carry.parquet').is_symlink()
        receipt_sha=sha(final/'_DONE.json')
        assert handoff.prepare(f['cat'],f['run'],f['key'],2,1,1)==final
        assert sha(final/'_DONE.json')==receipt_sha
        # Corruption of a referenced completed file is still rejected on resume.
        (f['parent']/'PRIVATE/history/2024-07/carry.parquet').write_bytes(b'damaged')
        try:handoff.prepare(f['cat'],f['run'],f['key'],2,1,1)
        except RuntimeError:pass
        else:raise AssertionError('Corrupted reused history accepted')
    finally:handoff.ROOT=saved_root


def needed_set_failure(root):
    f=reuse_fixture(root);saved_root=handoff.ROOT
    try:
        handoff.ROOT=f['authority']
        pd.DataFrame({'chooser':[1,2]}).to_parquet(f['parent']/'PRIVATE/needed.parquet',index=False)
        try:handoff.prepare(f['cat'],f['run'],f['key'],2,1,1)
        except RuntimeError as exc:assert 'Needed chooser set differs' in str(exc)
        else:raise AssertionError('Incomplete parent chooser set accepted')
        report=load(f['run']/'report/NEEDED_CHOOSER_CHECK.json')
        assert report['missing_from_parent']==1 and report['extra_in_parent']==0
        assert not (f['run']/'PRIVATE/history').exists()
    finally:handoff.ROOT=saved_root


def spill_test(root):
    from history_checks import Checks,FEATURES
    c=db(root/'spill',.2,2)
    try:
        c.execute('SET debug_force_external=true')
        n=1000000
        c.execute(f'''CREATE TEMP TABLE annotated AS SELECT 'g'||(i//2) game_id,
            (i%2)+1 AS chooser, 1700000000000+(i//2)*1000 t,i//2 ordinal,1 speed_code,
            i//2 prior_same_speed,1 tie_n,NULL::BIGINT prev_t,NULL::VARCHAR prev_gid,
            NULL::INTEGER prev_result,NULL::INTEGER prev_tie,
            1::BIGINT pos15,1::BIGINT pos30,1::BIGINT pos60,
            false cens15,false cens30,false cens60 FROM range({n}) q(i)''')
        run=root/'run';p=run/'PRIVATE/focal/2023-11/rows.parquet'
        copy(c,'SELECT game_id,chooser,t,ordinal,speed_code FROM annotated WHERE chooser=1 AND ordinal%20=0',p)
        c.execute('CREATE TEMP TABLE needed AS SELECT 1::BIGINT chooser')
        c.execute('CREATE TEMP VIEW focal AS SELECT * FROM '+scan(p))
        tracker=Checks(c,run,'2023-11',root/'out')
        tracker.features()
        dest=root/'written.parquet'
        copy(c,'SELECT f.*,'+','.join('a.'+x for x in FEATURES)+' FROM focal f JOIN focal_features a USING(chooser,game_id)',dest)
        tracker.written(dest);tracker.finish()
        assert pq.ParquetFile(dest).metadata.num_rows==25000
        print('SPILL_JOIN_TEST_OK: one million history rows; 25,000 focal rows; forced external execution; DuckDB '+duckdb.__version__,flush=True)
    finally:c.close()


def main(full=False):
    with tempfile.TemporaryDirectory(prefix='kac_resume_test_') as tmp:
        root=Path(tmp)
        for name,fn in [('parity',history_parity),('failure',strict_failure),('reuse',reuse_test),
                       ('needed_set_failure',needed_set_failure)]+([('spill',spill_test)] if full else []):
            folder=root/name;folder.mkdir();fn(folder)
    print('RESUME_TEST_OK: old/new history equality; needed-set and stage guards; all completed outputs reused; parent bytes/metadata preserved; damaged cache rejected.',flush=True)


if __name__=='__main__':main('--spill-check' in sys.argv)
