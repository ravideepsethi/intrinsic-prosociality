"""Payoff accounting and recipient-side current-Patron association."""
from pathlib import Path
import json, math
import numpy as np
from common import *

def payoff_audit(inputs,root,workers,memory):
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    c=connection(root,workers,memory);view_panel(c,inputs)
    require(c,'panel',['chooser_draw_payoff_v2','chooser_win_payoff_v2','chooser_win_premium_v2','chooser_elo','disconnected_elo','chooser_color','white_rating_diff_pgn','black_rating_diff_pgn','timeout_chooser_win'])
    c.execute('''CREATE OR REPLACE VIEW pay AS SELECT *,
       chooser_draw_payoff_v2 AS rg,chooser_win_payoff_v2 AS rc,chooser_win_premium_v2 AS kappa,
       disconnected_elo-chooser_elo AS opponent_minus_chooser_gap,
       CASE WHEN chooser_color='white' THEN white_rating_diff_pgn ELSE black_rating_diff_pgn END AS observed_delta,
       CASE WHEN kind_draw THEN chooser_draw_payoff_v2 WHEN timeout_chooser_win THEN chooser_win_payoff_v2 END AS predicted_delta
       FROM panel''')
    q='''SELECT count(*) n,count(*) FILTER(WHERE isfinite(rg) AND isfinite(rc) AND isfinite(kappa)) finite_rows,
       count(*) FILTER(WHERE isfinite(kappa) AND kappa<=0) nonpositive_premium,
       max(abs((rc-rg)-kappa)) identity_max_error,
       count(*) FILTER(WHERE abs((rc-rg)-kappa)>1e-7) identity_errors,
       count(*) FILTER(WHERE rg>0 AND kappa>0) positive_draw_but_costly_vs_claim,
       min(kappa) min_kappa,median(kappa) median_kappa,max(kappa) max_kappa FROM pay'''
    a=c.execute(q).fetchdf().to_dict('records')[0];js(pub/'payoff_identity.json',a)
    if a['identity_errors'] or a['nonpositive_premium']:raise RuntimeError('Reconstructed payoff identities failed; see payoff_identity.json')
    csv(c,'''SELECT month,count(*) n,avg(rg) mean_draw_payoff,avg(rc) mean_claim_payoff,avg(kappa) mean_sacrifice,
       quantile_cont(kappa,.1) premium_p10,median(kappa) premium_p50,quantile_cont(kappa,.9) premium_p90,
       100*avg(kind_draw::DOUBLE) kindness_pct FROM pay GROUP BY month ORDER BY month''',pub/'payoffs_by_month.csv')
    csv(c,'''SELECT CASE WHEN fair_competitive THEN 'competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'middle' END board_group,
       50*floor(opponent_minus_chooser_gap/50.0) gap_left,50*floor(opponent_minus_chooser_gap/50.0)+50 gap_right,
       count(*) n,avg(opponent_minus_chooser_gap) mean_gap,avg(rg) mean_draw_payoff,avg(rc) mean_claim_payoff,
       avg(kappa) mean_sacrifice,100*avg(kind_draw::DOUBLE) kindness_pct
       FROM pay WHERE opponent_minus_chooser_gap BETWEEN -600 AND 599
       GROUP BY 1,2,3 ORDER BY 1,2''',pub/'payoffs_and_kindness_by_gap.csv')
    csv(c,'''SELECT CASE WHEN kind_draw THEN 'draw' ELSE 'claim' END AS action_type,count(*) n,
       avg(predicted_delta-observed_delta) mean_signed_error,avg(abs(predicted_delta-observed_delta)) mean_abs_error,
       quantile_cont(abs(predicted_delta-observed_delta),.5) abs_error_p50,
       quantile_cont(abs(predicted_delta-observed_delta),.9) abs_error_p90,
       quantile_cont(abs(predicted_delta-observed_delta),.99) abs_error_p99,
       avg((abs(predicted_delta-observed_delta)<=1)::DOUBLE) within_one_rating_point
       FROM pay WHERE (kind_draw OR timeout_chooser_win) AND isfinite(predicted_delta) AND observed_delta IS NOT NULL
       GROUP BY 1''',pub/'observed_update_validation.csv')
    csv(c,'''SELECT count(*) n,count(*) FILTER(WHERE kind_draw OR timeout_chooser_win) comparable_action_rows,
       count(*) FILTER(WHERE (kind_draw OR timeout_chooser_win) AND observed_delta IS NOT NULL AND isfinite(predicted_delta)) validated_rows,
       count(*) FILTER(WHERE observed_delta IS NULL) missing_observed_update_rows FROM pay''',pub/'validation_coverage.csv')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pandas as pd
    d=pd.read_csv(pub/'payoffs_and_kindness_by_gap.csv');d=d[d.board_group=='competitive']
    fig,ax=plt.subplots(figsize=(8,4.6))
    for col,label in [('mean_claim_payoff','Claim: rating change'),('mean_draw_payoff','Draw: rating change'),('mean_sacrifice','Forgone claim payoff')]:
        ax.plot(d.mean_gap,d[col],label=label)
    ax.axhline(0,color='grey',lw=.7);ax.set(xlabel='Opponent rating − chooser rating',ylabel='Mean rating points',title='Actual reconstructed payoffs in competitive positions')
    ax.legend(frameon=False);fig.tight_layout();fig.savefig(pub/'payoff_accounting.png',dpi=180);plt.close(fig)
    # Fixed-scale illustration is algebra, not an estimate of the platform's exact Glicko expected score.
    k=float(a['median_kappa']);expected=np.array([.25,.5,.75]);K=2*k
    pd.DataFrame(dict(chooser_expected_score=expected,update_scale=K,claim=K*(1-expected),draw=K*(.5-expected),sacrifice=np.full(3,k))).to_csv(pub/'fixed_scale_illustration.csv',index=False)
    (pub/'INTERPRETATION.md').write_text('The sacrifice is claim payoff minus draw payoff. A positive draw payoff still sacrifices the claim premium. Gap curves are sample means and mix update scales. The fixed-scale illustration conditions on expected score; it is not an Elo approximation presented as exact Glicko reconstruction. Realized update errors include rounding and possible reconstruction error; they do not validate the unchosen payoff independently. No causal price effect is estimated.\n')
    c.close();return dict(status='COMPLETE',**a)

def profile_view(c,inputs):
    if 'snapshot' not in inputs:raise FileNotFoundError('Certified profile snapshot is unavailable')
    c.execute('CREATE OR REPLACE VIEW profiles AS SELECT * FROM '+parq([inputs['snapshot']]))
    require(c,'profiles',['username_norm','returned','patron','created_at_ms'])
    bad=c.execute('''SELECT count(*)-count(DISTINCT username_norm),
       count(*) FILTER(WHERE returned AND patron IS NULL),
       count(*) FILTER(WHERE NOT returned AND patron IS NOT NULL) FROM profiles''').fetchone()
    if any(bad):raise RuntimeError('Duplicate or inconsistent profile outcomes')

def patron_features(c):
    terms={
      'constant':'1.0','patron_competitive':'recipient_patron::DOUBLE*fair_competitive::DOUBLE',
      'patron_clearly_worse':'recipient_patron::DOUBLE*clearly_worse::DOUBLE',
      'rating':'chooser_elo/1000.0','rating_sq':'pow(chooser_elo/1000.0,2)',
      'gap':'(disconnected_elo-chooser_elo)/100.0','gap_sq':'pow((disconnected_elo-chooser_elo)/100.0,2)',
      'ply':'ln(1+greatest(coalesce(ply_count,0),0))','ply_sq':'pow(ln(1+greatest(coalesce(ply_count,0),0)),2)',
      'fair':'fair_competitive::DOUBLE',
      'cp':'greatest(-600,least(600,engine_eval_cp_disconnected))/100.0'}
    # Missingness gets an explicit indicator; the fill constant has no separate interpretation.
    for name,col in [('chooser_rd','chooser_pre_rd_v2'),('recipient_rd','disconnected_pre_rd_v2'),('chooser_clock','chooser_clock_last_obs_s'),('recipient_clock','disconnected_clock_last_obs_s'),('base','tc_base_s'),('increment','tc_inc_s')]:
        terms[name]=f'ln(1+greatest(CASE WHEN isfinite({ident(col)}) THEN {ident(col)} ELSE 0 END,0))'
        terms[name+'_missing']=f'({ident(col)} IS NULL OR NOT isfinite({ident(col)}))::DOUBLE'
    for k,m in enumerate(c.execute('SELECT DISTINCT month FROM joined ORDER BY month').fetchall()[1:]):terms[f'month_{k}']=f'(month={lit(m[0])})::DOUBLE'
    for k,s in enumerate(c.execute('SELECT DISTINCT api_speed FROM joined WHERE api_speed IS NOT NULL ORDER BY api_speed').fetchall()[1:]):terms[f'speed_{k}']=f'(coalesce(api_speed,\'missing\')={lit(s[0])})::DOUBLE'
    return terms

def patron_reversal(inputs,root,workers,memory):
    root=Path(root);pub=root/'public';pub.mkdir(parents=True,exist_ok=True)
    c=connection(root,workers,memory);view_panel(c,inputs);profile_view(c,inputs)
    require(c,'panel',['disconnected_username_norm','chooser_username_norm','month','api_speed','chooser_elo','disconnected_elo','ply_count','engine_eval_cp_disconnected','chooser_pre_rd_v2','disconnected_pre_rd_v2','chooser_clock_last_obs_s','disconnected_clock_last_obs_s','tc_base_s','tc_inc_s'])
    c.execute('''CREATE OR REPLACE VIEW joined AS SELECT p.*,s.returned AS recipient_returned,
      CASE WHEN s.returned THEN s.patron END AS recipient_patron,s.created_at_ms AS recipient_created_at_ms,
      (s.username_norm IS NOT NULL) AS profile_requested
      FROM panel p LEFT JOIN profiles s ON p.disconnected_username_norm=s.username_norm''')
    csv(c,'''SELECT month,CASE WHEN fair_competitive THEN 'competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'middle' END board_group,
      count(*) opportunities,count(DISTINCT disconnected_user_id) recipient_accounts,
      count(*) FILTER(WHERE profile_requested) requested_rows,count(*) FILTER(WHERE recipient_returned) returned_rows,
      count(*) FILTER(WHERE recipient_patron) patron_rows,
      count(*) FILTER(WHERE recipient_returned AND recipient_created_at_ms>utc_ms) inconsistent_creation_dates
      FROM joined GROUP BY 1,2 ORDER BY 1,2''',pub/'recipient_profile_coverage.csv')
    csv(c,'''SELECT CASE WHEN fair_competitive THEN 'competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'middle' END board_group,
      recipient_patron,count(*) n,count(DISTINCT disconnected_user_id) recipients,count(DISTINCT chooser_user_id) choosers,
      sum(kind_draw::BIGINT) grants,100*avg(kind_draw::DOUBLE) kindness_pct
      FROM joined WHERE recipient_returned AND recipient_patron IS NOT NULL GROUP BY 1,2 ORDER BY 1,2''',pub/'recipient_patron_raw_rates.csv')
    csv(c,'''SELECT board_group,recipient_patron,count(*) accounts,100*avg(rate) mean_account_rate_pct FROM (
      SELECT disconnected_user_id,CASE WHEN fair_competitive THEN 'competitive' WHEN clearly_worse THEN 'clearly_worse' ELSE 'middle' END board_group,
      recipient_patron,avg(kind_draw::DOUBLE) rate FROM joined WHERE recipient_returned AND recipient_patron IS NOT NULL
      GROUP BY 1,2,3) GROUP BY 1,2 ORDER BY 1,2''',pub/'recipient_equal_account_rates.csv')
    csv(c,'''SELECT count(*) choosers,count(*) FILTER(WHERE pmin<>pmax) choosers_facing_both_statuses,
       sum(n) AS n_rows,sum(n) FILTER(WHERE pmin<>pmax) AS rows_in_status_switchers FROM (
       SELECT chooser_user_id,min(recipient_patron::INTEGER) pmin,max(recipient_patron::INTEGER) pmax,count(*) n
       FROM joined WHERE recipient_returned AND (fair_competitive OR clearly_worse) GROUP BY 1)''',pub/'chooser_FE_support.csv')
    terms=patron_features(c);features=list(terms);targets=['patron_competitive','patron_clearly_worse']
    sql='SELECT chooser_user_id j,disconnected_user_id i,utc_ms//86400000 AS day,kind_draw::DOUBLE y,'+','.join(v+' AS '+ident(k) for k,v in terms.items())+''' FROM joined
       WHERE recipient_returned AND recipient_patron IS NOT NULL AND (fair_competitive OR clearly_worse)
       AND chooser_elo IS NOT NULL AND disconnected_elo IS NOT NULL AND engine_eval_cp_disconnected IS NOT NULL'''
    output=[]
    for fe in (False,True):
        log('Patron '+('chooser fixed effects' if fe else 'adjusted pooled')+' model: all eligible rows')
        with heartbeat('Full-sample Patron regression'):
            output+=streaming_lpm(c,sql,features,targets,root/('chooser_FE' if fe else 'pooled'),chooser_fe=fe)
    import pandas as pd
    pd.DataFrame(output).to_csv(pub/'recipient_patron_estimates.csv',index=False)
    js(pub/'recipient_patron_models.json',output)
    (pub/'INTERPRETATION.md').write_text('Recipient current-Patron association in accounts covered by the selected August 2026 acquisition sample. Unknown and unreturned profiles are excluded, never coded as non-Patron. This is not a representative recipient census. Status at the game and the payer are unknown; this does not estimate a causal badge effect. Account-equal raw rates and opportunity-weighted raw rates use different weights. Adjusted fits use every eligible known-profile row, competitive and clearly-worse states; middle positions are reported descriptively. Covariance allows shared accounts in either role or the same date (CR0). No population reweighting is attempted without acquisition probabilities.\n')
    c.close();return dict(status='COMPLETE_ASSOCIATION_ONLY',estimates=output)
