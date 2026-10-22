"""Additional table producers using the authenticated common input policy."""
from engine import *

def activity(args,auth,out):
    sys.path.insert(0,str(ROOT/'vendor/activity'))
    from runner.rates import analyze
    from runner.run import verify_previous
    c=db(out/'PRIVATE/spill',args.memory_gb,args.workers)
    try:
        frame=c.execute('''SELECT chooser_user_id AS chooser,
          count(*) FILTER(WHERE engine_eval_cp_disconnected>=-100)::BIGINT f,
          count(*) FILTER(WHERE engine_eval_cp_disconnected<=-300)::BIGINT l,
          coalesce(sum(outcome_kind_draw) FILTER(WHERE engine_eval_cp_disconnected>=-100),0)::BIGINT a,
          coalesce(sum(outcome_kind_draw) FILTER(WHERE engine_eval_cp_disconnected<=-300),0)::BIGINT b
          FROM '''+scan([r['path'] for r in auth['month_records']])+''' GROUP BY chooser_user_id''').fetchdf()
    finally:c.close()
    rates,cov,contrasts=analyze(frame,(6,16))
    baseline=verify_previous(rates) if args.variant=='included' else {'status':'NEW_EXCLUDED_ESTIMATES'}
    table(out/'report/state_rates_and_ratios',rates)
    table(out/'report/state_rate_covariance_pct2',cov)
    table(out/'report/activity_ratio_comparisons',contrasts)
    write(out/'report/METHOD.json',{'baseline':baseline,'activity_cutoffs':[6,16],
       'weights':'Original within-chooser weights; inverse-count within; equal chooser; pooled opportunities',
       'behavioral_counts_rebuilt':True,'zero_granters_retained':True,'replacement_accounts':0})
    return {'tables':3,'baseline':baseline}
