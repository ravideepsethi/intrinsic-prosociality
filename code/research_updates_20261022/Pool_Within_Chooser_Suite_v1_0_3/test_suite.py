"""Synthetic verification; never substitutes for running the private panel."""
from __future__ import annotations
import csv
import json
import tempfile
from pathlib import Path
import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import fe_suite as fe
import run_suite as run
import parallel_fe as parallel
import checked_math as checked


def fixture():
    rng=np.random.default_rng(87253)
    groups=112
    sizes=rng.integers(22,39,groups);sizes[:3]=1;sizes[5]=151
    ids=np.repeat(np.arange(groups),sizes);n=len(ids)
    b=rng.integers(0,5,n);p=rng.integers(0,8,n)
    exact=np.array([2,5,7,9,15,30,60,100])[p]
    # Multiple exact opening plies in each of the first four bands.
    exact=np.where((p<4)&(rng.random(n)<.5),exact+1,exact)
    speed=rng.integers(0,2,n);month=rng.integers(0,2,n)
    gap=rng.uniform(-700,700,n)
    premium=np.exp(rng.uniform(-2,5.5,n))
    patron=np.array([0,1,-1])[ids%3]
    prob=np.clip(.13+.015*b+.07*((b>=2)&(p>=4))-.01*p+
                 .012*(patron==1)*b+rng.normal(0,.06,groups)[ids],.01,.8)
    y=(rng.random(n)<prob).astype(float);y[ids==6]=0;y[ids==7]=1
    d=dict(chooser=ids.astype(np.int64),y=y,board=b.astype(np.int8),ply=p.astype(np.int8),
      exact_ply=exact,calendar=(month*2+speed).astype(np.int16),speed=speed.astype(np.int8),
      log_cclock=rng.uniform(0,7,n),log_dclock=rng.uniform(0,7,n),
      cclock_missing=(rng.random(n)<.07).astype(float),dclock_missing=(rng.random(n)<.05).astype(float),
      gap=gap,premium=premium,crd=rng.uniform(20,340,n),drd=rng.uniform(20,340,n),
      cvol=rng.uniform(.025,.12,n),dvol=rng.uniform(.025,.12,n),rating=rng.uniform(700,2600,n),patron=patron)
    meta=dict(rows=n,calendar=[['2023-11','blitz'],['2023-11','rapid'],['2023-12','blitz'],['2023-12','rapid']],
      speeds=['blitz','rapid'],early_levels=[3,6,8,10],competitive_weights=[.60,.20,.20],
      stage_weights=[.12,.10,.08,.09,.15,.17,.19,.10])
    return d,meta


def independent_reference(d,meta,fits,group):
    """Explicit full dummy WLS, clustered by account; no within transformation."""
    if group=='patron':d={k:v[d['patron']>=0] for k,v in d.items()}
    names,_=fe.layout(meta);X=fe.matrix(d,meta)
    # Independently check the central fully interacted state/stage design.
    expected=np.column_stack([(d['board']==b)&(d['ply']==p)
       for b in range(5) for p in range(8) if b*8+p])
    np.testing.assert_array_equal(X[:,:39],expected)
    unique,ci=np.unique(d['chooser'],return_inverse=True)
    units=np.column_stack([d['chooser'],d['speed']]) if group=='speed_fe' else d['chooser'][:,None]
    _,ui=np.unique(units,axis=0,return_inverse=True)
    D=np.eye(ui.max()+1)[ui]
    counts=np.bincount(ci)
    w=1/counts[ci] if group=='weighting' else np.ones(len(ci))
    berr=verr=0.
    for f in fits:
        xx=X[:,[names.index(t) for t in f['terms']]]
        A=np.column_stack([xx,D]);Aw=A*np.sqrt(w)[:,None]
        # Column normalization is numerical conditioning, not regularization.
        norms=np.linalg.norm(Aw,axis=0);scale=np.divide(1.,norms,out=np.zeros_like(norms),where=norms>0)
        B=Aw*scale
        pinv=np.linalg.pinv(B,rcond=1e-11)
        beta=scale*(pinv@(np.sqrt(w)*d['y']))
        residual=d['y']-A@beta
        bread=(pinv@pinv.T)*scale[:,None]*scale[None,:]
        scores=np.zeros((len(unique),A.shape[1]));np.add.at(scores,ci,A*(w*residual)[:,None])
        V=len(unique)/(len(unique)-1)*bread@scores.T@scores@bread
        k=len(f['terms']);cs=fe.contrast_definitions(f,meta)
        for c in cs:
            C=c['C']
            if not fe.estimable(f,C)[0][0]:continue
            a=float(C@f['beta']);b=float(C@beta[:k])
            av=float(C@f['cov']@C);bv=float(C@V[:k,:k]@C)
            np.testing.assert_allclose(a,b,atol=4e-9,rtol=2e-7)
            np.testing.assert_allclose(av,bv,atol=4e-10,rtol=2e-7)
            berr=max(berr,abs(a-b));verr=max(verr,abs(av-bv))
        assert f['counts']['zero_grant_choosers']>0
    return dict(group=group,max_contrast_error=berr,max_variance_error=verr)


def sql_check(d,meta,root):
    n=len(d['y']);names=np.array([f'user{x}' for x in d['chooser']])
    cp=np.array([-350,-200,0,200,350],dtype=float)[d['board']]
    # Exercise every CP boundary without changing its intended bin.
    boundaries={0:[-301,-300],1:[-299,-101],2:[-100,0,100],3:[101,299],4:[300,301]}
    for b,vals in boundaries.items():
        ix=np.flatnonzero(d['board']==b)[:len(vals)];cp[ix]=vals
    premium=d['premium'].copy();premium[12]=np.nan
    clocks=np.expm1(d['log_cclock']);clocks[13]=np.nan;clocks[14]=-2
    plies=d['exact_ply'].astype(float).copy();plies[15]=-.5
    months=np.array([meta['calendar'][k][0] for k in d['calendar']],dtype=object);months[16]=None
    raw=dict(chooser_user_id=d['chooser'],chooser_username_norm=names,outcome_kind_draw=d['y'].astype(bool),
      engine_fairness_bin=np.array(run.RAW_BINS)[d['board']],engine_eval_cp_disconnected=cp,ply_count=plies,
      month=months,api_speed=np.array(meta['speeds'])[d['speed']],chooser_win_premium_v2=premium,
      chooser_clock_last_obs_s=clocks,disconnected_clock_last_obs_s=np.expm1(d['log_dclock']),
      chooser_elo=d['rating'],disconnected_elo=d['rating']+d['gap'],chooser_pre_rd_v2=d['crd'],
      disconnected_pre_rd_v2=d['drd'],chooser_pre_sigma_v2=d['cvol'],disconnected_pre_sigma_v2=d['dvol'])
    shuffled=pa.table(raw).take(pa.array(np.random.default_rng(2).permutation(n)))
    path=root/'raw_PRIVATE.parquet';pq.write_table(shuffled,path)
    old=(run.EXPECTED,run.BIN_COUNTS,run.BIN_DRAWS)
    run.EXPECTED=dict(rows=n,kind_draws=int(d['y'].sum()),choosers=len(np.unique(d['chooser'])))
    run.BIN_COUNTS=[int((d['board']==i).sum()) for i in range(5)]
    run.BIN_DRAWS=[int(d['y'][d['board']==i].sum()) for i in range(5)]
    out=root/'sql';out.mkdir();private=root/'sql_private';private.mkdir()
    db=duckdb.connect()
    unique=np.unique(d['chooser']);keep=unique[unique%3!=2]
    db.register('profiles',pa.table({'username':[f'user{x}' for x in keep],'patron':(keep%3==1).astype(np.int8)}))
    db.execute('CREATE TABLE patrons AS SELECT * FROM profiles')
    try:cache,m=run.prepare(db,[path],private,out)
    finally:
        run.EXPECTED,run.BIN_COUNTS,run.BIN_DRAWS=old
        db.close()
    assert m['rows']==n-3
    reasons={r['reason']:r['rows'] for r in m['common_support_exclusions']}
    assert reasons['invalid_core']==reasons['invalid_calendar']==reasons['invalid_economic_controls']==1
    a=pq.read_table(cache).to_pydict()
    assert all(x in [-1,0,1] for x in a['patron']) and -1 in a['patron']
    assert sum(a['cclock_missing'])==1 and a['log_cclock'].count(0.)==2
    assert abs(sum(m['competitive_weights'])-1)<1e-12
    assert abs(sum(m['stage_weights'])-1)<1e-12
    fits=fe.fit_group(cache,m,out/'states','states',121);fe.export(fits,m,out/'states')
    return dict(test='SQL_boundaries_common_support_clocks_profile_join_exports',passed=True)


def run_tests():
    checks=[];d,meta=fixture()
    # Collinear centered spline columns: positive weighting must preserve them.
    rng=np.random.default_rng(813);X=rng.normal(size=(1001,9));X[:,8]=X[:,7]
    audit={};G=checked.gram(X,audit)
    np.testing.assert_allclose(G,np.einsum('ni,nj->ij',X,X,optimize=False),atol=1e-9)
    w=rng.uniform(.01,1,len(X));GW=checked.gram(X*np.sqrt(w)[:,None],audit)
    checked.positive_weight_nullspace(G,GW)
    # Inject a wrong backend product; the scalar-reduction fallback must repair it.
    original=checked._blas_gram
    def corrupted(a):
        result=original(a);result[0,0]+=1.;return result
    try:
        checked._blas_gram=corrupted
        fixed=checked.gram(X,audit)
        np.testing.assert_allclose(fixed,G,atol=1e-9)
        assert audit['gram_fallbacks']==1
    finally:checked._blas_gram=original
    checks.append(dict(test='independent_Gram_checks_corruption_fallback_weighted_nullspace',passed=True))
    actual=json.loads((Path(__file__).parent/'evidence/RETURNED_MOMENT_IDENTITY.json').read_text())
    rejected=False
    try:checked.positive_weight_nullspace(np.array(actual['states']),np.array(actual['weighting']))
    except ValueError:rejected=True
    assert rejected,'The uploaded weighted-moment fault must be detected'
    checks.append(dict(test='uploaded_v101_moment_inconsistency_detected',passed=True))
    with tempfile.TemporaryDirectory(prefix='within_chooser_suite_test_') as td:
        root=Path(td);cache=root/'synthetic_PRIVATE.parquet'
        pq.write_table(pa.table(d),cache,row_group_size=79)
        chunks=list(fe.blocks(cache,31))
        np.testing.assert_array_equal(np.concatenate([x['chooser'] for x in chunks]),d['chooser'])
        assert sum(len(np.unique(x['chooser'])) for x in chunks)==len(np.unique(d['chooser']))
        primary=None;serial={}
        for group in ['states','weighting','speed_fe','patron']:
            fits=fe.fit_group(cache,meta,root/group,group,131)
            checks.append(independent_reference(d,meta,fits,group))
            fe.export(fits,meta,root/group)
            serial[group]=fits
            if group=='states':primary=fits
        paths,receipt=parallel.shards(cache,root/'shards',2)
        assert receipt['rows']==len(d['y'])
        with parallel.pool(2) as executor:
            for group in ['states','weighting','speed_fe','patron']:
                fitted=parallel.fit_group(paths,meta,root/('parallel_'+group),group,executor,79)
                for a,b in zip(serial[group],fitted):
                    assert a['counts']==b['counts']
                    np.testing.assert_allclose(a['beta'],b['beta'],atol=5e-9,rtol=2e-8)
                    np.testing.assert_allclose(a['cov'],b['cov'],atol=5e-10,rtol=2e-8)
                fe.export(fitted,meta,root/('parallel_'+group))
                tab=pq.read_table(root/('parallel_'+group)/'contrasts.parquet')
                assert tab['estimate_pp'].type==pa.float64()
                assert (root/('parallel_'+group)/'moments.parquet').is_file()
        checks.append(dict(test='spawn_workers_vs_serial_all_families_Parquet_types',passed=True))
        other=fe.fit_group(cache,meta,root/'other','states',997)
        for a,b in zip(primary,other):
            np.testing.assert_allclose(a['beta'],b['beta'],atol=5e-9)
            np.testing.assert_allclose(a['cov'],b['cov'],atol=5e-10)
        assert primary[0]['counts']['singleton_choosers']==3
        # Unsupported target is explicitly nonestimable; constant nuisance is harmless.
        mask=~((d['patron']==1)&(d['board']==4)&(d['ply']==7))
        scarce={k:v[mask] for k,v in d.items()};scarce['cclock_missing']*=0
        c2=root/'scarce.parquet';pq.write_table(pa.table(scarce),c2)
        f=fe.fit_group(c2,meta,root/'scarce','patron',163)[0]
        term=f['terms'].index('patron_cell_b4_p7');C=np.eye(len(f['terms']))[term]
        assert not fe.summarize_contrast(f,C)['estimable']
        fe.export([f],meta,root/'scarce')
        unsupported=next(x for x in fe.contrast_definitions(f,meta) if x['label']=='patron_minus_nonpatron_clearly_better_vs_losing_at_81_plus')
        assert not fe.summarize_contrast(f,unsupported['C'])['estimable']
        # Wald uses the full covariance, including covariance across cell differences.
        f=primary[3];C=np.array([x['C'] for x in fe.contrast_definitions(f,meta) if x['family']=='equal_vs_better'])
        expected=float((C@f['beta'])@np.linalg.solve(C@f['cov']@C.T,C@f['beta']))
        np.testing.assert_allclose(fe.joint_test(f,'independent',C)['wald'],expected,rtol=1e-8)
        checks.append(dict(test='batch_invariance_singletons_nonidentification_joint_covariance',passed=True))
        checks.append(sql_check(d,meta,root))
        # Verify all bundled empirical result archives, without fitting them again.
        reuse=root/'reuse';reuse.mkdir();ledger=run.reuse_results(reuse)
        assert len(ledger)==2 and all(r['action']=='VERIFIED_EXISTING_RESULTS' for r in ledger)
        with (reuse/'completed_analyses/receipt_primary_and_repeat_comparisons.csv').open() as f:
            assert len(list(csv.DictReader(f)))>=3
        # Profile absence blocks only Patron; it does not create false non-Patrons.
        db=duckdb.connect();r=run.load_patron(db,root/'no_project',root)
        assert r['status']=='BLOCKED_MISSING_CERTIFIED_PROFILE'
        assert db.execute('SELECT count(*) FROM patrons').fetchone()[0]==0
        db.close()
        # Exercise the certified-profile SQL, including a nonreturn with no outcome.
        profile_path=root/run.SNAPSHOT;profile_path.parent.mkdir(parents=True)
        pq.write_table(pa.table({'username_norm':[' A ','B','c','d'],
          'returned':[True,True,True,False],'patron':[True,False,False,None],
          'queried_at_utc':['2026-08-21T00:00:00Z']*4}),profile_path)
        old_sha,old_counts=run.SNAPSHOT_SHA,run.SNAPSHOT_EXPECTED
        try:
            run.SNAPSHOT_SHA=run.auth.sha256_file(profile_path)
            run.SNAPSHOT_EXPECTED={'returned':3,'patrons':1,'missing_patron':0}
            db=duckdb.connect();profile=run.load_patron(db,root,root)
            assert profile['status']=='READY_SELECTED_PROFILE_SAMPLE'
            assert db.execute('SELECT * FROM patrons ORDER BY username').fetchall()==[('a',1),('b',0),('c',0)]
            db.close()
        finally:run.SNAPSHOT_SHA,run.SNAPSHOT_EXPECTED=old_sha,old_counts
        checks.append(dict(test='completed_results_hashes_provenance_missing_profile_handling',passed=True))
    result=dict(status='PASS',data='synthetic only; private panel not run in this environment',checks=checks)
    print(json.dumps(result,indent=2),flush=True)
    return result


if __name__=='__main__':
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):run_tests()
