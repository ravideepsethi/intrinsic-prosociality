"""Synthetic, independent checks of the operations that can change inference."""
from util import *
import tempfile

def quick():
    lines='''11632 /a/python -u /Desktop/Lichess_Desktop/kac_a2_repair.x/run.py --workers 10
11690 caffeinate -i /a/python -u /Desktop/Lichess_Desktop/kac_a2_repair.x/run.py --workers 10
33130 /opt/homebrew/bin/stockfish
90270 /Volumes/XT_Pro/lichess_kindness/venv/bin/python code/run.py --threads 4
90272 /usr/bin/caffeinate -dimsu /a/python code/run.py --threads 4
99999 /a/python /new/companion/run.py --worker-budget 10'''
    got=process_reservations(lines,99999,'/new/companion')
    assert len(got)==2 and sum(r['workers'] for r in got)==14
    for code in (0,1,2):assert (code-1)==-(1-code)

def focal_frame(n=1500,seed=28):
    rng=np.random.default_rng(seed);chooser=np.repeat(np.arange(50),n//50);n=len(chooser)
    board=rng.choice([-700,-400,-75,-25,25,75,150,250,450,700],n)
    pos=rng.integers(1,40,n);y=rng.binomial(1,.05,n);y[chooser<10]=0
    return pd.DataFrame(dict(prefix_count_uncertain=((chooser==22)&(np.arange(n)%5==1)).astype(int),chooser=chooser,game_id=['x'+str(i) for i in range(n)],t=np.arange(n),ordinal=np.arange(n),
        y=y,cp=board,board=board,mate=np.zeros(n,bool),ply=np.full(n,30),stage=rng.choice([6,7,8,9],n),
        month_code=rng.integers(0,24,n),speed_code=rng.integers(0,5,n),tier=np.ones(n,int),material=np.zeros(n),
        rating=np.full(n,1700),gap=rng.normal(0,100,n),clock_c=np.ones(n)*60,clock_d=np.ones(n)*50,
        premium=np.ones(n)*6,rd_c=np.ones(n)*60,rd_d=np.ones(n)*60,prior_same_speed=rng.integers(1,10000,n),
        pos15=pos,pos30=pos,pos60=pos,cens15=np.zeros(n,bool),cens30=np.zeros(n,bool),cens60=np.zeros(n,bool),tie_n=np.ones(n,int)))

def fe_test(root):
    import repetition as r
    d=focal_frame();s=r.specs()[5];a,X,names,p=r.design(d,s);W,y,starts=r.within(a,X)
    fit=r.solve(W.T@W,W.T@y)
    # Explicit account dummy regression is an independent point-estimate check.
    D=pd.get_dummies(a.chooser,dtype=float).to_numpy()
    B=np.linalg.lstsq(np.column_stack([D,X]),a.y.to_numpy()*100,rcond=1e-10)[0][D.shape[1]:]
    assert np.max(abs(fit['beta'][:p]-B[:p]))<1e-7
    shards=[d[d.chooser%3==j] for j in range(3)]
    xx=np.zeros_like(W.T@W);xy=np.zeros(W.shape[1]);meat=np.zeros_like(xx)
    for shard in shards:
        ad,xd,_,_=r.design(shard,s);wd,yd,ss=r.within(ad,xd);xx+=wd.T@wd;xy+=wd.T@yd
        score=np.add.reduceat(wd*(yd-wd@fit['beta'])[:,None],ss,axis=0);meat+=score.T@score
    assert np.max(abs(xx-W.T@W))<1e-6 and np.max(abs(xy-W.T@y))<1e-7
    score=np.add.reduceat(W*(y-W@fit['beta'])[:,None],starts,axis=0)
    assert np.max(abs(meat-score.T@score))<1e-5
    # Exercise production worker caches, including the all-zero chooser accounts.
    f=root/'focal.parquet';d.to_parquet(f,index=False)
    out=r.worker(([f],root/'moments','test',1,[s],[]));tot=r.reduce([out])
    assert int(tot['0_g'])==50 and int(tot['0_n'])==len(a)
    assert r.worker(([f],root/'moments','test',1,[s],[]))==out
    assert r.design(d.assign(tie_n=2),s)[0].empty

def history_test(root):
    from history import initial_state,month_history
    def ms(s):return int(pd.Timestamp(s,tz='UTC').timestamp()*1000)
    run=root/'history_run';(run/'PRIVATE').mkdir(parents=True)
    pd.DataFrame({'chooser':[1,2,3]}).to_parquet(run/'PRIVATE/needed.parquet',index=False)
    (run/'PRIVATE/uncertain_prefix').mkdir()
    pd.DataFrame({'chooser':[1]}).to_parquet(run/'PRIVATE/uncertain_prefix/choosers.parquet',index=False)
    pf=root/'prefix.parquet'
    pd.DataFrame(dict(chooser=[1,2,3],speed_code=[1,1,1],n=[2,1,1],last_t=[ms('2023-10-01')-HOUR]*3)).to_parquet(pf,index=False)
    prev=initial_state(run,[pf],'test',1,1)
    def raw(month,speed,events):
        p=root/(month+'_'+str(speed)+'.parquet')
        z=pd.DataFrame(events,columns=['game_id','t','white_id','black_id','result_code'])
        z['utc_ms']=z.pop('t').map(ms);z['archive_ordinal']=np.arange(len(z));z['white_rating_diff']=2;z['black_rating_diff']=-2
        z.to_parquet(p,index=False)
        return dict(path=str(p),speed_code=speed,stat=snapshot(p)),z
    oct,z=raw('2023-10',1,[('a','2023-10-31 23:50',1,2,2),('b','2023-10-31 23:59',3,1,0)])
    prev=month_history('2023-10',[oct],run,prev,'test',1,1)
    nov,z=raw('2023-11',1,[('c','2023-11-01 00:01',1,2,1),('d','2023-11-01 00:02',1,3,2),
        ('e','2023-11-01 00:02',1,2,0),('f','2023-11-01 00:40',2,1,2)])
    blitz,zb=raw('2023-11',2,[('g','2023-11-01 00:50',1,3,2)])
    base=focal_frame(1500).iloc[:len(z)+len(zb)].copy().reset_index(drop=True)
    whole=pd.concat([z,zb],ignore_index=True);base['chooser']=1;base['game_id']=whole.game_id;base['t']=whole.utc_ms
    base['speed_code']=[1]*len(z)+[2];base=base.drop(columns=['prior_same_speed','pos15','pos30','pos60','cens15','cens30','cens60','tie_n','prefix_count_uncertain'])
    p=run/'PRIVATE/focal/2023-11/rows.parquet';p.parent.mkdir(parents=True);base.to_parquet(p,index=False)
    dest=month_history('2023-11',[nov,blitz],run,prev,'test',1,1)
    got=pd.read_parquet(dest/'focal_history.parquet').set_index('game_id')
    assert got.loc['c','pos30']==3 and got.loc['c','prior_same_speed']==4
    assert got.loc['c','prev_gid']=='b' and got.loc['c','prev_result']==1
    assert got.loc['d','prior_same_speed']==5 and got.loc['e','prior_same_speed']==5
    assert got.loc['d','tie_n']==2 and got.loc['f','prev_tie']==2
    assert got.loc['f','pos30']==1 and got.loc['f','pos60']==6
    assert got.loc['g','prior_same_speed']==0 and got.loc['g','pos30']==2
    assert (got.cens30==False).all()
    assert got.loc['c','prefix_count_uncertain']==1 and got.loc['g','prefix_count_uncertain']==0
    assert month_history('2023-11',[nov,blitz],run,prev,'test',1,1)==dest
    before=sha(Path(nov['path']));assert before==load(dest/'_DONE.json')['sources'][0]['sha256']
    counts=pd.read_parquet(dest/'counts.parquet');assert int(counts.query('chooser==1 and speed_code==1').n.iloc[0])==8
    # Cache damage must be rejected, never accepted by row counts alone.
    (dest/'QA.json').write_text('{}')
    try:month_history('2023-11',[nov,blitz],run,prev,'test',1,1)
    except RuntimeError as e:assert 'Checkpoint damaged' in str(e)
    else:raise AssertionError('Damaged history cache accepted')
