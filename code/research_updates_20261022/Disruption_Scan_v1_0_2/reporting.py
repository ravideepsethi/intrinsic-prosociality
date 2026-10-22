"""Episode diagnostics and aggregate-only report. No kindness coefficients."""
import csv as csvlib
from pathlib import Path
import numpy as np,pandas as pd
from support import *
from detector import baseline

def episode_windows(episodes):
 rows=[]
 for e in episodes:
  t=START+e['minute_index']*MINUTE;h=e['width_minutes']//2
  rows.append(dict(episode_id=e['episode_id'],t=t,lo=t-60*MINUTE,hi=t+61*MINUTE,peak_lo=t-h*MINUTE,peak_hi=t+(h+1)*MINUTE,screen_series=e['series']))
 return pd.DataFrame(rows,columns=['episode_id','t','lo','hi','peak_lo','peak_hi','screen_series'])

def diagnostics(root,episodes,summaries,workers,memory,project,with_main=True,cache_root=None):
 root=Path(root);pub=root/'public';pub.mkdir(exist_ok=True);win=episode_windows(episodes)
 if win.empty:return []
 c=connect(root/'diagnostics',workers,memory)
 try:
  c.register('windows',win);events=[Path(cache_root or root)/'api'/r['month']/'events.parquet' for r in summaries]
  c.execute('CREATE OR REPLACE VIEW events AS SELECT * FROM '+parq(events))
  where=' OR '.join(f'(t>={r.lo} AND t<{r.hi})' for r in win.itertuples())
  with heartbeat('Collecting candidate episode diagnostics'):
   copy(c,f'''SELECT w.episode_id,w.t AS center,w.peak_lo,w.peak_hi,w.screen_series,e.*
      FROM (SELECT * FROM events WHERE {where}) e JOIN windows w ON e.t>=w.lo AND e.t<w.hi''',root/'diagnostics/context_events_PRIVATE.parquet')
   c.execute('CREATE OR REPLACE VIEW near AS SELECT * FROM '+parq([root/'diagnostics/context_events_PRIVATE.parquet']))
   c.execute("CREATE OR REPLACE VIEW peak AS SELECT * FROM near WHERE t>=peak_lo AND t<peak_hi AND (screen_series='all' OR speed=screen_series)")
   csv(c,'''SELECT episode_id,(floor((t-center)/60000.0))::INTEGER minute_offset,
      speed,status,fold,count(*) n FROM near GROUP BY ALL ORDER BY ALL''',pub/'episode_context_counts.csv')
   csv(c,'''SELECT episode_id,floor((t-center)/10000.0)::INTEGER ten_second_offset,
      status,fold,count(*) n FROM near WHERE t>=center-300000 AND t<center+360000
      GROUP BY ALL ORDER BY ALL''',pub/'episode_ten_second_counts.csv')
   csv(c,'''SELECT episode_id,fold,count(*) games,count(DISTINCT white) white_accounts,
      count(DISTINCT black) black_accounts,count(DISTINCT least(white,black)||'|'||greatest(white,black)) distinct_pairs,
      count(*) FILTER(WHERE t%1000=0) timestamps_on_second,count(*) FILTER(WHERE t%60000=0) timestamps_on_minute,
      quantile_cont((t-start_ms)/1000.0,[.1,.5,.9]) recorded_duration_seconds
      FROM peak GROUP BY episode_id,fold ORDER BY episode_id,fold''',pub/'episode_timestamp_and_pair_audit.csv')
   # Account-disjoint folds are deterministic across every game and both colors.
   account='SELECT episode_id,fold,white AS account FROM peak WHERE white IS NOT NULL UNION ALL SELECT episode_id,fold,black AS account FROM peak WHERE black IS NOT NULL'
   c.execute('CREATE OR REPLACE TEMP VIEW account_counts AS SELECT episode_id,fold,account,count(*) n FROM ('+account+') GROUP BY ALL')
   csv(c,'''SELECT episode_id,fold,count(*) distinct_accounts,max(n) largest_account_game_count
      FROM account_counts GROUP BY episode_id,fold ORDER BY episode_id,fold''',pub/'episode_account_support.csv')
   df=c.execute('''WITH a AS (SELECT episode_id,fold,count(*) distinct_accounts,max(n) largest_account_game_count FROM account_counts GROUP BY episode_id,fold),
     g AS (SELECT episode_id,fold,count(*) games FROM peak GROUP BY episode_id,fold),
     q AS (SELECT episode_id,fold,max(n) max_identical_timestamp_count FROM (SELECT episode_id,fold,t,count(*) n FROM peak GROUP BY episode_id,fold,t) GROUP BY episode_id,fold)
     SELECT g.*,a.distinct_accounts,a.largest_account_game_count,q.max_identical_timestamp_count
     FROM g LEFT JOIN a USING(episode_id,fold) LEFT JOIN q USING(episode_id,fold)''').fetchdf()
   rows=[]
   for e in episodes:
    r=dict(e)
    for fold,label in [(0,'discovery'),(1,'validation')]:
     a=df[(df.episode_id==e['episode_id'])&(df.fold==fold)]
     if len(a):
      v=a.iloc[0];r[label+'_screen_accounts']=int(v.distinct_accounts);r[label+'_screen_games']=int(v.games)
      r[label+'_largest_account_share']=float(v.largest_account_game_count/v.games)
      r[label+'_identical_timestamp_share']=float(v.max_identical_timestamp_count/v.games)
    r['account_concentration_flag']=bool(r.get('discovery_largest_account_share',1)>.05 or r.get('validation_largest_account_share',1)>.05)
    r['candidate_minute_utc']=utc(START+r['minute_index']*MINUTE)
    r['screen_window_start_utc']=utc(START+(r['minute_index']-r['width_minutes']//2)*MINUTE)
    r['screen_window_end_exclusive_utc']=utc(START+(r['minute_index']+r['width_minutes']//2+1)*MINUTE)
    r['externally_verified_outage']=False
    rows.append(r)
  main_status={'status':'NOT_REQUESTED'}
  if with_main:
   contract=read(PKG/'evidence/main_panel_contract.json');files=[]
   main_status={'status':'UNAVAILABLE'}
   if all((Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'/e['relative_path']).is_file() for e in contract['panel_outputs']):
    with heartbeat('Checking main-panel diagnostic overlay'):
     checks=[]
     for e in contract['panel_outputs']:
      p=Path(project)/'derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'/e['relative_path']
      if p.stat().st_size!=e['size_bytes'] or pq.ParquetFile(p).metadata.num_rows!=e['rows'] or sha(p)!=e['sha256']:raise RuntimeError('Main overlay differs from certified input')
      files.append(p);checks.append(dict(path=str(p),sha256=e['sha256']))
     js(root/'diagnostics/main_inputs_PRIVATE.json',checks)
     c.execute('CREATE OR REPLACE VIEW main AS SELECT game_id,api_last_move_at_ms AS t,fair_competitive,clearly_worse,chooser_clock_last_obs_s,disconnected_clock_last_obs_s FROM '+parq(files))
     csv(c,'''SELECT w.episode_id,count(*) main_sample_choices,
        sum(fair_competitive::BIGINT) competitive_choices,sum(clearly_worse::BIGINT) clearly_worse_choices,
        median(chooser_clock_last_obs_s) chooser_clock_median_s,
        median(disconnected_clock_last_obs_s) disconnected_clock_median_s
        FROM main m JOIN windows w ON m.t>=w.peak_lo AND m.t<w.peak_hi GROUP BY w.episode_id ORDER BY w.episode_id''',pub/'main_sample_choice_availability.csv')
     main_status={'status':'AUTHENTICATED_DIAGNOSTIC_OVERLAY','no_kindness_outcomes_read':True}
  js(pub/'main_overlay_status.json',main_status);return rows
 finally:c.close()

def plot_episodes(pub,episodes,counts,all_counts,all_speeds,starts,valid,traffic,baseline_mode):
 import matplotlib;matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 pub=Path(pub);plots=pub/'figures';plots.mkdir(exist_ok=True);cache={};contexts=[]
 startbase=baseline(np.nan_to_num(starts),np.isfinite(starts),1,None)
 for e in episodes:
  i=e['minute_index'];ii=np.arange(max(0,i-60),min(len(valid),i+61));x=ii-i;key=(e['series'],e['width_minutes'])
  if key not in cache:cache[key]=[baseline(counts[key[0]][f],valid,key[1],traffic) for f in (0,1)]
  b=cache[key];fig,axs=plt.subplots(4,1,figsize=(10,10),sharex=True,layout='constrained')
  for f,label,col in [(0,'Discovery accounts','#1d6395'),(1,'Validation accounts','#d46b2c')]:
   axs[0].plot(x,b[f]['count'][ii],label=label,color=col,lw=1.5)
   axs[0].plot(x,b[f]['expected'][ii],color=col,ls='--',alpha=.65,label=label+' baseline')
  axs[0].set_ylabel(f'Games / {e["width_minutes"]} min');axs[0].legend(fontsize=8,ncol=2)
  axs[0].set_title(f'{e["episode_id"]}   {e["candidate_minute_utc"]}   |   screening series: {e["series"]}\nCandidate disruption; last-move proxy, not a verified disconnect time',fontsize=11)
  for j,label in enumerate(['timeout: recorded claim/draw resolution','outoftime: clock expiration']):axs[1].plot(x,all_counts[j,ii],label=label)
  axs[1].set_ylabel('All groups / min');axs[1].legend(fontsize=8)
  if np.isfinite(starts[ii]).any():
   axs[2].plot(x,starts[ii],label='Archived real-time game starts',color='#343434')
   axs[2].plot(x,startbase['expected'][ii],label='Same-time weekly baseline',color='#8e8e8e',ls='--');axs[2].legend(fontsize=8)
  else:
   axs[2].text(.5,.5,'Game-start chronology unavailable for this episode',ha='center',va='center',transform=axs[2].transAxes,color='#555555');axs[2].set_yticks([])
  axs[2].set_ylabel('Starts / min')
  for s in SPEEDS:axs[3].plot(x,all_speeds[s][ii],label=s)
  axs[3].set_ylabel('All groups / min');axs[3].legend(fontsize=8,ncol=5);axs[3].set_xlabel('Minutes relative to candidate minute (UTC)')
  for ax in axs:ax.axvline(0,color='grey',lw=.7);ax.grid(alpha=.15);ax.spines[['top','right']].set_visible(False)
  fig.savefig(plots/(e['episode_id']+'.png'),dpi=150);plt.close(fig)
  for k,j in enumerate(ii):
   contexts.append(dict(episode_id=e['episode_id'],minute_offset=int(x[k]),utc=utc(START+int(j)*MINUTE),
    discovery_count=b[0]['count'][j],discovery_baseline=b[0]['expected'][j],validation_count=b[1]['count'][j],validation_baseline=b[1]['expected'][j],
    timeout_count=all_counts[0,j],outoftime_count=all_counts[1,j],archived_starts=starts[j],starts_baseline=startbase['expected'][j],baseline_mode=baseline_mode))
 pd.DataFrame(contexts).to_csv(pub/'episode_plot_data.csv',index=False)

def review_text(pub,episodes,coverage,baseline_mode,issues):
 pub=Path(pub)
 columns=['episode_id','candidate_minute_utc','series','width_minutes','discovery_count','discovery_expected','discovery_score','discovery_ratio','validation_count','validation_expected','validation_score','validation_ratio','replicates_in_disjoint_accounts','account_concentration_flag','externally_verified_outage']
 d=pd.DataFrame(episodes)
 if d.empty:d=pd.DataFrame(columns=columns)
 d.to_csv(pub/'ranked_candidates.csv',index=False)
 pd.DataFrame([dict(episode_id=e['episode_id'],candidate_minute_utc=e['candidate_minute_utc'],independent_incident_source='',incident_start_utc='',incident_end_utc='',scope='',chooser_able_to_act='',review_decision='',review_notes='') for e in episodes],columns=['episode_id','candidate_minute_utc','independent_incident_source','incident_start_utc','incident_end_utc','scope','chooser_able_to_act','review_decision','review_notes']).to_csv(pub/'incident_review_template.csv',index=False)
 usable=[r['month'] for r in coverage if r.get('coverage_usable')]
 text=f'''# Disruption candidate screen

Computational result: {len(episodes)} ranked candidate episodes. None is automatically classified as a verified outage.

Usable completed API months: {', '.join(usable) or 'none'}.
Baseline mode: {baseline_mode}.

Read ranked_candidates.csv, then figures/E001.png and the subsequent episode plots. The order is frozen using discovery-account counts only. Validation uses games between a disjoint set of accounts; cross-group games enter diagnostics only. Neither draw outcomes, rating payoffs, nor later kindness enter detection.

Scores are robust anomaly scores, not statistical significance tests. Many minutes, speeds and scales are searched. The validation flag identifies temporal replication in disjoint accounts, not a causal mechanism or an independently verified outage. A technical artifact shared by both groups could also replicate. Concentration and timestamp flags require review.

The source frame contains upstream API-enriched time-forfeit candidates, including ordinary clock expirations. It is not a census of physical disconnections. Aborted, resumed, unrecorded, and sub-five-second games may be missing. Only saved, completed canonical months with sufficient timing/account quality are screened. Missing coverage is never filled as zero traffic. Seven days following a source gap are excluded from detection to protect against games crossing month boundaries.

The timestamp is raw API lastMoveAt, not a certified connection-loss or claim-click time. A visible burst could precede an outage; eventual endings can be delayed. Ten-second counts are diagnostic only. Recorded game starts are a traffic proxy, not an exact risk set of concurrent games.

The optional main-panel overlay reports whether actual choice opportunities exist near an episode. It does not report kindness rates. Its clock summaries cover that selected main sample, not the broader API population. This package estimates no treatment effect, warrant, involuntary-exit probability, or transmission multiplier.

Next: review independent incident evidence for the strongest candidates and establish whether one player could still act. Then decide which episodes define a defensible sample for studying selection into disconnection. No prediction that generosity must increase or that board position should cease to matter is built into this scan.

'''
 if episodes:
  text+='| Episode | UTC candidate minute | Series | Discovery ratio | Validation ratio | Replicates |\n|---|---|---|---:|---:|---|\n'
  for e in episodes:text+=f'| {e["episode_id"]} | {e["candidate_minute_utc"]} | {e["series"]} | {e["discovery_ratio"]:.2f} | {e["validation_ratio"]:.2f} | {e["replicates_in_disjoint_accounts"]} |\n'
 else:text+='No episodes met the prespecified detection thresholds. This does not prove that no outages occurred.\n'
 (pub/'READ_RESULTS.md').write_text(text)
