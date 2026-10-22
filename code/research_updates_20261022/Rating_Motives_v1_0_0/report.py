"""Aggregate-only reports and figures. Never exports user/game-level records."""
import csv, json, shutil, zipfile
from pathlib import Path
import numpy as np
from scipy import sparse
from common import *
from estimate import cluster_matrix,inference
from fe_core import onehot,solve,iter_blocks

def predictive_validation(con,path,work,report):
    report=Path(report)
    if path is None:
        save_json(report/'performance_validation.json',dict(status='UNSUPPORTED_HISTORY_INPUT'));return
    coverage=records(con,f"SELECT count(*) anchors,count(*) FILTER(WHERE isfinite(residual)) scored_anchors,sum(followup_30d_covered::INT) full_followup_anchors FROM {parquet(path)}")[0]
    ordered=Path(work)/'validation_sorted.parquet'
    copy_parquet(con,f"SELECT *, (CAST(substr(month,1,4) AS INT)-2023)*12+CAST(substr(month,6,2) AS INT)-11 month_idx FROM {parquet(path)} WHERE isfinite(residual) AND isfinite(dperf) ORDER BY chooser,month,speed",ordered)
    def matrix(d):
        return sparse.hstack([sparse.csr_matrix(np.column_stack([np.ones(len(d['chooser'])),d['dperf']/100])),
           onehot(d['month_idx'].astype(int),24)[:,1:],onehot(d['speed'].astype(int),6)[:,1:]],format='csr')
    S=np.zeros((30,30));b=np.zeros(30);N=G=0
    for d in iter_blocks(ordered):
        X=matrix(d);y=d['residual'];S+=(X.T@X).toarray();b+=X.T@y;N+=len(y);G+=len(np.unique(d['chooser']))
    if not N or G<2:
        save_json(report/'performance_validation.json',dict(status='INSUFFICIENT_VALIDATION_SUPPORT',**coverage));return
    C=np.zeros((1,30));C[0,1]=1;fit=solve(S,b,C);v=fit['bread']@C.T;meat=0
    for d in iter_blocks(ordered):
        X=matrix(d);u=d['residual']-X@fit['beta'];_,_,A=cluster_matrix(d['chooser']);score=A@((X@v)*u[:,None]);meat+=float((score.T@score)[0,0])
    df=N-fit['rank'];variance=meat*G/(G-1)*(N-1)/df if df>0 else np.nan
    r=inference(float((C@fit['beta'])[0]),variance,G-1) if fit['identified'][0] else dict(status='UNIDENTIFIED_TARGET')
    # Units here are percentage points of ordinary-game score residual, not concession probability.
    save_json(report/'performance_validation.json',dict(**r,**coverage,N=N,choosers=G,full_rank=fit['rank'],
      contrast='100 rating points of displayed-minus-performance; outcome is next ordinary-game score minus baseline expected score',
      expected_sign='negative',primary_family=False,account_sampling='SHA256 rating-motives-v1.1-validation|canonical_normalized_account_id; first 16 hex digits mod 10 = 0',
      selection='First eligible ordinary anchor each account/speed/month; next ordinary start after anchor completion within 30 days; no future data in predictor'))

def descriptions(con,paths,report):
    src=parquet(paths);report=Path(report)
    rows=records(con,f"""SELECT state,CASE WHEN e<.5 THEN 'below_0.50' WHEN e>.95 THEN 'above_0.95'
      ELSE printf('%.2f_to_%.2f', .5+.05*least(8,floor((e-.5+1e-12)/.05)),.55+.05*least(8,floor((e-.5+1e-12)/.05))) END e_bin,
      count(*) opportunities,sum(y) grants,count(DISTINCT chooser) choosers,100*avg(y) grant_rate_percent,
      avg(e) mean_e FROM {src} GROUP BY state,e_bin ORDER BY state,mean_e""")
    write_csv(report/'E_raw_profile.csv',rows)
    write_csv(report/'threshold_exact_and_tie_support.csv',records(con,f"""SELECT state,count(*) eligible,
      count(*) FILTER(WHERE abs(e-.75)<=1e-12) exact_threshold,
      count(*) FILTER(WHERE rating=opp_rating) equal_displayed,
      count(*) FILTER(WHERE rating=opp_rating AND abs(rg)<=1e-9) arithmetic_zero_equal_displayed,
      max(abs(rg)) FILTER(WHERE rating=opp_rating) max_abs_draw_at_equal_display FROM {src} GROUP BY state"""))
    write_csv(report/'history_linkage_by_state.csv',records(con,f"SELECT state,count(*) AS rows,count(*) FILTER(WHERE isfinite(opp_prior_count)) recipient_count_known,count(*) FILTER(WHERE isfinite(dperf) AND isfinite(peak) AND prior_count>=30) performance_peak_eligible,count(*) FILTER(WHERE isfinite(dperf) AND isfinite(peak) AND prior_count>=30 AND peak-rating>0 AND peak-rating<=20) near_peak_eligible FROM {src} GROUP BY state"))
    write_csv(report/'E_profile_estimation_support.csv',records(con,f"""WITH eligible AS (
      SELECT *,count(*) OVER(PARTITION BY chooser,state) within_n FROM {src} WHERE e>=.50 AND e<=.95)
      SELECT state,least(8,floor((e-.5+1e-12)/.05)) e_bin_code,count(*) opportunities,sum(y) grants,
      count(DISTINCT chooser) choosers,count(DISTINCT recipient) recipients,100*avg(y) grant_rate_percent
      FROM eligible WHERE within_n>=2 GROUP BY 1,2 ORDER BY 1,2"""))
    write_csv(report/'T4_distance_raw_profile.csv',records(con,f"""WITH eligible AS (
      SELECT *,peak-rating distance,count(*) OVER(PARTITION BY chooser,state) within_n
      FROM {src} WHERE isfinite(peak) AND isfinite(dperf) AND prior_count>=30)
      SELECT state,CASE WHEN distance<=0 THEN '0_at_or_above' WHEN distance<=5 THEN '1_(0,5]'
      WHEN distance<=10 THEN '2_(5,10]' WHEN distance<=20 THEN '3_(10,20]'
      WHEN distance<=40 THEN '4_(20,40]' ELSE '5_above_40' END distance_bin,
      count(*) opportunities,sum(y) grants,count(DISTINCT chooser) choosers,count(DISTINCT recipient) recipients,
      100*avg(y) grant_rate_percent FROM eligible WHERE within_n>=2 GROUP BY 1,2 ORDER BY 1,2"""))
    return rows

def figures(report,estimates,raw):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    report=Path(report);plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    for state,color,label in [(1,'#1766a1','Competitive'),(0,'#b96526','Clearly losing')]:
        rr=[r for r in raw if r['state']==state and .5<=r['mean_e']<=.95]
        axes[0].plot([r['mean_e'] for r in rr],[r['grant_rate_percent'] for r in rr],marker='o',label=label,color=color)
        er=[r for r in estimates if r.get('test')=='T5' and r.get('variant')=='profile' and r.get('state')==('competitive' if state else 'losing') and r.get('status')=='ESTIMATED']
        er.sort(key=lambda r:r['contrast'])
        xx=[.525+.05*int(r['contrast'].split('_')[-1]) for r in er]
        yy=[r['estimate_pp'] for r in er]
        axes[1].errorbar(xx,yy,yerr=[[r['estimate_pp']-r['ci_low_pp'] for r in er],[r['ci_high_pp']-r['estimate_pp'] for r in er]],fmt='o-',color=color,label=label,capsize=2)
    axes[0].set_ylabel('Observed grant rate (%)');axes[1].set_ylabel('Adjusted difference from E ∈ [0.70, 0.75) (pp)')
    axes[0].set_title('Age-known linked sample');axes[1].set_title('Chooser effects and specified controls')
    for ax in axes:ax.set_xlabel('Effective expected score E');ax.axvline(.75,color='#666666',ls='--',lw=.8);ax.legend(frameon=False)
    axes[1].axhline(0,color='#666666',lw=.8);fig.tight_layout();fig.savefig(report/'E_profiles.png',dpi=180);fig.savefig(report/'E_profiles.pdf');plt.close(fig)

def summary(report,primary,differences,identity,has_history):
    report=Path(report)
    lines=['# Rating motives — local run report','',
      'Results below come from this run only. The bundled prior Patron estimates are previously completed evidence, not rerun estimates.','',
      '| Test | Status | Estimate (pp) | 95% CI (pp) | Raw p | Holm p (5) |',
      '|---|---|---:|---|---:|---:|']
    for r in primary:
        fmt=lambda k: f"{r[k]:.4g}" if r.get(k) is not None else '—'
        ci=f"[{fmt('ci_low_pp')}, {fmt('ci_high_pp')}]" if r.get('status')=='ESTIMATED' else '—'
        lines.append(f"| {r['test']} | {r['status']} | {fmt('estimate_pp')} | {ci} | {fmt('p_value')} | {fmt('p_holm_5')} |")
    lines+=['','Unsupported coefficients enter the five-test adjustment as p = 1. No missing estimate is treated as a null finding.',
      '', '## What ran and what remains', '',
      ('Authenticated enriched history was supplied; see feature coverage and support for which coefficients were estimable.' if has_history else
       'Enriched completed-game history was not supplied. T1/T2 no-count diagnostics are secondary and do not fulfill their primary specifications. T3/T4 and predictive validation remain pending. T5 runs only if effective-E/payoff validation passes.'),
      '', 'The sample requires a known account-creation date and at least 365 days of age at game start. Profile acquisition was outcome-selected. These are associations in the linked sample; chooser fixed effects do not repair that selection.',
      '', 'T6 responsibility remains under its separate frozen plan. Previous recipient-Patron evidence is copied to `prior_recipient_patron_estimates.csv` with its original inference and scope. T7 casual-game acquisition is deferred.',
      '', '## Reading the evidence', '',
      'Report each coefficient and interval before interpreting a motive. An insignificant estimate does not establish zero. Practical equivalence uses a separate five-test Holm family with ±0.10 pp margins. Competitive-minus-losing differences use joint covariance; clearly losing is a state comparison, not an automatic placebo.',
      '', 'Pure minimum rating movement has no ordinal K effect; its sharp action boundary is E = 0.75. A correction motive has no universal cutoff independent of perceived misrating. The observed peak-crossing coefficient is a conditional association, not a causal discontinuity.',
      '', 'The E figure shows raw rates and adjusted bin contrasts. The threshold regression uses unbinned E. Activity, flag visibility, country pulls, moderation and engine responsibility analyses are outside this package.',
      '', '## Audit and privacy', '',
      'Input sources are read only. The certified 41,534,331-row pool frame and profile sources are checksum checked. This report ZIP contains aggregate tables, methods and executed code only. Prepared rows, usernames, game IDs and cluster scores stay in the PRIVATE output tree.',
      '', f'Run identity: `{identity}`','']
    atomic_text(report/'SUMMARY.md','\n'.join(lines))
    predictions={'T1':'Recipient rating benefit: positive under the narrow rating-point-benefit channel; no direct role in restricted own-only models.',
                 'T2':'No ordinal K effect for pure minimum movement; signs depend on cardinal/noisy or own-opportunity-cost model.',
                 'T3':'Positive if performance discrepancy measures perceived overrating and other paths are controlled.',
                 'T4':'Negative under a positive personal-record bonus; no extra peak term in pure correction after conditioning.',
                 'T5':'Negative jump for sharp deterministic minimum movement, no universal fixed cutoff for correction.'}
    write_csv(report/'predictions_vs_results.csv',[dict(test=r['test'],prediction=predictions[r['test']],status=r['status'],
       observed_sign=('positive' if r['estimate_pp']>0 else 'negative' if r['estimate_pp']<0 else 'zero') if r.get('estimate_pp') is not None else 'not estimated',
       estimate_pp=r.get('estimate_pp'),ci_low_pp=r.get('ci_low_pp'),ci_high_pp=r.get('ci_high_pp')) for r in primary])

def package_report(report,destination,identity):
    report=Path(report);destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    code=report/'executed_code';code.mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'PACKAGE_MANIFEST.json').read_text())
    for name in manifest['sha256']:
        p=code/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,p)
    shutil.copy2(ROOT/'PACKAGE_MANIFEST.json',code/'PACKAGE_MANIFEST.json')
    sums=[]
    for p in sorted(report.rglob('*')):
        if p.is_file() and p.name!='REPORT_SHA256SUMS.txt':sums.append(sha256_file(p)+'  '+str(p.relative_to(report)))
    atomic_text(report/'REPORT_SHA256SUMS.txt','\n'.join(sums)+'\n')
    output=destination/f'Rating_Motives_RESULTS_{identity[:12]}.zip';tmp=output.with_suffix('.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(report.rglob('*')):
            if p.is_file():z.write(p,'Rating_Motives_RESULTS_'+identity[:12]+'/'+str(p.relative_to(report)))
    tmp.replace(output);atomic_text(Path(str(output)+'.sha256'),sha256_file(output)+'  '+output.name+'\n')
    return output
