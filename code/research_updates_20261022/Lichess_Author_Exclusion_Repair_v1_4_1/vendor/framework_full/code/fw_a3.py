"""Reuse the exact AFE recipient-Patron model and shared-account/date covariance."""
from fw_common import *

def run(a,run,key):
    work=run/'A3';report=work/'report';report.mkdir(parents=True,exist_ok=True);ak=digest([key,'A3'])
    if completed(work/'final',ak):return load(work/'final/status.json')
    ac=module('common',ROOT/'vendor_afe/common.py');st=module('framework_afe_static',ROOT/'vendor_afe/static_analyses.py')
    source=load(run/'SOURCE_PRIVATE.json');panels=[r['path'] for r in source['month_records']]
    # The shared projector has already verified every source hash and its identity.
    records=load(run/'INPUTS_PRIVATE.json')
    require(len(panels)==24 and len(records)==24,'A3 needs authenticated monthly inputs')
    snapshot=a.project_root/'derived/replication/patron_profile_snapshot_24m_v100_FINAL_CERTIFIED/profile_snapshot_24m_private_lossless.parquet'
    require(sha(snapshot)==ac.SNAPSHOT_SHA,'A3 August snapshot differs from AFE producer')
    c=conn(work/'spill',max(1,a.memory_gb-2),min(a.workers,3));rows=[]
    try:
        st.profile_view(c,dict(snapshot=str(snapshot)))
        c.execute('CREATE VIEW panel AS SELECT * FROM '+parq(panels)+' WHERE '+u.author_predicate())
        c.execute('''CREATE VIEW joined_all AS SELECT p.*,s.returned recipient_returned,
          CASE WHEN s.returned THEN s.patron END recipient_patron,
          coalesce(s.tos_violation,false) OR coalesce(s.disabled,false) recipient_flagged
          FROM panel p LEFT JOIN profiles s ON p.disconnected_username_norm=s.username_norm''')
        coverage=c.execute('''SELECT CASE WHEN fair_competitive THEN 'C' WHEN clearly_worse THEN 'L' ELSE 'middle' END state,
          count(*) opportunities,count(*) FILTER(WHERE recipient_returned) returned,
          count(*) FILTER(WHERE recipient_returned AND recipient_flagged) flagged
          FROM joined_all GROUP BY 1''').fetchdf()
        table(report,'tabA3_profile_coverage',coverage)
        for rule in ['author_clean_baseline','exclude_either_recipient_flag']:
            folder=work/rule;mk=digest([ak,rule])
            if completed(folder,mk):rr=load(folder/'results.json')
            else:
                c.execute('CREATE OR REPLACE VIEW joined AS SELECT * FROM joined_all'+(' WHERE NOT recipient_flagged' if rule.startswith('exclude') else ''))
                terms=st.patron_features(c);features=list(terms)
                sql='SELECT chooser_user_id j,disconnected_user_id i,utc_ms//86400000 AS day,kind_draw::DOUBLE y,'+','.join(v+' AS '+ac.ident(k) for k,v in terms.items())+''' FROM joined
                  WHERE recipient_returned AND recipient_patron IS NOT NULL AND (fair_competitive OR clearly_worse)
                  AND chooser_elo IS NOT NULL AND disconnected_elo IS NOT NULL AND engine_eval_cp_disconnected IS NOT NULL'''
                with heartbeat('A3 recipient Patron '+rule):
                    rr=ac.streaming_lpm(c,sql,features,['patron_competitive','patron_clearly_worse'],folder,chooser_fe=True)
                save(folder/'results.json',rr);certify(folder,mk,panels+[snapshot])
            rows += [dict(r,specification=rule) for r in rr]
    finally:c.close()
    table(report,'tabA3_recipient_patron_excluding_flags',rows)
    table(report,'original_reviewed_recipient_estimates',load(ROOT/'evidence/afe_recipient_patron_models.json'))
    status=dict(status='ESTIMATED',producer='AFE_Followups_v1_0_0/static_analyses.py:patron_features + common.py:streaming_lpm',
        original_estimates='Archived reviewed authority supplied for provenance; new author-clean estimates are not labeled an exact reproduction.',
        interpretation='Selected August 2026 profile coverage; future snapshot, not historical badge exposure or a causal badge effect.',
        covariance='Original shared-account-OR-date CR0',authors_excluded_both_roles=True)
    save(work/'final/status.json',status);certify(work/'final',ak,panels+[snapshot],outputs=list(report.glob('*')));return status
