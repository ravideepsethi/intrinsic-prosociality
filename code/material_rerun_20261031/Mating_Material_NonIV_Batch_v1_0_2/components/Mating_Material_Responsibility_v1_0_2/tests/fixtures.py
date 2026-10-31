from pathlib import Path
import numpy as np,pandas as pd
from sources import prepare_targets

def frames(folder,n=3200,seed=871):
    rng=np.random.default_rng(seed);ply=rng.choice([2,3,4,5,7,10,11,20,21,41,81,120],n)
    board=rng.choice([-900,-500,-300,-150,-100,-50,0,50,100,150,250,300,500,599,700,10000,-10000],n)
    clocks=rng.uniform(2,600,(n,2));gaps=rng.normal(0,180,n)
    choosers=np.arange(n)//8+1;cc_missing=rng.random(n)<.01;dc_missing=rng.random(n)<.01
    raw=pd.DataFrame(dict(game_id=[f'g{i:08d}' for i in range(n)],chooser=choosers,y=(rng.random(n)<.03).astype(int),
        board=board,engine_eval_is_mate=np.abs(board)==10000,ply_count=ply,rating=rng.normal(1600,300,n),gap100=gaps/100,
        premium10=rng.uniform(.15,2,n),crd100=rng.uniform(.3,1.2,n),drd100=rng.uniform(.3,1.5,n),
        month=np.array([f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)])[rng.integers(0,24,n)],
        speed=np.array(['ultraBullet','bullet','blitz','rapid','classical'])[rng.integers(1,5,n)],
        log_cc=np.where(cc_missing,0,np.log1p(clocks[:,0])),log_dc=np.where(dc_missing,0,np.log1p(clocks[:,1])),
        cc_missing=cc_missing.astype(int),dc_missing=dc_missing.astype(int),time_control=np.array(['60+0','180+2','600+0'])[rng.integers(0,3,n)],game_ms=np.full(n,1714000000000)))
    # One singleton, retained by the original covariance and census conventions.
    raw.loc[n-1,'chooser']=int(raw.chooser.max())+1
    path=Path(folder)/'target.parquet';path.parent.mkdir(parents=True,exist_ok=True);raw.to_parquet(path,index=False)
    d=prepare_targets(path)
    f=pd.DataFrame(dict(game_id=raw.game_id,replay_status='VERIFIED',trajectory_ok=True,
                       material_swing4=rng.integers(-4,5,n).astype(float),
                       recomputed_final_cp=raw.board.where(~raw.engine_eval_is_mate,np.nan),
                       recomputed_final_mate=np.where(raw.engine_eval_is_mate,np.sign(raw.board)*3,np.nan)))
    kinds=['finite','to_positive_mate','to_negative_mate','from_positive_mate','from_negative_mate','positive_mate_both','negative_mate_both','missing']
    for prefix in ('own','net2','net4'):
        kind=np.array(kinds,dtype=object)[rng.choice(8,n,p=[.9,.014,.014,.014,.014,.014,.014,.016])]
        if prefix=='net4':kind[ply<4]='missing'
        loss=np.clip(rng.normal(.5,2,n),-10,10);loss[kind!='finite']=0;loss[kind=='missing']=np.nan
        f[prefix+'_kind']=kind;f[prefix+'_loss100']=loss
    f.loc[ply<4,'material_swing4']=np.nan
    f.loc[np.arange(n)%79==0,'trajectory_ok']=False
    return raw,d,f

def joined(folder,n=3200):
    raw,d,f=frames(folder,n);return d.merge(f,on='game_id',validate='one_to_one')
