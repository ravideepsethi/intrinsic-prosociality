"""Consolidate new metadata and reclassify only formerly unresolved rows."""
from collections import Counter
from common import *

def finish(work,plan,contract,batches,threads):
    root=work/'final';root.mkdir(exist_ok=True);auth=work/'authentication'
    binding=digest(dict(plan=plan['binding'],batches=[dict(path=str(r['root']),sha256=sha(Path(r['root'])/'_DONE.json')) for r in batches]))
    ready=root/'SOURCE_SUPPLEMENT_READY_PRIVATE.json'
    if ready.is_file():
        done=load(ready)
        if done['binding']!=binding:raise RuntimeError('Completed API supplement has a different binding')
        for r in done['files']:checked(root/r['path'],r,auth)
        return done
    c=connection(root,threads);parts=[]
    try:
        # Consolidate at most 100 request files per output part. This avoids an
        # enormous open-file set and lets interrupted consolidation resume.
        for offset in range(0,len(batches),100):
            group=batches[offset:offset+100];i=offset//100
            part=root/f'metadata-part-{i:05d}_PRIVATE.parquet';rp=part.with_suffix('.receipt.json')
            part_binding=digest([dict(path=r['root'],binding=r['done']['binding'],files=r['done']['files'][0]) for r in group])
            if rp.is_file():
                r=load(rp)
                if r['binding']!=part_binding:raise RuntimeError('Consolidation part binding changed')
                checked(part,r['file'],auth)
            else:
                paths=[Path(r['root'])/'metadata_PRIVATE.parquet' for r in group]
                temp=part.with_suffix('.parquet.partial')
                if temp.exists():temp.unlink()  # Disposable output of this stage only.
                c.execute('COPY (SELECT * FROM '+scan(paths)+') TO '+lit(temp)+' (FORMAT PARQUET, COMPRESSION ZSTD)')
                os.replace(temp,part)
                write_json(rp,dict(binding=part_binding,file=receipt(part,root)))
            parts.append(part)
            if i%10==0:log(f'Consolidated {min(offset+100,len(batches)):,}/{len(batches):,} API batches')
        c.execute('CREATE VIEW r AS SELECT * FROM '+scan(parts))
        total,unique=c.execute('SELECT count(*),count(DISTINCT game_id) FROM r').fetchone()
        if (total,unique)!=(plan['total_ids'],plan['total_ids']):raise RuntimeError('API metadata has missing or duplicate target rows')
        coverage=query_rows(c,'''SELECT month,record_status,count(*) AS rows FROM r GROUP BY ALL ORDER BY 1,2''')
        source_counts=query_rows(c,"SELECT month,source,count(*) AS rows FROM r WHERE record_status='validated_source' GROUP BY ALL ORDER BY 1,2")
        field_coverage=query_rows(c,'''SELECT month,count(*) target_rows,
          count(*) FILTER(WHERE record_status<>'not_returned_after_retries') returned_rows,
          count(*) FILTER(WHERE api_last_move_at_ms>=api_created_at_ms) usable_last_move_rows,
          count(*) FILTER(WHERE white_user_id IS NOT NULL AND black_user_id IS NOT NULL) both_player_ids_rows,
          count(*) FILTER(WHERE white_rating IS NOT NULL AND black_rating IS NOT NULL) both_ratings_rows,
          count(*) FILTER(WHERE clocks_count>0) clock_history_rows,
          count(*) FILTER(WHERE clock_initial_s IS NOT NULL AND clock_increment_s IS NOT NULL) time_control_rows
          FROM r GROUP BY 1 ORDER BY 1''')
        supplements=[];deltas=[];flow=[]
        for month in MONTHS:
            supplemental=root/f'source-supplement-{month}_PRIVATE.parquet'
            copy_query=f'''SELECT game_id,month,
              CASE WHEN record_status='validated_source' THEN source END AS source,
              CASE WHEN record_status='validated_source' THEN 'recovered' ELSE record_status END AS source_status,
              CASE WHEN record_status='validated_source' THEN 'receipt_iv_source_api_v100:'||native_attempt END AS source_provenance,
              CASE WHEN record_status='not_returned_after_retries' THEN 0 ELSE 1 END AS evidence_rows,
              CASE WHEN source IS NULL OR source='' THEN 0 ELSE 1 END AS distinct_sources
              FROM r WHERE month={lit(month)}'''
            atomic_copy(c,copy_query,supplemental);supplements.append(supplemental)
            old=Path(contract['membership'][month]['path'])
            checked(old,contract['membership'][month],auth)
            c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+scan(old))
            c.execute('CREATE OR REPLACE VIEW s AS SELECT * FROM '+scan(supplemental))
            wrong=c.execute("SELECT count(*) FROM m JOIN s USING(game_id,month) WHERE m.source_status<>'missing' OR m.source IS NOT NULL").fetchone()[0]
            if wrong:raise RuntimeError('Source pull would overwrite an already-classified game')
            eligibility="""CASE WHEN s.source_status<>'recovered' OR s.source IS NULL THEN NULL
              WHEN s.source<>'pool' THEN FALSE
              WHEN m.previous_classification_status='not_mutually_adjacent_observed' THEN TRUE
              WHEN m.previous_classification_status='mutual_adjacency_candidate_timing_unresolved' THEN FALSE
              ELSE NULL END"""
            delta=root/f'membership-delta-{month}_PRIVATE.parquet'
            q=f'''SELECT m.game_id,m.month,s.source,s.source_status,s.source_provenance,
              m.previous_classification_status,m.mutual_previous_same_pair,
              {eligibility} pool_nonadjacent_eligible,NULL::BOOLEAN final_iv_eligible
              FROM m JOIN s USING(game_id,month)'''
            atomic_copy(c,q,delta);deltas.append(delta)
            n=pq.ParquetFile(delta).metadata.num_rows
            if n!=EXPECTED[month]:raise RuntimeError('Cached membership join changed target count')
            rows=query_rows(c,'''SELECT month,count(*) target_rows,
              count(*) FILTER(WHERE pool_nonadjacent_eligible) additional_known_main_rows,
              count(*) FILTER(WHERE pool_nonadjacent_eligible IS FALSE) known_excluded_rows,
              count(*) FILTER(WHERE pool_nonadjacent_eligible IS NULL) unresolved_membership_rows
              FROM '''+scan(delta)+' GROUP BY 1')
            flow+=rows
        bad=sum(r['rows'] for r in coverage if r['record_status']!='validated_source')
        before=contract['known_main_rows_before'];added=sum(r['additional_known_main_rows'] for r in flow)
        summary=dict(status='SOURCE_PULL_COMPLETE' if not bad else 'SOURCE_PULL_FINISHED_WITH_UNRESOLVED_IDS',
            target_rows=total,validated_source_rows=total-bad,unresolved_source_rows=bad,
            coverage=coverage,source_counts=source_counts,field_coverage=field_coverage,membership_delta=flow,
            known_main_rows_before=before,additional_known_main_rows=added,known_main_rows_after_supplement=before+added,
            source_labels_from_API_only=True,final_IV_sample_rows=None,new_IV_estimate=None,
            broad_incident_denominator_reconstructed=False,hidden_rating_states_reconstructed=False,
            clocks_are_centiseconds=True,clocks_not_used_to_redefine_opportunities=True)
        all_files=[*parts,*supplements,*deltas]
        done=dict(binding=binding,plan_binding=plan['binding'],files=[receipt(p,root) for p in all_files],
            metadata_parts=[str(p) for p in parts],source_supplements=[str(p) for p in supplements],
            membership_deltas=[str(p) for p in deltas],summary=summary,
            original_cohort_ready=contract['cohort_ready_path'],
            next_step='Assemble choices and join existing all-source IV scores using the supplement; do not recompute chronology or scores')
        write_json(ready,done);return done
    finally:c.close()

def atomic_copy(c,query,path):
    temp=path.with_suffix('.parquet.partial')
    if temp.exists():temp.unlink()
    c.execute('COPY ('+query+') TO '+lit(temp)+' (FORMAT PARQUET, COMPRESSION ZSTD)')
    os.replace(temp,path)
