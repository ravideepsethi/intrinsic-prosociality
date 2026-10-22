#!/usr/bin/env python3
"""B/C analyses on the frozen 24-month POOL/NONADJACENT sample.

Never run directly on the 47.59m-row all-source Stage07 dataset.
Never changes certified inputs; writes only under a new output root.
Dependencies: duckdb, numpy, pandas, matplotlib; no scipy, API or Stockfish.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,os,sys,time,math,traceback
from pathlib import Path
import numpy as np
import pandas as pd
from methods import GROUPS,fit_gp_zip,model_design,f_vector,within_chunk_cross_products,within_chunk_cluster_scores,gp_logpmf,choose_within_identified

ALIASES={
 'chooser':['chooser_user_id','chooser_id','chooser','chooser_username'],
 'grant':['outcome_kind_draw','grant','kind_draw','is_kind_draw'],
 'v':['engine_eval_cp_disconnected','eval_cp_disconnected','engine_eval_cp','v'],
 'ply':['ply_count','ply','num_plies'],
 'speed':['api_speed','speed','speed_category'],
 'month':['month','game_month'],
 'rG':['chooser_draw_payoff_v2','chooser_draw_payoff','rG','draw_payoff'],
 'kappa':['chooser_win_premium_v2','chooser_win_premium','kappa','forgone_premium'],
 'rd_chooser':['chooser_pre_rd_v2','chooser_pre_rd','chooser_rd'],
 'rd_opponent':['disconnected_pre_rd_v2','disconnected_pre_rd','opponent_rd'],
 'clock_chooser':['chooser_clock_last_obs_s','chooser_clock_s','chooser_seconds'],
 'clock_opponent':['disconnected_clock_last_obs_s','disconnected_clock_s','opponent_seconds'],
 'rating_chooser':['chooser_elo','chooser_rating','rating_chooser'],
 'rating_opponent':['disconnected_elo','disconnected_rating','opponent_rating'],
}

def ident(s): return '"'+str(s).replace('"','""')+'"'
def lit(s): return "'"+str(s).replace("'","''")+"'"
def announce(s):
 print('['+dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')+'] '+s,flush=True)

def candidate_paths(root):
 base=Path(root)/'derived'/'replication'
 if not base.is_dir():return []
 out=[]
 # Avoid scanning raw PGNs / gigantic unrelated output trees.
 for r,dirs,files in os.walk(base):
  depth=len(Path(r).relative_to(base).parts)
  if depth>4:dirs[:]=[];continue
  nm=r.lower()
  matches=any(s in nm for s in ['pool','nonadj','non_adj','author_excl','analysis_main','main_sample'])
  if matches and any(f.endswith('.parquet') for f in files):out.append(r)
  for file in files:
   if file.endswith('.duckdb') and any(s in file.lower() for s in ['pool','main','author']):out.append(str(Path(r)/file))
 return sorted(set(out))

def connect(out,workers,memory):
 import duckdb
 cn=duckdb.connect(database=':memory:')
 cn.execute(f"SET threads = {int(workers)}")
 cn.execute(f"SET memory_limit = {lit(str(int(memory))+'GB')}")
 tmp=Path(out)/'private'/'duckdb_spill';tmp.mkdir(parents=True,exist_ok=True)
 cn.execute('SET temp_directory = '+lit(str(tmp)))
 return cn

def input_sql(path,view):
 p=Path(path)
 if not p.exists():raise FileNotFoundError(f'Input absent: {p}')
 if p.suffix=='.duckdb':
  if not view:raise ValueError('Specify --view for a DuckDB database')
  return 'main_data.'+ident(view),'duckdb'
 if p.is_dir():
  if not any(p.rglob('*.parquet')):raise ValueError(f'No Parquet in {p}')
  pat=str(p/'**'/'*.parquet')
 elif p.suffix=='.parquet':pat=str(p)
 else:raise ValueError('Main sample must be a Parquet directory/file or .duckdb with --view')
 return 'read_parquet('+lit(pat)+', union_by_name=true, hive_partitioning=true)','parquet'

def create_norm(cn,path,view):
 source,kind=input_sql(path,view)
 if kind=='duckdb':cn.execute('ATTACH '+lit(str(path))+' AS main_data (READ_ONLY)')
 descriptions=cn.execute('DESCRIBE SELECT * FROM '+source+' LIMIT 0').fetchall()
 name_map={x[0].lower():x[0] for x in descriptions}
 cols={}
 for semantic, candidates in ALIASES.items():
  match=next((name_map[z.lower()] for z in candidates if z.lower() in name_map),None)
  if not match:raise ValueError(f'Missing {semantic}; available: {sorted(name_map)}')
  cols[semantic]=match
 types={'chooser':'VARCHAR','grant':'INTEGER','v':'DOUBLE','ply':'INTEGER',
        'speed':'VARCHAR','month':'VARCHAR','rG':'DOUBLE','kappa':'DOUBLE',
        'rd_chooser':'DOUBLE','rd_opponent':'DOUBLE','clock_chooser':'DOUBLE',
        'clock_opponent':'DOUBLE','rating_chooser':'DOUBLE','rating_opponent':'DOUBLE'}
 select=[]
 for name,typ in types.items():
  c=ident(cols[name]);expr='TRY_CAST('+c+' AS '+typ+')'
  if name=='month':expr=f'SUBSTR({expr},1,7)'
  if name=='speed':expr='LOWER('+expr+')'
  select.append(expr+' AS '+ident(name))
 cn.execute('CREATE OR REPLACE VIEW norm AS SELECT '+', '.join(select)+' FROM '+source)
 return cols

def validate(cn,expect_rows,expect_grants,expect_comp):
 announce('Preflight: validating sample identity and missingness')
 stat=cn.execute('''SELECT COUNT(*) n, SUM(grant) ng,
 SUM(CASE WHEN v >= -100 THEN 1 ELSE 0 END) nf,
 SUM(CASE WHEN chooser IS NULL OR grant NOT IN (0,1) OR grant IS NULL
        OR v IS NULL OR month IS NULL OR ply IS NULL OR speed IS NULL
        OR rG IS NULL OR kappa IS NULL OR rd_chooser IS NULL OR rd_opponent IS NULL
        OR rating_chooser IS NULL OR rating_opponent IS NULL
        THEN 1 ELSE 0 END) missing_essential,
 MIN(month) first_month, MAX(month) last_month FROM norm''').fetchone()
 info=dict(zip(['rows','grants','competitive','missing_essential','first_month','last_month'],stat))
 if stat[0]!=expect_rows or stat[1]!=expect_grants or stat[2]!=expect_comp:
  raise ValueError('FAIL-CLOSED: sample mismatch: '+str(info)+'; expected '+
   str((expect_rows,expect_grants,expect_comp))+'; this is likely the all-source Stage07 panel, '
   'not the 41.5m POOL/NONADJACENT analysis sample')
 if stat[3]:raise ValueError('FAIL-CLOSED: missing essential observations: '+str(info))
 if (stat[4],stat[5])!=('2023-11','2025-10'):
  raise ValueError('FAIL-CLOSED: panel date window mismatch: '+str(info))
 return info

def write_csv(path, rows, columns=None):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 rows=list(rows)
 if columns is None: columns=list(rows[0]) if rows else []
 with path.open('w',newline='') as f:
  wr=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore')
  wr.writeheader();wr.writerows(rows)

def build_base(cn,out):
 target=Path(out)/'private'/'main_norm.parquet'
 announce('25%: exporting normalized 41.5m-row sample (one pass)')
 cn.execute('COPY (SELECT * FROM norm) TO '+lit(str(target))+
            ' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 250000)')
 cn.execute('CREATE OR REPLACE VIEW base AS SELECT * FROM read_parquet('+lit(str(target))+')')
 return target

def build_b(cn,out):
 private=Path(out)/'private'; public=Path(out)/'public'
 announce('Test B: build year-one groups from earlier choices only')
 b1=private/'accounts_B_groups.parquet'
 cn.execute('''CREATE OR REPLACE TEMP VIEW b1_sum AS
 SELECT chooser,
 SUM(CASE WHEN v>=-100 THEN 1 ELSE 0 END) AS n_comp,
 SUM(CASE WHEN v<=-300 THEN 1 ELSE 0 END) AS n_lost,
 SUM(CASE WHEN v>=-100 THEN grant ELSE 0 END) AS y_comp,
 SUM(CASE WHEN v<=-300 THEN grant ELSE 0 END) AS y_lost
 FROM base WHERE month BETWEEN '2023-11' AND '2024-10'
 GROUP BY chooser''')
 q='''SELECT chooser, n_comp, n_lost, y_comp, y_lost,
 CASE WHEN y_comp>0 AND y_lost=0 THEN 'CO'
      WHEN y_comp>0 AND y_lost>0 THEN 'BOTH'
      WHEN y_comp=0 AND y_lost>0 THEN 'LO' ELSE 'NEI' END AS grp
 FROM b1_sum WHERE n_comp>=4 AND n_lost>=4'''
 cn.execute('COPY ('+q+') TO '+lit(str(b1))+' (FORMAT PARQUET, COMPRESSION ZSTD)')
 counts=cn.execute('''SELECT grp, COUNT(*) accounts_p1,
 SUM(n_comp) p1_comp_opportunities,SUM(n_lost) p1_lost_opportunities,
 SUM(y_comp) p1_comp_grants,SUM(y_lost) p1_lost_grants
 FROM read_parquet('''+lit(str(b1))+''') GROUP BY grp ORDER BY grp''').fetchdf()
 counts.to_csv(public/'tabB1_group_sizes.csv',index=False)
 p2=private/'P2_competitive_after10_sorted.parquet'
 announce('Test B: exporting year-two competitive choice records, sorted by chooser')
 qry='''SELECT b.chooser,b.grant,b.v,b.ply,b.speed,b.month,b.rG,b.kappa,
 b.rd_chooser,b.rd_opponent,b.clock_chooser,b.clock_opponent,
 b.rating_chooser,b.rating_opponent,g.grp,
 CASE WHEN b.ply<=20 THEN '11-20'
      WHEN b.ply<=40 THEN '21-40'
      WHEN b.ply<=80 THEN '41-80' ELSE '81+' END AS stage,
 (b.rating_opponent-b.rating_chooser) AS gap
 FROM base b JOIN read_parquet('''+lit(str(b1))+''') g USING(chooser)
 WHERE b.month BETWEEN '2024-11' AND '2025-10' AND b.v>=-100 AND b.ply>10
 ORDER BY b.chooser'''
 cn.execute('COPY ('+qry+') TO '+lit(str(p2))+
            ' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 200000)')
 p2_summary=cn.execute('''SELECT grp,COUNT(*) p2_comp_after10_opportunities,
 COUNT(DISTINCT chooser) p2_active_accounts,SUM(grant) p2_grants,
 100.0*AVG(grant) p2_grant_rate_pp
 FROM read_parquet('''+lit(str(p2))+''') GROUP BY grp ORDER BY grp''').fetchdf()
 # Retention is conditional on at least one P2 competitive AFTER ply 10; clearly labeled.
 p2_summary=p2_summary.merge(counts[['grp','accounts_p1']],on='grp',how='left')
 p2_summary['p2_comp_after10_retention']=p2_summary.p2_active_accounts/p2_summary.accounts_p1
 p2_summary.to_csv(public/'tabB1_P2_retention.csv',index=False)
 if len(p2_summary)!=4:raise ValueError('All four B groups required for a joint model')
 return p2,p2_summary

def fetch_complete_account_batches(cn,p2,rows_per_chunk=50):
 """Yield DataFrames preserving entire account groups across DuckDB chunks."""
 q='SELECT * FROM read_parquet('+lit(str(p2))+') ORDER BY chooser'
 cur=cn.execute(q)
 carry=None
 while True:
  df=cur.fetch_df_chunk(vectors_per_chunk=rows_per_chunk)
  if len(df)==0:
   if carry is not None and len(carry)>0:yield carry
   break
  if carry is not None:
   df=pd.concat([carry,df],ignore_index=True)
   carry=None
  last=df['chooser'].iloc[-1]
  boundary=len(df)-int((df['chooser'].iloc[::-1]==last).cumprod().sum())
  if boundary==0:
   carry=df
   continue
  yield df.iloc[:boundary].copy()
  carry=df.iloc[boundary:].copy()

def normal_p(est,se):
 if not math.isfinite(se) or se<=0:return float('nan')
 return math.erfc(abs(est/se)/math.sqrt(2))

def estimate_b(cn,out,p2,p2_summary):
 public=Path(out)/'public'
 months=[str(x[0]) for x in cn.execute('SELECT DISTINCT month FROM read_parquet('+lit(str(p2))+') ORDER BY month').fetchall()]
 speeds=[str(x[0]) for x in cn.execute('SELECT DISTINCT speed FROM read_parquet('+lit(str(p2))+') ORDER BY speed').fetchall()]
 _,_,labels=model_design(pd.DataFrame({
  'grp':['CO'],'rG':[0.],'v':[0.],'stage':['11-20'],'speed':[speeds[0]],'month':[months[0]],
  'kappa':[5.],'rd_chooser':[40.],'rd_opponent':[40.],
  'clock_chooser':[30.],'clock_opponent':[30.],'grant':[0]}),months,speeds)
 p=len(labels);sxx=np.zeros((p,p));sxy=np.zeros(p);n=0;ng=0
 start=time.monotonic()
 announce('50%: Test B joint within-chooser regression: normal equations')
 for block in fetch_complete_account_batches(cn,p2):
  X,y,lab=model_design(block,months,speeds)
  assert lab==labels
  xx,xy,g=within_chunk_cross_products(X,y,block.chooser.to_numpy())
  sxx+=xx;sxy+=xy;n+=len(block);ng+=g
  if n and (n%500000)<len(block):
   expected=int(p2_summary.p2_comp_after10_opportunities.sum())
   elapsed=time.monotonic()-start
   remaining=max(0,(expected-n)/max(n,1)*elapsed)
   announce(f'Test B pass1: {n:,}/{expected:,} rows, {ng:,} accounts; ETA pass1 {remaining/60:.1f} min')
 # Protect draw-payoff slopes and spline profile terms. When rare-tail
 # indicators or nuisance controls are collinear, log and omit ONLY those.
 retained,omitted=choose_within_identified(sxx,labels,
     protected=lambda name:name.startswith('beta_') or name.startswith('f_'))
 dropped=[q['regressor'] for q in omitted]
 if dropped:announce('B: redundant nuisance columns dropped: '+', '.join(dropped))
 keep=np.zeros(p,dtype=bool);keep[retained]=True
 xx=sxx[np.ix_(keep,keep)];xy=sxy[keep]
 rank=int(np.linalg.matrix_rank(xx))
 if rank<xx.shape[0]:
  # Rank of normal equations may be ill-conditioned despite original design's
  # full rank: test scale-invariant correlation instead.
  ss=np.sqrt(np.maximum(1e-30,np.diag(xx)))
  rnk=int(np.linalg.matrix_rank(xx/ss[:,None]/ss[None,:],tol=1e-9))
  if rnk<xx.shape[0]:
   raise ValueError(f'FAIL-CLOSED: B adjusted Gram rank {rnk}/{xx.shape[0]}')
  rank=rnk
 betasub=np.linalg.solve(xx,xy)
 beta=np.zeros(p);beta[keep]=betasub
 announce('Test B: second streaming pass for exact chooser-cluster sandwich')
 meat=np.zeros_like(sxx);clusters=0; rows2=0; start2=time.monotonic()
 for block in fetch_complete_account_batches(cn,p2):
  X,y,_=model_design(block,months,speeds)
  mm,g=within_chunk_cluster_scores(X,y,block.chooser.to_numpy(),beta)
  meat+=mm;clusters+=g;rows2+=len(block)
  if rows2 and (rows2%500000)<len(block):
   t=time.monotonic()-start2
   remaining=max(0,(n-rows2)/max(rows2,1)*t)
   announce(f'Test B pass2: {rows2:,}/{n:,} rows, {clusters:,} clusters; ETA covariance {remaining/60:.1f} min')
 if rows2!=n:raise ValueError('Rows changed between B passes')
 if clusters!=ng:raise ValueError('Cluster count changed between regression passes')
 inv=np.linalg.inv(xx)
 vsub=(ng/(ng-1))*(inv@meat[np.ix_(keep,keep)]@inv)
 vcov=np.zeros_like(sxx)
 vcov[np.ix_(keep,keep)]=vsub
 if np.any(np.diag(vcov)<-1e-10):raise ValueError('Invalid covariance diagonal')
 write_csv(public/'tabB2_model_metadata.csv',[{'opportunities':n,'accounts':ng,'parameters':p,
 'design_rank':rank,'dropped_zero_variation_columns':';'.join(dropped),'covariance':'chooser CR0 * G/(G-1)',
 'common_stage_control':'NO: stage-by-prior-group interactions included',
 'm_g':'own P2 sample mean; fitted-standardized mean equals raw with chooser FE'}])
 results=[]
 mean_map=p2_summary.set_index('grp')['p2_grant_rate_pp'].to_dict()
 def make_row(group,name,L,rate=True):
  est=float(L@beta);se=float(math.sqrt(max(0,L@vcov@L)))
  m=float(mean_map[group]) if group in mean_map else float('nan')
  is_difference=(group=='BOTH-CO')
  row={'group':group,'estimand':name,'unit':'relative-to-own-base' if is_difference else 'pp (beta: pp per rG point)',
       'estimate_pp':float('nan') if is_difference else est,
       'se_pp':float('nan') if is_difference else se,
       'p_value':normal_p(est,se),
       'ci95_lo_pp':float('nan') if is_difference else est-1.96*se,
       'ci95_hi_pp':float('nan') if is_difference else est+1.96*se,
       'group_base_rate_pp':m,
       'proportional_estimate':est if is_difference else (est/m if rate and m>0 else float('nan')),
       'proportional_se_conditional_on_m':se if is_difference else (se/m if rate and m>0 else float('nan')),
       'proportional_ci_lo':est-1.96*se if is_difference else (est-1.96*se)/m if m>0 else float('nan'),
       'proportional_ci_hi':est+1.96*se if is_difference else (est+1.96*se)/m if m>0 else float('nan'),
       'notes':'ratio SE holds sample mean m fixed; descriptive, NOT full delta method'}
  results.append(row);return L,est,se
 vectors={}
 for g in GROUPS:
  for nm in ('beta','step100','step300','step500','stage41-80'):
   L=np.zeros(p)
   if nm=='beta':L[labels.index(f'beta_{g}_rG')]=1
   elif nm=='step100':L=f_vector(100,g,labels)-f_vector(0,g,labels)
   elif nm=='step300':L=f_vector(300,g,labels)-f_vector(100,g,labels)
   elif nm=='step500':L=f_vector(500,g,labels)-f_vector(300,g,labels)
   elif nm=='stage41-80':L[labels.index(f'stage_{g}_41-80')]=1
   vectors[g,nm]=L
   make_row(g,nm,L)
 for nm in ('beta','step100','step300','step500','stage41-80'):
  g1,g0='BOTH','CO';m1=float(mean_map[g1]);m0=float(mean_map[g0]);
  L=(vectors[g1,nm]/m1)-(vectors[g0,nm]/m0)
  make_row('BOTH-CO',f'proportional_difference_{nm}',L,rate=False)
 pd.DataFrame(results).to_csv(public/'tabB2_slopes_by_group.csv',index=False)
 # Descriptive figures are explicitly NOT covariate-adjusted.
 raw=cn.execute('''SELECT grp,
 CASE WHEN gap < -400 THEN -425 WHEN gap>=400 THEN 425
 ELSE CAST(FLOOR((gap+25)/50)*50 AS INTEGER) END AS gap_center,
 COUNT(*) n,SUM(grant) grants,100*AVG(grant) rate
 FROM read_parquet('''+lit(str(p2))+''')
 WHERE v>=-100 AND v<100
 GROUP BY grp,gap_center ORDER BY grp,gap_center''').fetchdf()
 raw.to_csv(public/'tabB3_raw_gap_profiles.csv',index=False)
 ev=cn.execute('''SELECT grp,
 CASE WHEN v<-50 THEN '1[-100,-50)' WHEN v<0 THEN '2[-50,0)'
 WHEN v<50 THEN '3[0,50)' WHEN v<=100 THEN '4[50,100]'
 WHEN v<=200 THEN '5(100,200]' WHEN v<300 THEN '6(200,300)'
 WHEN v<600 THEN '7[300,600)' ELSE '8>=600/mate' END AS bin,
 COUNT(*) n,SUM(grant) grants,100*AVG(grant) rate
 FROM read_parquet('''+lit(str(p2))+''') GROUP BY grp,bin ORDER BY grp,bin''').fetchdf()
 ev.to_csv(public/'tabB3_raw_evaluation_profiles.csv',index=False)
 try:
  import matplotlib;matplotlib.use('Agg')
  import matplotlib.pyplot as plt
  fig,axs=plt.subplots(2,1,figsize=(8.5,9),constrained_layout=True)
  for g in GROUPS:
   dat=raw[(raw.grp==g)&(raw.gap_center.between(-425,425))]
   axs[0].plot(dat.gap_center,dat.rate,marker='.',label=g)
   dat=ev[ev.grp==g]
   axs[1].plot(range(len(dat)),dat.rate,marker='.',label=g)
  axs[0].set(xlabel='Opponent minus chooser rating, 50-point bins',ylabel='Raw grant rate (%)',title='P2, roughly equal, after ply 10 — descriptive')
  axs[1].set(xlabel='Position bin (left to right: rival worse to better)',ylabel='Raw grant rate (%)',title='P2 competitive opportunities — descriptive')
  axs[0].legend();axs[1].legend();fig.savefig(public/'figB1_raw_profiles.pdf');plt.close(fig)
 except ImportError: announce('Matplotlib absent; B figure skipped; CSVs saved')
 return {'opportunities':n,'accounts':ng,'model_parameters':p,'minutes':(time.monotonic()-start)/60}

def c_cell_expr():
 # Five evaluation bins, four ply bins, five speed bins, five gap bins.
 return '''
 (CASE WHEN v<=-300 THEN 0 WHEN v < -100 THEN 1 WHEN v <=100 THEN 2
       WHEN v <300 THEN 3 ELSE 4 END)*100
 +(CASE WHEN ply<=10 THEN 0 WHEN ply<=30 THEN 1 WHEN ply<=60 THEN 2 ELSE 3 END)*25
 +(CASE speed WHEN 'ultrabullet' THEN 0 WHEN 'bullet' THEN 1 WHEN 'blitz' THEN 2
    WHEN 'rapid' THEN 3 WHEN 'classical' THEN 4 ELSE 999 END)*5
 +(CASE WHEN (rating_opponent-rating_chooser)<-200 THEN 0
        WHEN (rating_opponent-rating_chooser)<-100 THEN 1
        WHEN (rating_opponent-rating_chooser)<100 THEN 2
        WHEN (rating_opponent-rating_chooser)<200 THEN 3 ELSE 4 END)
 '''

def build_c(cn,out):
 private=Path(out)/'private';public=Path(out)/'public'
 announce('75%: Test C population cell propensities and account exposures')
 cn.execute('CREATE OR REPLACE VIEW c_rows AS SELECT chooser,month,grant,('+c_cell_expr()+') AS cell FROM base WHERE v>=-100')
 bad=cn.execute('SELECT COUNT(*) FROM c_rows WHERE cell>=500 OR cell<0').fetchone()[0]
 if bad:raise ValueError(f'Unrecognized speed or corrupted grid: {bad} competitive rows')
 cn.execute('''CREATE OR REPLACE VIEW c_rates AS
 SELECT cell,AVG(CAST(grant AS DOUBLE)) AS rate_all,
 AVG(CASE WHEN month<='2024-10' THEN CAST(grant AS DOUBLE) END) AS rate_p1,
 COUNT(*) AS n_all,SUM(grant) AS y_all FROM c_rows GROUP BY cell''')
 coverage=cn.execute('SELECT COUNT(*), SUM(CASE WHEN rate_p1 IS NULL THEN 1 ELSE 0 END) FROM c_rates').fetchone()
 if coverage[1]:raise ValueError(f'{coverage[1]} cells unsupported in year 1; do not invent a fallback')
 acct=private/'accounts_C_exposure.parquet'
 query='''SELECT c.chooser,COUNT(*) n, SUM(c.grant) y, SUM(p.rate_all) E,
 SUM(CASE WHEN c.month<='2024-10' THEN 1 ELSE 0 END) n1,
 SUM(CASE WHEN c.month<='2024-10' THEN c.grant ELSE 0 END) y1,
 SUM(CASE WHEN c.month<='2024-10' THEN p.rate_p1 ELSE 0 END) E1,
 SUM(CASE WHEN c.month>='2024-11' THEN 1 ELSE 0 END) n2,
 SUM(CASE WHEN c.month>='2024-11' THEN c.grant ELSE 0 END) y2,
 SUM(CASE WHEN c.month>='2024-11' THEN p.rate_p1 ELSE 0 END) E2
 FROM c_rows c JOIN c_rates p USING(cell)
 GROUP BY c.chooser'''
 cn.execute('COPY ('+query+') TO '+lit(str(acct))+' (FORMAT PARQUET, COMPRESSION ZSTD)')
 frame=cn.execute('SELECT * FROM read_parquet('+lit(str(acct))+') WHERE E>=0.25').fetchdf()
 if frame.empty:raise ValueError('Test C no accounts above exposure threshold')
 announce('Test C ML: gamma-Poisson and zero-inflated mixture (full-panel)')
 fit=fit_gp_zip(frame['y'].to_numpy(),frame['E'].to_numpy())
 tab=[]
 edges=[(.25,.5),(.5,1),(1,2),(2,4),(4,8),(8,16),(16,32),(32,float('inf'))]
 for lo,hi in edges:
  group=frame[(frame.E>=lo)&(frame.E<hi)]
  if not len(group):continue
  ee=group.E.to_numpy(dtype=float)
  k=fit['gp_k'];kz=fit['zip_k'];ga=fit['zip_gamma_active']
  p0gp=np.exp(-k*np.log1p(ee/k))
  p0zip=1-ga+ga*np.exp(-kz*np.log1p(ee/kz))
  tab.append({'E_bin':f'[{lo},{hi})','accounts':len(group),'mean_E':np.mean(ee),
  'observed_zero_share':float(np.mean(group.y==0)),
  'gp_predicted_zero_share':float(np.mean(p0gp)),
  'zip_predicted_zero_share':float(np.mean(p0zip))})
 write_csv(public/'tabC1_zero_share.csv',tab)
 p1=cn.execute('SELECT y1,E1,n2,y2,E2 FROM read_parquet('+lit(str(acct))+') WHERE E1>=0.25').fetchdf()
 announce('Test C ML: first-year model and genuine second-year heldout')
 fit1=fit_gp_zip(p1.y1.to_numpy(),p1.E1.to_numpy())
 heavy=p1[(p1.y1==0)&(p1.E1>=8)&(p1.n2>0)].copy()
 if len(heavy):
  e1=heavy.E1.to_numpy();e2=heavy.E2.to_numpy();n2=heavy.n2.to_numpy();
  k1=fit1['gp_k']; k2=fit1['zip_k']; gamma=fit1['zip_gamma_active']
  predgp=e2*k1/(k1+e1)
  p0=np.exp(-k2*np.log1p(e1/k2))
  postactive=gamma*p0/(1-gamma+gamma*p0)
  predzip=e2*postactive*k2/(k2+e1)
  holdout={'p1_heavy_zero_accounts_with_P2':len(heavy),'p2_opportunities':int(np.sum(n2)),
           'p2_grants':int(np.sum(heavy.y2)),
           'actual_p2_rate_percent':100*float(np.sum(heavy.y2))/float(np.sum(n2)),
           'gp_pred_p2_rate_percent':100*float(np.sum(predgp))/float(np.sum(n2)),
           'zip_pred_p2_rate_percent':100*float(np.sum(predzip))/float(np.sum(n2))}
 else:
  holdout={'p1_heavy_zero_accounts_with_P2':0,'warning':'No year-one E>=8 zero granters returned in P2'}
 write_csv(public/'tabC1_model_fit.csv',[dict({'period':'all'},**fit),dict({'period':'P1'},**fit1)])
 write_csv(public/'tabC2_P1_to_P2_forecast.csv',[holdout])
 try:
  import matplotlib;matplotlib.use('Agg')
  import matplotlib.pyplot as plt
  x=np.arange(len(tab));wid=.24
  fig,ax=plt.subplots(figsize=(10,5))
  for shift,key,name in [(-wid,'observed_zero_share','Observed'),(0,'gp_predicted_zero_share','Gamma–Poisson'),(wid,'zip_predicted_zero_share','Zero-inflated GP')]:
   ax.bar(x+shift,[z[key] for z in tab],width=wid,label=name)
  ax.set_xticks(x,[z['E_bin'] for z in tab],rotation=35)
  ax.set(xlabel='Expected grants E (population state-rate adjusted)',ylabel='Share of accounts with zero grants',title='Zero grants by opportunities; models are descriptive')
  ax.legend();fig.tight_layout();fig.savefig(public/'figC1_zero_share.pdf');plt.close(fig)
 except ImportError: announce('Matplotlib absent; C figure skipped; CSV saved')
 return {'accounts_fit':len(frame),'fit':fit,'year1_fit':fit1,'holdout':holdout}

def write_receipt(root,argv,main,summary):
 public=Path(root)/'public'
 for script in (Path(__file__),Path(__file__).with_name('methods.py')):
  (public/(script.name+'.sha256')).write_text(hashlib.sha256(script.read_bytes()).hexdigest()+'  '+script.name+'\n')
 hashes={}
 for p in sorted(public.glob('*')):
  if p.is_file():hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
 (public/'report_manifest_sha256.json').write_text(json.dumps(hashes,indent=2,sort_keys=True)+'\n')
 rc={'status':'FRAMEWORK_BC_V110_COMPLETE','utc':dt.datetime.now(dt.timezone.utc).isoformat(),
     'input_main_path':str(main),'command':argv,'summary':summary,
     'methods':'Test B holdout FE descriptive heterogeneity; Test C zero-inflation diagnostic. NO causal mechanism assignment.'}
 (Path(root)/'private'/'RUN_RECEIPT_PRIVATE.json').write_text(json.dumps(rc,indent=2,default=str)+'\n')
 (public/'SUCCESS.json').write_text(json.dumps({'status':'FRAMEWORK_BC_V110_COMPLETE',
   'input_sample_rows':summary['preflight']['rows'],'b_rows':summary['B']['opportunities'],
   'c_accounts_fit':summary['C']['accounts_fit'],
   'notice':'PRIVATE account tables are not included'},indent=2)+'\n')

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--root',default='/Volumes/XT_Pro/lichess_kindness')
 ap.add_argument('--main',help='Exact Parquet main sample path OR DuckDB database path')
 ap.add_argument('--view',help='View in DuckDB database when --main ends with .duckdb')
 ap.add_argument('--out',help='New, empty output root on XT_Pro')
 ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=int,default=11)
 ap.add_argument('--expect-rows',type=int,default=41534331)
 ap.add_argument('--expect-grants',type=int,default=570091)
 ap.add_argument('--expect-competitive',type=int,default=15207423)
 ap.add_argument('--discover',action='store_true')
 args=ap.parse_args()
 if args.discover:
  print('Candidate POOL/NONADJACENT main datasets (verify source identity before use):')
  print('\n'.join(candidate_paths(args.root)) or '(none identified automatically)');return
 if not args.main:ap.error('Use --discover, then specify --main path (never infer 41.5m from Stage07)')
 if not args.out:ap.error('--out required to protect certified outputs')
 out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
 (out/'private').mkdir();(out/'public').mkdir()
 announce('Framework B/C start: fresh immutable result root '+str(out))
 cn=connect(out,args.workers,args.memory_gb)
 try:
  aliases=create_norm(cn,args.main,args.view)
  (out/'private'/'input_columns.json').write_text(json.dumps(aliases,indent=2)+'\n')
  preflight=validate(cn,args.expect_rows,args.expect_grants,args.expect_competitive)
  announce('Preflight matched current manuscript 41.53m rows, 570,091 grants, 15.21m competitive')
  build_base(cn,out)
  p2,p2_summary=build_b(cn,out)
  b=estimate_b(cn,out,p2,p2_summary)
  c=build_c(cn,out)
  summary={'preflight':preflight,'B':b,'C':c}
  write_receipt(out,sys.argv,args.main,summary)
  announce('100%: BC COMPLETE. Public-safe results: '+str(out/'public'))
 except Exception:
  (out/'private'/'FAILED.txt').write_text(traceback.format_exc())
  announce('FAILED CLOSED. Diagnostics: '+str(out/'private'/'FAILED.txt'))
  raise
 finally:cn.close()

if __name__=='__main__':main()
