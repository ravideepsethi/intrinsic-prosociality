"""Offline checks; no Mac paths, API calls, game recovery or engine execution."""
from common import *
from features import change,score_kind,one_game,material,prepare_targets,convert_unit
from design import dummy,design,select,specifications,point_vector
from estimate import within,solve,moments,meat,coefficient_cov,estimable
import chess,tempfile,gzip

def synthetic(accounts=100,per_account=12):
    rng=np.random.default_rng(7139028);n=accounts*per_account
    d=pd.concat([dummy()]*n,ignore_index=True)
    d['chooser']=np.repeat(np.arange(accounts),per_account);d['game_id']=['synthetic_'+str(i) for i in range(n)]
    d['board']=rng.choice([-800,-500,-300,-75,0,100,200,350,500,700,10000],n)
    d['mate']=d.board==10000;d['cp']=d.board.where(~d.mate,np.nan)
    d['ply']=rng.choice([2,4,8,16,30,60,90],n)
    d['stage']=np.select([d.ply<2,d.ply==2,d.ply<=4,d.ply<=6,d.ply<=8,d.ply<=10,d.ply<=20,d.ply<=40,d.ply<=80],range(9),default=9)
    d['month_code']=rng.integers(0,24,n);d['speed_code']=rng.integers(0,5,n)
    d['gap']=rng.normal(0,150,n);d['clock_c']=rng.uniform(0,180,n);d['clock_d']=rng.uniform(5,180,n)
    d['log_rival_clock']=np.log1p(d.clock_d);d['clock_ratio']=d.clock_d/d.clock_c;d['clock_fraction']=d.clock_d/180
    d['time_trouble']=(d.clock_fraction<.1).astype(int)
    for p in ['own','net2','net4']:
        d[p+'_loss100']=np.clip(rng.normal(1,2,n),-10,10);d[p+'_kind']='finite'
    d['material_swing4']=rng.integers(-5,6,n)
    d['trajectory_ok']=rng.random(n)>.06;d['y']=(rng.random(n)<(.05+.03*(d.board>=-100))).astype(int)
    d['replay_status']='VERIFIED';d['recomputed_final_cp']=d.cp;d['recomputed_final_mate']=np.where(d.mate,3,np.nan)
    d['game_ms']=1700000000000+np.arange(n)*1000
    return d
def test_scores():
    def sc(cp=None,mate=None,status='SCORED'):return dict(cp=cp,mate=mate,status=status,nodes=100000)
    assert change(sc(150),sc(-70))==(2.2,'finite')
    assert change(sc(2000),sc(-2000))==(10.,'finite')
    assert change(sc(-2000),sc(2000))==(-10.,'finite')
    assert change(sc(50),sc(mate=3))==(0.,'to_positive_mate')
    assert change(sc(mate=-3),sc(50))==(0.,'from_negative_mate')
    assert score_kind(sc(mate=4,status='SHORT'))=='positive'
    assert score_kind(sc(mate=4,status='BOUNDED')) is None
    assert score_kind(sc(40,status='SHORT')) is None
    board=chess.Board();positions=[dict(ply=0,fen=board.fen())]
    for i,san in enumerate(['e4','e5','Nf3','Nc6'],1):board.push_san(san);positions.append(dict(ply=i,fen=board.fen()))
    g=dict(game_id='toy',status='VERIFIED',color='white',n=4,positions=positions)
    rows=[dict(game_id='toy',color='white',**p,**sc(v)) for p,v in zip(positions,[10,20,70,-150,-80])]
    r=one_game(g,rows)
    assert abs(r['own_loss100']-2.2)<1e-12 and abs(r['net2_loss100']-1.5)<1e-12
    assert abs(r['net4_loss100']-.9)<1e-12 and r['material_swing4']==0
    assert r['trajectory_ok']
    # Opposite color: own move is n-1 again, not the chooser's final move.
    board.push_san('Bb5');positions.append(dict(ply=5,fen=board.fen()))
    g.update(n=5,color='black',positions=positions[1:])
    rows=[dict(game_id='toy',color='black',**p,**sc(v)) for p,v in zip(positions[1:],[10,20,200,-100,-300])]
    r=one_game(g,rows);assert r['own_loss100']==3. and r['net2_loss100']==5.
    f='4k3/8/8/8/8/8/P7/4K3 w - - 0 1'
    assert material(f,'white')==1 and material(f,'black')==-1
def test_estimation():
    rng=np.random.default_rng(17);g=np.repeat(np.arange(30),5);n=len(g)
    X=rng.normal(size=(n,3));y=X@np.array([.3,-.8,1.1])+rng.normal(size=n)+np.repeat(rng.normal(size=30),5)
    W,v,starts,counts=within(X,y,g);b,inv,_,_,_=solve(W.T@W,W.T@v)
    D=np.eye(30)[g];Z=np.column_stack([X,D]);full=np.linalg.lstsq(Z,y,rcond=None)[0]
    np.testing.assert_allclose(b,full[:3],rtol=1e-10,atol=1e-10)
    residual=y-Z@full;scores=np.add.reduceat(Z*residual[:,None],starts,axis=0)
    zi=np.linalg.inv(Z.T@Z);fullcov=30/29*zi@scores.T@scores@zi
    score=np.add.reduceat(W*(v-W@b)[:,None],starts,axis=0)
    cov=30/29*inv@score.T@score@inv
    np.testing.assert_allclose(cov,fullcov[:3,:3],rtol=1e-9,atol=1e-10)
    # The actual A2 designs include empty/aliased mate and tail directions.
    d=synthetic();specs=specifications(False)
    for s in specs:
        a=select(d,s);A,names,p,_,_=design(a,s);E,en,ep,_,_=design(a.iloc[:0],s)
        assert np.isfinite(A).all() and names==en and p==ep and E.shape==(0,len(names))
    s=next(s for s in specs if s['name']=='curve_late_common_proxies')
    m,names,p,ng=moments(d,s);b,inv,scale,null,rank=solve(m['xx'],m['xy'])
    fit=dict(beta=b,inverse=inv,scale=scale,null=null,rank=rank,p=p,ng=ng,names=names,n=int(m['n']),g=int(m['g']),
             mean_y=float(m['y_sum']/m['n']),mean_f=m['f_sum']/m['n'],group_share=m['group_sum']/m['n'])
    parts=[d[d.chooser%7==i].reset_index(drop=True) for i in range(7)]
    np.testing.assert_allclose(sum(moments(x,s)[0]['xx'] for x in parts),m['xx'],rtol=1e-10,atol=1e-8)
    np.testing.assert_allclose(sum(meat(x,s,fit) for x in parts),meat(d,s,fit),rtol=1e-10,atol=1e-7)
    assert estimable(fit,point_vector(fit,300)-point_vector(fit,100))
    a=select(d,next(s for s in specs if s['name']=='curve_late_common_baseline'))
    c=select(d,s);assert a.game_id.tolist()==c.game_id.tolist()
def test_projection_and_cache():
    from lineage import digest
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        t=pd.DataFrame(dict(game_id=['a','b'],chooser=[1,1],y=[0,1],board=[0,10000],engine_eval_is_mate=[False,True],
            ply_count=[12,20],rating=[1700,1700],gap100=[.5,-.5],premium10=[.6,.6],crd100=[.6,.6],drd100=[.7,.7],
            month=['2023-11','2025-10'],speed=['blitz','rapid'],log_cc=[0,np.log(31)],log_dc=[np.log(19),np.log(19)],
            cc_missing=[0,0],dc_missing=[0,1],time_control=['180+2','0+1'],game_ms=[1700000000000,1760000000000]))
        p=root/'target.parquet';t.to_parquet(p,index=False);d=prepare_targets(p)
        assert d.clock_d.iloc[0]==18 and d.time_trouble.iloc[0]==0 and d.clock_fraction.iloc[0]==.1
        assert np.isnan(d.clock_ratio.iloc[0]) and np.isnan(d.clock_d.iloc[1]) and np.isnan(d.clock_fraction.iloc[1])
        assert d.gap.tolist()==[50,-50] and d.premium.tolist()==[6,6] and np.isnan(d.cp.iloc[1])
        g=dict(game_id='toy',status='NONRETURN',positions=[])
        rp=root/'replay.json';dump(rp,[g]);sp=root/'scores.json.gz'
        with gzip.open(sp,'wt') as f:json.dump([],f)
        for x in [rp,sp]:dump(str(x)+'.receipt.json',dict(key='unit-test',sha256=digest(x)))
        out=root/'features.parquet';job=(dict(replay=str(rp),scores=str(sp),key='unit-test'),str(out),'new-test')
        convert_unit(job);before=out.stat().st_mtime_ns;convert_unit(job)
        assert out.stat().st_mtime_ns==before
        q=pd.read_parquet(out);assert q.replay_status.iloc[0]=='NONRETURN' and not q.trajectory_ok.iloc[0]
def main():
    test_scores();test_estimation();test_projection_and_cache();print('SELF_TEST_OK: move orientation, mate/CP separation, capping, material signs, clock thresholds, authenticated cache reuse, all designs, FE and clustered covariance, whole-chooser partition parity.',flush=True)
if __name__=='__main__':main()
