#!/usr/bin/env python3
"""Numerical, boundary, streaming, checkpoint and synthetic staging tests.

Synthetic fixtures are never reachable through the production command's
authentication path. They are not empirical Lichess findings.
"""
import os
for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[key]='1'
from pathlib import Path
import tempfile
import numpy as np
from scipy import sparse
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from fe_core import groups,solve,iter_blocks
from milestone_model import milestone_geometry,specifications,select,design,MONTHS,SPEEDS
from prepare import empty_frame,stage_base,stage_shards,write_raw_tables
from estimator import Moment,prepare_block,common_design,init_moments,fit,score,save_moments,load_moments,holm
from pooled_utils import checkpoint_ok,certify_checkpoint
from source import pool_wave1_common as common


def fixture(seed=519,groups_count=80,per=35):
    rng=np.random.default_rng(seed);n=groups_count*per
    f={k:np.zeros(n) for k in empty_frame()}
    f.update(chooser=np.repeat(np.arange(groups_count,dtype=np.int64),per),y=rng.binomial(1,.15,n).astype(float),
        rating=rng.choice([1000,1500,2000,2500],n)+rng.integers(-25,26,n),
        gap=rng.normal(0,200,n),K=rng.uniform(8,30,n),board=rng.uniform(-100,700,n),
        ply=rng.integers(2,140,n),crd=rng.uniform(35,130,n),drd=rng.uniform(35,130,n),
        cvol=rng.uniform(.04,.08,n),dvol=rng.uniform(.04,.08,n),
        cclock=rng.uniform(5,300,n),dclock=rng.uniform(5,300,n),base_s=rng.choice([60,180,300,600],n),
        increment_s=rng.choice([0,1,2,3],n),white=rng.integers(0,2,n),
        month=rng.integers(0,24,n),speed=rng.integers(0,5,n))
    expected=1/(1+10**(f['gap']/400));f['payoff']=f['K']*(.5-expected);f['win']=f['payoff']+f['K']/2
    return f


def boundaries():
    f=dict(rating=np.array([2002,1998,1998,2000,2001,1999]),
           payoff=np.array([-3.,-1.,3.,-.2,-.8,-.1]),win=np.array([3.,4.,6.,3.,3.,.2]))
    _,_,_,_,lc,gc=milestone_geometry(f)
    assert lc.tolist()==[True,False,False,True,False,False]
    assert gc.tolist()==[False,True,False,False,False,False]
    _,_,_,_,rlc,rgc=milestone_geometry(f,rounding='nearest_integer')
    assert not rlc[3] and not rgc[5]
    f=dict(rating=np.array([1998.,2002.]),payoff=np.array([2.,-2.]),win=np.array([4.,3.]))
    _,_,_,_,lc,gc=milestone_geometry(f)
    assert not lc.any() and not gc.any() # Ending exactly at a threshold retains/reaches it.
    assert np.allclose(holm([.01,.04,.03]),[.03,.06,.06])
    print('BOUNDARIES_AND_HOLM_OK',flush=True)


def compare_dummy_ols():
    f=fixture();spec=specifications()[0]
    original,small,shared=prepare_block(f,spec,common_design(f))
    m=Moment(spec,empty_frame());m.add(original,small,shared)
    sol=solve(m.S,m.b,m.C)
    X,_,_,_=design(small,spec,shared);g,n,A=groups(small);y=small['y']
    # Explicit nuisance dummies for every chooser, independently fitted with SVD.
    D=np.column_stack([X.toarray(),A.T.toarray()])
    scale=np.linalg.norm(D,axis=0);active=scale>1e-12
    Ds=D[:,active]/scale[active]
    inv=np.linalg.pinv(Ds,rcond=1e-10)
    gamma=inv@y;full_beta=np.zeros(D.shape[1]);full_beta[active]=gamma/scale[active]
    direct=m.C@full_beta[:X.shape[1]]
    assert sol['identified'].all()
    assert np.max(np.abs(m.C@sol['beta']-direct))<2e-7
    residual=y-D@full_beta
    Cfull=np.zeros((2,D.shape[1]));Cfull[:,:X.shape[1]]=m.C
    influence=(Cfull[:,active]/scale[active])@inv
    scores_direct=(A@(influence*residual).T)
    cov_direct=np.asarray(scores_direct).T@np.asarray(scores_direct)
    e=y-np.asarray(X@sol['beta']).ravel();e-=np.asarray(A@e).ravel()[g]/n[g]
    scores_within=np.asarray((A@X.multiply(e[:,None]))@(sol['bread']@m.C.T))
    cov_within=scores_within.T@scores_within
    assert np.max(np.abs(cov_direct-cov_within))<1e-8
    # A known synthetic linear signal must be recovered after absorbing FE.
    synthetic_y=np.asarray(X[:,0].toarray()).ravel()*(-.025)+np.asarray(X[:,1].toarray()).ravel()*(-.015)+.2+g*.0001
    fake={k:v.copy() for k,v in small.items()};fake['y']=synthetic_y
    # Use normal equations directly: synthetic fractional y isn't a binary outcome fixture.
    sums=A@X;S=(X.T@X-(sparse.diags(1/np.sqrt(n))@sums).T@(sparse.diags(1/np.sqrt(n))@sums)).toarray()
    b=np.asarray(X.T@synthetic_y).ravel()-np.asarray(sums.T@((A@synthetic_y)/n)).ravel()
    recovered=m.C@solve(S,b,m.C)['beta']
    assert np.allclose(recovered,[-.025,-.015],atol=1e-8)
    # Collinear and constant treatment contrasts must be marked unidentified.
    bad=solve(np.array([[1.,1.,0],[1.,1.,0],[0,0,0]]),np.array([1.,1.,0]),np.eye(3))
    assert not bad['identified'].any()
    print('DUMMY_OLS_COEFFICIENTS_COVARIANCE_AND_KNOWN_SIGNAL_OK',flush=True)


def io_and_staging():
    f=fixture(groups_count=60,per=40)
    with tempfile.TemporaryDirectory(prefix='milestone_selftest_') as td:
        root=Path(td);p=root/'sorted.parquet';pq.write_table(pa.table(f),p)
        blocks=list(iter_blocks(p,73));assert sum(len(x['y']) for x in blocks)==len(f['y'])
        seen=[]
        for b in blocks:
            users=np.unique(b['chooser']);assert not np.intersect1d(users,seen).size;seen.extend(users.tolist())
        certify_checkpoint(p,'test');assert checkpoint_ok(p,'test')
        with p.open('ab') as stream:stream.write(b'corruption')
        try:checkpoint_ok(p,'test')
        except RuntimeError:pass
        else:raise AssertionError('Corruption went undetected')
        # Test production SQL and its missing-clock handling on a 24-month fixture.
        n=len(f['y']);f['cclock'][0]=np.nan
        raw=dict(chooser_user_id=f['chooser'],outcome_kind_draw=f['y'].astype(bool),chooser_elo=f['rating'].astype(np.int32),
                 disconnected_elo=(f['rating']+f['gap']).astype(np.int32),chooser_draw_payoff_v2=f['payoff'],
                 chooser_win_payoff_v2=f['win'],chooser_win_premium_v2=f['K']/2,
                 engine_eval_cp_disconnected=f['board'],ply_count=f['ply'],chooser_pre_rd_v2=f['crd'],
                 disconnected_pre_rd_v2=f['drd'],chooser_pre_sigma_v2=f['cvol'],disconnected_pre_sigma_v2=f['dvol'],
                 chooser_clock_last_obs_s=f['cclock'],disconnected_clock_last_obs_s=f['dclock'],tc_base_s=f['base_s'],
                 tc_inc_s=f['increment_s'],chooser_color=np.where(f['white']==1,'white','black'),
                 month=[MONTHS[i] for i in f['month']],api_speed=[SPEEDS[i] for i in f['speed']],
                 api_status=['timeout']*n,five_second_rule_passed=[True]*n,sf100k_nodes_requested=[100000]*n,
                 fair_competitive=[True]*n)
        source=root/'source.parquet';pq.write_table(pa.table(raw),source)
        expected=dict(rows=n,kind_draws=int(f['y'].sum()),fair_rows=n,fair_kind_draws=int(f['y'].sum()),choosers=60)
        db=duckdb.connect();private=root/'private'
        base,audit=stage_base(db,[source],private,'fixture',expected=expected)
        assert audit['counts']['missing_chooser_clock']==1
        shards=stage_shards(base,private,'fixture',3,n)
        allids=[]
        for shard in shards:
            for block in iter_blocks(shard,90):allids.extend(np.unique(block['chooser']).tolist())
        assert len(allids)==len(set(allids))==60
        report=root/'report';report.mkdir();write_raw_tables(db,base,report)
        assert (report/'raw_crossing_cells.csv').is_file()
        stage_base(db,[source],private,'fixture',expected=expected)
        db.close()
        # Compare chunked and unsplit moment accumulation.
        spec=specifications()[0];a=Moment(spec,empty_frame());b=Moment(spec,empty_frame())
        o,s,c=prepare_block(f,spec,common_design(f));a.add(o,s,c)
        for block in blocks:
            o,s,c=prepare_block(block,spec,common_design(block));b.add(o,s,c)
        # f's one missing clock was added after blocks were built; compare all
        # quantities not affected by that one control in a fresh streaming pass.
        pq.write_table(pa.table(f),root/'fresh.parquet');b=Moment(spec,empty_frame())
        for block in iter_blocks(root/'fresh.parquet',73):
            o,s,c=prepare_block(block,spec,common_design(block));b.add(o,s,c)
        assert a.N==b.N and a.G==b.G and np.allclose(a.S,b.S,atol=1e-7) and np.allclose(a.b,b.b,atol=1e-8)
        allm=init_moments(empty_frame());allm[spec['key']]=a
        save_moments(root/'moments.npz',allm);loaded=load_moments(root/'moments.npz',empty_frame())
        assert np.array_equal(loaded[spec['key']].S,a.S)
    print('STREAMING_SQL_STAGING_CHECKPOINTS_AND_RESUME_OK',flush=True)


def main():
    authority,_=common.verify_report_package()
    assert authority['rows']==41534331 and authority['fair_rows']==15207423
    boundaries();compare_dummy_ols();io_and_staging()
    print('SELF_TEST_OK (synthetic checks only; no empirical estimates produced)',flush=True)


if __name__=='__main__':main()
