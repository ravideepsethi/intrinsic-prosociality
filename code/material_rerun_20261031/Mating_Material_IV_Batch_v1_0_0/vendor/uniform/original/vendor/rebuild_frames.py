"""Rebuild features, receipt-entry labels, ENV and both final populations."""
from rebuild_common import *

def features(a,run,conf,b):
    q=run/'PRIVATE/metadata_complete/queries.parquet'
    known=check_stage(Path(b['frame_root'])/'assembled/features.parquet',b['frame_conf'])
    fields=COUNTS+OUTCOMES+['history_window_complete']
    def reuse(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([q]));c.execute('CREATE VIEW k AS SELECT * FROM '+parq([known]))
            ensure(c,'SELECT count(*) FROM q JOIN k USING(game_id) WHERE '+' OR '.join('q.'+x+' IS DISTINCT FROM k.'+x for x in IDENTITY[1:]),'Old/new focal identities or timing changed')
            valid='k.y IS NOT NULL AND k.reached IS NOT NULL'
            copy_query(c,'SELECT q.row_id,'+','.join('k.'+x for x in fields)+' FROM q JOIN k USING('+','.join(IDENTITY)+') WHERE '+valid+' ORDER BY q.row_id',tmp/'hits.parquet')
            c.execute('CREATE VIEW hits AS SELECT * FROM '+parq([tmp/'hits.parquet']));ensure_unique(c,'hits')
            copy_query(c,'SELECT q.* FROM q ANTI JOIN hits USING(row_id) ORDER BY row_id',tmp/'missing.parquet')
            for s in range(16):copy_query(c,'SELECT * FROM '+parq([tmp/'missing.parquet'])+f' WHERE recipient_id%16={s} ORDER BY row_id',tmp/f'outcome_{s:02}.parquet')
            return dict(rows=pq.ParquetFile(q).metadata.num_rows,reused=pq.ParquetFile(tmp/'hits.parquet').metadata.num_rows,missing=pq.ParquetFile(tmp/'missing.parquet').metadata.num_rows)
        finally:c.close()
    prep,info=stage(run/'PRIVATE/behavior_plan',conf,reuse,[q,known])
    save(run/'report/behavior_reuse.json',{k:v for k,v in info.items() if k not in ('files','dependencies')})
    jobs=inputs.outcome_jobs(b['primary']['bound'],prep,run/'PRIVATE/behavior',conf)
    mapped(fast.outcome_job,jobs,min(2,a.workers),'Missing recipient histories and later choices')
    fresh=[str(Path(j['output'])/'outcomes.parquet') for j in jobs]
    def combine(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([q]))
            c.execute('CREATE VIEW h AS SELECT row_id,'+','.join(fields)+' FROM '+parq([prep/'hits.parquet'])+' UNION ALL SELECT row_id,'+','.join(fields)+' FROM '+parq(fresh))
            ensure_unique(c,'h');ensure(c,'SELECT count(*) FROM q FULL JOIN h USING(row_id) WHERE q.row_id IS NULL OR h.row_id IS NULL','Behavior join lost rows')
            copy_query(c,'SELECT q.*,h.* EXCLUDE(row_id) FROM q JOIN h USING(row_id) ORDER BY row_id',tmp/'features.parquet')
            end=int(phase_inputs.core.PANEL_END)
            ensure(c,'SELECT count(*) FROM '+parq([tmp/'features.parquet'])+f' WHERE NOT history_window_complete OR archive_start_ms+{90*DAY}>={end}','Invalid entry observation window')
            ensure(c,'SELECT count(*) FROM '+parq([tmp/'features.parquet'])+' WHERE y AND NOT reached','Grant without a later opportunity')
            ensure(c,'SELECT count(*) FROM '+parq([tmp/'features.parquet'])+f''' WHERE reached AND (outcome_t<=anchor_ms OR outcome_t>anchor_ms+{90*DAY}
              OR outcome_start<=anchor_ms OR outcome_opponent=opponent_id OR outcome_gid=game_id)''','Invalid later-choice timing or focal-pair exclusion')
            return dict(rows=pq.ParquetFile(q).metadata.num_rows)
        finally:c.close()
    combined,_=stage(run/'PRIVATE/behavior_combined',conf,combine,[q,prep/'hits.parquet']+fresh)
    return combined/'features.parquet'

def labels(a,run,conf,b,source):
    base=b['primary']['bound']['features'];jobs=[]
    for k,p in enumerate(base['futures']):
        keys=check_stage(Path(p)/'keys.parquet',base['main_conf'])
        jobs.append(dict(queries=str(source),keys=str(keys),memory=3.,conf=conf,output=str(run/'PRIVATE/roles'/f'{k:02}')))
    mapped(fast.role_job,jobs,min(2,a.workers),'Entry main-panel roles')
    roles=[str(Path(j['output'])/'roles.parquet') for j in jobs];stream=candidate_root(run,b)/'PRIVATE/receipt_stream/stream.parquet'
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+parq([source]));c.execute('CREATE VIEW m AS SELECT * FROM '+parq(roles));ensure_unique(c,'m')
            c.execute('CREATE VIEW s AS SELECT * FROM '+parq([stream]))
            ensure(c,"SELECT count(*) FROM q JOIN m USING(row_id) WHERE q.status<>'timeout' OR NOT ((q.recipient_id=m.i AND q.opponent_id=m.j) OR (q.recipient_id=m.j AND q.opponent_id=m.i))",'Focal main-panel role conflict')
            sql='''SELECT q.*,
              coalesce(q.recipient_id=m.i,FALSE) recipient_disconnect_main,
              coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) recipient_fair_arm_main,
              coalesce(s.rebuilt_spaced90,FALSE) selected_entry_90,
              coalesce(s.rebuilt_spaced90 AND s.rebuilt_observation_complete,FALSE) analysis_entry_90,
              q.anchor_ms+'''+str(90*DAY)+'<'+str(int(phase_inputs.core.PANEL_END))+''' complete90
              FROM q LEFT JOIN m USING(row_id) LEFT JOIN s ON q.game_id=s.game_id AND q.recipient_id=s.recipient_id ORDER BY q.row_id'''
            copy_query(c,sql,tmp/'model.parquet');c.execute('CREATE VIEW result AS SELECT * FROM '+parq([tmp/'model.parquet']));ensure_unique(c,'result',pq.ParquetFile(source).metadata.num_rows)
            ensure(c,'SELECT count(*) FROM result WHERE '+' OR '.join(f'({y} AND NOT {x})' for x,y in zip(ENTRY[:-1],ENTRY[1:])),'Rebuilt entry labels are not nested')
            events={x:c.execute('SELECT count(*) FROM result WHERE '+x).fetchone()[0] for x in ENTRY}
            save(tmp/'labels.json',dict(rows=pq.ParquetFile(source).metadata.num_rows,events=events));return dict(rows=pq.ParquetFile(source).metadata.num_rows)
        finally:c.close()
    folder,_=stage(run/'PRIVATE/labeled',conf,build,[source,stream]+roles)
    save(run/'report/entry_label_counts.json',load(folder/'labels.json'))
    return folder/'model.parquet'

def pool_rates(a,run,conf,b):
    paths=b['primary']['known_rates']
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            keys=['person','partner','month_code'];columns=pq.ParquetFile(paths[0]).schema_arrow.names;values=[x for x in columns if x not in keys]
            union=' UNION ALL '.join('SELECT '+str(k)+' priority,* FROM '+parq([p]) for k,p in enumerate(paths))
            c.execute('CREATE VIEW rates AS '+union)
            tests=[]
            schema=pq.ParquetFile(paths[0]).schema_arrow
            for x in values:
                if pa.types.is_floating(schema.field(x).type):tests.append(f'(max({x})-min({x})>2e-12)')
                else:tests.append('count(DISTINCT '+x+')>1')
                tests.append(f'(count({x})>0 AND count({x})<count(*))')
            ensure(c,'SELECT count(*) FROM (SELECT '+','.join(keys)+' FROM rates GROUP BY '+','.join(keys)+' HAVING '+' OR '.join(tests)+')','Existing ENV caches disagree')
            copy_query(c,'SELECT * EXCLUDE(priority) FROM rates QUALIFY row_number() OVER(PARTITION BY '+','.join(keys)+' ORDER BY priority)=1',tmp/'rates.parquet')
            return dict(rows=pq.ParquetFile(tmp/'rates.parquet').metadata.num_rows)
        finally:c.close()
    return stage(run/'PRIVATE/rate_pool',conf,build,paths)[0]/'rates.parquet'

def assemble(a,run,conf,b):
    src=labels(a,run,conf,b,features(a,run,conf,b))
    bb=dict(b['primary'],known_rates=[str(pool_rates(a,run,conf,b))])
    src=primary.environment(a,run,conf,bb,src)
    if isinstance(src,tuple):src=src[0]
    scores=candidate_root(run,b)/'PRIVATE/supported/scores.parquet'
    def build(tmp):
        c=connection(tmp,a.memory_gb-2)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM '+parq([src]));c.execute('CREATE VIEW s AS SELECT * FROM '+parq([scores]))
            ensure_unique(c,'f');ensure_unique(c,'s')
            ensure(c,'SELECT count(*) FROM f LEFT JOIN s USING(row_id) WHERE s.row_id IS NULL OR s.n_A<5 OR NOT isfinite(s.adjusted_A) OR NOT isfinite(s.expected_A)','Final frame has missing or unsupported scores')
            ensure(c,'SELECT count(*) FROM f WHERE NOT eligible_main OR NOT first_observed_pair OR NOT at_risk_90 OR tc_base_s<=0','Final frame violates a local eligibility rule')
            overlap=[]
            for tag,where in [('F','TRUE'),('O','ordinary_narrow AND complete90')]:
                omit=OUTCOMES if tag=='F' else []
                fields='f.*'+(' EXCLUDE('+','.join(omit)+')' if omit else '')
                copy_query(c,'SELECT '+fields+' FROM f WHERE '+where+' ORDER BY row_id',tmp/(tag+'.parquet'))
                copy_query(c,'SELECT s.* FROM s JOIN f USING(row_id) WHERE '+where+' ORDER BY row_id',tmp/(tag+'_scores.parquet'))
                c.execute('CREATE OR REPLACE VIEW newf AS SELECT * FROM '+parq([tmp/(tag+'.parquet')]))
                c.execute('CREATE OR REPLACE VIEW oldf AS SELECT * FROM '+parq([b['old_paths'][tag]]))
                n,people=c.execute('SELECT count(*),count(DISTINCT recipient_id) FROM newf').fetchone()
                require(pq.ParquetFile(tmp/(tag+'_scores.parquet')).metadata.num_rows==n,'Frame/score row count mismatch')
                oldn,oldpeople=c.execute('SELECT count(*),count(DISTINCT recipient_id) FROM oldf').fetchone()
                retained=c.execute('SELECT count(*) FROM newf JOIN oldf USING(game_id)').fetchone()[0]
                commonpeople=c.execute('SELECT count(*) FROM (SELECT DISTINCT recipient_id FROM newf INTERSECT SELECT DISTINCT recipient_id FROM oldf)').fetchone()[0]
                ensure(c,'SELECT count(*) FROM newf JOIN oldf USING(game_id) WHERE '+' OR '.join('newf.'+k+' IS DISTINCT FROM oldf.'+k for k in IDENTITY[1:]+COUNTS+['pre_games_30d']),'Reusable comparison features changed on common rows')
                if tag=='O':
                    ensure(c,'SELECT count(*) FROM newf JOIN oldf USING(game_id) WHERE '+' OR '.join('newf.'+k+' IS DISTINCT FROM oldf.'+k for k in ['y','reached']),'Ordinary outcomes changed on common rows')
                c.execute('CREATE OR REPLACE VIEW oldscore AS SELECT * FROM '+parq([b['old_scores'][tag]]))
                tests=['s.'+k+' IS DISTINCT FROM os.'+k for k in ('n_A','counterparts_A')]
                tests += ['NOT coalesce(abs(s.'+k+'-os.'+k+')<=2e-10,FALSE)' for k in ('adjusted_A','expected_A')]
                ensure(c,'SELECT count(*) FROM newf n JOIN oldf o USING(game_id) JOIN s ON n.row_id=s.row_id LEFT JOIN oldscore os ON o.row_id=os.row_id WHERE '+' OR '.join(tests),'Score A or its donor controls changed on common comparison games')
                overlap.append(dict(frame=tag,rows=n,recipients=people,old_rows=oldn,retained_rows=retained,added_rows=n-retained,removed_rows=oldn-retained,
                  old_recipients=oldpeople,retained_recipients=commonpeople,added_recipients=people-commonpeople,removed_recipients=oldpeople-commonpeople,common_score_A_and_controls_reproduced=True))
            save(tmp/'overlap.json',overlap)
            return dict(frames=overlap,alltime_support=True,receipt_cooldown_rebuilt=True)
        finally:c.close()
    folder,_=stage(run/'PRIVATE/frames',conf,build,[src,scores]+[b[k][x] for k in ('old_paths','old_scores') for x in ('F','O')])
    csv_out(run/'report/frame_overlap.csv',load(folder/'overlap.json'))
    change_audit(a,run,conf,b,folder)
    return folder

def change_audit(a,run,conf,b,frames):
    """Trace changed rows to the recorded screens; export aggregate reasons only."""
    paths=dict(d=candidate_root(run,b)/'PRIVATE/candidates/dispositions.parquet',
      s=candidate_root(run,b)/'PRIVATE/supported/support_dispositions.parquet',
      x=run/'PRIVATE/chronology/features.parquet',m=run/'PRIVATE/metadata_complete/dispositions.parquet',
      legacy_stream=Path(b['source']['stream']))
    fr=Path(b['frame_root']);fc=b['frame_conf']
    for name,rel in [('oldq','prepared/queries.parquet'),('olde','early/dispositions.parquet'),('olds','support/dispositions.parquet')]:
        paths[name]=check_stage(fr/rel,fc)
    def build(tmp):
        c=connection(tmp,a.memory_gb-2);rows=[]
        try:
            for name,path in paths.items():c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+parq([path]))
            for tag in ('F','O'):
                c.execute('CREATE OR REPLACE VIEW newf AS SELECT * FROM '+parq([frames/(tag+'.parquet')]))
                c.execute('CREATE OR REPLACE VIEW oldf AS SELECT * FROM '+parq([b['old_paths'][tag]]))
                c.execute('CREATE OR REPLACE VIEW added AS SELECT n.* FROM newf n ANTI JOIN oldf o USING(game_id)')
                c.execute('CREATE OR REPLACE VIEW removed AS SELECT o.* FROM oldf o ANTI JOIN newf n USING(game_id)')
                sql=f'''SELECT a.row_id,a.game_id,a.recipient_id,'added' AS direction,
                  CASE WHEN a.legacy_prior_count<5 THEN 'old_prior_support_below_five'
                    WHEN p.anchor_ms IS NOT NULL AND a.archive_start_ms<=p.anchor_ms+{90*DAY} THEN 'old_receipt_cooldown'
                    WHEN oq.row_id IS NULL THEN 'old_prepared_pool_or_calendar_screen'
                    WHEN e.reason IS DISTINCT FROM 'KEEP' THEN 'old_early_'||coalesce(e.reason,'missing')
                    WHEN s.keep IS DISTINCT FROM TRUE THEN 'old_lag7_score_support'
                    ELSE 'UNEXPLAINED' END AS reason
                  FROM added a ASOF LEFT JOIN legacy_stream p ON a.recipient_id=p.recipient_id AND a.archive_start_ms>p.anchor_ms
                  LEFT JOIN oldq oq ON a.game_id=oq.game_id LEFT JOIN olde e ON oq.row_id=e.row_id LEFT JOIN olds s ON oq.row_id=s.row_id'''
                copy_query(c,sql,tmp/(tag+'_added_PRIVATE.parquet'))
                # First failed new screen in production order; unchanged rules are audited too.
                sql='''SELECT o.row_id,o.game_id,o.recipient_id,'removed' AS direction,
                  CASE WHEN d.row_id IS NULL THEN 'UNEXPLAINED'
                    WHEN d.previous_frame THEN 'old_pilot_sample'
                    WHEN NOT d.author_clean THEN 'author_focal_game'
                    WHEN NOT d.history_complete THEN 'history97'
                    WHEN NOT d.start_calendar_complete THEN 'start_calendar90'
                    WHEN NOT d.at_risk_90 THEN 'new_receipt_cooldown'
                    WHEN s.total_five_supported IS DISTINCT FROM TRUE THEN 'alltime_score_support'
                    WHEN x.eligible_main IS DISTINCT FROM TRUE THEN 'chronological_predecessor'
                    WHEN x.first_observed_pair IS DISTINCT FROM TRUE THEN 'first_pair'
                    WHEN m.inherited_quarantine THEN 'inherited_metadata_quarantine'
                    WHEN m.disposition='CACHED_NONPOOL' THEN 'nonpool_metadata'
                    ELSE 'UNEXPLAINED' END AS reason
                  FROM removed o LEFT JOIN d ON o.game_id=d.game_id LEFT JOIN s ON d.row_id=s.row_id
                  LEFT JOIN x ON d.row_id=x.row_id LEFT JOIN m ON d.row_id=m.row_id'''
                copy_query(c,sql,tmp/(tag+'_removed_PRIVATE.parquet'))
                c.execute('CREATE OR REPLACE VIEW changes AS SELECT * FROM '+parq([tmp/(tag+'_added_PRIVATE.parquet'),tmp/(tag+'_removed_PRIVATE.parquet')]))
                rows += [dict(frame=tag,direction=di,reason=re,rows=n,recipients=people)
                  for di,re,n,people in c.execute('SELECT direction,reason,count(*),count(DISTINCT recipient_id) FROM changes GROUP BY 1,2 ORDER BY 1,2').fetchall()]
            save(tmp/'reasons.json',rows)
            csv_out(run/'report/frame_change_reasons.csv',rows)
            require(not any(v['reason']=='UNEXPLAINED' for v in rows),'Unexplained comparison membership changes; inspect private row audit before estimating')
            return dict(changed_rows=sum(v['rows'] for v in rows),unexplained=0,
              recipients_may_appear_in_multiple_reason_groups=True)
        finally:c.close()
    folder,_=stage(run/'PRIVATE/overlap_audit',conf,build,list(paths.values())+
      [frames/(t+'.parquet') for t in ('F','O')]+[b['old_paths'][t] for t in ('F','O')])
    csv_out(run/'report/frame_change_reasons.csv',load(folder/'reasons.json'))
