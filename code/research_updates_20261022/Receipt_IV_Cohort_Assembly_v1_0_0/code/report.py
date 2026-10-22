"""Small aggregate return bundle. Identifiable rows stay on the project drive."""
import shutil,zipfile
from common import *
from contracts import snap,ACCOUNT_POLICY
import logic

GATES=[dict(item='author_account_exclusion',status='DEFERRED_BY_EXPLICIT_USER_INSTRUCTION'),
    dict(item='complete_source_pull',status='COMPLETE_5891950_VALIDATED_IDS'),
    dict(item='mechanics_source_and_deployment_censor',status='UNFROZEN'),
    dict(item='broader_incident_denominator',status='NOT_SUPPLIED_BY_TARGETED_SOURCE_PULL'),
    dict(item='new_month_rating_state_calibration_and_RD_attachment',status='OPEN'),
    dict(item='later_choice_nonreacher_control_specification',status='NOT_FROZEN'),
    dict(item='announcement_timestamp',status='NOT_PINNED'),
    dict(item='IV_reduced_form_2SLS_exclusion_sensitivity_MDE',status='NOT_ESTIMATED')]

def assemble(products,month_products,firstpair,prepared,runroot,code,threads,memory_mb,auth):
    snaps=[snap(Path(p['root'])/'_DONE.json') for p in products]+[snap(firstpair/'_DONE.json'),snap(prepared/'_DONE.json')]
    key=digest(dict(code=code,inputs=snaps))
    def build(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        try:
            paths=[Path(p['root'])/'analysis_PRIVATE.parquet' for p in products if p['result']['rows']]
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(paths))
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM a').fetchone()
            if n!=u or n!=load(firstpair/'_DONE.json')['result']['first_observed_pair_rows']:raise RuntimeError('Final assembly is not one-to-one')
            cols=['month','count(*) first_pair_rows','count(*) FILTER(WHERE support_7d_floor5) support5_rows',
                'count(*) FILTER(WHERE support_7d_floor10) support10_rows','count(*) FILTER(WHERE spaced90_7d_floor5) selected90_before_cuts',
                'count(*) FILTER(WHERE calendar_primary_7d_floor5) calendar_primary_rows',
                'count(*) FILTER(WHERE calendar_common5_10) common5_10_rows',
                'count(*) FILTER(WHERE calendar_independently_spaced_floor10) independently_spaced_floor10_rows',
                'count(*) FILTER(WHERE NOT complete90_data) incomplete90_rows',
                'count(*) FILTER(WHERE NOT history_window_complete) incomplete97_history_rows',
                'count(*) FILTER(WHERE outcome_membership_ambiguous) ambiguous_outcome_rows',
                'count(*) FILTER(WHERE NOT authenticated_rating_states_attached) unattached_RD_rows',
                'count(*) FILTER(WHERE calendar_primary_7d_floor5 AND reached) primary_reached_rows',
                'count(*) FILTER(WHERE calendar_primary_7d_floor5 AND NOT reached) primary_nonreached_rows']
            t=c.execute('SELECT '+','.join(cols)+' FROM a GROUP BY month ORDER BY month').to_arrow_table()
            table(t.to_pylist(),tmp/'COHORT_COUNTS')
            # Raw score support, not a first-stage/reduced-form coefficient or MDE.
            out=[]
            for lag in (7,30):
                for scope,condition in [('calendar_primary','calendar_primary_7d_floor5'),('common5_10','calendar_common5_10')]:
                    r=c.execute(f'''SELECT count(*),stddev_samp(adjusted_{lag}d) FILTER(WHERE isfinite(adjusted_{lag}d)),
                        min(n_{lag}d),median(n_{lag}d),count(*) FILTER(WHERE outcome_membership_ambiguous),
                        count(*) FILTER(WHERE isfinite(adjusted_{lag}d)) FROM a WHERE {condition}''').fetchone()
                    out.append(dict(scope=scope,lag_days=lag,rows=r[0],raw_score_sd=r[1],minimum_prior_decisions=r[2],median_prior_decisions=r[3],ambiguous_outcomes=r[4],finite_score_rows=r[5]))
            table(out,tmp/'SCORE_SUPPORT')
            t=c.execute('''SELECT index_policy_period,later_choice_policy_period,count(*) AS rows,
                count(*) FILTER(WHERE later_choice_is_identified) identified_later_choices,
                count(*) FILTER(WHERE calendar_primary_7d_floor5) calendar_primary_rows
                FROM a GROUP BY ALL ORDER BY 1,2''').to_arrow_table();table(t.to_pylist(),tmp/'POLICY_AVAILABILITY')
            table([p['result'] for p in month_products],tmp/'MEMBERSHIP_COUNTS')
            totals=c.execute('''SELECT count(*) FILTER(WHERE calendar_primary_7d_floor5),count(*) FILTER(WHERE calendar_common5_10),
                count(*) FILTER(WHERE outcome_membership_ambiguous),count(*) FILTER(WHERE calendar_primary_7d_floor5 AND recipient_rd IS NULL)
                FROM a''').fetchone()
            manifest=dict(status='COHORT_ASSEMBLED_CENSOR_AND_ESTIMATION_GATES_OPEN',code_signature=code,
                account_policy=ACCOUNT_POLICY,analysis_paths=[str(p) for p in paths],
                selected_streams={str(gap):[str(Path(p['root'])/f'selected_stream_{gap}_PRIVATE.parquet') for p in products if p['result']['rows']] for gap in (30,90)},
                receipts=snaps,mechanics_censor=None,final_iv_eligible_n=None,new_IV_estimate=None,
                policy_time_basis='Inherited lastMoveAt anchor proxy, with 07:15–07:22 UTC bracket retained; not an observed decision instant.',
                first_pair_scope='Union of original pinned historical manifest and current canonical 32-month files, deduplicated by resolved path; pair minima tolerate overlapping coverage.',
                primary_response='y_calendar is NULL for incomplete 90-day windows or potentially displaced first outcomes. Later policy interaction is NULL for nonreachers/ambiguous choices/bracket.',
                floor_comparison='Floors 5 and 10 use the same all-history instrument; common5_10_on_primary_stream is the >=10 subset of floor5 spacing. Independently spaced floor10 is separate.',
                newly_unresolved_membership_rows=195582)
            write_json(tmp/'ASSEMBLY_MANIFEST_PRIVATE.json',manifest)
            return dict(status=manifest['status'],known_main_rows=55467033,first_pair_rows=n,
                calendar_primary_rows_before_mechanics=totals[0],common5_10_rows_before_mechanics=totals[1],
                ambiguous_outcome_rows=totals[2],primary_rows_with_missing_recipient_RD=totals[3],
                final_iv_eligible_n=None,mechanics_censor=None,new_IV_estimate=None,author_exclusion_applied=False,
                source_requests=0,rating_replays=0,Stockfish_calls=0,instrument_recomputations=0)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(runroot/'assembled'/key,key,snaps,build,auth)

def zip_report(report,desktop):
    allowed={'RUN_CONFIGURATION.json','SUMMARY.json','ERRORS.json','GATES.json','ACCOUNT_POLICY.json',
        'CHRONOLOGY_BENCHMARK.json','COHORT_COUNTS.csv','COHORT_COUNTS.parquet','SCORE_SUPPORT.csv','SCORE_SUPPORT.parquet',
        'POLICY_AVAILABILITY.csv','POLICY_AVAILABILITY.parquet','MEMBERSHIP_COUNTS.csv','MEMBERSHIP_COUNTS.parquet','READ_ME_FIRST.txt'}
    files=[p for p in sorted(report.iterdir()) if p.is_file()]
    if any(p.name not in allowed for p in files):raise RuntimeError('Unexpected public report file')
    write_json(report/'RESULT_MANIFEST.json',dict(files=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in files]))
    dest=Path(desktop)/(report.name+'.zip')
    with zipfile.ZipFile(dest,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for p in [*files,report/'RESULT_MANIFEST.json']:z.write(p,report.name+'/'+p.name)
    dest.with_suffix('.zip.sha256').write_text(sha(dest)+'  '+dest.name+'\n')
    return dest
