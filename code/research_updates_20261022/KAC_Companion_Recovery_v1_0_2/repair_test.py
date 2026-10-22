"""Regression checks for the two observed failure modes and cache adoption."""
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd
import sparse_fe

def projection_test():
    rng=np.random.default_rng(1928);n=7000
    hour=np.repeat(np.arange(70),100)
    month=hour//10
    month[999]=1 # one bridge; ordinary cyclic absorption is very slow here
    cell=rng.integers(0,17,n)
    a=rng.normal(size=(n,4));a[:,2]*=40
    w=rng.uniform(.02,1,n)
    groups=[cell,month,hour]
    z,it,last=sparse_fe.absorb(a,w,groups)
    D=np.column_stack([pd.get_dummies(g,dtype=float).to_numpy() for g in groups])
    b=np.linalg.lstsq(D*np.sqrt(w)[:,None],a*np.sqrt(w)[:,None],rcond=1e-13)[0]
    expected=a-D@b
    assert np.max(np.abs(z-expected))<2e-8
    assert last<=1e-10
    # Duplicate/nested FEs and disconnected components keep the same span.
    z2,_,_=sparse_fe.absorb(a,w,groups+[hour,cell])
    assert np.max(np.abs(z-z2))<2e-8
    zu,_,_=sparse_fe.absorb(a,np.ones(n),groups)
    bz=np.linalg.lstsq(D,a,rcond=1e-13)[0]
    assert np.max(np.abs(zu-(a-D@bz)))<2e-8
    print('SPARSE_FE_TEST_OK: nearly nested bridge; explicit weighted/unweighted dummy projection; redundant effects; original tolerance.',flush=True)

def audit_test(root):
    from util import snapshot,sha,commit,digest,load
    from resume import timestamp_audit,adopt_checkpoint
    from history import prefix_job
    run=root/'run';(run/'PRIVATE').mkdir(parents=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(run/'PRIVATE/needed.parquet',index=False)
    t=int(pd.Timestamp('2023-06-15',tz='UTC').timestamp()*1000)
    source=root/'history.parquet'
    d=pd.DataFrame(dict(game_id=['a','b','c'],white_id=[1,2,44],black_id=[2,3,45],utc_ms=[t,t+1000,0]))
    d.to_parquet(source,index=False)
    def record():return dict(path=str(source),speed='bullet',speed_code=1,month='2023-06',rows=3,bytes=source.stat().st_size,stat=snapshot(source))
    cat=dict(chronology=[record()])
    report=timestamp_audit(cat,run)
    assert report['status']=='PASS_NO_ANALYSIS_CHOOSER_AFFECTED'
    assert report['suspicious_files'][0]['invalid_rows']==1
    counts=prefix_job((record(),str(run),'audit_test'))
    got=pd.read_parquet(counts).set_index('chooser')
    assert got.n.to_dict()=={1:1,2:2,3:1}
    assert sha(source)==load(Path(counts).parent/'_DONE.json')['source']['sha256']
    d.loc[2,'white_id']=1;d.to_parquet(source,index=False)
    report=timestamp_audit(dict(chronology=[record()]),run)
    assert report['status']=='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP'
    assert report['affected_chooser_file_counts']==1
    other=root/'bad_run';(other/'PRIVATE').mkdir(parents=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(other/'PRIVATE/needed.parquet',index=False)
    try:prefix_job((record(),str(other),'bad'))
    except RuntimeError as e:assert 'Invalid analysis-chooser' in str(e)
    else:raise AssertionError('Affected zero timestamp silently accepted')
    # A genuinely future row is also blocked, not reclassified as a zero.
    d.loc[2,'utc_ms']=int(pd.Timestamp('2023-10-02',tz='UTC').timestamp()*1000);d.to_parquet(source,index=False)
    assert timestamp_audit(dict(chronology=[record()]),run)['status']=='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP'
    # Explicit provenance when a compatible checkpoint is adopted.
    old=root/'old';old.mkdir();pd.DataFrame({'x':[1,2]}).to_parquet(old/'counts.parquet',index=False)
    auth=dict(path=str(source),stat=snapshot(source),sha256=sha(source))
    commit(old,'old-key',source=auth,rows=2)
    before=sha(old/'_DONE.json')
    assert adopt_checkpoint(old,root/'new','old-key','new-key',source)
    assert sha(old/'_DONE.json')==before
    assert load(root/'new/_DONE.json')['adopted_from']['key']=='old-key'
    (old/'counts.parquet').write_bytes(b'corrupted')
    try:adopt_checkpoint(old,root/'bad_copy','old-key','new-key',source)
    except RuntimeError as e:assert 'Checkpoint damaged' in str(e)
    else:raise AssertionError('Damaged parent cache adopted')
    print('RESUME_TEST_OK: unrelated zero row; affected zero/future rows blocked; strict counts; source preservation; authenticated adoption; corruption rejected.',flush=True)

def main():
    projection_test()
    with tempfile.TemporaryDirectory() as d:audit_test(Path(d))

if __name__=='__main__':main()
