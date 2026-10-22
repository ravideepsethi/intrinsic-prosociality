"""Synthetic validation only. These fixtures are not Lichess findings."""
import json, tempfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy import linalg, sparse, stats
from common import DAY,connect,parquet,copy_parquet
from history import performance,features_for_user,selected_validation,validation_rows,join_features,FEATURES
from models import registry,sample,build,subgroup,poly
from estimate import blank,moment_update,fit_moments,moment_worker,merge_moments,score_worker,load_arrays,save_arrays,inference,holm,run_models
from fe_core import iter_blocks,solve

def fixture(users=40,per_user=24):
    rng=np.random.default_rng(421);n=users*per_user;ids=np.repeat(np.arange(1,users+1),per_user)
    rating=rng.integers(1300,2450,n).astype(float);opp=rating+rng.integers(-450,451,n)
    k=np.exp(rng.normal(3,.25,n));e=rng.uniform(.55,.9,n);e[::5]=.5;opp[::5]=rating[::5]
    rg=k*(.5-e);premium=k/2;start=1700000000000+np.arange(n)*DAY/5
    f=dict(game_id=np.array(['g'+str(i) for i in range(n)]),chooser=ids,recipient=rng.integers(100,160,n),
      username=np.array(['synthetic'+str(i) for i in ids]),start_ms=start.astype('int64'),created_ms=np.full(n,1600000000000,dtype='int64'),
      month_idx=rng.integers(0,24,n),speed=rng.integers(0,4,n),y=rng.binomial(1,.2,n).astype('int16'),
      state=rng.integers(0,2,n),rating=rating,opp_rating=opp,rg=rg,rc=rg+premium,premium=premium,
      k=k,e=e,opp_stake=rng.uniform(3,15,n),rd=rng.uniform(35,105,n),opp_rd=rng.uniform(35,105,n),
      ply=rng.integers(0,130,n),clock=rng.uniform(0,500,n),opp_clock=rng.uniform(0,500,n),age_days=rng.uniform(366,2000,n),
      prior_count=np.full(n,500.),opp_prior_count=rng.integers(1,2000,n).astype(float),
      inactivity_days=rng.uniform(0,50,n),history_days=rng.uniform(200,800,n),peak=rating+rng.uniform(-10,45,n),
      peak365=rating+rng.uniform(-10,45,n),dperf=rng.normal(0,80,n),dperf15=rng.normal(0,90,n),
      dperf60=rng.normal(0,50,n),dperf200=rng.normal(0,40,n),dperf800=rng.normal(0,100,n),
      missing_post_updates=np.zeros(n),lookback_tie=np.zeros(n))
    f['board']=np.where(f['state']==1,rng.choice([-100,0,100,200,500],n),-500.)
    f['clock'][::31]=np.nan
    return f

def test_history():
    n=80;ends=np.arange(1,n+1)*DAY;rating=np.full(n,1600.)
    h=dict(end_ms=ends,start_ms=ends-1000,rating=rating,opp_rating=np.full(n,1600.),rd=np.full(n,50.),
      opp_rd=np.full(n,50.),rating_diff=np.full(n,3.),score=np.ones(n),ordinary=np.ones(n,bool))
    # Future rating and result must not affect a prior anchor. Equality is excluded.
    a=dict(start_ms=np.array([31*DAY,31*DAY+1,60*DAY+1]),rating=np.full(3,1600.))
    f=features_for_user(h,a)
    assert np.array_equal(f['prior_count'],[30,31,60])
    assert np.all(f['dperf']<0) and np.all(np.isfinite(f['dperf']))
    assert f['peak'][0]==1603
    h2={k:v.copy() for k,v in h.items()};h2['rating'][40:]=9000;h2['score'][40:]=0
    f2=features_for_user(h2,a);assert f['dperf'][0]==f2['dperf'][0] and f['peak'][0]==f2['peak'][0]
    # Late completion, despite earlier start, does not enter the lookback.
    h2={k:v.copy() for k,v in h.items()};h2['start_ms'][-1]=0
    assert features_for_user(h2,a)['prior_count'][0]==30
    h2={k:v.copy() for k,v in h.items()};h2['end_ms'][10]=h2['end_ms'][11]
    assert np.isnan(features_for_user(h2,a)['dperf'][0])
    h2={k:v.copy() for k,v in h.items()};h2['rd'][10]=111
    assert np.isnan(features_for_user(h2,a)['dperf'][0])
    h2={k:v.copy() for k,v in h.items()};h2['ordinary'][:16]=False
    assert np.isnan(features_for_user(h2,a)['dperf'][0])
    h2={k:v.copy() for k,v in h.items()};h2['rating_diff'][0]=np.nan
    assert features_for_user(h2,a)['peak'][0]==1603
    # Direct scalar objective optimization is independent of the score-equation solver.
    from scipy.optimize import minimize_scalar
    from scipy.special import expit
    g=1/173.7178/np.sqrt(1+3*(50/173.7178)**2/np.pi**2)
    for score in [0.,.5,1.]:
        out=performance(np.array([1600.]),np.full((1,30),1600.),np.full((1,30),50.),np.full((1,30),score),np.ones((1,30),bool))[0]
        def obj(t):
            z=g*(t-1600);return 30*(np.logaddexp(0,z)-score*z)+(t-1600)**2/(2*400**2)
        opt=minimize_scalar(obj,bounds=(-1000,5000),method='bounded',options={'xatol':1e-7})
        assert abs((1600-out)-opt.x)<1e-3
    h3={k:v.copy() for k,v in h.items()};h3['end_ms']=ends+int(np.datetime64('2023-09-20','ms').astype('int64'));h3['start_ms']=h3['end_ms']-1000
    username=next('synthetic_'+str(i) for i in range(100) if selected_validation('synthetic_'+str(i)))
    vr=validation_rows(1,2,username,h3,int(np.datetime64('2024-03-01','ms').astype('int64')))
    assert len(vr)>=1 and all(np.isfinite(row['residual']) for row in vr)
    print('PASS: strict completion cutoff, no future leakage, ties, RD/status rules and finite performance solver')

def dense_reference(d,m):
    X,names,C,labels,z,target=build(d,m);g,n,A=subgroup(d,m['fe'])
    Z=np.column_stack([A.toarray().T,X.toarray()]);scale=np.sqrt(np.sum(Z*Z,axis=0));scale[scale==0]=1
    Q=Z/scale
    coef,_,rank,_=linalg.lstsq(Q,d['y'],cond=1e-10,lapack_driver='gelsd');coef/=scale
    pinv=linalg.pinv(Q,rtol=1e-10)/scale[:,None]
    fullC=np.column_stack([np.zeros((len(C),len(n))),C]);est=fullC@coef
    u=d['y']-Z@coef;influence=(fullC@pinv).T*u[:,None]
    _,ci=np.unique(d['chooser'],return_inverse=True)
    score=np.zeros((ci.max()+1,len(C)));np.add.at(score,ci,influence)
    G=len(score);N=len(u);V=score.T@score*G/(G-1)*(N-1)/(N-rank)
    return est,V,rank

def test_estimator(tmp):
    f=fixture();m=dict(test='T1',variant='primary',state='competitive',key='T1__primary__competitive',fe='chooser')
    d,selected=sample(f,m);X,names,C,labels,z,target=build(d,m);a=blank(X,names,C,labels);moment_update(a,d,m,X,selected,z)
    fit=fit_moments({m['key']:a},[m])[m['key']]
    g,n,A=subgroup(d,m['fe']);u=d['y']-X@fit['beta'];u-=np.asarray(A@u/n)[g]
    inf=X@fit['P'];inf=(inf-(A@inf/n[:,None])[g])*u[:,None]
    from estimate import cluster_matrix
    _,cn,B=cluster_matrix(d['chooser']);sc=B@inf
    V=sc.T@sc*len(cn)/(len(cn)-1)*(len(u)-1)/fit['residual_df']
    est,refV,rank=dense_reference(d,m)
    assert np.allclose(est,fit['est'],atol=2e-7), (est,fit['est'])
    assert np.allclose(V,refV,rtol=2e-5,atol=1e-9), (V,refV)
    assert rank==fit['full_rank']
    # Target aliases cannot silently produce a coefficient.
    bad=solve(np.array([[1.,1.],[1.,1.]]),np.array([1.,1.]),np.array([[1.,0.]]));assert not bad['identified'][0]
    # Stream partition invariance, including clusters larger than Arrow batches.
    p=tmp/'fixture.parquet';pq.write_table(pa.table(f),p,row_group_size=11)
    blocks=list(iter_blocks(p,13));assert sum(len(b['y']) for b in blocks)==len(f['y'])
    clusters=[set(b['chooser']) for b in blocks]
    assert sum(map(len,clusters))==len(set.union(*clusters))
    aa=tmp/'moments.npz';moment_worker((str(p),[m],str(aa),'fixture',13));merged=merge_moments([aa])
    assert np.allclose(a['S'],merged[m['key']]['S'],rtol=1e-7,atol=1e-7)
    assert np.allclose(a['b'],merged[m['key']]['b'],atol=1e-7)
    fitpath=tmp/'fit.npz';save_arrays(fitpath,{m['key']:fit});sp=tmp/'scores.npz'
    score_worker((str(p),[m],str(fitpath),str(sp),'fixture',13));s=load_arrays(sp)[m['key']]
    assert np.allclose(s['meat'],sc.T@sc,atol=1e-8,rtol=1e-5)
    # Validate recipient and pair scores against dense role-cluster aggregation.
    _,rn,R=cluster_matrix(d['recipient']);rs=R@inf
    _,pn,P=cluster_matrix(np.column_stack([d['chooser'],d['recipient']]));ps=P@inf
    con=connect(tmp,1,'1GB')
    meat=con.execute(f'SELECT sum(s*s) FROM (SELECT recipient,sum(s0) s FROM {parquet(s["recipient_scores"])} GROUP BY recipient)').fetchone()[0]
    assert np.isclose(meat,float((rs.T@rs)[0,0]),rtol=1e-5,atol=1e-8)
    assert np.allclose(s['pair_meat'],ps.T@ps,rtol=1e-5,atol=1e-8)
    con.close()
    # Block-diagonal joint fit must retain separate coefficients and cross-state covariance.
    mods=[];acc={}
    for state,fe in [('competitive','chooser'),('losing','chooser'),('difference','chooser_state')]:
        mm=dict(m,state=state,fe=fe,key='T1__primary__'+state);mods.append(mm)
        dd,ns=sample(f,mm);xx,nn,cc,ll,zz,_=build(dd,mm);ar=blank(xx,nn,cc,ll);moment_update(ar,dd,mm,xx,ns,zz);acc[mm['key']]=ar
    ff=fit_moments(acc,mods);joint=ff['T1__primary__difference']['est']
    assert abs(joint[0]-ff['T1__primary__competitive']['est'][0])<1e-6
    assert abs(joint[1]-ff['T1__primary__losing']['est'][0])<1e-6
    assert np.isclose(joint[2],joint[0]-joint[1])
    print('PASS: dense dummy-FE reference, full-rank CR1, aliases, streaming, two-way scores and joint state differences')

def test_designs():
    f=fixture(15,40);models,pending=registry(True)
    for m in models:
        d,_=sample(f,m)
        if d is not None:
            X,names,C,labels,z,targets=build(d,m)
            assert X.shape==(len(d['y']),len(names))
            assert C.shape[1]==X.shape[1] and len(labels)==C.shape[0]
            assert np.isfinite(X.data).all()
    assert len(poly([np.ones(2),np.ones(2)],3)[0])==9
    assert len(poly([np.ones(2),np.ones(2),np.ones(2)],3)[0])==19
    mm=[m for m in models if m['test']=='T2' and m['variant']=='primary' and m['state']=='competitive'][0]
    d,_=sample(f,mm);names=build(d,mm)[1]
    assert 'log_k' in names and not any(n.startswith(('Q_','log_k_','rd')) for n in names)
    assert np.allclose(holm([.01,.03,.04,1,1]),[.05,.12,.12,1,1])
    assert inference(0.,1e-8,100)['p_equiv']<.05
    assert inference(0.,.01,100)['p_equiv']>.05
    assert inference(.001,-1,100)['status']=='UNSUPPORTED_COVARIANCE'
    print('PASS: all registered designs, basis sizes, exact-zero controls and separate equivalence arithmetic')

def test_preparation(tmp):
    from prepare import profiles,projection
    con=connect(tmp,1,'1GB')
    ps=tmp/'profiles.parquet'
    pq.write_table(pa.table(dict(username_norm=['alice','bob','alice'],returned=[True,True,True],
       raw_user_json=['{"id":"alice","createdAt":1}','{"id":"bob"}','{"id":"alice","createdAt":1}'],acquisition_role=['granter','control','supplement'])),ps)
    profiles(con,[dict(path=str(ps),role_fallback='unknown')])
    assert con.execute('SELECT count(*) FROM profiles').fetchone()[0]==2
    assert con.execute("SELECT created_ms FROM profiles WHERE username='bob'").fetchone()[0] is None
    f=fixture(3,6);f={k:v for k,v in f.items() if k not in FEATURES+['opp_prior_count']};src=tmp/'base.parquet';pq.write_table(pa.table(f),src)
    joined=join_features(con,[src],None,tmp,'join-fixture')
    assert pq.ParquetFile(joined[0]).metadata.num_rows==len(f['y'])
    # Missing history stays missing, never coded as zero prior games.
    assert con.execute(f'SELECT count(*) FROM {parquet(joined)} WHERE opp_prior_count IS NOT NULL').fetchone()[0]==0
    con.close();print('PASS: creation-date deduplication and missing-history preservation')

def test_month_projection(tmp):
    from prepare import prepare
    from scipy.special import expit
    w=tmp/'month_check';w.mkdir();r=w/'report';r.mkdir()
    # Intentionally tiny fixture: verifies every monthly query, then MUST fail the census count gate.
    n=6;rd=np.full(n,50.);rating=np.array([1600,1500,1800,2000,2100,1900.]);opp=np.full(n,1800.)
    k=np.full(n,20.);e=expit((rating-opp)/173.7178/np.sqrt(1+3*(rd/173.7178)**2/np.pi**2));rg=k*(.5-e)
    f=dict(game_id=['synthetic'+str(i) for i in range(n)],chooser_user_id=np.arange(1,n+1),disconnected_user_id=np.arange(100,100+n),
      chooser_username_norm=['u'+str(i) for i in range(n)],api_created_at_ms=np.full(n,1700000000000),utc_ms=np.full(n,1700000000000),
      api_speed=['blitz']*n,outcome_kind_draw=[True,False,False,True,False,False],engine_eval_cp_disconnected=[0,400,-500,0,-500,0],
      chooser_elo=rating,disconnected_elo=opp,chooser_draw_payoff_v2=rg,chooser_win_payoff_v2=rg+k/2,chooser_win_premium_v2=k/2,
      chooser_color=['white']*n,disconnected_color=['black']*n,white_draw_ratingdiff_v2=rg,white_win_ratingdiff_v2=rg+k/2,
      white_win_premium_v2=k/2,black_draw_ratingdiff_v2=-rg,black_win_ratingdiff_v2=-rg+k/2,black_win_premium_v2=k/2,
      chooser_pre_rd_v2=rd,disconnected_pre_rd_v2=rd,ply_count=np.full(n,30),chooser_clock_last_obs_s=np.full(n,20.),disconnected_clock_last_obs_s=np.full(n,10.),
      chooser_elo_v2_source=rating,disconnected_elo_v2_source=opp)
    src=w/'main.parquet';pq.write_table(pa.table(f),src)
    ps=w/'profiles.parquet';pq.write_table(pa.table(dict(username_norm=f['chooser_username_norm'],returned=[True]*n,
      raw_user_json=[json.dumps(dict(id='u'+str(i),createdAt=1600000000000)) for i in range(n)],acquisition_role=['fixture']*n)),ps)
    con=connect(w,1,'1GB')
    try:
        prepare(con,dict(month_records=[dict(month='2023-11',path=src)]),[dict(path=str(ps),role_fallback='fixture')],w,r,'synthetic-month',2)
    except RuntimeError as e:
        assert 'Certified counts failed reproduction' in str(e),str(e)
    else:raise AssertionError('Synthetic data wrongly passed census gate')
    audit=json.loads((w/'monthly/2023-11.json').read_text())['extra']['audit']
    assert audit['bad_payoff']==0 and audit['bad_base']==0 and audit['inconsistent_recipient_payoff']==0
    assert audit['max_e_glicko_check_difference']<1e-12
    con.close();print('PASS: complete monthly SQL projection/payoff audit and immutable census-count gate')

def integration(tmp):
    from history import make_features
    from report import descriptions,predictive_validation,figures,summary
    w=tmp/'integration';w.mkdir();rep=w/'report';rep.mkdir();con=connect(w,1,'1GB')
    f=fixture(20,20);src=w/'fixture.parquet';pq.write_table(pa.table(f),src)
    mods,pending=registry(False)
    rows,primary,differences=run_models(con,[src],mods,pending,w/'estimate',rep,'synthetic-integration',workers=2,batch=127)
    assert len(primary)==5 and all(r['family_size']==5 for r in primary)
    assert [r['status'] for r in primary[:4]]==['UNSUPPORTED_INPUT']*4
    raw=descriptions(con,[src],rep);predictive_validation(con,None,w,rep);figures(rep,rows,raw);summary(rep,primary,differences,'synthetic-integration',False)
    # A small enriched game history exercises the actual disk builder and joining path.
    small={k:v[:30] for k,v in f.items() if k not in FEATURES+['opp_prior_count']}
    base=w/'small.parquet';pq.write_table(pa.table(small),base)
    games=[]
    for uid in np.unique(np.r_[small['chooser'],small['recipient']]):
        for j in range(65):
            end=1690000000000+j*DAY
            games.append(dict(game_id=f'h_{uid}_{j}',speed='blitz',start_ms=end-600000,end_ms=end,
                white_id=int(uid),black_id=999999,white_rating=1700.,black_rating=1700.,white_rd=50.,black_rd=50.,white_rating_diff=1.,black_rating_diff=-1.,white_score=1.,status='mate'))
    for j,gid in enumerate(small['game_id']):
        from common import SPEEDS
        games.append(dict(game_id=str(gid),speed=SPEEDS[small['speed'][j]],start_ms=int(small['start_ms'][j]),end_ms=int(small['start_ms'][j])+600000,
          white_id=int(small['chooser'][j]),black_id=int(small['recipient'][j]),white_rating=float(small['rating'][j]),black_rating=float(small['opp_rating'][j]),
          white_rd=50.,black_rd=50.,white_rating_diff=1.,black_rating_diff=-1.,white_score=1.,status='outoftime'))
    hs=w/'history.parquet';pq.write_table(pa.Table.from_pylist(games),hs)
    # Contract authenticity itself is checked by inspect_history in production. Here all data are explicitly synthetic.
    manifest=dict(files=[dict(resolved_path=str(hs))],coverage_start_ms=1600000000000,coverage_end_ms=1800000000000)
    hp,vp=make_features(con,[base],manifest,w,rep,'synthetic-history',2)
    joined=join_features(con,[base],hp,w/'joined','synthetic-joined')
    assert pq.ParquetFile(joined[0]).metadata.num_rows==len(small['y'])
    predictive_validation(con,vp,w,rep)
    # Exercise the nonempty predictive-validation regression, independent of concession outcomes.
    rng=np.random.default_rng(333);nv=500
    gap=rng.normal(0,80,nv);res=-.1*gap/100+rng.normal(0,.2,nv)
    valid=pa.table(dict(chooser=np.repeat(np.arange(1,26),20),speed=rng.integers(0,4,nv),month=np.array(['2023-11','2023-12']*(nv//2)),dperf=gap,residual=res,followup_30d_covered=np.ones(nv,bool)))
    vp2=w/'validation_nonempty.parquet';pq.write_table(valid,vp2);predictive_validation(con,vp2,w,rep)
    vv=json.loads((rep/'performance_validation.json').read_text());assert vv['status']=='ESTIMATED' and vv['estimate_pp']<0 and vv['N']==nv
    # History-dependent specification variants also pass through both estimation passes.
    fullmods,fullpending=registry(True)
    fullrows,fullprimary,_=run_models(con,[src],fullmods,fullpending,w/'full_estimate',rep,'synthetic-full-models',workers=2,batch=127)
    assert len(fullprimary)==5 and all('status' in r for r in fullprimary)
    # Resumption must reuse byte-identical completed shard checkpoints.
    rows2,_,_=run_models(con,[src],mods,pending,w/'estimate',rep,'synthetic-integration',workers=2,batch=127)
    assert rows2==rows
    con.close();print('PASS: multiprocessing model/report run, enriched history build/join and identical resumed estimates')

def run():
    with tempfile.TemporaryDirectory(prefix='rating_motives_test_') as t:
        tmp=Path(t);test_history();test_designs();test_estimator(tmp);test_preparation(tmp);test_month_projection(tmp);integration(tmp)
    print('ALL SYNTHETIC VALIDATION CHECKS PASSED — no empirical Lichess estimates were run')

if __name__=='__main__':run()
