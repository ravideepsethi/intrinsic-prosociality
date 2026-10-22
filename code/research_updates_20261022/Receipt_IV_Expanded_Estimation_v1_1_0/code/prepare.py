"""Select saved rows without reconstructing histories, scores or spacing."""
import shutil
from common import *
import contracts,design

def fail_if(c,query,message):
    if c.execute(query).fetchone()[0]:raise RuntimeError(message)

def validate_primary(c,expected):
    n,nr,ng=c.execute('SELECT count(*),count(DISTINCT row_id),count(DISTINCT game_id) FROM p').fetchone()
    if n!=expected['primary'] or n!=nr or n!=ng:raise RuntimeError('Primary count or unique identifiers differ')
    fail_if(c,f'''SELECT count(*) FROM p WHERE NOT calendar_primary_7d_floor5 OR
        NOT history_window_complete OR NOT complete90_data OR outcome_membership_ambiguous OR
        archive_start_ms IS NULL OR anchor_ms IS NULL OR anchor_ms<archive_start_ms OR
        anchor_ms+{90*DAY}>={design.ENDPOINT} OR recipient_id IS NULL OR opponent_id IS NULL OR
        recipient_id=opponent_id OR n_7d<5 OR n_7d IS NULL OR NOT isfinite(adjusted_7d) OR
        adjusted_7d IS NULL OR NOT isfinite(expected_7d) OR expected_7d IS NULL OR
        recipient_rating IS NULL OR opponent_rating IS NULL OR NOT isfinite(recipient_rating) OR
        NOT isfinite(opponent_rating) OR tc_base_s IS NULL OR tc_base_s<=0 OR tc_inc_s IS NULL OR
        pre_games_30d IS NULL OR pre_games_30d<0 OR y_calendar IS NULL OR reached IS NULL OR received IS NULL OR
        index_chooser_color IS NULL OR index_chooser_color NOT IN ('white','black')''',
        'Invalid predetermined fields, outcome or endpoint in primary rows')
    for days in (90,30):
        tests=[f'{v}_{days} IS NULL OR {v}_{days}<0' for v in ('fair','kind','disconnect','receipt','claim')]
        tests += [f'kind_{days}>fair_{days}',f'receipt_{days}+claim_{days}>disconnect_{days}']
        fail_if(c,'SELECT count(*) FROM p WHERE '+' OR '.join(tests),'Invalid recipient history counts')
    fail_if(c,'''SELECT count(*) FROM p WHERE reached AND
        (later_choice_is_identified IS DISTINCT FROM TRUE OR outcome_color IS NULL OR
         outcome_color NOT IN ('white','black') OR outcome_gid IS NULL OR outcome_gid=game_id OR
         outcome_gid='' OR outcome_start IS NULL OR outcome_t IS NULL OR outcome_opponent IS NULL OR
         outcome_start<=anchor_ms OR outcome_t<outcome_start OR
         outcome_t>anchor_ms+7776000000 OR outcome_opponent=opponent_id)''',
        'Invalid future choice inside a complete window')
    # Audit policy labels but never use realized later policy/color to select rows.
    fail_if(c,f'''SELECT count(*) FROM p WHERE reached AND (
        later_choice_policy_period IS DISTINCT FROM CASE WHEN outcome_t<{design.COLOR_LO} THEN 'pre'
            WHEN outcome_t>={design.COLOR_HI} THEN 'post' ELSE 'implementation_bracket' END OR
        later_white_x_post IS DISTINCT FROM CASE WHEN outcome_t>={design.COLOR_LO} AND outcome_t<{design.COLOR_HI}
            THEN NULL ELSE (outcome_color='white')::INTEGER*(outcome_t>={design.COLOR_HI})::INTEGER END)''',
        'Later policy metadata disagrees with the recorded choice; no policy-based exclusion was applied')
    fail_if(c,'''SELECT count(*) FROM p WHERE NOT reached AND
        (y_calendar IS DISTINCT FROM FALSE OR later_white_x_post IS NOT NULL OR later_choice_is_identified)''',
        'Nonreachers were dropped, recoded, or assigned a later color')
    fail_if(c,'SELECT count(*) FROM (SELECT outcome_gid FROM p WHERE reached GROUP BY 1 HAVING count(*)>1)',
        'A future outcome is reused in the primary sample')
    fail_if(c,f'''SELECT count(*) FROM (SELECT archive_start_ms,
        lag(anchor_ms) OVER(PARTITION BY recipient_id ORDER BY archive_start_ms,archive_ordinal,game_id) AS previous_anchor
        FROM p) WHERE archive_start_ms<=previous_anchor+{90*DAY}''','Primary outcome windows overlap')
    counts=c.execute('''SELECT count(*) FILTER(WHERE n_7d>=10),count(*) FILTER(WHERE support_30d_floor5),
        count(*) FILTER(WHERE n_7d>=10 AND support_30d_floor10),count(*) FILTER(WHERE reached),
        count(*) FILTER(WHERE NOT reached) FROM p''').fetchone()
    for key,value in zip(('common10','lag30_common5','lag30_common10','reached','nonreached'),counts):
        if value!=expected[key]:raise RuntimeError('Reviewed calendar-cohort count differs: '+key)
    later=c.execute(f'''SELECT count(*) FILTER(WHERE reached AND outcome_t>={design.COLOR_HI}),
        count(*) FILTER(WHERE reached AND outcome_t>={design.COLOR_LO} AND outcome_t<{design.COLOR_HI}) FROM p''').fetchone()
    if later!=(expected['later_post'],expected['later_bracket']):
        raise RuntimeError('Reviewed later-choice policy counts differ')
    for sample in ('precolor','mechanics_guard','color_post','color_spanning'):
        got=c.execute('SELECT count(*) FROM p WHERE '+design.sample_where(sample)).fetchone()[0]
        if got!=expected[sample]:raise RuntimeError('Reviewed calendar sensitivity count differs: '+sample)
    fail_if(c,'''SELECT count(*) FROM p WHERE calendar_common5_10 IS DISTINCT FROM (n_7d>=10)
        OR support_30d_floor5 IS DISTINCT FROM (n_30d>=5 AND isfinite(adjusted_30d) AND isfinite(expected_30d))
        OR support_30d_floor10 IS DISTINCT FROM (n_30d>=10 AND isfinite(adjusted_30d) AND isfinite(expected_30d))''',
        'Saved support flags disagree with the inherited score definitions')
    return dict(primary_rows=n,common10_rows=counts[0],lag30_common5_rows=counts[1],
        lag30_common10_rows=counts[2],reached_rows=counts[3],nonreached_rows=counts[4],
        later_post_color_rows=later[0],later_color_bracket_rows=later[1],
        precolor_rows=expected['precolor'],mechanics_guard_rows=expected['mechanics_guard'],
        color_post_rows=expected['color_post'],color_spanning_rows=expected['color_spanning'],
        author_exclusion_applied=False)

def historical_bridge(c,historical):
    c.execute('CREATE VIEW h AS SELECT * FROM '+scan(historical))
    fail_if(c,'SELECT count(*)-count(DISTINCT game_id) FROM h','Historical cohort has duplicated games')
    # Row IDs and month-origin codes can change under the expanded universe.
    keys='game_id,recipient_id'
    immutable=['opponent_id','archive_start_ms','anchor_ms','received','reached','recipient_rating','opponent_rating',
        'tc_base_s','tc_inc_s','outcome_gid','outcome_t','outcome_start','outcome_opponent','pre_games_30d']
    immutable += [f'{v}_{days}' for days in (90,30) for v in ('fair','kind','disconnect','receipt','claim')]
    comparisons=['p.y_calendar IS DISTINCT FROM h.y']+[f'p.{k} IS DISTINCT FROM h.{k}' for k in immutable]
    overlap,disagree=c.execute('SELECT count(*),count(*) FILTER(WHERE '+' OR '.join(comparisons)+') FROM p JOIN h USING('+keys+')').fetchone()
    if disagree:raise RuntimeError('Historical common-game outcomes or predetermined fields disagree')
    current_n=c.execute('SELECT count(*) FROM p').fetchone()[0];old_n=c.execute('SELECT count(*) FROM h').fetchone()[0]
    score_fields=[f'{v}_{lag}d' for lag in (7,30) for v in ('n','adjusted','expected','counterparts')]
    changes=[]
    for col in score_fields:
        row=c.execute(f'''SELECT count(*) FILTER(WHERE p.{col} IS DISTINCT FROM h.{col}),
          max(abs(p.{col}-h.{col})) FROM p JOIN h USING({keys})''').fetchone()
        changes.append(dict(field=col,exactly_different_rows=row[0],max_absolute_change=row[1]))
    # Decompose the counts without assuming that the old cohort nests in the new.
    groups=c.execute(f'''SELECT strftime(to_timestamp(p.archive_start_ms/1000.0),'%Y-%m') AS month,
       CASE WHEN h.game_id IS NULL THEN 'new_only' ELSE 'common' END AS membership,count(*)::BIGINT AS rows
       FROM p LEFT JOIN h USING({keys}) GROUP BY ALL
       UNION ALL SELECT strftime(to_timestamp(h.archive_start_ms/1000.0),'%Y-%m') AS month,
       'old_only' AS membership,count(*)::BIGINT AS rows FROM h ANTI JOIN p USING({keys}) GROUP BY ALL ORDER BY 1,2''').to_arrow_table().to_pylist()
    return dict(historical_rows=old_n,new_primary_rows=current_n,common_game_recipient_rows=overlap,
        new_only_rows=current_n-overlap,old_only_rows=old_n-overlap,net_count_difference=current_n-old_n,
        immutable_common_field_mismatches=disagree,score_changes=changes,
        interpretation='Extending recorded history can alter scores and greedy selection. This is not assumed to be an append-only sample.'),groups

def build(inputs,root,code,threads,memory_mb,auth):
    key=digest(dict(code=code,inputs=inputs['snapshots'],freeze=design.freeze()))
    def producer(tmp):
        c=connection(tmp/'spill',threads,memory_mb)
        c.execute('SET enable_progress_bar=false')
        try:
            c.execute('CREATE VIEW a AS SELECT * FROM '+scan(inputs['paths']))
            n,calendar=c.execute('SELECT count(*),count(*) FILTER(WHERE calendar_primary_7d_floor5) FROM a').fetchone()
            if (n,calendar)!=(design.EXPECTED['first_pair'],design.EXPECTED['calendar_primary']):
                raise RuntimeError('Upstream counts changed before selection')
            c.execute(f'CREATE VIEW p AS SELECT * FROM a WHERE calendar_primary_7d_floor5 AND anchor_ms+{90*DAY}<{design.ENDPOINT}')
            accounting=validate_primary(c,design.EXPECTED)
            bridge,membership=historical_bridge(c,inputs['historical_path'])
            write_json(tmp/'HISTORICAL_MEMBERSHIP_BRIDGE.json',bridge);table(membership,tmp/'HISTORICAL_MEMBERSHIP_BY_MONTH')
            period_counts=c.execute('''SELECT month,count(*)::BIGINT AS rows,count(*) FILTER(WHERE received)::BIGINT AS receipts,
                count(*) FILTER(WHERE reached)::BIGINT AS reached,count(*) FILTER(WHERE y_calendar)::BIGINT AS kind_outcomes,
                count(*) FILTER(WHERE NOT reached)::BIGINT AS nonreachers,count(*) FILTER(WHERE n_7d>=10)::BIGINT AS common10
                FROM p GROUP BY 1 ORDER BY 1''').to_arrow_table().to_pylist()
            table(period_counts,tmp/'PRIMARY_COUNTS_BY_MONTH')
            regimes=c.execute(f'''SELECT {design.color_window_sql()} AS color_window,
                CASE WHEN anchor_ms+{90*DAY}<{design.MECHANICS_GUARD} THEN 'before_source_day_guard'
                     ELSE 'crosses_or_after_source_day_guard' END AS mechanics_window,
                index_chooser_color,count(*)::BIGINT AS rows,count(*) FILTER(WHERE received)::BIGINT AS receipts,
                count(*) FILTER(WHERE reached)::BIGINT AS reached,count(*) FILTER(WHERE y_calendar)::BIGINT AS kind_outcomes,
                count(*) FILTER(WHERE NOT reached)::BIGINT AS nonreachers FROM p GROUP BY ALL ORDER BY ALL''').to_arrow_table().to_pylist()
            table(regimes,tmp/'CALENDAR_REGIME_COUNTS')
            later=c.execute('''SELECT later_choice_policy_period,count(*)::BIGINT AS rows,
                count(*) FILTER(WHERE received)::BIGINT AS receipts,count(*) FILTER(WHERE y_calendar)::BIGINT AS kind_outcomes
                FROM p GROUP BY 1 ORDER BY 1''').to_arrow_table().to_pylist()
            table(later,tmp/'LATER_CHOICE_POLICY_DESCRIPTIVE')
            # One private extraction reused by every new model; only needed model fields.
            original=[k for k in design.MODEL_COLUMNS if k not in ('y','complete90','month_code')]
            query='SELECT '+','.join(ident(k) for k in original)+f''',y_calendar AS y,TRUE AS complete90,
                date_diff('month',DATE '2023-11-01',strptime(month||'-01','%Y-%m-%d'))::BIGINT AS month_code,
                support_30d_floor5,(index_chooser_color='white')::INTEGER AS index_color_white,
                count(*) OVER(PARTITION BY recipient_id)::BIGINT AS recipient_selected_count
                FROM p ORDER BY row_id'''
            copy(c,query,tmp/'primary_PRIVATE.parquet')
            c.execute('CREATE VIEW s AS SELECT * FROM '+scan(tmp/'primary_PRIVATE.parquet'))
            samples={s['sample'] for s in design.specifications() if s['sample']!='historical'}
            sample_counts={s:c.execute('SELECT count(*) FROM s WHERE '+design.sample_where(s)).fetchone()[0] for s in sorted(samples)}
            accounting.update(samples=sample_counts,historical_rows=bridge['historical_rows'])
            write_json(tmp/'SAMPLE_ACCOUNTING.json',accounting)
            write_json(tmp/'COMMON_HISTORY_CONTRACT.json',dict(common_rows=accounting['common10_rows'],
                score_identical_under_both_floors=True,common_fit='calendar90_common10',
                floor5_fit_on_own_sample='calendar90_primary',
                interpretation='Both common-sample threshold labels reference the same fit. No artificial last-five or last-ten instrument is constructed.'))
            return accounting
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return stage(root/'prepare'/key,key,inputs['snapshots'],producer,auth)

def load_model(c,path,spec):
    where='TRUE' if spec['sample']=='historical' else design.sample_where(spec['sample'])
    fields=','.join(ident(k) for k in design.MODEL_COLUMNS)
    if spec['sample']!='historical':fields+=',index_color_white'
    t=c.execute('SELECT '+fields+' FROM '+scan(path)+' WHERE '+where+' ORDER BY row_id').to_arrow_table()
    return {k:arr(t,k) for k in t.column_names}
