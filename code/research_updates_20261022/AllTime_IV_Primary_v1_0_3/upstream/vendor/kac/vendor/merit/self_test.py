"""Numerical reference tests. Synthetic rows never pass the production census gate."""
from common import *
import argparse,tempfile
from design import *
from estimate import *
from prepare import fen_material,project_month,partition,raw_summaries

def fixture(naccounts=100,nper=35,seed=61027):
    rng=np.random.default_rng(seed);n=naccounts*nper;cp=rng.integers(-700,950,n).astype(float)
    mate=rng.random(n)<.06;cp[mate]=np.where(rng.random(mate.sum())>.35,10000,-10000)
    ply=rng.choice([2,4,6,8,10,16,32,60,100],n);stage=np.searchsorted([2,3,5,7,9,11,21,41,81],ply,side='right')
    tier=rng.integers(0,4,n);material=rng.integers(-5,9,n)
    p=.01+.035/(1+np.exp(-np.clip(cp,-1500,1500)/250))+.04*(ply<=10)
    chooser=np.repeat(np.arange(naccounts),nper)
    y=(rng.random(n)<p).astype(int);y[chooser<4]=0
    return pd.DataFrame(dict(chooser=chooser,y=y,cp=cp,board=cp,mate=mate,ply=ply,material=material,
        rating=np.choose(tier,[1400,1800,2200,2500]),gap=rng.normal(0,120,n),tier=tier,
        clock_c=rng.uniform(5,100,n),clock_d=rng.uniform(5,100,n),premium=rng.uniform(4,9,n),
        rd_c=rng.uniform(45,100,n),rd_d=rng.uniform(45,100,n),month_code=rng.integers(0,24,n),
        speed_code=rng.integers(0,5,n),stage=stage))

def fit_one(d,s):
    m,names,p,ng=moments(d,s);b,inv,scale,null,rank=solve(m['xx'],m['xy'])
    return dict(beta=b,inverse=inv,scale=scale,null=null,rank=rank,names=names,p=p,ng=ng,
        mean_y=float(m['y_sum']/m['n']),mean_f=m['f_sum']/m['n'],group_share=m['group_sum']/m['n'],n=int(m['n']),g=int(m['g']),
        singletons=int(m['singletons']),never=int(m['never']),vary_g=int(m['vary_g']),vary_n=int(m['vary_n']))

def numerical_tests():
    # Orientation is checked on independent explicit FENs, including a rook/queen imbalance.
    assert fen_material('4k3/8/8/8/8/8/8/3QK3 b - - 0 1','black')==-9
    assert fen_material('4k3/8/8/8/8/8/8/3QK3 w - - 0 1','white')==9
    assert fen_material('3qk3/8/8/8/8/8/8/3RK3 w - - 0 1','white')==-4
    knots=(-100,0,100,300,600);cs=interpolator(knots)
    np.testing.assert_allclose(cs([-1,6],2),0,atol=1e-12)
    np.testing.assert_allclose(natural_basis([0],knots),0,atol=1e-12)
    d=fixture();s=specifications()[0];a=select(d,s);f=fit_one(d,s);X,names,p,groups,ng=design(a,s);y=a.y.to_numpy()*100
    starts,counts=grouped(a.chooser.to_numpy());codes=np.repeat(np.arange(len(starts)),counts)
    D=np.column_stack([np.eye(len(starts))[codes],X]);coef=np.linalg.lstsq(D,y,rcond=1e-11)[0]
    W,v,_,_=within(X,y,a.chooser.to_numpy())
    np.testing.assert_allclose(W@f['beta'],W@coef[len(starts):],atol=2e-7)
    resid=y-D@coef;ds=np.add.reduceat(D*resid[:,None],starts,axis=0)
    direct_inv=np.linalg.pinv(D.T@D,rcond=1e-11);direct_cov=direct_inv@(ds.T@ds)@direct_inv*len(starts)/(len(starts)-1)
    M=meat(d,s,f);V=coefficient_cov(f,M)
    delta=np.zeros(X.shape[1]);delta[:p]=(counterfocal(s,dict(cp=300),ng)-counterfocal(s,dict(cp=0),ng))[0]
    R=np.r_[np.zeros(len(starts)),delta]
    np.testing.assert_allclose(delta@V@delta,R@direct_cov@R,rtol=2e-7,atol=2e-7)
    # Independently differentiate whole-cluster weighted refits, including the changing target.
    counter=counterfocal(s,dict(cp=100),ng);value,se,ok=level(f,M,counter);assert ok and se>0
    N=f['n'];z=np.column_stack([np.add.reduceat(y,starts)-counts*f['mean_y'],
        np.add.reduceat(X[:,:p],starts,axis=0)-counts[:,None]*f['mean_f'],
        counts[:,None]-counts[:,None]*f['group_share'],np.add.reduceat(W*(v-W@f['beta'])[:,None],starts,axis=0)])
    delta=np.zeros(X.shape[1]);delta[:p]=counter[0]-f['mean_f']
    grad=np.r_[1/N,-f['beta'][:p]/N,counter@f['beta'][:p]/N,f['inverse']@delta]
    def weighted_level(g,eps):
        weight=np.ones(len(a));weight[codes==g]+=eps
        b=np.linalg.lstsq(W*np.sqrt(weight)[:,None],v*np.sqrt(weight),rcond=1e-11)[0]
        return np.average(y,weights=weight)+(counter[0]-np.average(X[:,:p],axis=0,weights=weight))@b[:p]
    for g in [0,4,20,70]:
        numeric=(weighted_level(g,1e-4)-weighted_level(g,-1e-4))/2e-4
        np.testing.assert_allclose(z[g]@grad,numeric,rtol=3e-5,atol=3e-7)
    # Splitting only by chooser preserves cross-month scores; compare all 23 designs.
    for spec in specifications():
        whole=fit_one(d,spec);m,_,_,_=moments(d,spec)
        chunks=[d[d.chooser%3==b].reset_index(drop=True) for b in range(3)]
        parts=[moments(x,spec)[0] for x in chunks]
        for k in m:np.testing.assert_allclose(sum(p[k] for p in parts),m[k],rtol=1e-10,atol=1e-7)
        np.testing.assert_allclose(sum(meat(x,spec,whole) for x in chunks),meat(d,spec,whole),rtol=1e-8,atol=1e-5)
    # Rare outcomes, singleton accounts, and empty support are retained/handled.
    short=d.groupby('chooser',sort=False).head(1).copy();short['ply']=20
    m,_,_,_=moments(short,s);assert int(m['singletons'])==int(m['g'])
    np.testing.assert_allclose(m['xx'],0,atol=1e-10)
    m,_,_,_=moments(d.iloc[:0],s);assert int(m['n'])==0
    b=focal(pd.DataFrame(dict(board=[-100,-50,0,50,100,101,200,201,299,300,599,600,10000])),dict(kind='bins'))[0]
    assert bins_code(pd.DataFrame(dict(board=[100,101,200,201,300,600]))).tolist()==[3,4,4,5,6,7]
    print('NUMERICAL_SELF_TEST_OK: explicit dummy OLS, clustered covariance, level influence, 23 partitioned designs, boundaries and material orientation.',flush=True)

def integration_test():
    from run import analyse
    with tempfile.TemporaryDirectory(prefix='kac_a1_test_') as temp:
        root=Path(temp);(root/'report').mkdir();(root/'PRIVATE').mkdir()
        d=fixture(80,35);raw=d.copy();raw['game_id']=['g'+str(j) for j in range(len(d))]
        raw['chooser_user_id']=d.chooser;raw['outcome_kind_draw']=d.y.astype(bool)
        for col in ['engine_eval_cp_disconnected_raw','engine_eval_cp_disconnected']:raw[col]=d.cp.astype(int)
        raw['engine_eval_is_mate']=d.mate;raw['ply_count']=d.ply;raw['chooser_elo']=d.rating;raw['disconnected_elo']=d.rating+d.gap.round()
        raw['sf100k_nodes_requested']=100000;raw['sf100k_fen_turn_matches_disconnected_color']=True
        for col in ['disconnected_color','sf100k_disconnected_color_for_perspective','side_to_move_after_last']:raw[col]='white'
        raw['api_status']='timeout';raw['five_second_rule_passed']=True;raw['api_rated']=True;raw['api_variant']='standard';raw['api_speed']=[SPEEDS[j] for j in d.speed_code]
        # Projection independently reconstructs simple pawn material; FEN check uses first 32 equal positions.
        for role in ['chooser','disconnected']:
            for piece in ['pawns','knights','bishops','rooks','queens']:raw[role+'_'+piece]=0
        raw['chooser_pawns']=np.maximum(-d.material,0);raw['disconnected_pawns']=np.maximum(d.material,0)
        raw.loc[:31,['chooser_pawns','disconnected_pawns']]=0
        raw['disconnected_minus_chooser_material']=raw.disconnected_pawns-raw.chooser_pawns
        raw['fen_after_last_move']='4k3/8/8/8/8/8/8/4K3 w - - 0 1'
        for output,input in [('chooser_clock_last_obs_s','clock_c'),('disconnected_clock_last_obs_s','clock_d'),('chooser_win_premium_v2','premium'),('chooser_pre_rd_v2','rd_c'),('disconnected_pre_rd_v2','rd_d')]:raw[output]=d[input]
        raw['month']='2023-11';source=root/'fixture.parquet';raw.to_parquet(source,index=False)
        out=root/'PRIVATE/projection.parquet';task=dict(source=str(source),output=str(out),expected_sha256=sha(source),rows=len(d),month='2023-11',key='synthetic',memory_gb=.5)
        r=project_month(task);assert r['n']==len(d);assert project_month(task)['reused']
        # Corrupt only the projection to verify that its checksum causes regeneration.
        with open(out,'ab') as f:f.write(b'damage')
        assert not project_month(task)['reused']
        part=partition([out],root,4,2,.5,'synthetic');assert partition([out],root,4,2,.5,'synthetic')==part
        val=raw_summaries([out],root,2,.5)
        specs=specifications();analyse(root,[out],specs,part,2,2,'synthetic',val)
        before={p.name:sha(p) for p in (root/'PRIVATE/moments').glob('*.npz')}
        analyse(root,[out],specs,part,2,2,'synthetic',val)
        assert before=={p.name:sha(p) for p in (root/'PRIVATE/moments').glob('*.npz')}
        assert (root/'report/merit_continuous.pdf').exists()
        # Retain figures only when explicitly requested for development visual QA.
        dest=os.environ.get('KAC_QA_DIR')
        if dest:
            import shutil
            shutil.copytree(root/'report',dest,dirs_exist_ok=True)
        print('INTEGRATION_SELF_TEST_OK: Parquet projection, semantic checks, cache corruption/reuse, spawn workers, 23 models, report and figures.',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--integration',action='store_true');a=ap.parse_args()
    numerical_tests()
    if a.integration:integration_test()
