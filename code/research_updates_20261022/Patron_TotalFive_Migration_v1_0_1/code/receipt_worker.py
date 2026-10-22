"""Authenticate R12, reconstruct selection, and build only required Patron variants."""
import sys
from pathlib import Path
import migration_util as mu
sys.path.insert(0,str(mu.PACKAGE/'vendor_primary'))
import primary_common as pc
import primary_inputs as pi

def bind(a):
    a.r9_root=None;a.r12_root=a.project/'derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3'
    pc.frozen.u.no_network()
    b=pi.bind(a,a.run,a.conf)
    files=[('primary',b['primary']),('primary_scores',b['primary_scores']),('preminimum',b['raw']),('state_reference',b['bound']['reference'])]+[(f'alltime_score_shard_{s:02}',p) for s,p in enumerate(b['all_scores'])]
    mu.save(a.run/'report/receipt_input_hashes.json',[dict(role=role,sha256=mu.sha(path),bytes=Path(path).stat().st_size) for role,path in files])
    selected=pi.build_selection(a,a.run,a.conf,b)
    # This is the FULL accepted stream, before calendar/history cuts. It also
    # supplies the future entry labels; the final 3.1m frame is too late for this.
    c=pc.db(a.run/'PRIVATE/spill_stream',a.memory_gb-2)
    try:
        c.execute('CREATE VIEW raw AS SELECT * FROM '+pc.parq([b['raw']]))
        c.execute('CREATE VIEW s AS SELECT * FROM '+pc.parq([selected]))
        streamkey=pc.key([a.conf,pc.sha(b['raw']),pc.sha(selected),'full_pre_window_stream'])
        universe=a.run/'PRIVATE/selection_universe.parquet';stream=a.run/'PRIVATE/full_selected_stream90.parquet'
        if not pc.cached(universe,streamkey):
            pc.copy_query(c,'SELECT raw.* EXCLUDE(spaced30,spaced90,first_recipient),s.spaced30,s.spaced90,s.first_recipient,s.supported FROM raw JOIN s USING(row_id) ORDER BY row_id',universe);pc.seal(universe,streamkey)
        if not pc.cached(stream,streamkey):
            pc.copy_query(c,'SELECT * FROM '+pc.parq([universe])+' WHERE spaced90 ORDER BY recipient_id,archive_start_ms,row_id',stream);pc.seal(stream,streamkey)
        c.execute('CREATE VIEW q AS SELECT row_id FROM '+pc.parq([b['primary']]))
        wrong=c.execute('SELECT count(*) FROM q FULL JOIN (SELECT row_id FROM raw JOIN s USING(row_id) WHERE s.spaced90 AND s.observation_complete) n USING(row_id) WHERE q.row_id IS NULL OR n.row_id IS NULL').fetchone()[0]
        pc.require(wrong==0,'Recomputed selection differs from completed R12 row identities')
        info=c.execute('SELECT count(*),sum(supported),sum(spaced90),sum(spaced90 AND observation_complete),sum(first_recipient AND keep) FROM s').fetchone()
    finally:c.close()
    pc.save(a.run/'report/receipt_selection.json',dict(author_clean_candidates=info[0],total5_finite_supported=info[1],accepted_before_window_cuts=info[2],primary_exposures=info[3],first_observed_supported=info[4],primary_recipients=pc.EXPECTED_RECIPIENTS,exact_R12_row_set_reproduced=True,spacing_before_windows=True))
    mu.save(a.run/'PRIVATE/RECEIPT_PATHS.json',dict(primary=b['primary'],primary_scores=b['primary_scores'],old=b['bound']['s0'],old_scores=str(Path(b['bound']['parent'])/'scores_combined/S0.parquet'),selection=str(selected)))

def variants(a):
    import cutoffs, primary_scores
    a.r9_root=None;a.r12_root=a.project/'derived/replication/r12_r13_followups_v100_PRIVATE/4df83f1178f3'
    pc.frozen.u.no_network();b=pc.load(a.run/'PRIVATE/BOUND.json')
    p=mu.load(a.run/'PRIVATE/RECEIPT_PATHS.json');selected=Path(p['selection'])
    narrow=a.run/'PRIVATE/wider/patron_selection.parquet';ck=pc.key([a.conf,pc.sha(selected),'primary_and_first_observed_only'])
    if not pc.cached(narrow,ck):
        c=pc.db(a.run/'PRIVATE/spill_narrow',a.memory_gb-2)
        try:pc.copy_query(c,'SELECT * EXCLUDE(keep),keep AND (spaced90 OR first_recipient) AS keep FROM '+pc.parq([selected]),narrow);pc.seal(narrow,ck)
        finally:c.close()
    clean,known=pi.rebuild_wider_features(a,a.run,a.conf,b,narrow)
    volume=cutoffs.add_volume(a,dict(b['bound'],original=str(known)),clean,a.run/'PRIVATE/wider',a.conf)
    source=pi.environment(a,a.run,a.conf,b,volume)
    c=pc.db(a.run/'PRIVATE/spill_first',a.memory_gb-2)
    first=a.run/'PRIVATE/first_reference.parquet';score=a.run/'PRIVATE/first_reference_scores.parquet'
    try:
        firstkey=pc.key([a.conf,pc.sha(source),[pc.sha(p) for p in b['all_scores']]])
        if not pc.cached(first,firstkey):
            pc.copy_query(c,'SELECT * FROM '+pc.parq([source])+' WHERE first_recipient ORDER BY row_id',first);pc.seal(first,firstkey)
        if not pc.cached(score,firstkey):
            pc.copy_query(c,'SELECT s.* FROM '+pc.parq(b['all_scores'])+' s JOIN '+pc.parq([first])+' f USING(row_id) ORDER BY s.row_id',score);pc.seal(score,firstkey)
        pc.require(c.execute('SELECT count(*)-count(DISTINCT recipient_id) FROM '+pc.parq([first])).fetchone()[0]==0,'First observed candidate is not unique per recipient')
    finally:c.close()
    timing,flags=primary_scores.prepare(a,a.run,a.conf,b)
    p.update(first_reference=str(first),first_reference_scores=str(score),primary_timing_scores=str(timing))
    mu.save(a.run/'PRIVATE/RECEIPT_PATHS.json',p)

if __name__=='__main__':
    a=mu.parser().parse_args()
    with mu.pulse('Receipt '+a.mode):
        if a.mode=='bind':bind(a)
        elif a.mode=='variants':variants(a)
        else:raise ValueError(a.mode)
