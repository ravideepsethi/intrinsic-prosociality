"""Outcome-blind exploratory anomaly screen. Scores are NOT p-values."""
from __future__ import annotations
import warnings
import numpy as np,pandas as pd
from support import *

# Fixed before inspecting real incident counts or kindness.
THRESHOLDS=dict(score=8.0,ratio=2.5,excess=50,min_count=100,validation_score=4.0,validation_ratio=1.5,validation_excess=20)
WINDOWS=(1,5)
REFERENCES=(-28,-21,-14,-7,7,14,21,28)

def trailing(x,width):
 cs=np.r_[0.,np.cumsum(np.asarray(x,float))];out=np.full(len(x),np.nan)
 out[width-1:]=cs[width:]-cs[:-width];return out

def centered(x,width):
 if width%2!=1:raise ValueError('Odd windows only')
 v=trailing(x,width);out=np.full(len(v),np.nan);h=width//2
 if h:out[h:len(v)-h]=v[2*h:]
 else:out=v
 return out

def before_traffic(x):
 # Minutes [t-60,t-10); avoids normalizing by a contemporaneous collapse in starts.
 x=np.asarray(x,float);cs=np.r_[0.,np.cumsum(np.nan_to_num(x))];missing=np.r_[0,np.cumsum(~np.isfinite(x))]
 out=np.full(len(x),np.nan);i=np.arange(60,len(x));valid=missing[i-10]==missing[i-60]
 out[i[valid]]=cs[i[valid]-10]-cs[i[valid]-60];return out

def baseline(counts,valid,width,traffic=None):
 y=centered(counts,width);eligible=np.asarray(valid,bool).copy();eligible &= centered(valid.astype(float),width)==width
 ref=np.full((len(REFERENCES),len(y)),np.nan)
 for k,day in enumerate(REFERENCES):
  shift=day*1440;dst=np.arange(max(0,-shift),min(len(y),len(y)-shift));src=dst+shift
  ok=eligible[src]
  values=y[src].copy()
  if traffic is not None:
   ok &= np.isfinite(traffic[src]) & np.isfinite(traffic[dst]) & (traffic[src]>=100) & (traffic[dst]>=100)
   ratio=traffic[dst]/np.maximum(traffic[src],1)
   # Large traffic changes are not extrapolated into a baseline.
   ok &= (ratio>=.25)&(ratio<=4);values*=ratio
  ref[k,dst[ok]]=values[ok]
 with warnings.catch_warnings():
  warnings.simplefilter('ignore',RuntimeWarning)
  expected=np.nanmedian(ref,axis=0);mad=np.nanmedian(abs(ref-expected),axis=0)
 nref=np.isfinite(ref).sum(axis=0);eligible &= nref>=4
 sd=np.maximum(np.sqrt(np.maximum(expected,0)+1),1.4826*mad)
 score=(y-expected)/sd;ratio=y/np.maximum(expected,5)
 score[~eligible]=np.nan;ratio[~eligible]=np.nan
 return dict(count=y,expected=expected,score=score,ratio=ratio,excess=y-expected,nref=nref,eligible=eligible)

def find_seeds(counts,valid,traffic=None,thresholds=None):
 th=thresholds or THRESHOLDS;out=[]
 for width in WINDOWS:
  for series,x in counts.items():
   if not np.any(x[0]):continue
   b=baseline(x[0],valid,width,traffic)
   hit=b['eligible']&(b['score']>=th['score'])&(b['ratio']>=th['ratio'])&(b['excess']>=th['excess'])&(b['count']>=th['min_count'])
   for i in np.flatnonzero(hit):
    out.append(dict(minute_index=int(i),series=series,width_minutes=width,
      discovery_count=float(b['count'][i]),discovery_expected=float(b['expected'][i]),
      discovery_score=float(b['score'][i]),discovery_ratio=float(b['ratio'][i]),discovery_excess=float(b['excess'][i]),reference_windows=int(b['nref'][i])))
 return sorted(out,key=lambda r:(-r['discovery_score'],-r['discovery_excess'],r['minute_index'],r['series'],r['width_minutes']))

def select_episodes(seeds,top=30,separation=30):
 out=[]
 for r in seeds:
  if any(abs(r['minute_index']-x['minute_index'])<=separation for x in out):continue
  out.append(dict(r,episode_id=f'E{len(out)+1:03d}'))
  if len(out)>=top:break
 return out

def validate(episodes,counts,valid,traffic=None,thresholds=None):
 th=thresholds or THRESHOLDS;cache={};out=[]
 for event in episodes:
  key=(event['series'],event['width_minutes'])
  if key not in cache:cache[key]=baseline(counts[key[0]][1],valid,key[1],traffic)
  b=cache[key];i=event['minute_index'];r=dict(event)
  for name in ('count','expected','score','ratio','excess','nref'):r['validation_'+name]=float(b[name][i])
  r['replicates_in_disjoint_accounts']=bool(b['eligible'][i] and b['score'][i]>=th['validation_score'] and b['ratio'][i]>=th['validation_ratio'] and b['excess'][i]>=th['validation_excess'])
  out.append(r)
 return out

def grid(months):
 n=(END-START)//MINUTE;valid=np.zeros(n,bool)
 for m in months:
  a,b=bounds(m);valid[(a-START)//MINUTE:(b-START)//MINUTE]=True
 # Require seven days of complete source creation-month coverage for crossing games.
 # LastMoveAt-start is bounded at seven days in the audited projection.
 valid=trailing(valid.astype(float),7*1440+1)==7*1440+1
 return valid

def assemble(root,summaries):
 n=(END-START)//MINUTE;counts={s:np.zeros((2,n),np.int64) for s in ['all']+SPEEDS};all_counts=np.zeros((2,n),np.int64)
 all_speeds={s:np.zeros(n,np.int64) for s in SPEEDS}
 good=[r['month'] for r in summaries if r['coverage_usable']]
 for r in summaries:
  p=Path(root)/'api'/r['month']/'minute_counts.parquet';d=pd.read_parquet(p);idx=d.minute.to_numpy(np.int64)-START//MINUTE
  for si,status in enumerate(('timeout','outoftime')):
   mask=d.status.eq(status).to_numpy();np.add.at(all_counts[si],idx[mask],d.n.to_numpy(np.int64)[mask])
  for speed in SPEEDS:
   sm=d.speed.eq(speed).to_numpy();np.add.at(all_speeds[speed],idx[sm],d.n.to_numpy(np.int64)[sm])
   for fold in (0,1):
    use=sm&d.fold.eq(fold).to_numpy();np.add.at(counts[speed][fold],idx[use],d.n.to_numpy(np.int64)[use])
 for s in SPEEDS:counts['all']+=counts[s]
 starts=np.full(n,np.nan)
 for m in good:
  p=Path(root)/'traffic'/m/'starts.parquet'
  if not p.is_file():continue
  d=pd.read_parquet(p);a,b=bounds(m);starts[(a-START)//MINUTE:(b-START)//MINUTE]=0
  use=d.speed.isin(SPEEDS);np.add.at(starts,d.minute[use].to_numpy(np.int64)-START//MINUTE,d.n[use].to_numpy(np.int64))
 valid=grid(good);return counts,all_counts,all_speeds,starts,valid
