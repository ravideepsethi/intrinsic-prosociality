"""Generated, non-research rows with repeated chooser-month opportunities."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from common import *
from design import counterfactual

def fixture(accounts=80,seed=9282):
    rng=np.random.default_rng(seed);rows=[]
    for chooser in range(accounts):
        intercept=rng.normal(0,.5)
        for mi,month in enumerate(MONTHS):
            for j in range(3):
                gap=int(rng.choice([-300,-200,-100,-50,0,50,100,200,300]))
                own=float(rng.choice([45,50,70,100,140,230],p=[.35,.2,.15,.15,.1,.05]))
                opp=float(rng.choice([45,50,70,100,160,240],p=[.3,.2,.2,.15,.1,.05]))
                rating=1500+chooser*2+int(rng.integers(-25,26))
                eta=-1.6+intercept+.16*gap/100
                rows.append(dict(game_id=f'syn{chooser:05d}{mi:02d}{j}',chooser=chooser,opponent=10000+chooser,
                    t=int(pd.Timestamp(month+'-01',tz='UTC').timestamp()*1000)+j*1000,month=month,
                    state='equal',regular=(chooser%19!=0),tier2=True,y=int(rng.random()<1/(1+np.exp(-eta))),
                    rd=own,opp_rd=opp,rating=rating,opp_rating=rating+gap,g=gap,color='white' if j%2 else 'black',
                    speed=rng.choice(SPEEDS),ply=int(rng.integers(12,95)),cp=int(rng.integers(-99,100)),
                    clock=float(rng.integers(3,300)),opp_clock=float(rng.integers(3,300)),
                    history_days=400+mi*30,prior_starts=150+mi*40+chooser,
                    inactivity_days=float(rng.uniform(0,7)),opp_prior_starts=int(rng.integers(100,5000))))
    d=counterfactual(pd.DataFrame(rows))
    return d

def metadata(d):
    a=d.groupby(['month','chooser']).y.agg(['sum','count']).reset_index()
    a['informative']=(a['sum']>0)&(a['sum']<a['count'])
    out=[]
    for month,g in a.groupby('month'):
        out.append(dict(month=month,rows=int(g['count'].sum()),grants=int(g['sum'].sum()),
            informative_groups=int(g.informative.sum()),informative_rows=int(g.loc[g.informative,'count'].sum())))
    return out

def informative(d):
    g=d.groupby(['chooser','month']).y
    return d[(g.transform('sum')>0)&(g.transform('sum')<g.transform('size'))]
