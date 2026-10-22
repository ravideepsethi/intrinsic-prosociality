"""Audit the FULL acquisition denominator; never relabel a filtered query as a rebuild."""
import sys,csv
from pathlib import Path
import migration_util as mu
from comparison_logic import total_count_query,metadata_query
sys.path.insert(0,str(mu.PACKAGE/'vendor_phase100/code'))
from phase100_common import *
import phase100_inputs as checkpoint
import cached_inputs as cache_inputs

def table(out,name,data):
    data=list(data);mu.save(out/(name+'.json'),data)
    keys=list(dict.fromkeys(k for r in data for k in r)) or ['status']
    with (out/(name+'.csv')).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(data)
def rows(c,sql):
    cur=c.execute(sql);names=[r[0] for r in cur.description];return [dict(zip(names,r)) for r in cur.fetchall()]

def run(a):
    no_network();a.project_root=a.project;a.plan=None
    local=authenticate(a);phase=checkpoint.authenticate_checkpoint(a,local)
    source=mu.load(a.run/'PRIVATE/BOUND.json')['bound'];parts=source['parts'];ids=source['binding']['author_ids']
    root=a.run/'PRIVATE/comparison_audit';root.mkdir(parents=True,exist_ok=True)
    conf=a.conf;authors_sql=','.join(map(str,ids))
    # All grant-or-claim decisions, both before and after each candidate.
    def counts_build(tmp):
        for rec in parts:io.checked(rec['path'],rec['sha256'],rec.get('bytes'))
        c=io.conn(tmp/'spill',a.memory_gb-2,1)
        try:
            clean='arm AND j NOT IN ('+authors_sql+') AND i NOT IN ('+authors_sql+')'
            io.copy(c,'SELECT j,i,count(*)::BIGINT n FROM '+io.parq([r['path'] for r in parts])+' WHERE '+clean+' GROUP BY j,i',tmp/'pair_counts.parquet')
            io.copy(c,'SELECT j,sum(n)::BIGINT n FROM '+io.parq([tmp/'pair_counts.parquet'])+' GROUP BY j',tmp/'person_counts.parquet')
            return dict(source_rows=sum(r['rows'] for r in parts),all_time_decisions=True,both_author_roles_excluded=True)
        finally:finish_connection(c,tmp/'spill')
    counts=stable_stage(root/'counts',conf,counts_build,[r['path'] for r in parts])[0]
    # The original cache can contain formerly excluded games that never entered
    # the local-first candidate cache. Read all three authenticated snapshots.
    original=local['manifest']['original_cached_metadata']
    mu.require(isinstance(original,str),'Unexpected original metadata reference schema')
    original_path=Path(original)
    mu.require(io.complete(original_path.parent,PREP_CONF) is not None,'Original preparation metadata cache is incomplete')
    caches=[('original',original),('local_first',local['metadata']),('phase100',phase['metadata'])]
    seen=set();caches=[(label,p) for label,p in caches if not (p in seen or seen.add(p))]
    allrows=[];dependencies=[]
    for month,ledger in zip(ex.MONTHS,local['ledgers']):
        metadata=[(label,cache_inputs.metadata_for_month(p,month)) for label,p in caches]
        inputs=[ledger,str(counts/'pair_counts.parquet'),str(counts/'person_counts.parquet')]+[p for _,ps in metadata for p in ps]
        dependencies += inputs
        def build(tmp,month=month,ledger=ledger,metadata=metadata):
            c=io.conn(tmp/'spill',a.memory_gb-2,1)
            try:
                c.execute('CREATE VIEW pairs AS SELECT * FROM '+io.parq([counts/'pair_counts.parquet']))
                c.execute('CREATE VIEW people AS SELECT * FROM '+io.parq([counts/'person_counts.parquet']))
                q=total_count_query(io.parq([ledger]))
                io.copy(c,q,tmp/'denominator_PRIVATE.parquet')
                c.execute('CREATE VIEW d AS SELECT * FROM '+io.parq([tmp/'denominator_PRIVATE.parquet']))
                mu.require(c.execute('SELECT count(*) FROM d WHERE total_pair_excluded_decisions<0 OR total_pair_excluded_decisions<n7_author_clean').fetchone()[0]==0,'All-time decision count is below historical clean count')
                mu.require(c.execute('SELECT count(*) FROM d').fetchone()[0]==pq.ParquetFile(ledger).metadata.num_rows,'Full ledger join changed denominator')
                # Count support is necessary, not a claim to final finite-score,
                # pool, identity, first-pair, cooldown, or complete-window support.
                pred='NOT author_game AND prior_97d_complete AND n7_author_clean<5 AND total_pair_excluded_decisions>=5'
                io.copy(c,'SELECT * FROM d WHERE '+pred,tmp/'new_count_supported_PRIVATE.parquet')
                c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([tmp/'new_count_supported_PRIVATE.parquet']))
                fingerprints=['source','status','api_start_ms','anchor_ms','rated','variant','speed','tc_base_s','tc_inc_s','white_username','black_username','white_rating','black_rating','winner']
                statuspaths=[]
                for label,paths in metadata:
                    c.execute('CREATE OR REPLACE VIEW m AS SELECT * FROM '+io.parq(paths))
                    mu.require(c.execute('SELECT count(*)-count(DISTINCT game_id) FROM m').fetchone()[0]==0,'Duplicate metadata game within immutable snapshot')
                    fp='sha256(to_json(struct_pack('+','.join(k+':=m.'+k for k in fingerprints)+')))'
                    status=tmp/(label+'_status_PRIVATE.parquet')
                    io.copy(c,'SELECT f.game_id,('+original_plan.readiness_sql()+') metadata_status,'+fp+' fingerprint FROM f LEFT JOIN m USING(game_id)',status);statuspaths.append(status)
                c.execute('CREATE VIEW statuses AS SELECT * FROM '+io.parq(statuspaths))
                query=metadata_query()
                io.copy(c,query,tmp/'metadata_disposition_PRIVATE.parquet')
                summary=rows(c,'SELECT '+io.lit(month)+' AS "month",status,count(*) candidate_games FROM ('+query+') GROUP BY status ORDER BY status')
                io.copy(c,'SELECT f.*,s.status FROM f JOIN '+io.parq([tmp/'metadata_disposition_PRIVATE.parquet'])+" s USING(game_id) WHERE s.status NOT IN ('CACHED_POOL_METADATA','CACHED_NONPOOL')",tmp/'unresolved_candidates_PRIVATE.parquet')
                totals=rows(c,'SELECT '+io.lit(month)+' AS "month",count(*) full_frame_games,count(*) FILTER(WHERE NOT author_game AND prior_97d_complete AND n7_author_clean<5) old_low_prior_exclusions,count(*) FILTER(WHERE '+pred+') newly_count_supported FROM d')[0]
                mu.save(tmp/'summary.json',dict(totals=totals,metadata=summary))
                return totals
            finally:finish_connection(c,tmp/'spill')
        folder,info=stable_stage(root/month,conf,build,inputs)
        allrows.append(mu.load(folder/'summary.json'));mu.log('Full-denominator metadata audit completed '+month)
    report=a.run/'report'
    table(report,'comparison_full_denominator',[r['totals'] for r in allrows])
    table(report,'comparison_new_support_metadata',[s for r in allrows for s in r['metadata']])
    n=sum(r['totals']['newly_count_supported'] for r in allrows)
    unresolved=sum(s['candidate_games'] for r in allrows for s in r['metadata'] if s['status'] not in ('CACHED_POOL_METADATA','CACHED_NONPOOL'))
    mu.save(report/'comparison_next_step.json',dict(status='PRELIMINARY_FULL_DENOMINATOR_METADATA_AUDIT_COMPLETE',newly_count_supported_candidates=n,metadata_missing_conflicted_or_needing_legacy_source=unresolved,final_API_target_count=None,final_population_rebuilt=False,
        required_next_steps=['Compute finite pair-excluded Score A and expected rates on count-supported candidates; use current source authority.', 'Resolve only metadata gaps surviving applicable outcome-independent gates. Missing metadata is not an ordinary/nonpool classification.', 'Rebuild first-pair/adjacency, histories/outcomes, and cooldown from full_selected_stream90, before final model window cuts.', 'Recompute selected_entry_90 and analysis_entry_90 labels from the rebuilt receipt selection; old entry outcomes describe the old algorithm.', 'Fit new F/O populations and joint receipt-minus-ordinary account/date contrasts; then attach original badge snapshot for the new Patron placebo.'],
        bound_note='Counts precede finite-score, pool, identity, chronology and cooldown gates: they are NOT final API requests or final sample sizes.',network_requests=0,uses_old_filtered_prepared_queries_as_universe=False))
    input_rows=[dict(input_index=i,path=p,sha256=mu.sha(p),bytes=Path(p).stat().st_size) for i,p in enumerate(sorted(set(dependencies)))]
    mu.save(a.run/'PRIVATE/COMPARISON_AUDIT_INPUTS.json',dict(local=local,phase=phase,files=input_rows))
    mu.save(report/'comparison_input_hashes.json',[{k:v for k,v in r.items() if k!='path'} for r in input_rows])

if __name__=='__main__':
    a=mu.parser().parse_args()
    with mu.pulse('Comparison full-denominator metadata audit'):run(a)
