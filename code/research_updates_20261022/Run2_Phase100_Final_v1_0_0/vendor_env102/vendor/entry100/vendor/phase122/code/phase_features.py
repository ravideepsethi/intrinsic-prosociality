"""Shared preparation for the frozen ordinary90 and entry90 equations."""
from cached_common import *
import legacy_schema
ENTRY_COLUMNS=['active_timeout','recipient_disconnect_main','recipient_fair_arm_main','selected_entry_90','analysis_entry_90']
QUERY_COLUMNS=QUERY_COLUMNS+['active_timeout']
OLD_COLUMNS=OLD_COLUMNS+ENTRY_COLUMNS
SPECS={family:next(s for s in design.specifications() if s['name']==name)
       for family,name in [('ordinary','ordinary90_placebo'),('entry','entry90_pooled')]}

def verify_original(path):
    d=arrays(io.read(path)); keep,_=design.entry_mask(d,90)
    baseline={k:v[keep] for k,v in d.items()}; fits={}
    expected=io.load(VENDOR/'comparison_original/evidence/expanded_estimates.json')
    for family,spec in SPECS.items():
        use=np.asarray(baseline['ordinary_narrow'],bool)&np.asarray(baseline['complete90'],bool) if family=='ordinary' else np.ones(keep.sum(),bool)
        sample={k:v[use] for k,v in baseline.items()}; fit=stats.estimate(sample,spec); fits[family]=fit
        saved=[r for r in expected if r.get('specification')==spec['name']]
        if not saved:raise RuntimeError('Missing frozen original estimate')
        for old in saved:
            row=next(r for r in fit['estimates'] if r.get('outcome')==old['outcome'])
            for key in ('n','events','row_set_sha256'):
                if row[key]!=old[key]:raise RuntimeError('Original '+family+' bridge failed: '+key)
            for key in ('coefficient_pp','standard_error_pp'):
                if not np.isclose(row[key],old[key],rtol=1e-8,atol=1e-10):raise RuntimeError('Original '+family+' numerical bridge failed: '+key)
    return baseline,fits

def prepare_queries(ordinary,source,root,conf,memory,legacy_outcomes=None,write_shards=True):
    def build(tmp):
        schema=legacy_schema.preflight(source,legacy_outcomes,OLD_COLUMNS)
        baseline,fit=verify_original(source)
        order=np.argsort(baseline['row_id']);baseline={k:v[order] for k,v in baseline.items()}
        baseline,recovery=legacy_schema.restore(baseline,legacy_outcomes,tmp,memory)
        io.js(tmp/'legacy_schema.json',dict(schema=schema,recovery=recovery))
        io.js(tmp/'baseline_reproduction.json',fit)
        # Keep the frozen old row IDs, including rows affected by author cleaning.
        io.table(tmp/'baseline_original.parquet',pa.table({k:baseline[k] for k in OLD_COLUMNS}))
        old={k:baseline[k] for k in QUERY_COLUMNS if k in baseline}
        old.update(previous_frame=np.ones(len(baseline['row_id']),bool),expected_n7=np.asarray(baseline['n_7d'],np.int64))
        # Legacy analysis tables retain the verified ordinary-ending flag,
        # but may omit export status and API labels. Do not invent those values.
        for name in ('status','recipient_username','opponent_username'):
            if name not in old:old[name]=pa.nulls(len(baseline['row_id']),type=pa.string())
        io.table(tmp/'baseline_queries.parquet',pa.table({k:old[k] for k in QUERY_COLUMNS}))
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW new AS SELECT * FROM '+io.parq(ordinary))
            complete=f'archive_start_ms+{90*DAY}<{core.PANEL_END}'
            query=f'''SELECT {NEW_ID_BASE}+row_number() OVER(ORDER BY game_id)::BIGINT AS row_id,*,
                status IN ('mate','resign','stalemate') AS ordinary_narrow, status='timeout' AS active_timeout,
                FALSE previous_frame,0::BIGINT pre_games_30d,FALSE eligible_main,FALSE first_observed_pair
                FROM new WHERE {complete}'''
            io.copy(c,'SELECT '+','.join(QUERY_COLUMNS)+' FROM ('+query+')',tmp/'new_queries.parquet')
            io.copy(c,'SELECT * FROM '+io.parq([tmp/'baseline_queries.parquet',tmp/'new_queries.parquet'])+' ORDER BY row_id',tmp/'queries.parquet')
            n,u=c.execute('SELECT count(*),count(DISTINCT game_id) FROM '+io.parq([tmp/'queries.parquet'])).fetchone()
            if n!=u:raise RuntimeError('Old/new query samples overlap or duplicate games')
            before=c.execute('SELECT count(*) FROM new').fetchone()[0]
            newn=pq.ParquetFile(tmp/'new_queries.parquet').metadata.num_rows
        finally:finish_connection(c,tmp/'spill')
        # Small physical query shards avoid copying the entire query population in workers.
        if write_shards:
            q=io.read(tmp/'queries.parquet')
            a=arrays(q.select(['row_id','opponent_id','recipient_id']))
            score_shard=num.user_hash(a['opponent_id'])%np.uint64(16)
            for s in range(16):
                io.table(tmp/f'score_{s:02}.parquet',q.filter(pa.array(score_shard==s)))
                io.table(tmp/f'outcome_{s:02}.parquet',q.filter(pa.array(a['recipient_id']%16==s)))
        return dict(old_frozen_rows=len(baseline['row_id']),new_pool_before_calendar=before,
                    new_calendar_supported_queries=newn,new_without_start_calendar_support=before-newn,rows=n)
    return stable_stage(root,conf,build,[source]+ordinary+([legacy_outcomes] if legacy_outcomes else []))

def verify_original_features(d,saved):
    old=np.asarray(d['previous_frame'],bool);oi=np.flatnonzero(old)
    if len(oi)!=len(saved['row_id']) or len(np.unique(d['row_id'][oi]))!=len(oi):
        raise RuntimeError('Original comparison feature row set changed')
    pos=num.lookup(saved['row_id'],d['row_id'][old])
    if np.any(pos<0):raise RuntimeError('Original comparison row ID is missing')
    for k in SCORE_COLS+COUNT_COLUMNS+['y','reached']+legacy_schema.DETAILS:
        a=d['original_'+k][oi];b=saved[k][pos]
        good=np.allclose(a,b,rtol=1e-10,atol=2e-11,equal_nan=True) if a.dtype.kind in 'fi' else np.array_equal(a,b)
        if not good:raise RuntimeError('Original comparison feature reproduction failed: '+k)
    for k in ENTRY_COLUMNS:
        if not np.array_equal(d[k][oi],saved[k][pos]):raise RuntimeError('Original entry-label reproduction failed: '+k)
    return pos

def check_before_chronology(queries,baseline,scorepaths,outcomepaths,entrypath,root,conf,memory):
    """Reject any original-feature discrepancy before the billions-row scan."""
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT row_id,previous_frame,active_timeout FROM '+io.parq([queries])+' WHERE previous_frame')
            c.execute('CREATE VIEW s AS SELECT * FROM '+io.parq(scorepaths))
            c.execute('CREATE VIEW o AS SELECT * FROM '+io.parq(outcomepaths))
            c.execute('CREATE VIEW e AS SELECT * FROM '+io.parq([entrypath]))
            fields=['q.*']+['s.original_'+k for k in SCORE_COLS]+['o.original_'+k for k in COUNT_COLUMNS+['y','reached']+legacy_schema.DETAILS]+['e.'+k for k in ENTRY_COLUMNS if k!='active_timeout']
            query='SELECT '+','.join(fields)+' FROM q JOIN s USING(row_id) JOIN o USING(row_id) JOIN e USING(row_id)'
            saved=arrays(io.read(baseline));assert_rows(c,query,len(saved['row_id']),'Early original feature join')
            d=arrays(c.execute(query+' ORDER BY q.row_id').to_arrow_table())
            verify_original_features(d,saved)
            result=dict(status='ORIGINAL_FEATURES_REPRODUCED_BEFORE_CHRONOLOGY',rows=len(saved['row_id']))
            io.js(tmp/'summary.json',result);return result
        finally:finish_connection(c,tmp/'spill')
    return stable_stage(root,conf,build,[queries,baseline,entrypath]+scorepaths+outcomepaths)

def combine(queries,baseline,scorepaths,outcomepaths,chronpath,stream,author_ids,root,conf,memory,entrypath,new_cohort="new_phase10"):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW scores AS SELECT * FROM '+io.parq(scorepaths))
            c.execute('CREATE VIEW o AS SELECT * FROM '+io.parq(outcomepaths))
            c.execute('CREATE VIEW x AS SELECT * FROM '+io.parq([chronpath]))
            c.execute('CREATE VIEW e AS SELECT * FROM '+io.parq([entrypath]))
            query='''SELECT q.* EXCLUDE(pre_games_30d,eligible_main,first_observed_pair),
                CASE WHEN q.previous_frame THEN q.pre_games_30d ELSE x.pre_games_30d END AS pre_games_30d,
                CASE WHEN q.previous_frame THEN q.eligible_main ELSE x.eligible_main END AS eligible_main,
                CASE WHEN q.previous_frame THEN q.first_observed_pair ELSE x.first_observed_pair END AS first_observed_pair,
                scores.* EXCLUDE(row_id),o.* EXCLUDE(row_id),e.* EXCLUDE(row_id)
                FROM q JOIN scores USING(row_id) JOIN o USING(row_id) JOIN e USING(row_id) LEFT JOIN x USING(row_id)'''
            count=pq.ParquetFile(queries).metadata.num_rows;assert_rows(c,query,count,'Final feature join')
            t=c.execute(query+' ORDER BY q.row_id').to_arrow_table()
        finally:finish_connection(c,tmp/'spill')
        d=arrays(t);old=d['previous_frame'].astype(bool);saved=arrays(io.read(baseline))
        pos=verify_original_features(d,saved)
        if np.any(d['matched_main'] & ~d['eligible_main']):raise RuntimeError('Main panel and recomputed adjacency disagree')
        risk=design.prospective_risk(arrays(io.read(stream)),d,90)
        if not np.array_equal(risk['at_risk'][old],saved['at_risk_90'][pos]):raise RuntimeError('Full-stream cooldown does not reproduce original comparison')
        d['at_risk_90']=risk['at_risk'];d['history_complete']=d['history_window_complete']
        d['complete90']=d['anchor_ms']+90*DAY<core.PANEL_END
        # Original rows use their authenticated frozen classification; new rows
        # use the explicit metadata classification saved during preparation.
        all_known(d,['ordinary_narrow']+ENTRY_COLUMNS)
        new=~d['previous_frame'].astype(bool)
        if not np.array_equal(d['ordinary_narrow'][new],np.isin(d['status'][new],list(core.NARROW))):
            raise RuntimeError('New ordinary-ending classification disagrees with metadata')
        all_known(d,['eligible_main','first_observed_pair','pre_games_30d']+COUNT_COLUMNS)
        design.validate_history(d,True)
        involved=authors.author_mask(d['recipient_id'],d['opponent_id'],author_ids)
        entry_keep,flow=design.entry_mask(d,90)
        entry_keep &= ~involved
        keep=entry_keep & d['ordinary_narrow'] & d['complete90']
        if np.any(d['y']&~d['reached']):raise RuntimeError('Kindness without reaching a choice')
        reached=d['reached'].astype(bool)
        if np.any(reached&((d['outcome_t']>d['anchor_ms']+90*DAY)|(d['outcome_t']<=d['anchor_ms'])|
            (d['outcome_start']<=d['anchor_ms'])|(d['outcome_opponent']==d['opponent_id'])|(d['outcome_gid']==d['game_id']))):
            raise RuntimeError('Invalid follow-up timing or opponent')
        # Save every assembled query with disposition; no incomplete window becomes a zero.
        feature_table=pa.table(dict(d,analysis_eligible=keep,entry_eligible=entry_keep,author_game=involved))
        # Observed flags are distinct from the complete-window outcome, even in
        # synthetic/diagnostic queries that include incomplete windows.
        for name in ('y','reached'):
            feature_table=feature_table.append_column('observed_'+name,pa.array(d[name]))
            feature_table=feature_table.set_column(feature_table.schema.get_field_index(name),name,
                pa.array(d[name],mask=~d['complete90']))
        io.table(tmp/'features.parquet',feature_table)
        selected={k:v for k,v in d.items() if not k.startswith('original_')}
        groups={}
        for family,fmask in [('ordinary',keep),('entry',entry_keep)]:
            for label,cohort in [(new_cohort,~old),('old_author_clean',old),('pooled',np.ones(len(old),bool))]:
                mask=fmask & cohort
                sample={k:v[mask] for k,v in selected.items()}
                # Entry equations never use later-choice outcomes. Do not store incomplete outcomes as zeros.
                if family=='entry':
                    for k in ('y','reached','outcome_gid','outcome_t','outcome_start','outcome_opponent'):sample.pop(k,None)
                name=family+'_'+label
                io.table(tmp/(name+'.parquet'),pa.table(sample));groups[name]=stats.describe(sample)
        flows=[]
        for label,mask in [(new_cohort,~old),('old_original',old)]:
            subset={k:v[mask] for k,v in d.items()};sm,sf=design.entry_mask(subset,90)
            flows += [dict(sample=label,**r) for r in sf]
            flows.append(dict(sample=label,step='entry_after_author_exclusion',rows=int((entry_keep&mask).sum())))
            flows.append(dict(sample=label,step='ordinary_complete90_after_author_exclusion',rows=int((keep&mask).sum())))
        io.js(tmp/'flow.json',flows)
        return dict(sample_accounting=groups,original_features_reproduced=int(old.sum()),
                    author_targets_excluded=int(involved.sum()),full_original_exposure_stream_preserved=True,
                    earlier_started_unanchored=int(risk['earlier_started_not_yet_anchored'].sum()))
    return stable_stage(root,conf,build,[queries,baseline,chronpath,stream,entrypath]+scorepaths+outcomepaths)
