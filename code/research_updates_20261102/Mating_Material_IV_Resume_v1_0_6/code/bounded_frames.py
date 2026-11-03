"""Original comparison definitions with narrow SQL lookups and streaming payloads."""
from bootstrap import *
import stream_frames
import pyarrow.compute as pc


def environment_attach(input_path,rates,root,conf,memory):
    """Same three-key inner join, bounded before the wide streaming attachment."""
    from environment_partitions import attach
    return attach(input_path,rates,root,conf,memory)


def label_frame(tmp,source,roles,raw,flags,memory):
    """Compute only five new columns in SQL; preserve every original source row."""
    lookup=tmp/'labels_by_row.parquet'
    db=connect(tmp,min(memory,6.))
    try:
        view(db,'q',source);view(db,'m',roles);c.ensure_unique(db,'m')
        view(db,'raw',raw);view(db,'flags',flags)
        c.ensure(db,"SELECT count(*) FROM q JOIN m USING(row_id) WHERE q.status<>'timeout' OR NOT ((q.recipient_id=m.i AND q.opponent_id=m.j) OR (q.recipient_id=m.j AND q.opponent_id=m.i))",'Main-panel role or focal-pair mismatch')
        db.execute('CREATE VIEW s AS SELECT raw.game_id,raw.recipient_id,flags.supported,flags.uniform_keep FROM raw JOIN flags USING(row_id)')
        c.ensure(db,'SELECT count(*) FROM (SELECT game_id,recipient_id FROM s GROUP BY 1,2 HAVING count(*)>1)','Duplicate receipt exposure key')
        copy(db,f'''SELECT q.row_id,
          coalesce(q.recipient_id=m.i,FALSE) recipient_disconnect_main,
          coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) recipient_fair_arm_main,
          coalesce(s.supported,FALSE) supported_receipt_entry,
          coalesce(s.uniform_keep,FALSE) analysis_entry_uniform90,
          q.anchor_ms+{90*DAY}<{int(c.phase_inputs.core.PANEL_END)} complete90
          FROM q LEFT JOIN m USING(row_id) LEFT JOIN s ON q.game_id=s.game_id AND q.recipient_id=s.recipient_id ORDER BY q.row_id''',lookup)
    finally:db.close()
    stream_frames.attach(source,[lookup],tmp/'model.parquet',replace=False,label='Attaching comparison labels')
    lookup.unlink()
    db=connect(tmp,4.)
    try:
        view(db,'l',tmp/'model.parquet')
        labels=['active_timeout','recipient_disconnect_main','recipient_fair_arm_main','supported_receipt_entry','analysis_entry_uniform90']
        c.ensure(db,'SELECT count(*) FROM l WHERE '+' OR '.join(f'({y} AND NOT {x})' for x,y in zip(labels[:-1],labels[1:])),'Entry labels not nested')
        save(tmp/'counts.json',{x:db.execute('SELECT count(*) FROM l WHERE '+x).fetchone()[0] for x in labels})
        return dict(rows=rows(source))
    finally:db.close()


def finish_frames(tmp,source,scores,memory):
    db=connect(tmp,min(memory,6.))
    try:
        view(db,'q',source);view(db,'s',scores);c.ensure_unique(db,'q');c.ensure_unique(db,'s')
        c.ensure(db,'SELECT count(*) FROM q WHERE NOT eligible_main OR NOT first_observed_pair OR tc_base_s<=0 OR NOT history_window_complete','Comparison eligibility rule failed')
        c.ensure(db,'SELECT count(*) FROM q LEFT JOIN s USING(row_id) WHERE s.row_id IS NULL OR n_A<5 OR NOT isfinite(adjusted_A) OR NOT isfinite(expected_A)','Comparison support incomplete')
        counts=[]
        for tag,where in [('F','TRUE'),('O','ordinary_narrow AND complete90')]:
            n,people=db.execute('SELECT count(*),count(DISTINCT recipient_id) FROM q WHERE '+where).fetchone()
            counts.append(dict(frame=tag,rows=n,recipients=people))
    finally:db.close()
    for count in counts:
        tag=count['frame']
        predicate=None if tag=='F' else lambda t:pc.and_kleene(t['ordinary_narrow'],t['complete90'])
        stream_frames.select(source,tmp/(tag+'.parquet'),predicate=predicate)
        stream_frames.select(scores,tmp/(tag+'_scores.parquet'),ids=tmp/(tag+'.parquet'))
        require(rows(tmp/(tag+'.parquet'))==rows(tmp/(tag+'_scores.parquet'))==count['rows'],
                'Final frame or aligned scores lost rows')
    save(tmp/'counts.json',counts)
    return dict(rows=rows(source))


def frames90(a,run,conf,b,receipt_run):
    import features
    import fast_comparisons as fc
    from environment_partitions import pool_rates,environment_rates
    src=run/'PRIVATE/metadata_complete/queries.parquet'
    src=features.behavior(a,run,conf,b['primary']['bound'],src)
    known=[a.legacy_root/'comparisons/PRIVATE/frames90/F.parquet']
    src=features.volume(a,run,conf,b['primary']['bound'],src,known,90)
    base=b['primary']['bound']['features'];jobs=[]
    for k,p in enumerate(base['futures']):
        roles=c.check_stage(Path(p)/'keys.parquet',base['main_conf'])
        jobs.append(dict(queries=str(src),keys=str(roles),memory=3.,conf=conf,output=str(run/'PRIVATE/roles'/f'{k:02}')))
    c.mapped(fc.fast.role_job,jobs,min(a.workers,2),'Expanded entry roles')
    roles=[str(Path(j['output'])/'roles.parquet') for j in jobs]
    flags=receipt_run/'PRIVATE/selection90/flags.parquet';raw=b['primary']['raw']
    labeled,_=stage(run/'PRIVATE/labeled90',conf,
        lambda tmp:label_frame(tmp,src,roles,raw,flags,a.memory_gb-2),[src,raw,flags]+roles)
    save(run/'report/entry_label_counts.json',read(labeled/'counts.json'))
    bb=dict(b['primary'],known_rates=[str(pool_rates(a,run,conf,b))])
    removed=Path(read(receipt_run/'PRIVATE/REMOVED_MAIN.json')['path'])
    source=features.environment(a,run,conf,bb,labeled/'model.parquet',removed,
                                rates_builder=environment_rates)
    scores=run/'PRIVATE/supported/scores.parquet'
    folder,_=stage(run/'PRIVATE/frames90',conf,
        lambda tmp:finish_frames(tmp,source,scores,a.memory_gb-2),[source,scores])
    c.csv_out(run/'report/comparison_frame_counts.csv',read(folder/'counts.json'))
