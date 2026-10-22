#!/usr/bin/env python3
"""Rebuild chooser-leniency IV and comparison diagnostics for the September 9 main sample."""
from __future__ import annotations
import argparse, csv, fcntl, hashlib, json, math, os, platform, shutil, sys, time, zipfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import local_io as io
import rebuild_logic as logic
import iv_numerics as num
import iv_models as models
import comparison_core as cmp
from preliminary_core import DAY,MONTHS,STARTS,PANEL_END,SPEEDS

PKG=Path(__file__).resolve().parent
VERSION='1.0.0'
CHRON_MANIFEST='output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/chronology_input_manifest.tsv'
CHRON_SHA='1d4648bb17cafd9e58c14ab78d32abe855f0bc62a6fb75ac88e02494a73337cd'
DEFAULT_ROOT=Path('/Volumes/XT_Pro/lichess_kindness')
ADJ_START=1696118400000  # 2023-10-01; exact history boundary of the main-sample adjacency rule.

def relocate(project,p):
    p=Path(p)
    if p.is_absolute():
        try:p=p.relative_to(DEFAULT_ROOT)
        except ValueError:raise RuntimeError('Saved input is outside the expected project: '+str(p))
    return io.child(project,p)

def authenticate(project):
    a=io.load(PKG/'evidence/prior_authority.json');main=io.load(PKG/'evidence/main_sample_report.json')
    if main['status']!='POOL_MAIN_SAMPLE_24M_CERTIFIED_OK':raise RuntimeError('New main sample is not certified')
    root=relocate(project,main['private_output_root']);panels=[];snapshots=[]
    with io.heartbeat('Verifying the new main sample'):
        for m in main['panel_outputs']:
            p=io.child(root,m['relative_path']);snapshots.append(io.checked(p,m['sha256'],m['size_bytes']))
            if pq.ParquetFile(p).metadata.num_rows!=int(m['rows']):raise RuntimeError('Main monthly row count changed')
            panels.append(str(p))
    if len(panels)!=24 or sum(pq.ParquetFile(p).metadata.num_rows for p in panels)!=41534331:raise RuntimeError('Wrong main-sample coverage')
    eligroot=root/'eligibility';er=[r for r in main['stages'] if r['relative_path']=='eligibility'][0]
    snapshots.append(io.checked(eligroot/'_DONE.json',er['receipt_sha256']));elig=[]
    for r in io.load(eligroot/'_DONE.json')['files']:
        if r['relative_path'].endswith('.parquet'):
            p=io.child(eligroot,r['relative_path']);snapshots.append(io.checked(p,r['sha256'],r['size_bytes']));elig.append(str(p))
    if not elig:raise RuntimeError('Certified eligibility dataset is missing')
    previous=project/'derived/replication/comparison_tests_v110_PRIVATE'/a['comparison_run']
    done=io.load(previous/'_SUCCESS.json')
    if (done.get('status')!='CHOOSER_COMPARISON_TESTS_COMPLETE' or done.get('config_sha256')!=a['comparison_config_sha256']
        or done.get('report_sha256')!=a['comparison_report_sha256']):raise RuntimeError('Completed, repaired comparison v1.1.0 is missing')
    if io.cfgsha(io.load(previous/'config.json'))!=a['comparison_config_sha256']:raise RuntimeError('Comparison configuration changed')
    snapshots.append(io.checked(previous/'lineage_PRIVATE.json',a['comparison_lineage_sha256']))
    line=io.load(previous/'lineage_PRIVATE.json')
    receipt=io.load(previous/'analysis_rows/_COMPLETE.json')
    if receipt['config_sha256']!=a['comparison_config_sha256']:raise RuntimeError('Comparison checkpoint changed')
    rec=[x for x in receipt['files'] if x['path']=='pool_analysis.parquet']
    if len(rec)!=1:raise RuntimeError('Missing comparison analysis receipt')
    qpath=previous/'analysis_rows/pool_analysis.parquet';snapshots.append(io.checked(qpath,rec[0]['sha256'],rec[0]['bytes']))
    q=io.read(qpath)
    if len(q)!=1661563 or len(set(q['game_id'].to_pylist()))!=len(q):raise RuntimeError('Full pool comparison denominator changed')
    report_path=relocate(project,done['private_report_path'])
    for name in ['identity_audit.json','dictionary_check.json']:
        r=[x for x in a['comparison_public_files'] if x['file']==name][0]
        snapshots.append(io.checked(report_path/name,r['sha256'],r['bytes']))
    iv=project/'derived/replication/chooser_leniency_iv_pilot_v100_PRIVATE'/a['iv_run']
    ivdone=io.load(iv/'_SUCCESS.json')
    if ivdone.get('config_sha256')!=a['iv_config_sha256'] or ivdone.get('report_zip_sha256')!=a['iv_report_sha256']:raise RuntimeError('Verified full-history projections unavailable')
    projection=[];deltas=[]
    with io.heartbeat('Verifying existing full histories'):
        for shard,parts in enumerate(line['projections']):
            for r in parts:
                p=relocate(project,r['path']);snapshots.append(io.checked(p,r['sha256'],r['bytes']))
                receiptp=p.parent/'_COMPLETE.json';io.checked(receiptp,r['receipt_sha256'])
                projection.append(dict(r,path=str(p),shard=shard))
        for month in MONTHS:
            d=iv/'projection'/('month='+month);r=io.load(d/'_COMPLETE.json')
            items=[x for x in r['files'] if x['path']=='reference_deltas.npz']
            if len(items)!=1 or r['config_sha256']!=a['iv_config_sha256']:raise RuntimeError('Missing historical reference checkpoint')
            p=d/'reference_deltas.npz';snapshots.append(io.checked(p,items[0]['sha256'],items[0]['bytes']));deltas.append(str(p))
    if {(x['month'],x['shard']) for x in projection}!={(m,s) for m in MONTHS for s in range(16)}:raise RuntimeError('Incomplete history grid')
    if sum(x['rows'] for x in projection)!=47587020:raise RuntimeError('Full historical opportunity count differs')
    # Original panel receipts also pin the source of all score/outcome projection rows.
    originals=[dict(r,path=str(relocate(project,r['path']))) for r in line['stage07']]
    io.checked(project/'derived/replication/analysis_panel_24m_sf100k/_SUCCESS.json',a['stage07_success_sha256'])
    manifest=project/CHRON_MANIFEST;snapshots.append(io.checked(manifest,CHRON_SHA))
    with manifest.open() as f:chron=list(csv.DictReader(f,delimiter='\t'))
    if len(chron)!=852 or sum(int(x['rows']) for x in chron)!=7763847245:raise RuntimeError('Canonical chronology coverage changed')
    for k,r in enumerate(chron):
        p=relocate(project,r['path']);pf=pq.ParquetFile(p)
        if int(r['file_index'])!=k or p.stat().st_size!=int(r['bytes']) or pf.metadata.num_rows!=int(r['rows']) or pf.metadata.num_row_groups!=int(r['row_groups']):raise RuntimeError('Chronology manifest mismatch: '+str(p))
        need={'utc_ms','white_id','black_id','game_id'}
        if not need<=set(pf.schema_arrow.names):raise RuntimeError('Canonical chronology schema changed')
        r['path']=str(p);r['signature']=io.sig(p)
        r['month']=next((x[6:] for x in p.parts if x.startswith('month=')),None)
        if not r['month']:raise RuntimeError('Chronology month unavailable')
    return dict(main=main,panels=panels,eligibility=elig,originals=originals,projection=projection,deltas=deltas,
      chron=chron,qpath=str(qpath),snapshots=snapshots,authority=a)

def targets(inputs,root,conf,memory):
    def build(tmp):
        c=io.conn(tmp/'spill',memory)
        try:
            n=io.copy(c,logic.exposure_sql(io.parq(inputs['panels'])),tmp/'first_exposures.parquet')
            q=io.read(inputs['qpath']);qcols=['sample_row','game_id','recipient_id','opponent_id','archive_start_ms']
            io.table(tmp/'comparison.parquet',q.select(qcols))
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([tmp/'comparison.parquet']))
            io.copy(c,'''SELECT sample_row,0 AS role,recipient_id AS user_id,opponent_id,game_id,archive_start_ms FROM q
                UNION ALL SELECT sample_row,1 AS role,opponent_id AS user_id,recipient_id AS opponent_id,game_id,archive_start_ms FROM q''',tmp/'comparison_sides.parquet')
            return dict(first_exposures=n,comparison_games=len(q),first_exposure_ranked_before_arm_cut=True)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return io.stage(root/'targets',conf,build)

def chronology_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    r=job['input'];p=Path(r['path'])
    if io.sig(p)!=r['signature']:raise RuntimeError('Chronology input changed')
    def build(tmp):
        q=io.read(job['targets'],['target_row','recipient_id','chooser_id','archive_start_ms'])
        qids=io.arr(q,'recipient_id').astype(np.int64);st=io.arr(q,'archive_start_ms').astype(np.int64)
        if np.any(np.diff(qids)<=0):raise RuntimeError('First-exposure recipients are not unique/sorted')
        keys,inv=np.unique(logic.pair_keys(qids,io.arr(q,'chooser_id')),return_inverse=True)
        pre=np.zeros(len(q),np.int64);mins=np.full(len(keys),np.iinfo(np.int64).max,np.int64)
        pf=pq.ParquetFile(p);nr=0
        for batch in pf.iter_batches(columns=['utc_ms','white_id','black_id'],batch_size=262144,use_threads=False):
            t=pa.Table.from_batches([batch]);a=[]
            for col in ['utc_ms','white_id','black_id']:
                a.append(t[col].fill_null(-1).to_numpy().astype(np.int64))
            logic.chronology_accumulate(*a,qids,st,keys,pre,mins);nr+=len(t)
        if nr!=int(r['rows']):raise RuntimeError('Chronology scan lost rows')
        ix=np.flatnonzero(pre>0);io.table(tmp/'volume.parquet',pa.table({'target_row':ix,'pre_games_30d':pre[ix]}))
        byrow=mins[inv];ix=np.flatnonzero(byrow<np.iinfo(np.int64).max)
        io.table(tmp/'pairs.parquet',pa.table({'target_row':ix,'first_pair_start_ms':byrow[ix]}))
        # The main adjacency rule sees the inherited Oct 2023 onward chronology.
        if '2023-10'<=r['month']<='2025-07':
            c=io.conn(tmp/'spill',job['memory'])
            try:
                c.execute('CREATE VIEW ev AS SELECT game_id,utc_ms,white_id,black_id FROM '+io.parq([p])+f' WHERE utc_ms>={ADJ_START}')
                minimum=c.execute('SELECT min(utc_ms) FROM ev').fetchone()[0]
                c.execute('CREATE VIEW qs AS SELECT * FROM '+io.parq([job['sides']])+' WHERE archive_start_ms>='+str(minimum or 2**63-1))
                io.copy(c,logic.adjacency_candidates_sql('ev','qs'),tmp/'adjacency.parquet')
            finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        if io.sig(p)!=r['signature']:raise RuntimeError('Chronology changed while processing')
        return dict(scanned_rows=nr,input_signature=r['signature'],input_manifest_footer_signature=r['footer_signature_sha256'])
    dest,receipt=io.stage(job['out'],job['conf'],build)
    if receipt['input_signature']!=r['signature']:raise RuntimeError('Canonical input changed since the completed checkpoint')
    return str(dest)

def cohort_and_adjacency(inputs,root,conf,memory,chron_dirs):
    def build(tmp):
        c=io.conn(tmp/'spill',memory)
        try:
            f=root/'targets/first_exposures.parquet'
            c.execute('CREATE VIEW f AS SELECT * FROM '+io.parq([f]))
            p=io.parq([Path(d)/'pairs.parquet' for d in chron_dirs]);v=io.parq([Path(d)/'volume.parquet' for d in chron_dirs])
            query=f'''SELECT f.*,p.first_pair_start_ms,coalesce(v.pre_games_30d,0) AS pre_games_30d FROM f
              LEFT JOIN (SELECT target_row,min(first_pair_start_ms) AS first_pair_start_ms FROM {p} GROUP BY 1) p USING(target_row)
              LEFT JOIN (SELECT target_row,sum(pre_games_30d)::BIGINT AS pre_games_30d FROM {v} GROUP BY 1) v USING(target_row) ORDER BY target_row'''
            io.copy(c,query,tmp/'first_exposures_with_history.parquet');t=io.read(tmp/'first_exposures_with_history.parquet')
            a={n:io.arr(t,n) for n in t.column_names};ft=a['first_pair_start_ms']
            if not np.isfinite(ft).all() or np.any(ft>a['archive_start_ms']):raise RuntimeError('Canonical history does not recover every first-exposure pair')
            mask=logic.primary_cohort_mask(a,ft);keep=t.filter(pa.array(mask));keep=keep.append_column('pilot_row',pa.array(np.arange(len(keep),dtype=np.int64)))
            keep=keep.append_column('speed_code',pa.array([SPEEDS[x] for x in keep['speed'].to_pylist()],type=pa.int8()))
            if not len(keep):raise RuntimeError('No eligible IV cohort')
            io.table(tmp/'cohort.parquet',keep)
            adj=[Path(d)/'adjacency.parquet' for d in chron_dirs if (Path(d)/'adjacency.parquet').exists()]
            n=io.copy(c,logic.adjacency_final_sql(io.parq(adj),io.parq([root/'targets/comparison.parquet'])),tmp/'comparison_adjacency.parquet')
            counts=dict(c.execute('SELECT previous_classification_status,count(*) FROM '+io.parq([tmp/'comparison_adjacency.parquet'])+' GROUP BY 1').fetchall())
            if n!=pq.ParquetFile(inputs['qpath']).metadata.num_rows or counts.get('unmapped_or_inconsistent_focal',0):raise RuntimeError('Comparison chronology has unresolved focal mappings; denominator retained in checkpoint staging')
            if inputs.get('eligibility'):
                cq=io.parq([root/'targets/comparison.parquet']);ca=io.parq([tmp/'comparison_adjacency.parquet'])
                mismatch=c.execute('SELECT count(*) FROM '+cq+' q JOIN '+ca+' a USING(sample_row) JOIN '+io.parq(inputs['eligibility'])+' e USING(game_id) WHERE a.previous_classification_status IS DISTINCT FROM e.previous_classification_status').fetchone()[0]
                if mismatch:raise RuntimeError('New adjacency classification differs from the certified main eligibility ledger')
            cut=np.ones(len(t),bool);flow=[]
            for label,m in [('first_fair_nontournament_main_exposure',cut.copy()),('grant_or_claim_arm',a['arm_eligible'].astype(bool)),
                ('real_time',np.isin(a['speed'],list(SPEEDS))&(a['tc_base_s']>0)),('first_observed_pair',ft==a['archive_start_ms']),
                ('complete_90_days',a['anchor_ms']+90*DAY<PANEL_END)]:
                cut&=m;flow.append(dict(step=label,rows=int(cut.sum()),receipts=int(a['received'][cut].sum())))
            io.js(tmp/'cohort_flow.json',flow);io.js(tmp/'comparison_adjacency_counts.json',counts)
            return dict(cohort_rows=len(keep),receipts=int(io.arr(keep,'received').sum()),comparison_rows=n)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return io.stage(root/'cohort',conf,build)

def prepare_scores(inputs,root,conf,memory):
    def build(tmp):
        iv=io.read(root/'cohort/cohort.parquet');q=io.read(inputs['qpath'])
        def normalized(t,family,offset):
            return pa.table(dict(target_row=pa.array(np.arange(len(t),dtype=np.int64)+offset),family=[family]*len(t),
              sample_row=t['pilot_row' if family=='iv' else 'sample_row'],game_id=t['game_id'],recipient_id=t['recipient_id'],
              opponent_id=t['chooser_id' if family=='iv' else 'opponent_id'],archive_start_ms=t['archive_start_ms'],anchor_ms=t['anchor_ms'],
              month_code=pa.array(io.arr(t,'month_code').astype(np.int64))))
        combined=pa.concat_tables([normalized(iv,'iv',0),normalized(q,'comparison',len(iv))]);io.table(tmp/'queries.parquet',combined)
        for role,col in [('scores','opponent_id'),('outcomes','recipient_id')]:
            shard=num.user_hash(io.arr(combined,col))%np.uint64(16)
            for s in range(16):io.table(tmp/f'{role}_{s:02d}.parquet',combined.filter(pa.array(shard==s)))
        rn=np.zeros((2,25,4,4,500),np.int64);rs=np.zeros_like(rn)
        for p in inputs['deltas']:
            with np.load(p,allow_pickle=False) as z:rn+=z['n'];rs+=z['s']
        reference=num.expanding_reference(rn[:,:24],rs[:,:24]);np.save(tmp/'reference.npy',reference,allow_pickle=False)
        # Rebuild eligibility keys and role flags directly from the new certified panels.
        c=io.conn(tmp/'spill',memory)
        try:
            io.copy(c,'SELECT game_id,chooser_user_id AS j,disconnected_user_id AS i,kind_draw,fair_competitive,timeout_chooser_win FROM '+io.parq(inputs['panels']),tmp/'main_keys.parquet')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return dict(iv_rows=len(iv),comparison_rows=len(q),query_rows=len(combined),history_population='full original Stage07, all sources',reference_refit_from_verified_expanding_deltas=True)
    return io.stage(root/'score_inputs',conf,build)

def score_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(tmp):
        htab=pa.concat_tables([io.read(p) for p in job['parts']]);h={n:io.arr(htab,n) for n in htab.column_names};h['gid']=h['gid'].astype('U8');del htab
        c=io.conn(tmp/'spill',job['memory'])
        try:
            c.register('hj',pa.table({'gid':h['gid'],'j':h['j']}))
            main=c.execute('SELECT m.game_id FROM '+io.parq([job['keys']])+' m SEMI JOIN hj ON m.game_id=hj.gid AND m.j=hj.j').fetchall()
            eligible=np.isin(h['gid'],np.asarray([x[0] for x in main],dtype='U8'));del main
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        qt=io.read(job['outcomes']);q={n:io.arr(qt,n) for n in qt.column_names};q['sample_row']=q['target_row']
        out=logic.fresh_outcomes(h,q,eligible);out['target_row']=out.pop('sample_row');io.table(tmp/'outcomes.parquet',pa.table(out))
        qt=io.read(job['scores']);q={n:io.arr(qt,n) for n in qt.column_names};reference=np.load(job['reference'],allow_pickle=False)
        use=h['arm'];hj,hi,ht,hy,hc=(h[n][use] for n in ['j','i','t','y','cell'])
        result={'target_row':q['target_row']}
        for l,lag in enumerate([7,30]):
            a={n:np.full(len(qt),np.nan) for n in ['raw','adjusted','expected']}
            a.update({n:np.zeros(len(qt),np.int64) for n in ['n','counterparts','pair_removed']})
            for m in np.unique(q['month_code']):
                ix=np.flatnonzero(q['month_code']==m)
                score=num.score_month(hj,hi,ht,hy,hc,q['opponent_id'][ix],q['recipient_id'][ix],int(STARTS[int(m)]-lag*DAY),reference[l,int(m)],4)
                for n in a:a[n][ix]=score[n]
            for n,x in a.items():result[f'{n}_{lag}d']=x
            result[f'shrunken_adjusted_{lag}d']=a['adjusted']*a['n']/(a['n']+20.)
        io.table(tmp/'scores.parquet',pa.table(result))
        # i is not partitioned by this worker's chooser shard: each shard contributes
        # recipient disconnection counts, which are summed before estimation.
        iv=io.read(job['cohort'],['pilot_row','recipient_id','archive_start_ms']);ids=io.arr(iv,'recipient_id');order=np.argsort(ids)
        pos=num.lookup(ids[order],h['i']);found=pos>=0;row=order[np.maximum(pos,0)];end=io.arr(iv,'archive_start_ms')[row]-7*DAY
        before=found&(h['t']<end)&(h['t']>=end-90*DAY)
        nr=np.bincount(row[before],minlength=len(iv));nk=np.bincount(row[before],weights=h['y'][before],minlength=len(iv)).astype(np.int64)
        ix=np.flatnonzero(nr);io.table(tmp/'prior_receipts.parquet',pa.table({'pilot_row':ix,'prior_disconnects':nr[ix],'prior_receipts':nk[ix]}))
        return dict(history_rows=len(h['j']),main_history_rows=int(eligible.sum()),query_score_rows=len(qt))
    dest,_=io.stage(job['out'],job['conf'],build);return str(dest)

def assembled(inputs,root,conf,memory,score_dirs):
    def build(tmp):
        iv=io.read(root/'cohort/cohort.parquet');q=io.read(inputs['qpath']);n=len(iv)
        parts={}
        for name in ['scores','outcomes']:
            t=pa.concat_tables([io.read(Path(d)/(name+'.parquet')) for d in score_dirs]);t=t.take(pa.array(np.argsort(io.arr(t,'target_row'))))
            if not np.array_equal(io.arr(t,'target_row'),np.arange(n+len(q))):raise RuntimeError('Lost or duplicate query rows')
            parts[name]=t
        for name in parts['scores'].column_names:
            if name=='target_row':continue
            x=parts['scores'][name]
            if name in q.column_names:
                old=io.arr(q,name);new=x.slice(n).to_numpy()
                if not np.allclose(old,new,rtol=0,atol=1e-12,equal_nan=True):raise RuntimeError('Recomputed comparison history differs: '+name)
                q=q.drop([name])
            iv=iv.append_column(name,x.slice(0,n));q=q.append_column(name,x.slice(n))
        for name in parts['outcomes'].column_names:
            if name in ['target_row','prior_disconnects','prior_receipts']:continue
            x=parts['outcomes'][name];ivname={'y':'other_started_after_y','reached':'other_started_after_reached'}.get(name,name)
            iv=iv.append_column(ivname,x.slice(0,n))
            # Discard old later outcomes; retain previously authenticated earlier histories.
            if name in q.column_names:q=q.drop([name])
            q=q.append_column(name,x.slice(n))
        for stale in ['observed_kind','observed_reached','kind_complete90','reach_complete90']:
            if stale in q.column_names:q=q.drop([stale])
        pre=np.zeros((n,2),np.int64)
        for d in score_dirs:
            t=io.read(Path(d)/'prior_receipts.parquet');r=io.arr(t,'pilot_row')
            for k,name in enumerate(['prior_disconnects','prior_receipts']):pre[r,k]+=io.arr(t,name)
        for k,name in enumerate(['prior_disconnects','prior_receipts']):iv=iv.append_column(name,pa.array(pre[:,k]))
        if not io.arr(iv,'complete90').all():raise RuntimeError('Incomplete follow-up in IV')
        io.table(tmp/'iv.parquet',iv);io.table(tmp/'comparison_before_roles.parquet',q)
        c=io.conn(tmp/'spill',memory)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([tmp/'comparison_before_roles.parquet']))
            c.execute('CREATE VIEW iv AS SELECT * FROM '+io.parq([tmp/'iv.parquet']))
            c.execute('CREATE VIEW m AS SELECT * FROM '+io.parq([root/'score_inputs/main_keys.parquet']))
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([root/'cohort/comparison_adjacency.parquet']))
            # Historical numeric IDs, with random recipient orientation unchanged.
            mismatch=c.execute("SELECT count(*) FROM q JOIN m USING(game_id) WHERE q.status<>'timeout' OR NOT ((q.recipient_id=m.i AND q.opponent_id=m.j) OR (q.recipient_id=m.j AND q.opponent_id=m.i)) OR q.game_id IN (SELECT q.game_id FROM q JOIN m USING(game_id) JOIN a USING(sample_row) WHERE a.previous_classification_status<>'"+logic.NONADJ+"')").fetchone()[0]
            if mismatch:raise RuntimeError('Fresh comparison adjacency/roles disagree with certified main panel')
            query='''SELECT q.*,a.previous_classification_status,
              (a.previous_classification_status='not_mutually_adjacent_observed') AS eligible_main,
              (a.previous_classification_status IN ('not_mutually_adjacent_observed','left_boundary_unresolved')) AS eligible_restore_missing,
              coalesce(q.recipient_id=m.i,FALSE) AS recipient_disconnect_main,
              coalesce(q.recipient_id=m.j,FALSE) AS recipient_chooser_main,
              coalesce(q.recipient_id=m.i AND m.fair_competitive AND (m.kind_draw OR m.timeout_chooser_win),FALSE) AS recipient_fair_arm_main,
              coalesce(q.recipient_id=iv.recipient_id AND q.opponent_id=iv.chooser_id,FALSE) AS actual_iv_exposure
              FROM q JOIN a USING(sample_row) LEFT JOIN m USING(game_id) LEFT JOIN iv USING(game_id) ORDER BY q.sample_row'''
            count=io.copy(c,query,tmp/'comparison.parquet')
            if count!=len(q):raise RuntimeError('Role join changed comparison denominator')
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        return dict(iv_rows=n,comparison_rows=len(q),comparison_historical_scores_reproduced=True,new_outcomes_constructed=True,
          comparison_main_classification_matches_certified_timeout_subset=True,original_recipient_orientation_preserved=True)
    return io.stage(root/'analysis',conf,build)

def estimate_iv(root,conf):
    t=io.read(root/'analysis/iv.parquet');d={n:io.arr(t,n) for n in t.column_names}
    main=dict(name='PRIMARY_main_adjusted_7d_floor5',lag=7,floor=5,score='adjusted')
    specs=[main,{**main,'name':'raw_algebraic_check','score':'raw'},
      {**main,'name':'lag30_floor5','lag':30},*[{**main,'name':f'floor{n}','floor':n} for n in [1,10,25]],
      {**main,'name':'shrink20_floor1','score':'shrunken_adjusted','floor':1},
      {**main,'name':'recipient_history_controls','recipient_history_controls':True},
      {**main,'name':'state_controls_SENSITIVITY','state_controls':True},
      {**main,'name':'at_least_five_counterparts','breadth':5},
      {**main,'name':'conditional_reachers_SELECTION_CAVEAT','conditional':True}]
    allrows=[];balances=[];joint=[]
    for spec in specs:
        def build(tmp):
            with io.heartbeat('Estimating '+spec['name']):r,b,j=models.estimate_spec(d,spec,balance=spec==main)
            io.js(tmp/'result.json',dict(rows=r,balance=b,joint=j))
        dest,_=io.stage(root/'models_iv'/spec['name'],conf,build);r=io.load(dest/'result.json')
        allrows+=r['rows'];balances+=r['balance'];joint+=r['joint'];io.log('IV estimate ready: '+spec['name'])
    # First-stage sign checks by pregame speed/date, with board-state slices labelled
    # descriptive because the position arises after opponent assignment.
    strata=[]
    groups=[('speed_'+str(int(s)),d['speed_code']==s) for s in np.unique(d['speed_code'])]
    groups += [('before_2025',d['archive_start_ms']<1735689600000),('in_2025',d['archive_start_ms']>=1735689600000),
      ('board_equal_DESCRIPTIVE',d['exposure_eval_cp']<=100),('board_better_DESCRIPTIVE',(d['exposure_eval_cp']>100)&(d['exposure_eval_cp']<300)),
      ('board_clearly_better_DESCRIPTIVE',d['exposure_eval_cp']>=300)]
    for label,mask in groups:
        def build(tmp):
            with io.heartbeat('First-stage stratum '+label):r,_,_=models.estimate_spec(d,{**main,'name':label},extra_mask=mask)
            io.js(tmp/'rows.json',[x for x in r if x.get('estimator')=='first_stage_receipt_per_SD_Z' or not x.get('supported',True)])
        dest,_=io.stage(root/'first_stage_strata'/label,conf,build);strata+=io.load(dest/'rows.json')
    spec={**main,'name':'balance_among_recipients_with_prior_fair_opportunities','own_history':True}
    def prior_balance(tmp):
        with io.heartbeat('Balance among recipients with prior opportunities'):_,b,j=models.estimate_spec(d,spec,balance=True)
        io.js(tmp/'result.json',dict(balance=b,joint=j))
    dest,_=io.stage(root/'models_iv'/spec['name'],conf,prior_balance);r=io.load(dest/'result.json');balances+=r['balance'];joint+=r['joint']
    support=[]
    for lag in [7,30]:
        for floor in [1,5,10,25]:
            mask=(d[f'n_{lag}d']>=floor)&np.isfinite(d[f'adjusted_{lag}d'])
            support.append(dict(lag=lag,floor=floor,denominator=len(t),supported=int(mask.sum()),receipts=int(d['received'][mask].sum())))
    primary=[x for x in allrows if x.get('specification')==main['name'] and x.get('clustering')=='chooser_and_exposure_date_CR0']
    sd=next((r.get('residual_instrument_sd') for r in primary if r.get('supported')),None)
    rf=next((r.get('coefficient_pp') for r in primary if r.get('estimator')=='reduced_form_kindness_per_SD_Z'),None)
    return dict(estimates=allrows,balance=balances,joint_balance=joint,support=support,first_stage_strata=strata,primary=primary,reference_sd=sd,reference_rf_pp=rf)

def estimate_comparison(root,conf,ivresult):
    t=io.read(root/'analysis/comparison.parquet');d={n:io.arr(t,n) for n in t.column_names}
    sd=ivresult['reference_sd']
    if sd is None:return [dict(supported=False,reason='NEW_IV_HAS_NO_SUPPORTED_REFERENCE_SCALE')]
    cmp.PILOT_SD=sd;cmp.PILOT_RF_PP=ivresult['reference_rf_pp']
    rows=[]
    families=[('selection',None),('ordinary_placebo','ordinary_narrow'),('ordinary_draws_sensitivity','ordinary_broad')]
    for family,ordinary in families:
        for spec in [dict(name='primary',lag=7,floor=5),dict(name='lag30',lag=30,floor=5),dict(name='floor1',lag=7,floor=1),dict(name='floor10',lag=7,floor=10)]:
            label=family+'_'+spec['name']
            def build(tmp):
                mask=d['eligible_main'].astype(bool)&cmp.history_supported(d,spec['lag'],spec['floor'])
                if ordinary:mask&=d[ordinary].astype(bool)&d['complete90'].astype(bool)
                outcomes=['active_timeout','passive_outoftime','recipient_disconnect_main','recipient_chooser_main','recipient_fair_arm_main','actual_iv_exposure'] if ordinary is None else ['y','reached']
                n=int(mask.sum());answer=[]
                if n<2000:
                    io.js(tmp/'rows.json',[dict(family=family,specification=spec['name'],n=n,supported=False,reason='INSUFFICIENT_SUPPORT')]);return
                with io.heartbeat('Comparison '+label):
                    res,diag=cmp.residualize(d,mask,spec['lag'],outcomes)
                    codes=cmp.covariance_codes(d['recipient_id'][mask],d['opponent_id'][mask],d['archive_start_ms'][mask]//DAY)
                    for k,outcome in enumerate(outcomes):
                        mean=float(d[outcome][mask].mean());positive=int(d[outcome][mask].sum())
                        for withdate in [False,True]:
                            r=cmp.fit(res[:,k+1],res[:,0],codes,withdate,mean,equivalence=outcome=='y') if min(positive,n-positive)>=10 else dict(supported=False,reason='FEWER_THAN_TEN_EVENTS_OR_NONEVENTS')
                            # The old helper's numerical scale parameter now uses the freshly
                            # rebuilt primary IV SD. Rename every label so it cannot be mistaken.
                            r={key.replace('pilot_SD','current_IV_SD').replace('pilot_score_sd','current_IV_score_sd'):v for key,v in r.items()}
                            answer.append(dict(family=family,specification=spec['name'],n=n,outcome=outcome,outcome_mean=mean,
                              clustering='shared_account_OR_date_CR0' if withdate else 'shared_account_CR0',
                              sample_rule=logic.NONADJ,lag=spec['lag'],floor=spec['floor'],**diag,**r))
                io.js(tmp/'rows.json',answer)
            dest,_=io.stage(root/'models_comparison'/label,conf,build);rows+=io.load(dest/'rows.json');io.log('Comparison ready: '+label)
    # Two inherited primary diagnostic tests: selection and ordinary kindness.
    primary=[r for r in rows if r.get('specification')=='primary' and r.get('clustering')=='shared_account_OR_date_CR0'
      and ((r['family']=='selection' and r['outcome']=='active_timeout') or (r['family']=='ordinary_placebo' and r['outcome']=='y'))]
    ps=[r.get('p_value_asymptotic',1) if r.get('supported') else 1 for r in primary];run=0
    for rank,k in enumerate(np.argsort(ps)):
        run=max(run,(len(ps)-rank)*ps[k]);primary[k]['p_Holm_two_primary']=min(1.,run) if primary[k].get('supported') else None
    return rows

def csvout(path,rows):
    import csv
    rows=io.clean(rows);names=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(list,dict)) else v for k,v in r.items()})

def report(root,conf,inputs,iv,comparison,desktop):
    def build(tmp):
        cohort=io.load(root/'cohort/_DONE.json');analysis=io.load(root/'analysis/_DONE.json')
        summary=dict(status='CHOOSER_IV_MAIN_REBUILD_COMPLETE',version=VERSION,config_sha256=conf,
          main_opportunities=41534331,iv_exposures=cohort['cohort_rows'],iv_receipts=cohort['receipts'],
          comparison_games_before_history_and_adjacency_cuts=1661563,network_requests=0,
          first_exposures_reselected_from_new_main_sample=True,old_IV_cohort_used=False,
          full_earlier_histories_preserved=True,first_pairs_observed_in_canonical_history_not_lifetime_certified=True,
          causal_identification_certified=False,primary_iv=iv['primary'],current_iv_score_sd=iv['reference_sd'],
          comparison_classification_counts=io.load(root/'cohort/comparison_adjacency_counts.json'),
          chronology_manifest_sha256=CHRON_SHA,chronology_rows=7763847245,
          chronology_verification='pinned original manifest, file size/row-group/row counts and run-time change detection; no pre-existing full-byte hashes in chronology manifest',
          outcome='first later fair main-sample choice against a different opponent; start strictly after focal lastMoveAt anchor, decision within90d; zero only with complete90',
          eligibility_timing='observed previous nonadjacency, not verified end-to-start rematch status',
          instrument='all-source historical Stage07; month-start minus7/30days; pair leave-all-out, four-fold cross-fitted state adjustment',
          sampling_note='existing randomly oriented comparison frame retained; fresh sample-dependent outcomes and regressions',
          validation=analysis,elapsed_note='No estimated data results are bundled in the code package.')
        io.js(tmp/'summary.json',summary);io.js(tmp/'iv_primary.json',iv['primary']);io.js(tmp/'comparison_results.json',comparison)
        csvout(tmp/'iv_estimates.csv',iv['estimates']);csvout(tmp/'balance.csv',iv['balance']);csvout(tmp/'joint_balance.csv',iv['joint_balance']);csvout(tmp/'history_support.csv',iv['support']);csvout(tmp/'comparison_estimates.csv',comparison);csvout(tmp/'first_stage_strata.csv',iv['first_stage_strata'])
        shutil.copy2(root/'cohort/cohort_flow.json',tmp/'cohort_flow.json')
        shutil.copy2(root/'cohort/comparison_adjacency_counts.json',tmp/'comparison_adjacency_counts.json')
        shutil.copy2(root/'config.json',tmp/'config.json')
        (tmp/'REPORT.md').write_text('The IV and comparison checks were rebuilt for the certified pool / observed-previous-nonadjacent main sample.\n\n'
          'Read iv_primary.json, balance.csv, joint_balance.csv, comparison_estimates.csv and cohort_flow.json together. A strong first stage does not establish a valid instrument. The earlier selection warning is an open issue until these new checks are reviewed. A nonsignificant placebo is not evidence of a negligible effect: inspect its confidence interval.\n\n'
          'Histories retain excluded opportunities. First exposures are ranked in the new main sample before arm/first-pair/follow-up cuts. No ATT weights or treatment-dependent overlap cut are used. Fairness and clock controls measured during the exposure game are sensitivity controls only. Same-opponent future encounters are skipped.\n\n'
          'First pair means first observed pair in the inherited canonical rated-standard chronology. API lastMoveAt is a last-move anchor, not an observed claim-click or literal end. Main adjacency uses observed start order with the inherited October 2023 boundary; missing or tied predecessors remain explicit. Ordinary games are classified from the same observed chronology, not from the timeout-only eligibility table.\n\n'
          'The ordinary comparison has its own repeated-game sampling and narrower public-data controls. Its coefficients are displayed both per native residual SD and per the fresh primary IV residual SD. Normal inference treats the historical scores as fixed. The analysis is a candidate IV, with exclusion and selection assumptions still open.\n')
        return dict(status=summary['status'])
    public,_=io.stage(root/'report',conf,build)
    dest=desktop/f'CHOOSER_IV_MAIN_REBUILD_REPORT_{conf[:12]}.zip';tmp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.iterdir()):
            if p.is_file():z.write(p,p.name)
    os.replace(tmp,dest);Path(str(dest)+'.sha256').write_text(io.sha(dest)+'  '+dest.name+'\n')
    io.log('CHOOSER_IV_MAIN_REBUILD_COMPLETE');print('UPLOAD: '+str(dest));print('UPLOAD: '+str(dest)+'.sha256')

def execute(args):
    inputs=authenticate(args.project_root)
    manifest=io.sha(PKG/'PACKAGE_MANIFEST.sha256')
    cfg=dict(version=VERSION,package_manifest_sha256=manifest,main_report_sha256=io.sha(PKG/'evidence/main_sample_report.json'),
      comparison_authority_sha256=io.sha(PKG/'evidence/prior_authority.json'),chronology_manifest_sha256=CHRON_SHA,
      primary_history='full Stage07 all-source',focal_main_rule="source='pool' and previous_classification_status='not_mutually_adjacent_observed'",
      first_exposure_rule='first fair non-tournament-like main-sample event as disconnected recipient; then arm/realtime/first observed pair/complete90',
      outcome_rule='first fair main-sample different-opponent game started after focal anchor; decision within90d',
      versions=dict(python=platform.python_version(),numpy=np.__version__,pyarrow=pa.__version__,duckdb=duckdb.__version__))
    conf=io.cfgsha(cfg);root=args.project_root/'derived/replication/chooser_iv_main_rebuild_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This rebuild is already running')
        if (root/'config.json').exists() and io.load(root/'config.json')!=cfg:raise RuntimeError('Run configuration differs')
        io.js(root/'config.json',cfg);io.js(root/'input_verification_PRIVATE.json',inputs['snapshots'])
        io.log('New run directory: '+str(root));io.log(f'Workers={args.workers}; memory per chronology worker={args.memory_per_worker}GB')
        with io.heartbeat('Selecting first exposures'):targets(inputs,root,conf,args.memory_gb)
        jobs=[dict(input=r,out=str(root/'chronology'/f'file_{k:04d}'),conf=conf,memory=args.memory_per_worker,
          targets=str(root/'targets/first_exposures.parquet'),sides=str(root/'targets/comparison_sides.parquet')) for k,r in enumerate(inputs['chron'])]
        chron=io.mapped(chronology_job,jobs,args.workers,'Canonical history and comparison predecessors')
        with io.heartbeat('Assembling the fresh IV cohort'):cohort_and_adjacency(inputs,root,conf,args.memory_gb,chron)
        with io.heartbeat('Preparing score targets'):prepare_scores(inputs,root,conf,args.memory_gb)
        jobs=[dict(parts=[x['path'] for x in inputs['projection'] if x['shard']==s],out=str(root/'score_shards'/f'shard_{s:02d}'),conf=conf,
          outcomes=str(root/'score_inputs'/f'outcomes_{s:02d}.parquet'),scores=str(root/'score_inputs'/f'scores_{s:02d}.parquet'),
          keys=str(root/'score_inputs/main_keys.parquet'),reference=str(root/'score_inputs/reference.npy'),cohort=str(root/'cohort/cohort.parquet'),memory=args.memory_per_worker) for s in range(16)]
        dirs=io.mapped(score_job,jobs,min(args.workers,max(1,int(args.memory_gb//3))),'Fresh scores and later outcomes')
        with io.heartbeat('Joining fresh outcomes and role checks'):assembled(inputs,root,conf,args.memory_gb,dirs)
        iv=estimate_iv(root,conf);comparison=estimate_comparison(root,conf,iv)
        for r in inputs['snapshots']:
            if io.sig(r['path'])!=r['signature']:raise RuntimeError('Source input changed during run: '+r['path'])
        for r in inputs['chron']:
            if io.sig(r['path'])!=r['signature']:raise RuntimeError('Canonical chronology changed during run: '+r['path'])
        report(root,conf,inputs,iv,comparison,args.desktop)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--project-root',type=Path,default=DEFAULT_ROOT);ap.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    ap.add_argument('--workers',type=int,default=10);ap.add_argument('--memory-gb',type=float,default=0)
    args=ap.parse_args()
    if not args.project_root.is_dir():raise SystemExit('Project drive is not mounted: '+str(args.project_root))
    args.desktop.mkdir(parents=True,exist_ok=True)
    # Leave room for Python/Arrow arrays, alongside DuckDB buffers. No oversubscription.
    if sys.platform=='darwin':
        import subprocess
        ram=int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize']).strip())/1024**3
    else:ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/1024**3
    args.memory_gb=ram*.65 if args.memory_gb<=0 else min(max(2,args.memory_gb),ram*.65)
    args.workers=max(1,min(args.workers,10,int(args.memory_gb//3) or 1));args.memory_per_worker=max(1.,args.memory_gb/args.workers-1.)
    # Package integrity is checked before executing anything in the launcher, too.
    for line in (PKG/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        h,n=line.split('  ',1);io.checked(io.child(PKG,n),h)
    try:execute(args)
    except KeyboardInterrupt:io.log('Stopped. Run the same command to resume.');raise SystemExit(130)
    except Exception as e:
        import traceback
        traceback.print_exc();io.log('STOPPED: '+str(e));raise SystemExit(2)

if __name__=='__main__':main()
