"""Tests of rectangular projection, column resume, and one-game overlay."""
import copy,io,json,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
import sparse_fe

def numerical(root):
    rng=np.random.default_rng(511);n=9000
    hour=np.repeat(np.arange(90),100);month=hour//10
    cell=month*4+rng.integers(0,4,n)
    date=hour//3;anchor=hour.copy();anchor[299::300]+=1
    # Calendar dependence need not correspond to one FE nesting in another.
    groups=[cell,date,hour%21,anchor]
    a=np.column_stack([(cell%4==0).astype(float),rng.normal(size=n),month.astype(float)])
    w=10.**rng.uniform(-3,0,n)
    sparse_fe.configure(root/'columns','test')
    z,it,err=sparse_fe.absorb(a,w,groups)
    D=np.column_stack([pd.get_dummies(g,dtype=float).to_numpy() for g in groups])
    b=np.linalg.lstsq(D*np.sqrt(w)[:,None],a*np.sqrt(w)[:,None],rcond=1e-13)[0]
    assert np.max(np.abs(z-(a-D@b)))<3e-8
    assert err<=1e-10
    with patch.object(sparse_fe,'lsmr',side_effect=AssertionError('Completed column was recomputed')):
        z2,_,_=sparse_fe.absorb(a,w,groups)
    assert np.array_equal(z,z2) and sparse_fe.LAST_DIAGNOSTIC['reused_columns']==3
    cp=next((root/'columns').glob('*/column_001.npz'));cp.write_bytes(b'damaged')
    try:sparse_fe.absorb(a,w,groups)
    except RuntimeError as e:assert 'Damaged' in str(e)
    else:raise AssertionError('Damaged FE column accepted')
    sparse_fe.CHECKPOINT_ROOT=None;sparse_fe.MODEL_KEY=None
    print('RECTANGULAR_TEST_OK: calendar dependencies; weighted explicit-dummy parity; exact column resume; damage rejection.',flush=True)

def timestamp(root):
    from util import snapshot,sha,load
    from resume import timestamp_audit
    from timestamp_recovery import recover,validate_game,fetch_game
    from history import prefix_job
    run=root/'run';(run/'PRIVATE').mkdir(parents=True)
    pd.DataFrame({'chooser':[1]}).to_parquet(run/'PRIVATE/needed.parquet',index=False)
    t=int(pd.Timestamp('2023-06-21',tz='UTC').timestamp()*1000)
    source=root/'source.parquet'
    data=pd.DataFrame(dict(game_id=['aaaa0001','abcd1234','zzzz0000'],utc_ms=[t-1000,None,0],
        white_id=[1,1,50],black_id=[2,9,51],white_elo=[1610]*3,black_elo=[1600]*3,result_code=[2]*3))
    data.to_parquet(source,index=False);before=sha(source)
    rec=dict(path=str(source),speed='bullet',speed_code=1,month='2023-06',rows=3,bytes=source.stat().st_size,stat=snapshot(source))
    panel=root/'panel.parquet';pd.DataFrame(dict(chooser_user_id=[1],chooser_username_norm=['alice'])).to_parquet(panel,index=False)
    cat=dict(chronology=[rec],main=dict(month_records=[dict(path=str(panel))]))
    audit=timestamp_audit(cat,run)
    assert audit['status']=='BLOCKED_AFFECTED_CHOOSER_TIMESTAMP'
    obj=dict(id='abcd1234',createdAt=t+451,lastMoveAt=t+65000,rated=True,variant='standard',speed='bullet',
        status='mate',winner='white',players=dict(white=dict(rating=1610,user=dict(id='alice')),black=dict(rating=1600,user=dict(id='bob'))))
    payload=(json.dumps(obj)+'\n').encode()
    with patch('urllib.request.urlopen',return_value=io.BytesIO(payload)) as network:
        result=recover(cat,run,'test',audit);assert network.call_count==1
    assert result['status']=='PASS_VERIFIED_TIMESTAMP_OVERLAY'
    assert sha(source)==before
    counts=pd.read_parquet(prefix_job((rec,str(run),'test'))).set_index('chooser')
    assert counts.n.to_dict()=={1:2} and counts.loc[1,'last_t']==t
    with patch('urllib.request.urlopen',side_effect=AssertionError('Repeated API request')):
        assert fetch_game('abcd1234',run/'PRIVATE/timestamp_recovery')==obj
    row=data.iloc[1].to_dict()
    for field,value in [('id','wrong123'),('createdAt',0),('rated',False),('winner','black')]:
        bad=copy.deepcopy(obj);bad[field]=value
        try:validate_game(bad,row,{1:'alice'})
        except RuntimeError:pass
        else:raise AssertionError('Incorrect game metadata accepted: '+field)
    bad=copy.deepcopy(obj);bad['players']['white']['user']['id']='someone_else'
    try:validate_game(bad,row,{1:'alice'})
    except RuntimeError:pass
    else:raise AssertionError('Wrong chooser accepted')
    print('TIMESTAMP_RECOVERY_TEST_OK: one request; ID/name/rating/result/month checks; cache reuse; source unchanged; strict prefix count restored.',flush=True)

def main():
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);numerical(root);timestamp(root)

if __name__=='__main__':main()
