#!/usr/bin/env python3
"""Estimate the frozen ordinary-game placebo using completed local metadata only."""
from cached_common import *
import argparse,fcntl,platform,shutil,time,traceback
import cached_inputs as inputs_code
import cached_chronology as chronology
import cached_histories as histories

def prepare_queries(ordinary,source,root,conf,memory):
    def build(tmp):
        baseline,fit=verify_baseline(source)
        order=np.argsort(baseline['row_id']);baseline={k:v[order] for k,v in baseline.items()}
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
            complete=f'anchor_ms+{90*DAY}<{core.PANEL_END}'
            query=f'''SELECT {NEW_ID_BASE}+row_number() OVER(ORDER BY game_id)::BIGINT AS row_id,*,
                status IN ('mate','resign','stalemate') AS ordinary_narrow,
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
        q=io.read(tmp/'queries.parquet')
        a=arrays(q.select(['row_id','opponent_id','recipient_id']))
        score_shard=num.user_hash(a['opponent_id'])%np.uint64(16)
        for s in range(16):
            io.table(tmp/f'score_{s:02}.parquet',q.filter(pa.array(score_shard==s)))
            io.table(tmp/f'outcome_{s:02}.parquet',q.filter(pa.array(a['recipient_id']%16==s)))
        return dict(old_frozen_rows=len(baseline['row_id']),new_ordinary_before_followup=before,
                    new_complete90_queries=newn,new_incomplete90_excluded=before-newn,rows=n)
    return stable_stage(root,conf,build,[source]+ordinary)

def combine(queries,baseline,scorepaths,outcomepaths,chronpath,stream,author_ids,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([queries]))
            c.execute('CREATE VIEW scores AS SELECT * FROM '+io.parq(scorepaths))
            c.execute('CREATE VIEW o AS SELECT * FROM '+io.parq(outcomepaths))
            c.execute('CREATE VIEW x AS SELECT * FROM '+io.parq([chronpath]))
            query='''SELECT q.* EXCLUDE(pre_games_30d,eligible_main,first_observed_pair),
                CASE WHEN q.previous_frame THEN q.pre_games_30d ELSE x.pre_games_30d END AS pre_games_30d,
                CASE WHEN q.previous_frame THEN q.eligible_main ELSE x.eligible_main END AS eligible_main,
                CASE WHEN q.previous_frame THEN q.first_observed_pair ELSE x.first_observed_pair END AS first_observed_pair,
                scores.* EXCLUDE(row_id),o.* EXCLUDE(row_id)
                FROM q JOIN scores USING(row_id) JOIN o USING(row_id) LEFT JOIN x USING(row_id)'''
            count=pq.ParquetFile(queries).metadata.num_rows;assert_rows(c,query,count,'Final feature join')
            t=c.execute(query+' ORDER BY q.row_id').to_arrow_table()
        finally:finish_connection(c,tmp/'spill')
        d=arrays(t);old=d['previous_frame'].astype(bool);saved=arrays(io.read(baseline))
        oi=np.flatnonzero(old);pos=num.lookup(saved['row_id'],d['row_id'][old])
        if np.any(pos<0):raise RuntimeError('Original comparison row ID is missing')
        for k in SCORE_COLS+COUNT_COLUMNS+['y','reached','outcome_gid','outcome_t','outcome_start','outcome_opponent']:
            a=d['original_'+k][oi];b=saved[k][pos]
            good=np.allclose(a,b,rtol=1e-10,atol=2e-11,equal_nan=True) if a.dtype.kind in 'fi' else np.array_equal(a,b)
            if not good:raise RuntimeError('Original comparison feature reproduction failed: '+k)
        risk=design.prospective_risk(arrays(io.read(stream)),d,90)
        if not np.array_equal(risk['at_risk'][old],saved['at_risk_90'][pos]):raise RuntimeError('Full-stream cooldown does not reproduce original comparison')
        d['at_risk_90']=risk['at_risk'];d['history_complete']=d['history_window_complete']
        d['complete90']=d['anchor_ms']+90*DAY<core.PANEL_END
        # Original rows use their authenticated frozen classification; new rows
        # use the explicit metadata classification saved during preparation.
        all_known(d,['ordinary_narrow'])
        new=~d['previous_frame'].astype(bool)
        if not np.array_equal(d['ordinary_narrow'][new],np.isin(d['status'][new],list(core.NARROW))):
            raise RuntimeError('New ordinary-ending classification disagrees with metadata')
        all_known(d,['eligible_main','first_observed_pair','pre_games_30d']+COUNT_COLUMNS)
        design.validate_history(d,True)
        involved=authors.author_mask(d['recipient_id'],d['opponent_id'],author_ids)
        keep,flow=design.entry_mask(d,90)
        keep &= d['ordinary_narrow']&d['complete90']&~involved
        if np.any(d['y']&~d['reached']):raise RuntimeError('Kindness without reaching a choice')
        reached=d['reached'].astype(bool)
        if np.any(reached&((d['outcome_t']>d['anchor_ms']+90*DAY)|(d['outcome_t']<=d['anchor_ms'])|
            (d['outcome_start']<=d['anchor_ms'])|(d['outcome_opponent']==d['opponent_id'])|(d['outcome_gid']==d['game_id']))):
            raise RuntimeError('Invalid follow-up timing or opponent')
        # Save every assembled query with disposition; no incomplete window becomes a zero.
        feature_table=pa.table(dict(d,analysis_eligible=keep,author_game=involved))
        # Observed flags are distinct from the complete-window outcome, even in
        # synthetic/diagnostic queries that include incomplete windows.
        for name in ('y','reached'):
            feature_table=feature_table.append_column('observed_'+name,pa.array(d[name]))
            feature_table=feature_table.set_column(feature_table.schema.get_field_index(name),name,
                pa.array(d[name],mask=~d['complete90']))
        io.table(tmp/'features.parquet',feature_table)
        selected={k:v for k,v in d.items() if not k.startswith('original_')}
        groups={}
        for label,mask in [('new_cached',keep&~old),('old_author_clean',keep&old),('combined_cached',keep)]:
            sample={k:v[mask] for k,v in selected.items()}
            io.table(tmp/(label+'.parquet'),pa.table(sample));groups[label]=stats.describe(sample)
        flows=[]
        for label,mask in [('new_cached',~old),('old_original',old)]:
            subset={k:v[mask] for k,v in d.items()};sm,sf=design.entry_mask(subset,90)
            flows += [dict(sample=label,**r) for r in sf]
            flows.append(dict(sample=label,step='ordinary_complete90_and_author_exclusion',rows=int((keep&mask).sum())))
        io.js(tmp/'flow.json',flows)
        return dict(sample_accounting=groups,original_features_reproduced=int(old.sum()),
                    author_targets_excluded=int(involved.sum()),full_original_exposure_stream_preserved=True,
                    earlier_started_unanchored=int(risk['earlier_started_not_yet_anchored'].sum()))
    return stable_stage(root,conf,build,[queries,baseline,chronpath,stream]+scorepaths+outcomepaths)

def model_job(job):
    threads_one()
    def build(tmp):
        d=arrays(io.read(job['sample']));r=stats.estimate(d,SPEC)
        r['sample']=job['label'];r['sample_accounting']=stats.describe(d)
        for row in r['estimates']:
            row['sample']=job['label'];row['cached_sample_interim_diagnostic']=True
            if row.get('supported'):
                row['ci95_includes_direct_effect_0_020386_pp']=row['ci_low_pp']<=.020386<=row['ci_high_pp']
        io.js(tmp/'result.json',r);return dict(rows=len(d['row_id']))
    return stable_stage(Path(job['output']),job['conf'],build,[job['sample']])[1]

def export(root,desktop,conf,coverage,status,started,details=None):
    report=root/'report';report.mkdir(exist_ok=True)
    summary=dict(version=VERSION,status=status,config_sha256=conf,network_requests=0,stockfish_searches=0,
        cached_pool_games=sum(r['cached_pool_rows'] for r in coverage),
        cached_ordinary_games_before_final_filters=sum(r['ordinary_rows'] for r in coverage),
        full_expansion_equivalence_gate_cleared=False,abstract_gate_cleared=False,
        sample_is_cache_selected=True,stopping_rules_changed=False,
        elapsed_seconds=time.monotonic()-started,**(details or {}))
    ending=[r for c in coverage for r in c['ending_counts']]
    write_rows(report,'cached_endings',ending)
    rows=[]
    original=[dict(r,sample='historical_original') for r in io.load(VENDOR/'comparison_original/evidence/expanded_estimates.json') if r.get('specification')=='ordinary90_placebo']
    for label in ('new_cached','old_author_clean','combined_cached'):
        path=root/'models'/label/'result.json'
        if path.exists():rows.extend(io.load(path)['estimates'])
    summary['estimates']=rows;summary['historical_comparison']=original
    io.js(report/'summary.json',summary);write_rows(report,'estimates',original+rows)
    if (root/'assembled/flow.json').is_file():write_rows(report,'sample_flow',io.load(root/'assembled/flow.json'))
    text=['Cached ordinary-game placebo','',status,'',
        f"New cached pool games: {summary['cached_pool_games']:,}; ordinary endings before final filters: {summary['cached_ordinary_games_before_final_filters']:,}.",
        'Ordinary means mate, resign or stalemate. No API requests or Stockfish searches.',
        'Below 2,000 new ordinary rows, the program stops before historical reconstruction. Counts are an upper bound before remaining exclusions; an unsupported sample is not a zero-effect result.',
        'These cached games can differ from the fixed full expansion. Estimates describe the cached eligible sample; they do not clear the full-expansion, abstract, title or IV exclusion gate.',
        'historical_original is the saved earlier estimate. old_author_clean recomputes that sample with author exclusions. new_cached is the separate interim estimate. combined_cached describes their union and is not an independent replication.',
        'The original prospective spacing stream is retained. Author accounts are excluded from focal games, behavior histories, score reference fitting, and later choices. Their factual chess chronology remains.',
        'The outcome is kindness at the first later fair main-panel choice against a different opponent, with game start strictly after the focal lastMoveAt and choice within 90 days. A zero requires complete follow-up.',
        'The frozen controls and shared-account OR exposure-date CR0 inference are unchanged. Reused outcomes are counted, and generated scores are treated as fixed.',
        'The direct-effect comparison is approximately +0.020386 percentage points per fixed score SD; merely failing to reject zero does not establish exclusion.','']
    for r in original+rows:
        if r.get('outcome')!='y' and r.get('supported'):continue
        text.append((f"{r['sample']}: {r['coefficient_pp']:+.6f} pp per SD; 95% CI [{r['ci_low_pp']:+.6f}, {r['ci_high_pp']:+.6f}], N={r['n']:,}." if r.get('supported') else f"{r['sample']}: not estimated ({r.get('reason','unsupported')}); N={r.get('n',0):,}."))
    (report/'READ_RESULTS.txt').write_text('\n'.join(text)+'\n')
    report_zip(report,desktop,'RUN2_CACHED_ANALYSIS_REPORT_'+conf[:12])
    return summary

def coverage_status(total):
    if total<0:raise ValueError('Negative ordinary-game count')
    if total==0:return 'NO_NEW_CACHED_ORDINARY_GAMES'
    if total<stats.MIN_MODEL_ROWS:return 'INSUFFICIENT_CACHED_ORDINARY_GAMES'
    return 'COVERAGE_COMPLETE_ANALYSIS_PENDING'

def execute(a):
    no_network();started=time.monotonic();verify_release()
    a.project_root=a.project_root.resolve();a.desktop=a.desktop.resolve()
    a.workers=max(1,min(a.workers,10,int(max(1,(a.memory_gb-2)//1.5))))
    io.log(f'Local workers: {a.workers}; memory budget {a.memory_gb:g} GiB; API requests: zero')
    with io.heartbeat('Verifying completed local inputs'):local=authenticate(a)
    config=dict(version=VERSION,code_sha256=io.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
                local_plan=UPSTREAM_PLAN,local_receipts=local['input_receipts'],
                specification=SPEC,authors=list(AUTHORS),metadata_snapshot='completed_local_first_only')
    conf=io.cfgsha(config);root=a.project_root/ANALYSIS_REL/conf[:12];root.mkdir(parents=True,exist_ok=True)
    a.desktop.mkdir(parents=True,exist_ok=True)
    # Only this analysis owns this lock. The phased downloader can keep running.
    with (root/'RUN.lock').open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This cached analysis is already running')
        io.js(root/'config.json',config)
        jobs=[dict(ledger=p,metadata=inputs_code.metadata_for_month(local['metadata'],m),month=m,
            output=str(root/'coverage'/m),conf=conf,memory=a.memory_gb/a.workers)
            for m,p in zip(ex.MONTHS,local['ledgers'])]
        coverage=io.mapped(inputs_code.coverage_job,jobs,a.workers,'Cached ordinary-game coverage')
        if sum(r['cached_pool_rows'] for r in coverage)!=local['summary']['disposition_counts'].get('LOCAL_POOL_METADATA_READY',0):
            raise RuntimeError('Cached ending counts do not reproduce the completed local-first ledger')
        total=sum(r['ordinary_rows'] for r in coverage)
        status=coverage_status(total)
        export(root,a.desktop,conf,coverage,status,started,dict(new_sample_minimum_rows=stats.MIN_MODEL_ROWS,new_eligible_rows_upper_bound=total))
        io.log(f'New cached ordinary games before final checks: {total:,}')
        if status!='COVERAGE_COMPLETE_ANALYSIS_PENDING':
            io.log(f'{status}: at most {total:,} new ordinary rows, below the frozen {stats.MIN_MODEL_ROWS:,}-row model minimum. No history reconstruction or regressions started.')
            return
        with io.heartbeat('Authenticating history and chronology inputs'):source=inputs_code.research_inputs(a.project_root,a.workers)
        binding=root/'INPUTS_PRIVATE.json'
        if binding.exists() and io.cfgsha(io.load(binding))!=io.cfgsha(source):
            raise RuntimeError('Research input binding changed; completed analysis checkpoints were not reused')
        io.js(binding,source)
        ordinary=[str(root/'coverage'/m/'ordinary.parquet') for m in ex.MONTHS]
        with io.heartbeat('Reproducing the original placebo and preparing queries'):
            prepared,prepinfo=prepare_queries(ordinary,source['comparison'],root/'prepared',conf,a.memory_gb)
        queries=prepared/'queries.parquet'
        with io.heartbeat('Checking global account identities'):
            identity,identityinfo=inputs_code.identity_check(queries,source,root/'identity',conf,a.memory_gb,a.workers)
        ids=list(source['author_ids'].values())
        removedjobs=[dict(parts=[r['path'] for r in source['parts'] if r['month']==m],ids=ids,
            output=str(root/'removed'/m),conf=conf) for m in MONTHS]
        io.mapped(authors.extract_author_month,removedjobs,a.workers,'Removing author decisions from the historical reference')
        reference,_=authors.prepare_reference(source,[Path(j['output'])/'removed.parquet' for j in removedjobs],root/'reference',conf)
        scorejobs=[dict(queries=str(prepared/f'score_{s:02}.parquet'),parts=[r['path'] for r in source['parts'] if r['shard']==s],
            shard=s,reference=str(reference),authors=ids,conf=conf,output=str(root/'scores'/f'{s:02}')) for s in range(16)]
        io.mapped(histories.score_job,scorejobs,a.workers,'Exact author-clean leniency scores')
        hjobs=[dict(queries=str(queries),parts=[r['path'] for r in source['parts'] if r['month']==m],month=m,authors=ids,
            memory=a.memory_gb/a.workers,output=str(root/'history'/m),conf=conf) for m in MONTHS]
        io.mapped(histories.history_month_job,hjobs,a.workers,'Recipient histories')
        fjobs=[dict(queries=str(queries),panel=r['path'],memory=a.memory_gb/a.workers,output=str(root/'future'/f'{k:02}'),conf=conf)
            for k,r in enumerate(source['panels'])]
        io.mapped(histories.future_month_job,fjobs,a.workers,'Certified main-panel future choices')
        ojobs=[dict(queries=str(prepared/f'outcome_{s:02}.parquet'),shard=s,authors=ids,
            original_histories=[str(Path(j['output'])/f'original_{s:02}.parquet') for j in hjobs],
            clean_histories=[str(Path(j['output'])/f'clean_{s:02}.parquet') for j in hjobs],
            futures=[str(Path(j['output'])/f'{s:02}.parquet') for j in fjobs],output=str(root/'outcomes'/f'{s:02}'),conf=conf) for s in range(16)]
        io.mapped(histories.outcomes_job,ojobs,a.workers,'Complete 90-day outcomes')
        cprep,cpinfo=chronology.prepare_chronology(queries,root/'chron_queries',conf,a.memory_gb)
        if cpinfo['rows']:
            # Future files cannot affect any chronological feature; older files remain.
            chjobs=[dict(r,latest=cpinfo['latest_start'],people=str(cprep/'people.parquet'),pairs=str(cprep/'pairs.parquet'),
                focal=str(cprep/'focal.parquet'),memory=a.memory_gb/a.workers,conf=conf,output=str(root/'chron_parts'/f"{r['file_index']:04}"))
                for r in source['chron'] if r['minimum'] is None or r['minimum']<=cpinfo['latest_start']]
            chjobs.sort(key=lambda r:r['rows'],reverse=True)
            io.log(f'Chronology: {len(chjobs)} files; all earlier history retained. This is the longest local step.')
            io.mapped(chronology.chronology_job,chjobs,a.workers,'First meetings, adjacency and all-game volume')
            with io.heartbeat('Combining chronological features'):
                chrout,chrinfo=chronology.merge_chronology(queries,cprep,[Path(j['output']) for j in chjobs],root/'chronology',conf,a.memory_gb,a.workers)
        else:
            def empty(tmp):io.table(tmp/'features.parquet',pa.table({'row_id':pa.array([],type=pa.int64()),'eligible_main':pa.array([],type=pa.bool_()),'first_observed_pair':pa.array([],type=pa.bool_()),'pre_games_30d':pa.array([],type=pa.int64())}))
            chrout,chrinfo=io.stage(root/'chronology',conf,empty)
        with io.heartbeat('Assembling samples and verifying the original features'):
            assembled,assembly=combine(queries,prepared/'baseline_original.parquet',[str(Path(j['output'])/'scores.parquet') for j in scorejobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],chrout/'features.parquet',source['stream'],ids,root/'assembled',conf,a.memory_gb)
        mjobs=[dict(sample=str(assembled/(label+'.parquet')),label=label,output=str(root/'models'/label),conf=conf)
            for label in ('new_cached','old_author_clean','combined_cached')]
        # Each fit loads its full design matrix; cap simultaneous fits by memory.
        modelworkers=max(1,min(3,a.workers,int(a.memory_gb//4)))
        io.mapped(model_job,mjobs,modelworkers,'Frozen placebo regressions')
        export(root,a.desktop,conf,coverage,'CACHED_SAMPLE_PLACEBO_COMPLETE',started,
            dict(preparation={k:v for k,v in prepinfo.items() if k not in ('files','config_sha256')},
                 sample_accounting=assembly['sample_accounting'],original_features_reproduced=assembly['original_features_reproduced'],
                 workers=a.workers,memory_gb=a.memory_gb))

def main():
    workers,memory=defaults();p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=BASE);p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=workers);p.add_argument('--memory-gb',type=float,default=memory)
    p.add_argument('--plan',type=Path)
    a=p.parse_args()
    if a.workers<1 or a.memory_gb<3:p.error('Use at least one worker and 3 GiB memory')
    execute(a)

if __name__=='__main__':main()
