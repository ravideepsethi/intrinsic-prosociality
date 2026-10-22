"""Role-specific receipt outcomes and separately labelled broader source frames.

No post-treatment opportunity count enters the IV controls or denominator.
The main panel is action-resolved; raw API candidates and chronology are different frames.
"""
from pathlib import Path
import json,traceback
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import disruption_support as ds
import receipt_tests as rt
from util import *
from prepare_sequences import DAY

PKG=Path(__file__).resolve().parent
HORIZONS=(7,30,90)
WINDOWS=((7,0,'days_1_7'),(30,7,'days_8_30'),(90,30,'days_31_90'))


def role_sql(role):
    require(role in ('chooser','self_disconnected'),'Unknown role')
    who,other=('chooser_user_id','disconnected_user_id') if role=='chooser' else ('disconnected_user_id','chooser_user_id')
    terms=[]
    for h in HORIZONS:
        for region,condition in [('all','TRUE'),('competitive','p.board>=2'),('lost','p.board=0')]:
            cond=f'p.api_last_move_at_ms<=q.anchor_ms+{h*DAY} AND {condition}'
            terms += [f'count(p.game_id) FILTER(WHERE {cond})::BIGINT AS {role}_n_{region}_{h}',
                      f'count(p.game_id) FILTER(WHERE {cond} AND p.y=1)::BIGINT AS {role}_g_{region}_{h}']
    return 'SELECT q.row_id,'+','.join(terms)+f''' FROM iv q LEFT JOIN source p
      ON p.{who}=q.recipient_id AND p.{other}<>q.opponent_id
      AND p.utc_ms>q.anchor_ms AND p.api_last_move_at_ms>q.anchor_ms
      AND p.api_last_move_at_ms<=q.anchor_ms+{90*DAY} AND p.game_id<>q.game_id GROUP BY q.row_id'''


def count_games_sql(source='traffic',api=False):
    # Two endpoints per game, with the other account retained to exclude the original partner.
    a,b=('white','black') if api else ('white_id','black_id')
    start='start_ms' if api else 'utc_ms';end='t' if api else start
    qwho,qother=('recipient_name','opponent_name') if api else ('recipient_id','opponent_id')
    terms=[]
    for h in HORIZONS:
        for kind,condition in ([('api_timeout',"p.status='timeout'"),('api_outoftime',"p.status='outoftime'")] if api else [('corpus_games','TRUE')]):
            terms.append(f'count(*) FILTER(WHERE p.{end}<=q.anchor_ms+{h*DAY} AND {condition})::BIGINT AS {kind}_{h}')
    return f'''SELECT q.row_id,{','.join(terms)} FROM {source} p
      CROSS JOIN LATERAL (VALUES(p.{a},p.{b}),(p.{b},p.{a})) e(player,other)
      JOIN {'named_iv' if api else 'iv'} q ON e.player=q.{qwho}
      AND e.other<>q.{qother} AND p.{start}>q.anchor_ms AND p.{end}>q.anchor_ms
      AND p.{end}<=q.anchor_ms+{90*DAY} AND p.game_id<>q.game_id GROUP BY q.row_id'''


def coverage_mask(anchor,months):
    """An exposure qualifies only when every month touched by its 90-day window is available."""
    a=np.asarray(anchor,dtype=np.int64);ok=np.ones(len(a),bool)
    for month in ds.MONTHS:
        if month in months:continue
        lo,hi=ds.bounds(month);ok &= ~((a<hi)&(a+90*DAY>=lo))
    ok &= (a>=ds.START)&(a+90*DAY<ds.END)
    return ok


def merge_parts(db,parts,names,dest,identity):
    require(parts,'No supported source parts')
    sums=','.join(f'coalesce(sum(v.{n}),0)::BIGINT AS {n}' for n in names)
    files='['+','.join(qs(p) for p in parts)+']'
    copy_query(db,f'SELECT q.row_id,{sums} FROM iv q LEFT JOIN read_parquet({files}) v USING(row_id) GROUP BY q.row_id',dest,identity)
    return dest


def aligned(path,row_ids):
    frame=pd.read_parquet(path).sort_values('row_id')
    require(np.array_equal(frame.row_id.to_numpy(),row_ids),'Outcome row alignment changed')
    return {k:frame[k].to_numpy() for k in frame if k!='row_id'}


def windows(data,prefix):
    return {f'{prefix}_{label}':np.asarray(data[f'{prefix}_{h}'],float)-(np.asarray(data[f'{prefix}_{prev}'],float) if prev else 0.) for h,prev,label in WINDOWS}


def fit_batches(data,mask,outputs,label):
    rows=[];names=list(outputs)
    for start in range(0,len(names),6):
        batch={k:outputs[k] for k in names[start:start+6]}
        result,_,_=rt.fit_group(data,mask,batch,label);rows.extend(result)
    return rows


def chronology(db,project,private,report,identity):
    contract=json.loads((PKG/'evidence/chronology_contract.json').read_text());entries=contract['entries']
    inputs=[]
    for r in entries:
        p=ds.relocate(project,r['path'])
        if not p.exists():return None,dict(status='NOT_RUN_MISSING_CHRONOLOGY_FILES',expected_files=len(entries))
        pf=pq.ParquetFile(p)
        require(p.stat().st_size==int(r['bytes']) and pf.metadata.num_rows==int(r['rows']) and pf.metadata.num_row_groups==int(r['row_groups']), 'Chronology contract mismatch: '+str(p))
        require({'game_id','utc_ms','white_id','black_id'}<=set(pf.schema_arrow.names),'Chronology fields changed')
        inputs.append((r,p))
    # Frozen, outcome-blind sample verifies that numeric IDs refer to the same participants.
    db.execute('''CREATE OR REPLACE TEMP TABLE id_bridge_sample AS SELECT game_id,recipient_id,opponent_id,archive_start_ms
      FROM iv ORDER BY md5(game_id || ':construal-v110-id-bridge') LIMIT 10000''')
    parts=[];bridges=[];lineage=[]
    for r,p in inputs:
        log('Chronology volume: '+p.parent.parent.name+' / '+p.parent.name)
        digest=sha256_file(p);part_identity=binding([identity,'chronology',r,digest])
        stem='chronology_'+str(r['file_index']);dest=private/'opportunity_parts'/(stem+'.parquet');bridge=dest.with_suffix('.json')
        lineage.append(dict(file_index=r['file_index'],rows=int(r['rows']),bytes=int(r['bytes']),sha256=digest))
        if not (ready(dest,part_identity) and ready(bridge,part_identity)):
            db.execute(f'CREATE OR REPLACE VIEW traffic AS SELECT game_id,utc_ms,white_id,black_id FROM read_parquet({qs(p)},hive_partitioning=false)')
            copy_query(db,count_games_sql(),dest,part_identity)
            result=records(db,'''SELECT count(*) matched_rows,count(DISTINCT q.game_id) distinct_matches,
              count(*) FILTER(WHERE p.utc_ms<>q.archive_start_ms OR NOT
               ((p.white_id=q.recipient_id AND p.black_id=q.opponent_id) OR
                (p.black_id=q.recipient_id AND p.white_id=q.opponent_id))) mismatches
              FROM traffic p JOIN id_bridge_sample q USING(game_id)''')[0]
            atomic_json(bridge,result);certify(bridge,part_identity)
        parts.append(dest);bridges.append(json.loads(bridge.read_text()))
    n=db.execute('SELECT count(*) FROM id_bridge_sample').fetchone()[0]
    require(sum(x['matched_rows'] for x in bridges)==n and sum(x['distinct_matches'] for x in bridges)==n and sum(x['mismatches'] for x in bridges)==0,'Chronology participant/time bridge failed')
    out=private/'chronology_counts.parquet';merge_parts(db,parts,[f'corpus_games_{h}' for h in HORIZONS],out,binding([identity,lineage]))
    atomic_json(report/'CHRONOLOGY_LINEAGE.json',dict(files=lineage,bridge_sample_rows=n,bridge_mismatches=0,
      authority='Frozen byte sizes, rows and row groups; current full SHA256 recorded. Historical full content digests unavailable.',
      frame='144-file rating replay chronology corpus, all listed speeds; game starts, not observed disconnections'))
    return out,dict(status='CHRONOLOGY_COUNTS_COMPLETE',files=len(parts),rows=sum(int(r['rows']) for r,p in inputs),
      timing='Strictly future game starts through day 90; same original opponent excluded')


def api_candidates(db,project,private,report,identity):
    items,issues=ds.discover(project)
    # Details may contain local paths; retain them only in private storage.
    atomic_json(private/'API_DISCOVERY.json',dict(items=items,issues=issues))
    if not items:return None,set(),dict(status='NOT_RUN_NO_COMPLETED_API_MONTHS')
    db.execute('''CREATE OR REPLACE TEMP TABLE named_iv AS SELECT q.*,
      lower(trim(p.disconnected_username_norm)) AS recipient_name,lower(trim(p.chooser_username_norm)) AS opponent_name
      FROM iv q JOIN source p ON q.game_id=p.game_id AND q.recipient_id=p.disconnected_user_id AND q.opponent_id=p.chooser_user_id''')
    qn=db.execute('SELECT count(*) FROM iv').fetchone()[0]
    n,u,bad=db.execute("SELECT count(*),count(DISTINCT row_id),count(*) FILTER(WHERE recipient_name IS NULL OR opponent_name IS NULL OR recipient_name='' OR opponent_name='' OR recipient_name=opponent_name) FROM named_iv").fetchone()
    require(n==u==qn and bad==0,'API exposure name bridge is incomplete')
    bad_id,bad_name=db.execute('''WITH names AS (SELECT recipient_id AS actor_id,recipient_name AS actor_name FROM named_iv UNION SELECT opponent_id,opponent_name FROM named_iv),
      by_id AS (SELECT actor_id,count(DISTINCT actor_name) n FROM names GROUP BY actor_id),by_name AS (SELECT actor_name,count(DISTINCT actor_id) n FROM names GROUP BY actor_name)
      SELECT (SELECT count(*) FROM by_id WHERE n<>1),(SELECT count(*) FROM by_name WHERE n<>1)''').fetchone()
    require(bad_id==bad_name==0,'Numeric ID / normalized username mapping is not one-to-one')
    parts=[];months=set();qa=[];lineage=[]
    for item in items:
        month=item['month'];lo,hi=ds.bounds(month);log('Broader API counts: '+month)
        snapshots=ds.records(item['paths']);part_identity=binding([identity,item,snapshots])
        dest=private/'opportunity_parts'/('api_'+month+'.parquet');audit=dest.with_suffix('.json')
        if not ready(audit,part_identity):
            db.execute('CREATE OR REPLACE VIEW api_normal AS '+ds.normal_sql(item['paths']))
            check=records(db,f'''SELECT count(*) n,count(DISTINCT game_id) u,
              count(*) FILTER(WHERE game_id IS NULL OR NOT regexp_full_match(game_id,'[A-Za-z0-9]{{8}}')) bad_ids,
              count(*) FILTER(WHERE alias_conflict) alias_conflicts,
              count(*) FILTER(WHERE start_ms IS NULL OR start_ms<{lo} OR start_ms>={hi}) bad_creation_month,
              count(*) FILTER(WHERE t IS NULL OR t<start_ms OR t-start_ms>{7*DAY}) bad_timing,
              count(*) FILTER(WHERE white IS NULL OR black IS NULL OR white=black) bad_accounts,
              count(*) FILTER(WHERE status NOT IN ('timeout','outoftime') OR status IS NULL) other_status
              FROM api_normal''')[0]
            check['usable']=bool(check['n']==check['u']==item['expected_rows'] and not any(check[k] for k in ['bad_ids','alias_conflicts','bad_creation_month']) and check['bad_timing']<=.001*check['n'] and check['bad_accounts']<=.02*check['n'])
            atomic_json(audit,check);certify(audit,part_identity)
        check=json.loads(audit.read_text());qa.append(dict(month=month,**check))
        if not check['usable']:continue
        if not ready(dest,part_identity):
            db.execute('CREATE OR REPLACE VIEW api_normal AS '+ds.normal_sql(item['paths']))
            db.execute(f'''CREATE OR REPLACE VIEW api_valid AS SELECT * FROM api_normal WHERE NOT alias_conflict
              AND rated=true AND variant='standard' AND speed IN ({','.join(qs(x) for x in ds.SPEEDS)})
              AND white IS NOT NULL AND black IS NOT NULL AND white<>black
              AND t>=start_ms AND t-start_ms<={7*DAY} AND status IN ('timeout','outoftime')''')
            copy_query(db,count_games_sql('api_valid',True),dest,part_identity)
        months.add(month);parts.append(dest)
        lineage.append(dict(month=month,source=item['source'],rows=check['n'],files=[{k:s[k] for k in ['bytes','sha256','rows']} for s in snapshots]))
    csv_write(report/'api_month_quality.csv',qa)
    atomic_json(report/'API_LINEAGE.json',dict(months=lineage,unavailable_or_failed_months=[m for m in ds.MONTHS if m not in months],
      exposure_name_bridge_rows=n,one_to_one_mapping=True,source_discovery_issues=len(issues)))
    if not parts:return None,months,dict(status='NOT_RUN_NO_USABLE_API_MONTHS')
    out=private/'api_counts.parquet';merge_parts(db,parts,[f'api_{s}_{h}' for s in ['timeout','outoftime'] for h in HORIZONS],out,binding([identity,lineage]))
    return out,months,dict(status='API_CANDIDATE_COUNTS_COMPLETE',months=sorted(months),
      frame='Usable rated standard real-time time-forfeit candidates; both player roles; missing months never treated as zero',
      limits='No verified actor or board evaluation for outoftime. Not a census of physical disconnections. Some invalid individual API rows excluded; see quality counts.')


def run(db,project,base,base_identity,private,report,identity,prior_report):
    oldpath=base/'PRIVATE/iv_analysis.parquet';require(ready(oldpath,base_identity),'Verified prior IV analysis cache required')
    db.execute(f'CREATE OR REPLACE VIEW iv AS SELECT * FROM read_parquet({qs(oldpath)})')
    table=pq.read_table(oldpath);data={k:table[k].combine_chunks().to_numpy(zero_copy_only=False) for k in table.column_names};del table
    order=np.argsort(data['row_id']);data={k:v[order] for k,v in data.items()}
    require(len(data['row_id'])==2682330 and len(np.unique(data['row_id']))==len(order),'Reviewed IV row count changed')
    require(np.asarray(data['complete90'],bool).all(),'Incomplete original follow-up')
    counts={};status={};rows=[]
    for role in ('chooser','self_disconnected'):
        dest=private/(role+'_counts.parquet')
        if not ready(dest,identity):copy_query(db,role_sql(role),dest,identity)
        values=aligned(dest,data['row_id']);counts.update(values)
        if role=='chooser':
            for kind in ('n','g'):
                for region in ('competitive','lost'):
                    for h in HORIZONS:np.testing.assert_array_equal(values[f'chooser_{kind}_{region}_{h}'],data[f'{kind}_{region}_{h}'])
    atomic_json(report/'OPPORTUNITY_DEFINITION.json',dict(original_n_lost='Recipient is the later chooser; the later disconnected opponent has engine evaluation <= -300 centipawns. Counts draws plus claims.',
      original_frame='Certified action-resolved pool / observed-nonadjacent panel, API status timeout, five-second rule. Excludes outoftime.',
      self_disconnected='Recipient is later the disconnected player; board evaluation is from that recipient side.',
      exclusions='Strict future start and recorded last move; original exposure game and original opponent excluded; reviewed complete 90-day cohort.',
      original_count_columns_reproduced=True,
      interpretation='Changes may reflect activity, position composition, disconnects, or action resolution. A receipt-mediated arrival effect is not by itself a violation of IV exclusion. Do not control for these post-treatment outcomes.'))
    outputs={}
    for role in ('chooser','self_disconnected'):
        for region in ('all','competitive','lost'):outputs.update(windows(counts,f'{role}_n_{region}'))
    # Separate chooser lost-position draw and claim counts; their sum equals n_lost exactly.
    outputs.update(windows(counts,'chooser_g_lost'))
    for h in HORIZONS:counts[f'chooser_claim_lost_{h}']=counts[f'chooser_n_lost_{h}']-counts[f'chooser_g_lost_{h}']
    outputs.update(windows(counts,'chooser_claim_lost'))
    outputs['next_grant_90']=np.asarray(data['y'],float)
    rows=fit_batches(data,np.ones(len(order),bool),outputs,'reviewed_complete90')
    bridge=[]
    for name,oldname in [('chooser_n_lost_days_8_30','n_lost_days_8_30'),('next_grant_90','next_grant_90')]:
        new=next(x for x in rows if x['outcome']==name);old=prior_report['receipt_IV_estimates.csv'];old=old[(old.group=='all')&(old.outcome==oldname)].iloc[0]
        require(abs(new['effect']-old.effect)<1e-7 and abs(new['SE']-old.SE)<1e-7,'Original opportunity IV does not reproduce')
        bridge.append(dict(outcome=name,effect=new['effect'],SE=new['SE'],effect_difference=new['effect']-old.effect,SE_difference=new['SE']-old.SE))
    csv_write(report/'opportunity_IV_bridge.csv',bridge);status['roles']=dict(status='ROLE_COUNTS_AND_IV_COMPLETE',rows=len(order))
    # Fixed families: 24 main count endpoints + one reviewed grant bridge; three chronology endpoints;
    # 6 API endpoints + 10 same-subset reference endpoints. Unavailable endpoints count as p=1.
    def export():
        for group,family_size in [('reviewed_complete90',25),('chronology_complete90',3),('api_covered_complete90',16)]:
            family=[r for r in rows if r['group']==group];padded=family+[dict(p_value=1.) for _ in range(max(0,family_size-len(family)))]
            rt.holm(padded,out='p_Holm_prespecified_frame_family')
        csv_write(report/'opportunity_IV_estimates.csv',rows);atomic_json(report/'OPPORTUNITY_STATUS.json',status)
    export()
    for kind in ['chronology','api']:
        try:
            if kind=='chronology':
                dest,s=chronology(db,project,private,report,identity);status[kind]=s
                if dest:
                    extra=windows(aligned(dest,data['row_id']),'corpus_games')
                    rows.extend(fit_batches(data,np.ones(len(order),bool),extra,'chronology_complete90'))
            else:
                dest,months,s=api_candidates(db,project,private,report,identity);status[kind]=s
                if dest:
                    mask=coverage_mask(data['anchor_ms'],months);status[kind]['complete_window_exposures']=int(mask.sum())
                    values=aligned(dest,data['row_id']);extra={}
                    for name in ['api_timeout','api_outoftime']:extra.update(windows(values,name))
                    for name in ['chooser_n_all','chooser_n_lost','self_disconnected_n_lost']:extra.update(windows(counts,name))
                    extra['next_grant_90']=outputs['next_grant_90']
                    rows.extend(fit_batches(data,mask,extra,'api_covered_complete90'))
        except Exception as exc:
            atomic_json(private/(kind+'_ERROR.json'),dict(error=repr(exc),traceback=traceback.format_exc()))
            status[kind]=dict(status='FAILED_REVIEW_PRIVATE_ERROR_LOG',error_type=type(exc).__name__)
            log(kind+' diagnostics failed; see private error log')
        export()
    return status
