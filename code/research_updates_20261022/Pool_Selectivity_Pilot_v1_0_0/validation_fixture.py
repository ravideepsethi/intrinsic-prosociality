import sys,json,time,types,tempfile,argparse
from pathlib import Path
import numpy as np,pandas as pd,duckdb
PKG=Path(__file__).resolve().parent
sys.path.insert(0,str(PKG))
from prepare import source_view,audit_source,support_census,pilot_sample
from run_pilot import run_models,write_summary,package_report
from util import MONTHS

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--scenario',choices=['heterogeneous','level-only'],default='heterogeneous');opts=parser.parse_args()
 root=Path(tempfile.mkdtemp(prefix='selectivity_synthetic_'));private=root/'PRIVATE';private.mkdir();report=root/'report';report.mkdir()
 rng=np.random.default_rng(194);N=2400;T=72;n=N*T
 chooser=np.repeat(np.arange(N),T);mi=np.tile(np.repeat(np.arange(24),3),N)
 board=rng.choice([-500,-200,0,200,500],n,p=[.56,.08,.25,.06,.05])
 stage=rng.choice([2,6,8,10,15,30,60,100],n,p=[.08,.02,.03,.07,.2,.28,.24,.08])
 c=(board>=-100).astype(int);latent=rng.choice(3,N,p=[.65,.20,.15])
 alpha=np.array([-9.,-4.,-5.5]);theta=np.array([1.,.2,3.5]) if opts.scenario=='heterogeneous' else np.array([1.2,1.2,1.2])
 from scipy.special import expit
 prob=expit(alpha[latent[chooser]]+theta[latent[chooser]]*c+np.where(stage<=10,.25,0))
 y=rng.binomial(1,prob)
 df=pd.DataFrame(dict(chooser_user_id=chooser,month=np.array(MONTHS)[mi],outcome_kind_draw=y.astype(bool),engine_eval_cp_disconnected=board,ply_count=stage,api_status='timeout',five_second_rule_passed=True,sf100k_nodes_requested=100000,fair_competitive=c.astype(bool),chooser_elo=rng.choice([1200,1500,1800,2100],n),disconnected_elo=rng.choice([1200,1500,1800,2100],n),chooser_pre_rd_v2=rng.choice([35.,55.,80.],n),disconnected_pre_rd_v2=rng.choice([35.,55.,80.],n),chooser_win_premium_v2=rng.choice([5.7,12.,25.],n),chooser_draw_payoff_v2=rng.choice([-12.,-3.,0.,3.],n),chooser_clock_last_obs_s=rng.choice([5.,25.,120.,800.],n),disconnected_clock_last_obs_s=rng.choice([5.,25.,120.,800.],n),chooser_pre_sigma_v2=.06,disconnected_pre_sigma_v2=.06,api_speed=rng.choice(['blitz','rapid'],n),chooser_color=rng.choice(['white','black'],n)))
 source=root/'fixture.parquet';df.to_parquet(source,index=False)
 db=duckdb.connect();db.execute('SET threads=2');source_view(db,[source])
 expected=dict(rows=n,kind_draws=int(y.sum()),fair_rows=int(c.sum()),fair_kind_draws=int(y[c==1].sum()),choosers=N)
 audit_source(db,report,expected);support_census(db,private,report,'synthetic_v1');pilot=pilot_sample(db,private,report,'synthetic_v1',N,99)
 args=types.SimpleNamespace(starts=2,maxiter=550,seed=9,ridge=1e-6,workers=2,pilot_accounts=N,audit_only=False)
 result=run_models(pilot,private,report,'synthetic_v1',args)
 (report/'SUMMARY.md').write_text('SYNTHETIC SOFTWARE VALIDATION ONLY. No real games or production findings. Scenario: '+opts.scenario+'\n')
 output=package_report(report,root,'synthetic')
 print(json.dumps(result,indent=2));print('REPORT',output)
 # Re-run reusable preparation checkpoints and verify deterministic sampling.
 support_census(db,private,report,'synthetic_v1');pilot_sample(db,private,report,'synthetic_v1',N,99)
 print('END_TO_END_SYNTHETIC_OK')
if __name__=='__main__':main()
