"""R11 independent dense-OLS, covariance, standardization and source tests."""
from common import *
from design import design,moments_design,COLS,STAGES,POSITIONS,MONTHS,REGIONS,GAP_NAMES,gap_basis,dummy
from estimate import first,second,fit_first,grouped
from report import Model,make_rows,write_report,GAP_CONTRASTS
from prepare import project_month,gap_support
from all_games import ply_count,speed_from_tc,pgn_month,safe_month,discover,finish,histogram_quantile
from scipy.linalg import lstsq,pinv
import tempfile

def synthetic():
    rng=np.random.default_rng(81429);counts=np.r_[np.ones(6,dtype=int),rng.integers(20,42,64)]
    ids=np.repeat(np.arange(len(counts)),counts);n=len(ids)
    d=pd.DataFrame(dict(chooser=ids,y=rng.binomial(1,.15,n),board=rng.choice([-600,-200,0,200,500],n),ply=rng.choice([2,5,7,9,15,30,60,100],n),
      gap=rng.normal(0,340,n),clock_c=rng.exponential(80,n),clock_d=rng.exponential(90,n),premium=np.exp(rng.normal(2,1,n)),
      rd_c=np.exp(rng.normal(4,.7,n)),rd_d=np.exp(rng.normal(4,.8,n)),month_code=rng.integers(0,24,n),speed_code=rng.integers(0,5,n)))
    d['position']=np.searchsorted([-300,-100,101,300],d.board,side='right')
    d['position']=d.board.map({-600:0,-200:1,0:2,200:3,500:4})
    d['stage']=np.searchsorted([4,6,8,10,20,40,80],d.ply,side='left')
    for name in ['clock_c','clock_d','premium','rd_c','rd_d','gap']:d.loc[rng.choice(n,25,replace=False),name]=np.nan
    return d

def test_projection(d,tmp):
    # Boundary values independently specified from the protocol, including both mate sentinels.
    cp=np.array([-10000,-300,-299,-101,-100,100,101,299,300,10000])
    plys=np.array([0,4,5,6,7,8,9,10,80,81]);n=len(cp)
    frame=pd.DataFrame(dict(month=['2023-11']*n,chooser_user_id=np.arange(n),outcome_kind_draw=np.arange(n)%2,
      engine_eval_cp_disconnected=cp,ply_count=plys,sf100k_nodes_requested=[100000]*n,sf100k_fen_turn_matches_disconnected_color=[True]*n,
      disconnected_color=['white']*n,sf100k_disconnected_color_for_perspective=['white']*n,side_to_move_after_last=['white']*n,
      api_status=['timeout']*n,five_second_rule_passed=[True]*n,api_rated=[True]*n,api_variant=['standard']*n,api_speed=['ultraBullet','bullet','blitz','rapid','classical']*2,
      disconnected_elo=[1600]*n,chooser_elo=[1550]*n,chooser_clock_last_obs_s=[30]*n,disconnected_clock_last_obs_s=[20]*n,
      chooser_win_premium_v2=[6]*n,chooser_pre_rd_v2=[60]*n,disconnected_pre_rd_v2=[70]*n))
    p=tmp/'source.parquet';frame.to_parquet(p);out=tmp/'projection.parquet'
    t=dict(source=str(p),output=str(out),month='2023-11',rows=n,expected_sha256=sha(p),key='test',memory=.3)
    project_month(t);z=pd.read_parquet(out)
    assert z.position.tolist()==[0,0,1,1,2,2,3,3,4,4]
    assert z.stage.tolist()==[0,0,1,1,2,2,3,3,6,7]
    assert project_month(t)['reused']
    frame.loc[0,'sf100k_nodes_requested']=10000;frame.to_parquet(p);t['expected_sha256']=sha(p)
    try:project_month(t)
    except RuntimeError:pass
    else:raise AssertionError('Wrong engine lineage did not stop projection')

def test_basis():
    r=np.array([-700,-600,-300,-100,0,100,300,600,700,np.nan]);B=gap_basis(r)
    expected=[[-6,0,0,0,0,0,1,0,0],[-6,0,0,0,0,0,0,0,0],[-3,0,0,0,0,0,0,0,0],[-1,2,0,0,0,0,0,0,0],
      [0,3,1,0,0,0,0,0,0],[1,4,2,1,0,0,0,0,0],[3,6,4,3,2,0,0,0,0],[6,9,7,6,5,3,0,0,0],[6,9,7,6,5,3,0,1,0],[0,3,1,0,0,0,0,0,1]]
    np.testing.assert_array_equal(B,expected)
    weights=[[2,2,2,1,0,0,0,0,0],[1,1,1,0,0,0,0,0,0],[1,1,1,1,0,0,0,0,0],[3,3,3,3,2,0,0,0,0],[-3,-3,-1,0,0,0,0,0,0]]
    for (hi,lo),w in zip(GAP_CONTRASTS,weights):np.testing.assert_array_equal(gap_basis([hi])[0]-gap_basis([lo])[0],w)
    d=pd.concat([dummy()]*len(r),ignore_index=True);d['gap']=r;d['position']=np.arange(len(r))%5
    X,names,ix=design(d);C=d.position.to_numpy()>=2
    for region,mask in [('competitive',C),('noncompetitive',~C)]:
        for j,name in enumerate(GAP_NAMES):np.testing.assert_array_equal(X[:,names.index(name+':'+region)],B[:,j]*mask)
    assert all('clock' not in names[j] and 'premium' not in names[j] and 'rd_' not in names[j] for j in ix['column2'])
    values=[-700,-600,-301,-300,-101,-100,-1,0,99,100,299,300,600,601,np.nan]
    frame=pd.DataFrame(dict(position=[0]*15+[2]*15,gap=values*2));c=duckdb.connect();c.register('p',frame)
    support=gap_support(c);c.close()
    for region in REGIONS:
        rows=[r for r in support if r['region']==region]
        assert [r['opportunities'] for r in rows]==[3,2,2,2,2,3,1,1,1]

def test_dense(d,tmp):
    X,names,indices=design(d);M,mnames=moments_design(d);y=100*d.y.to_numpy(float);paths=[]
    for k in range(7):
        a=d[d.chooser%7==k].reset_index(drop=True);p=tmp/f'p{k}.npz';npz(p,**first(a)[0]);paths.append(p)
    fit=fit_first(paths,names,indices,mnames);meat=second(d,fit);factor=fit['g']/(fit['g']-1)
    D=np.eye(fit['g'])[d.chooser.to_numpy()];start,counts=grouped(d.chooser.to_numpy())
    empirical=(D.T@M-counts[:,None]*fit['mean_m'])/len(d);max_beta=0.;max_cov=0.;covs={};dense_params={}
    for col in COLS:
        W=X[:,indices[col]];Z=np.column_stack([D,W]);scale=np.sqrt(np.mean(Z**2,axis=0));scale[scale<1e-12]=1;Zs=Z/scale
        beta=lstsq(Zs,y,cond=1e-12,lapack_driver='gelsd')[0]/scale;residual=y-Z@beta
        bread=pinv(Zs.T@Zs,rtol=1e-12)/scale[:,None]/scale[None,:];scores=D.T@(Z*residual[:,None]);psi=scores@bread
        joint=np.column_stack([psi[:,fit['g']:],empirical]);V=factor*joint.T@joint;ours=factor*meat[col]
        np.testing.assert_allclose(beta[fit['g']:],fit['fits'][col]['beta'],rtol=3e-6,atol=3e-6)
        np.testing.assert_allclose(V,ours,rtol=4e-5,atol=4e-5)
        max_beta=max(max_beta,float(np.max(np.abs(beta[fit['g']:]-fit['fits'][col]['beta']))));max_cov=max(max_cov,float(np.max(np.abs(V-ours))))
        covs[col]=V;dense_params[col]=beta
    assert fit['within_n']==len(d)-6 and fit['within_g']==fit['g']-6
    rows,coefs,profiles,rates,translations,weights=make_rows(fit,covs)
    for col in COLS:
        families={r['holm_family'] for r in rows if r['column']==col and r['holm_family']}
        assert families=={col+'_A_7',col+'_B_13',col+'_C_competitive_5',col+'_C_noncompetitive_5'}
        for family in families:
            a=sorted([r for r in rows if r['holm_family']==family],key=lambda r:r['p_value']);n=int(family.split('_')[-1]);assert len(a)==n
            expected=np.minimum(1,np.maximum.accumulate([r['p_value']*(n-j) for j,r in enumerate(a)]));np.testing.assert_allclose(expected,[r['p_holm'] for r in a])
    m=Model('column1',fit,covs['column1']);beta=dense_params['column1']
    # Full dummy predictions on explicitly changed rows: this checks region changes as well.
    for kind,labels in [('position',POSITIONS),('stage',STAGES)]:
        for k in range(len(labels)):
            cf=d.copy();cf[kind]=k;W=design(cf)[0][:,indices['column1']]
            direct=float(np.mean(D@beta[:fit['g']]+W@beta[fit['g']:]))
            np.testing.assert_allclose(m.rate(kind,k).v,direct,rtol=1e-7,atol=1e-7)
    # Raw-beta translation agrees with changing position at exactly stage 0 and gap 0.
    for k in range(1,5):
        lo=d.copy();lo['position']=0;lo['stage']=0;lo['gap']=0;hi=lo.copy();hi['position']=k
        delta=(design(hi)[0]-design(lo)[0])[:,indices['column1']].mean(axis=0)
        np.testing.assert_allclose(m.zero_gap_position(k).v,delta@fit['fits']['column1']['beta'],atol=1e-10)
    for fn in [lambda a:a.rate('position',4),lambda a:a.rate('stage',7),lambda a:a.stage(6,'competitive')/a.baseline('competitive'),lambda a:a.stage(7)]:
        value=fn(m)
        for i,name in enumerate(m.names):
            v=m.vars[name];old=v.v;step=1e-6*max(1,abs(old));v.v=old+step;up=fn(m).v;v.v=old-step;down=fn(m).v;v.v=old
            np.testing.assert_allclose((up-down)/(2*step),value.g[i],rtol=3e-5,atol=3e-5)
    for (hi,lo),w in zip(GAP_CONTRASTS,[[2,2,2,1,0,0,0,0,0],[1,1,1,0,0,0,0,0,0],[1,1,1,1,0,0,0,0,0],[3,3,3,3,2,0,0,0,0],[-3,-3,-1,0,0,0,0,0,0]]):
        for region in REGIONS:
            j=np.zeros(len(m.names))
            for name,v in zip(GAP_NAMES,w):j[m.names.index(name+':'+region)]=v
            value=m.h(hi,region)-m.h(lo,region)
            np.testing.assert_array_equal(j,value.g);np.testing.assert_allclose(value.v,j[:m.k]@m.f['beta'])
    run=tmp/'report_test';(run/'report').mkdir(parents=True);write_report(run,fit,meat)
    assert len(pd.read_csv(run/'report/adjusted_rates_column1.csv'))==13
    assert (run/'report/main_table.tex').is_file()
    # Structural rank loss must not turn an unavailable focal effect into a zero.
    badfit=dict(fit,fits=dict(fit['fits']));f=dict(fit['fits']['column1']);j=f['names'].index('position_clearly_better');f['null']=np.eye(len(f['names']))[:,[j]];badfit['fits']['column1']=f
    mm=Model('column1',badfit,covs['column1']);assert mm.row('test','unavailable',mm.pos(4))['status']=='NOT_ESTIMABLE'
    # First- and second-pass aggregation are invariant to chooser-complete partitioning.
    pooled=first(d)[0]
    for name,values in pooled.items():np.testing.assert_allclose(sum(np.load(p)[name] for p in paths),values,rtol=1e-10,atol=1e-8)
    shards=[second(d[d.chooser%7==k].reset_index(drop=True),fit) for k in range(7)]
    for col in COLS:np.testing.assert_allclose(sum(s[col] for s in shards),meat[col],rtol=1e-9,atol=1e-9)
    return dict(rows=len(d),choosers=fit['g'],max_abs_beta_difference=max_beta,max_abs_joint_covariance_difference=max_cov)

def test_rank_loss(d,tmp):
    # Match the production absence of ultrabullet and of missing controls/gaps.
    d=d.copy();d['speed_code']=np.maximum(d.speed_code,1)
    for name in ['gap','clock_c','clock_d','premium','rd_c','rd_d']:d[name]=d[name].fillna(1.)
    X,names,ix=design(d);M,mnames=moments_design(d);p=tmp/'rank.npz';npz(p,**first(d)[0]);fit=fit_first([p],names,ix,mnames)
    meat=second(d,fit);covs={c:fit['g']/(fit['g']-1)*meat[c] for c in COLS};rows=make_rows(fit,covs)[0]
    assert all(r['status']=='ESTIMATED' for r in rows if r['panel'] in ['A','B_region','C_gap','C_slope'])
    assert all(fit['fits'][c]['rank']<len(fit['fits'][c]['names']) for c in COLS)

def test_pgn(tmp):
    import zstandard
    assert [speed_from_tc(s) for s in ['15+0','30+0','180+0','480+0','1500+0']]==[0,1,2,3,4]
    assert ply_count('1. e4 { [%clk 0:01:00] } e5 2. Nf3 Nc6 1-0','1-0')==4
    assert ply_count('*','*')==0
    for broken in ['1. e4','1. e4 (1. d4) 1-0','1. e4 { incomplete 1-0']:
        try:ply_count(broken,'1-0')
        except RuntimeError:pass
        else:raise AssertionError('Broken PGN movetext was accepted')
    blocks=[]
    for tc in ['15+0','60+0','300+0','600+0','1800+0']:
        for body in ['1-0','1. e4 e5 1-0','1. d4 d5 2. c4 1-0','1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0']:
            blocks.append(f'[Event "Rated game"]\n[UTCDate "2023.11.12"]\n[TimeControl "{tc}"]\n[Result "1-0"]\n\n{body}\n\n')
    root=tmp/'pgn';root.mkdir();p=root/'lichess_db_standard_rated_2023-11.pgn.zst';p.write_bytes(zstandard.ZstdCompressor().compress(''.join(blocks).encode()))
    discovery,inventory=discover([root,tmp/'missing']);assert sum(bool(r['candidates']) for r in discovery)==1
    t=dict(discovery[0],key='test',out=str(tmp/'hist.json'));r=safe_month(t)
    assert r['included_games']==20 and safe_month(t)['reused']
    run=tmp/'quantiles';(run/'report').mkdir(parents=True);status=finish([r],run,discovery,inventory)
    assert status['status']=='PARTIAL_AVAILABLE_MONTHS' and status['months_used']==['2023-11']
    q=pd.read_csv(run/'report/all_games_plies_by_speed.csv');assert (q.p25_plies==1.5).all() and (q.median_plies==2.5).all() and (q.p75_plies==3.75).all()
    for values in [[0],[0,1],[1,1,3,8,8],[0,2,3,6],list(range(21))]:
        plies,counts=np.unique(values,return_counts=True)
        for quantile in [.25,.5,.75]:assert histogram_quantile(plies,counts,quantile)==np.quantile(values,quantile,method='linear')
    # A broken month is excluded and reported; other successful months remain usable.
    bad=root/'lichess_db_standard_rated_2023-12.pgn';bad.write_text('[Event "Rated game"]\n[UTCDate "2023.12.12"]\n[TimeControl "300+0"]\n[Result "1-0"]\n\n1. e4')
    discovery,inventory=discover([root]);failure=safe_month(dict(discovery[1],key='bad',out=str(tmp/'bad.json')));assert failure['status']=='SOURCE_FAILED'
    status=finish([r,failure],run,discovery,inventory);assert status['months_used']==['2023-11']
    status=finish([],run,discovery,inventory);assert status['status']=='NO_MONTHS_AVAILABLE'
    assert pd.read_csv(run/'report/all_games_plies_by_speed.csv').median_plies.isna().all()

def main():
    start=time.monotonic()
    with tempfile.TemporaryDirectory(prefix='r11_test_') as tmp:
        root=Path(tmp);d=synthetic();test_basis();r=test_dense(d,root);test_rank_loss(d,root);test_projection(d,root);test_pgn(root)
    print('R11_SYNTHETIC_TESTS_OK '+json.dumps(dict(r,seconds=time.monotonic()-start)),flush=True)

if __name__=='__main__':main()

