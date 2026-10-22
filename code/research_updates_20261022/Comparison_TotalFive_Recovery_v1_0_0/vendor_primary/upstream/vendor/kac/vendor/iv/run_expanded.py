#!/usr/bin/env python3
"""Local expanded IV, with a prospectively classified sampled game denominator."""
from __future__ import annotations
import argparse, concurrent.futures as cf, csv, fcntl, gc, json, multiprocessing as mp
import os, platform, shutil, sys, time, zipfile
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import local_io as io
import audit_logic as audit
import expanded_logic as logic
import expanded_stats as stats
import expanded_inputs as sources
import followup_logic as volume_logic
from preliminary_core import DAY, MONTHS, PANEL_END

PKG=Path(__file__).resolve().parent
VERSION='1.0.0'
VOLUME_CACHE={}


def arrays(t):return {n:io.arr(t,n) for n in t.column_names}


def verify_audit_table(c,path,baseline,expected=None):
    c.execute('CREATE OR REPLACE VIEW audited AS SELECT * FROM '+io.parq([path]))
    if c.execute('SELECT count(*)-count(DISTINCT row_id) FROM audited').fetchone()[0]:
        raise RuntimeError('Duplicate audited row IDs')
    if c.execute('SELECT count(*) FROM audited WHERE support7 IS DISTINCT FROM ('+audit.support_sql(7,5)+')').fetchone()[0]:
        raise RuntimeError('Audited score support differs')
    if c.execute('SELECT count(*) FROM audited WHERE history_window_complete IS DISTINCT FROM (archive_start_ms-'+str(97*DAY)+'>='+str(int(audit.STARTS[0]))+')').fetchone()[0]:
        raise RuntimeError('Audited history coverage differs')
    prior=[]
    if expected is not None:
        records={r['candidate']:r for r in expected}
        for name,where in audit.candidates():
            row=c.execute(f'''SELECT count(*),sum(received::BIGINT),sum(y::BIGINT),sum(reached::BIGINT),
                count(DISTINCT outcome_gid) FILTER(WHERE reached AND y),
                count(*) FILTER(WHERE NOT history_window_complete)
                FROM audited WHERE {where}''').fetchone()
            fields=['rows','receipts','positive_outcome_rows','reached_rows','distinct_kind_decisions','rows_with_left_truncated_97_day_history']
            if any(int(v)!=int(records[name][k]) for k,v in zip(fields,row)):
                raise RuntimeError('Saved audit candidate counts changed: '+name)
            prior.append(dict(candidate=name,**dict(zip(fields,row))))
    if baseline is not None:sources.bridge(c,'audited',baseline,2112795)
    # Spacing is not recalculated after history/follow-up exclusions.
    t=c.execute('SELECT row_id,recipient_id,archive_start_ms,anchor_ms,support7,spaced30,spaced90 FROM audited ORDER BY row_id').to_arrow_table()
    a=arrays(t)
    for gap in (30,90):
        flag=audit.spaced(a['recipient_id'],a['archive_start_ms'],a['anchor_ms'],a['support7'],gap)
        if not np.array_equal(flag,a[f'spaced{gap}']):raise RuntimeError('Audited spacing flags differ')
    return prior


def prepare(inputs,root,conf,memory,expected_counts=logic.EXPECTED_ROWS,verify=True):
    def build(tmp):
        c=io.conn(tmp/'spill',memory)
        try:
            if verify:
                rows=verify_audit_table(c,inputs['audit'],inputs['iv'],io.load(PKG/'evidence/audit_candidate_counts.json'))
                io.js(tmp/'audit_reproduction.json',rows)
            else:c.execute('CREATE VIEW audited AS SELECT * FROM '+io.parq([inputs['audit']]))
            counts={}
            for name in logic.FLAGS:
                counts[name]=int(c.execute('SELECT count(*) FROM audited WHERE '+logic.sample_condition(name)).fetchone()[0])
                if expected_counts is not None and counts[name]!=expected_counts[name]:raise RuntimeError('Frozen sample count changed: '+name)
            io.copy(c,'SELECT * FROM audited WHERE '+logic.sample_condition('all')+' ORDER BY row_id',tmp/'base.parquet')
            q=c.execute('SELECT recipient_id,archive_start_ms FROM '+io.parq([tmp/'base.parquet'])+' ORDER BY row_id').to_arrow_table()
            keys,order,people=volume_logic.volume_plan(io.arr(q,'recipient_id'),io.arr(q,'archive_start_ms'))
            np.save(tmp/'volume_keys.npy',keys,allow_pickle=False);np.save(tmp/'volume_order.npy',order,allow_pickle=False)
            np.save(tmp/'volume_people.npy',people,allow_pickle=False)
            io.js(tmp/'volume_query.json',dict(rows=len(q),minimum_start=int(io.arr(q,'archive_start_ms').min()),maximum_start=int(io.arr(q,'archive_start_ms').max())))
            for gap in (30,90):
                io.copy(c,f'SELECT row_id,game_id,recipient_id,archive_start_ms,anchor_ms FROM audited WHERE spaced{gap} ORDER BY recipient_id,anchor_ms,row_id',tmp/f'selected_stream_{gap}.parquet')
            # Preserve every enriched pool row, all endings and original orientation.
            qpath=inputs['followup_comparison'];c.execute('CREATE VIEW comparison AS SELECT * FROM '+io.parq([qpath]))
            io.copy(c,'SELECT * FROM comparison ORDER BY row_id',tmp/'comparison.parquet')
            fields=['q.row_id']
            for gap,flag in [(0,'support7'),(30,'spaced30'),(90,'spaced90')]:
                fields += [f'coalesce(a.{flag},FALSE) AS selected_entry_{gap}',
                    f'coalesce(a.{flag} AND a.history_window_complete AND a.complete90,FALSE) AS analysis_entry_{gap}']
            fields += ['coalesce(a.support7,FALSE) AS audit_supported_exposure']
            n=io.copy(c,'SELECT '+','.join(fields)+' FROM comparison q LEFT JOIN audited a ON q.game_id=a.game_id AND q.recipient_id=a.recipient_id ORDER BY q.row_id',tmp/'entry_labels.parquet')
            if n!=pq.ParquetFile(qpath).metadata.num_rows:raise RuntimeError('Exposure join changed the comparison denominator')
            io.js(tmp/'frozen_counts.json',counts)
            return dict(rows=counts['all'],candidate_rows=counts,comparison_rows=n)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return io.stage(root/'prepared',conf,build)


def volume_job(job):
    global VOLUME_CACHE
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    inp=job['input'];p=Path(inp['path'])
    if io.sig(p)!=inp['signature']:raise RuntimeError('Chronology changed before scan')
    def build(tmp):
        global VOLUME_CACHE
        directory=Path(job['queries'])
        if VOLUME_CACHE.get('path')!=str(directory):
            VOLUME_CACHE=dict(path=str(directory),meta=io.load(directory/'volume_query.json'))
            for name in ('keys','order','people'):
                VOLUME_CACHE[name]=np.load(directory/f'volume_{name}.npy',mmap_mode='r',allow_pickle=False)
        a=VOLUME_CACHE;m=a['meta'];delta=np.zeros(m['rows']+1,np.int64)
        pf=pq.ParquetFile(p);tcol=pf.schema_arrow.get_field_index('utc_ms')
        read=skipped=0;t0=time.monotonic()
        for k in range(pf.metadata.num_row_groups):
            rg=pf.metadata.row_group(k);s=rg.column(tcol).statistics
            if s is not None and s.has_min_max and (s.max<m['minimum_start']-30*DAY or s.min>=m['maximum_start']):
                skipped+=rg.num_rows;continue
            for batch in pf.iter_batches(row_groups=[k],columns=['utc_ms','white_id','black_id'],batch_size=262144,use_threads=False):
                t,w,b=[batch.column(j).fill_null(-1).to_numpy(zero_copy_only=False).astype(np.int64,copy=False) for j in range(3)]
                keep=(t>=m['minimum_start']-30*DAY)&(t<m['maximum_start'])
                if keep.any():volume_logic.accumulate_volume(t[keep],w[keep],b[keep],a['keys'],a['people'],delta)
                read+=len(batch)
        if read+skipped!=int(inp['rows']):raise RuntimeError('Chronology row accounting failed')
        value=volume_logic.finish_volume(delta,a['order']);ix=np.flatnonzero(value)
        io.table(tmp/'volume.parquet',pa.table({'query_row':ix,'pre_games_30d':value[ix]}))
        if io.sig(p)!=inp['signature']:raise RuntimeError('Chronology changed during scan')
        return dict(scanned_rows=read,skipped_rows=skipped,elapsed_seconds=time.monotonic()-t0,input_signature=inp['signature'])
    old=(Path(job['out'])/'_DONE.json').exists();dest,r=io.stage(job['out'],job['conf'],build)
    if r['input_signature']!=inp['signature']:raise RuntimeError('Chronology changed since checkpoint')
    return dict(path=str(dest),reused=old,**{k:r[k] for k in ('scanned_rows','skipped_rows','elapsed_seconds')})


def volume_scan(inputs,root,conf,workers):
    jobs=[dict(input=r,queries=str(root/'prepared'),out=str(root/'volume'/f'file_{k:04d}'),conf=conf) for k,r in enumerate(inputs['chron'])]
    first=list(dict.fromkeys(np.linspace(0,len(jobs)-1,min(len(jobs),workers)).astype(int)))
    order=first+[k for k in range(len(jobs)) if k not in first]
    total=sum(int(r['rows']) for r in inputs['chron']);results={};fresh=done=0;t0=time.monotonic()
    with cf.ProcessPoolExecutor(max_workers=workers,mp_context=mp.get_context('spawn')) as pool:
        pending={};at=0
        with io.heartbeat('Recent playing-volume chronology scan'):
            while pending or at<len(order):
                while len(pending)<2*workers and at<len(order):
                    k=order[at];pending[pool.submit(volume_job,jobs[k])]=k;at+=1
                ready,_=cf.wait(pending,return_when=cf.FIRST_COMPLETED)
                for future in ready:
                    k=pending.pop(future);r=future.result();results[k]=r
                    nr=r['scanned_rows']+r['skipped_rows'];done+=nr
                    if not r['reused']:fresh+=nr
                    elapsed=time.monotonic()-t0;eta=(total-done)/(fresh/elapsed)/3600 if fresh else None
                    io.log(f'Volume scan {len(results)}/{len(jobs)}; '+(f'current scan ETA {eta:.2f} h' if eta is not None else 'reusing completed files'))
    io.js(root/'volume_benchmark.json',dict(elapsed_seconds=time.monotonic()-t0,
        reused_files=sum(r['reused'] for r in results.values()),scanned_rows=sum(r['scanned_rows'] for r in results.values()),
        time_pruned_rows=sum(r['skipped_rows'] for r in results.values()),scan_only=True))
    return [results[k]['path'] for k in range(len(jobs))]


def comparison_events_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'])
        try:
            sql=audit.history_sql(io.parq(job['parts']),io.parq([job['comparison']]))
            c.execute('COPY ('+sql+') TO '+io.lit(tmp/'events')+' (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))')
            return dict(month=job['month'])
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    dest,_=io.stage(job['out'],job['conf'],build);return str(dest)


def comparison_history_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    def build(tmp):
        c=io.conn(tmp/'spill',job['memory'])
        try:
            qt=c.execute('SELECT row_id,recipient_id,archive_start_ms FROM '+io.parq([job['comparison']])+
                f' WHERE recipient_id%16={job["shard"]} ORDER BY row_id').to_arrow_table()
            ht=pa.concat_tables([io.read(p,['person','t',*audit.COUNTS]) for p in job['parts']]) if job['parts'] else None
            events=arrays(ht) if ht is not None else {n:np.empty(0,np.int64) for n in ('person','t',*audit.COUNTS)}
            out=audit.window_counts(events,io.arr(qt,'recipient_id'),io.arr(qt,'archive_start_ms'))
            out['row_id']=io.arr(qt,'row_id');io.table(tmp/'counts.parquet',pa.table(out))
            return dict(query_rows=len(qt),history_event_moments=len(ht) if ht is not None else 0)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    dest,_=io.stage(job['out'],job['conf'],build);return str(dest)


def make_comparison(root,conf,memory,history_dirs):
    def build(tmp):
        q=io.read(root/'prepared/comparison.parquet');d=arrays(q)
        counts=pa.concat_tables([io.read(Path(p)/'counts.parquet') for p in history_dirs])
        counts=counts.take(pa.array(np.argsort(io.arr(counts,'row_id'))))
        if not np.array_equal(io.arr(counts,'row_id'),d['row_id']):raise RuntimeError('History query rows changed')
        for days in (30,90):
            for name in ('fair','kind','disconnect','receipt'):
                field=f'{name}_{days}'
                if not np.array_equal(io.arr(counts,field),d[field]):raise RuntimeError('Rebuilt comparison history differs: '+field)
            field=f'claim_{days}';q=q.append_column(field,counts[field]);d[field]=io.arr(counts,field)
        logic.validate_history(d,True)
        labels=io.read(root/'prepared/entry_labels.parquet')
        if not np.array_equal(io.arr(labels,'row_id'),d['row_id']):raise RuntimeError('Entry label row identities changed')
        for name in labels.column_names:
            if name!='row_id':q=q.append_column(name,labels[name])
        accounting={'all_pool_rows_retained':len(q),'history_reproduction':True,'denominator_type':'existing random all-ending game frame; not a census'}
        for gap in (0,30,90):
            e=arrays(io.read(root/'prepared'/f'selected_stream_{gap}.parquet')) if gap else {}
            r=logic.prospective_risk(e,d,gap)
            for name,value in r.items():q=q.append_column(f'{name}_{gap}',pa.array(value))
            accounting[f'cooldown_{gap}']=dict(at_risk=int(r['at_risk'].sum()),
                anchored_ties=int(r['anchor_tie'].sum()),earlier_started_not_yet_anchored=int(r['earlier_started_not_yet_anchored'].sum()))
            actual=io.arr(q,f'analysis_entry_{gap}').astype(bool)
            bad=actual&~r['at_risk']
            if bad.any():raise RuntimeError('An audited selected analysis entry is outside the prospective risk set')
            # On overlapping actual exposures, both independent score pipelines must agree.
        io.table(tmp/'comparison.parquet',q)
        c=io.conn(tmp/'spill',memory)
        try:
            c.execute('CREATE VIEW q AS SELECT * FROM '+io.parq([tmp/'comparison.parquet']))
            c.execute('CREATE VIEW e AS SELECT * FROM '+io.parq([root/'prepared/base.parquet']))
            common=c.execute('''SELECT count(*),count(*) FILTER(WHERE q.opponent_id<>e.opponent_id
                OR q.archive_start_ms<>e.archive_start_ms OR q.anchor_ms<>e.anchor_ms
                OR abs(q.adjusted_7d-e.adjusted_7d)>1e-11 OR q.n_7d<>e.n_7d
                OR q.fair_90<>e.fair_90 OR q.kind_90<>e.kind_90 OR q.claim_90<>e.claim_90)
                FROM q JOIN e USING(game_id,recipient_id)''').fetchone()
            if common[1]:raise RuntimeError('Comparison/exposure overlap differs on identities, scores or histories')
            accounting.update(overlapping_expanded_games=int(common[0]),overlap_mismatches=int(common[1]))
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
        io.js(tmp/'denominator_accounting.json',accounting);return accounting
    return io.stage(root/'comparison',conf,build)


def assemble_exposures(inputs,root,conf,memory,volume_dirs):
    def build(tmp):
        c=io.conn(tmp/'spill',memory)
        try:
            c.execute('CREATE VIEW b AS SELECT *,row_number() OVER(ORDER BY row_id)-1 AS query_row FROM '+io.parq([root/'prepared/base.parquet']))
            c.execute('CREATE VIEW v AS SELECT query_row,sum(pre_games_30d)::BIGINT AS pre_games_30d FROM '+io.parq([Path(p)/'volume.parquet' for p in volume_dirs])+' GROUP BY 1')
            io.copy(c,'SELECT b.* EXCLUDE(query_row),coalesce(v.pre_games_30d,0)::BIGINT AS pre_games_30d FROM b LEFT JOIN v USING(query_row) ORDER BY row_id',tmp/'all.parquet')
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([tmp/'all.parquet']))
            for candidate in ('first','spaced30','spaced90'):
                io.copy(c,'SELECT * FROM a WHERE '+logic.sample_condition(candidate)+' ORDER BY row_id',tmp/(candidate+'.parquet'))
            # Independent all-game volume counts must reproduce the old first-exposure series.
            if inputs.get('followup_iv'):
                old=io.parq([inputs['followup_iv']])
                r=c.execute('SELECT count(*),count(*) FILTER(WHERE a.pre_games_30d<>b.pre_games_30d) FROM a JOIN '+old+' b USING(game_id,recipient_id) WHERE a.first_recipient').fetchone()
                if r[1] or r[0]!=logic.EXPECTED_ROWS['first']:raise RuntimeError('Expanded activity does not reproduce first-exposure activity')
            accounting={}
            for candidate in logic.FLAGS:
                t=io.read(tmp/(candidate+'.parquet'));d=arrays(t);logic.validate_history(d)
                if candidate=='spaced90':logic.validate_disjoint(d)
                r=stats.describe(d)
                if candidate=='spaced90':
                    keep=logic.repeat_mask(d['recipient_id']);io.table(tmp/'spaced90_repeat.parquet',t.filter(pa.array(keep)))
                    r['repeat_rows']=int(keep.sum())
                    r['repeat_row_set_sha256']=logic.row_digest(d['row_id'][keep])
                accounting[candidate]=r
                del t,d;gc.collect()
            io.js(tmp/'sample_accounting.json',accounting);return dict(candidates=accounting)
        finally:c.close();shutil.rmtree(tmp/'spill',ignore_errors=True)
    return io.stage(root/'analysis',conf,build)


def model(root,conf,spec):
    def build(tmp):
        if spec['family']=='iv':
            path=root/'analysis'/('spaced90_repeat.parquet' if spec['repeat'] else spec['candidate']+'.parquet')
            d=arrays(io.read(path));flow=[dict(step='frozen_exposure_rows',rows=len(d['row_id']))]
        else:
            d=arrays(io.read(root/'comparison/comparison.parquet'))
            keep,flow=logic.entry_mask(d,spec['gap'])
            if spec['family']=='ordinary':
                keep &= np.asarray(d['ordinary_narrow'],bool)&np.asarray(d['complete90'],bool)
                flow.append(dict(step='ordinary_ending_and_complete_anchor_followup',rows=int(keep.sum())))
            if spec['repeat']:
                selected=np.flatnonzero(keep);repeated=logic.repeat_mask(d['recipient_id'][selected]);keep[:]=False;keep[selected[repeated]]=True
                flow.append(dict(step='repeat_recipients_in_risk_denominator',rows=int(keep.sum())))
            d={n:a[keep] for n,a in d.items()}
        with io.heartbeat('Estimating '+spec['name']):r=stats.estimate(d,spec)
        r['sample_flow']=flow;r['sample_accounting']=stats.describe(d)
        io.js(tmp/'result.json',r);return dict(rows=len(d['row_id']))
    return io.stage(root/'models'/spec['name'],conf,build)


def write_csv(path,rows):
    names=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=names);w.writeheader()
        for r in io.clean(rows):w.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(dict,list)) else v for k,v in r.items()})


def export_report(root,conf,desktop,timings):
    estimates=[];balance=[];joint=[];flow=[];accounts={};designs={}
    for spec in logic.specifications():
        r=io.load(root/'models'/spec['name']/'result.json')
        estimates+=r['estimates'];balance+=r['balance'];joint+=r['joint_balance']
        flow.append(dict(specification=spec['name'],steps=r['sample_flow']))
        accounts[spec['name']]=r['sample_accounting'];designs[spec['name']]=r['design']
    for a,b in [('main90_repeat_pooled','main90_repeat_FE_diagnostic'),('entry90_repeat_pooled','entry90_repeat_FE_diagnostic'),
                ('main90_pooled','main90_without_recipient_history'),('first97_common_controls','first97_without_recipient_history')]:
        if accounts[a]['row_set_sha256']!=accounts[b]['row_set_sha256']:raise RuntimeError('Models expected to share rows do not: '+a)
    tests=[r for r in estimates if (r['specification']=='entry90_pooled' and r.get('outcome')=='analysis_entry_90') or
                                 (r['specification']=='ordinary90_placebo' and r.get('outcome')=='y')]
    stats.stats.holm(tests,out='p_Holm_two_primary_diagnostics')
    def build(tmp):
        for name,rows in [('estimates',estimates),('balance',balance),('joint_balance',joint)]:
            io.js(tmp/(name+'.json'),rows);write_csv(tmp/(name+'.csv'),rows)
        io.js(tmp/'model_row_counts.json',accounts);io.js(tmp/'model_designs.json',designs);io.js(tmp/'sample_flow.json',flow)
        shutil.copy2(root/'analysis/sample_accounting.json',tmp/'sample_accounting.json')
        shutil.copy2(root/'comparison/denominator_accounting.json',tmp/'denominator_accounting.json')
        shutil.copy2(root/'config.json',tmp/'config.json');shutil.copy2(root/'DESIGN_FREEZE.json',tmp/'DESIGN_FREEZE.json')
        shutil.copy2(PKG/'ANALYSIS_PLAN.md',tmp/'ANALYSIS_PLAN.md')
        shutil.copy2(PKG/'evidence/rebuild_iv_primary.json',tmp/'original_first_exposure_reference.json')
        shutil.copy2(PKG/'evidence/first_exposure_reviewed_estimates.json',tmp/'reviewed_first_exposure_followup.json')
        io.js(tmp/'runtime.json',timings);shutil.copy2(root/'volume_benchmark.json',tmp/'volume_benchmark.json')
        validation=io.load(root/'analysis/_DONE.json')
        summary=dict(status='CHOOSER_IV_EXPANDED_COMPLETE',version=VERSION,config_sha256=conf,
            primary='main90_pooled',main_rows=accounts['main90_pooled']['rows'],
            model_specifications=len(logic.specifications()),unsupported_estimate_rows=sum(not r.get('supported',False) for r in estimates),
            sampled_entry_denominator_built=True,entry_denominator_is_all_game_census=False,
            no_condition_on_eventual_recipient_exposure=True,network_requests_to_lichess=0,stockfish_searches=0,
            historical_scores_treated_as_fixed=True,post_assignment_state_controls=False,
            causal_identification_certified=False,first_exposure_results_previously_known=True,
            design_frozen_before_new_coefficients=True,matched_comparison_row_hashes_verified=True,
            analysis_validation=validation,
            limitations=['conditional opponent assignment and exclusion remain assumptions',
                'spacing does not remove intervening receipts, carry-over or feedback into play',
                'entry denominator is the existing sampled frame, not all games of every recipient',
                'lastMoveAt proxies prior exposure timing; no claim-click or certified finish timestamp',
                'first observed pairs and observed-start nonadjacency are not literal rematch certification',
                'CR0 conditions on historical scores; score estimation uncertainty and all downstream dependence are not certified',
                'recipient FE and repeat-recipient entry comparisons are diagnostics, not identification repairs'])
        io.js(tmp/'summary.json',summary)
        (tmp/'READ_RESULTS.md').write_text('Primary: main90_pooled, estimator 2SLS. Read its first stage, RF, and weak-IV interval together.\n\n'
            'All effect/first-stage/RF estimates use proportions internally and percentage points in *_pp fields. RF/selection effects use one common reference-score SD.\n\n'
            'Compare main90_repeat_pooled with main90_repeat_FE_diagnostic on the exact same rows; the full main and original first-exposure samples differ. '
            'The original first-exposure estimate and reviewed history follow-up are included as prior evidence, not newly preregistered findings.\n\n'
            'The 30-day and unspaced estimates must be reported whether or not they are significant. '
            'The ordinary-game placebo and entry test use an existing random game frame with original orientation and all ending types retained for selection. '
            'Nonrejection or a weak entry test does not establish assignment or exclusion.\n\n'
            'Zero-event, singular, or nonpositive-covariance models remain unsupported; covariance matrices are never repaired to force significance. '
            'Controlled traits do not count as independent balance evidence.\n')
        return dict(status=summary['status'])
    public,_=io.stage(root/'report',conf,build)
    dest=desktop/f'CHOOSER_IV_EXPANDED_REPORT_{conf[:12]}.zip';temp=dest.with_suffix('.zip.partial')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(public.iterdir()):
            if p.is_file():z.write(p,p.name)
    with zipfile.ZipFile(temp) as z:
        if z.testzip():raise RuntimeError('Report archive failed CRC check')
    os.replace(temp,dest);Path(str(dest)+'.sha256').write_text(io.sha(dest)+'  '+dest.name+'\n')
    io.log('CHOOSER_IV_EXPANDED_COMPLETE');print('UPLOAD: '+str(dest));print('UPLOAD: '+str(dest)+'.sha256')


def execute(args):
    timings={};t0=time.monotonic()
    with io.heartbeat('Authenticating saved audit and comparison inputs'):inputs=sources.authenticate(args.project_root)
    cfg=dict(version=VERSION,package_manifest_sha256=io.sha(PKG/'PACKAGE_MANIFEST.sha256'),
        analysis_plan_sha256=io.sha(PKG/'ANALYSIS_PLAN.md'),authority=inputs['expanded_authority'],
        expected_candidate_rows=logic.EXPECTED_ROWS,specifications=logic.specifications(),
        reference_score_sd=stats.REFERENCE_SD,
        versions=dict(python=platform.python_version(),numpy=np.__version__,duckdb=duckdb.__version__,pyarrow=pa.__version__))
    conf=io.cfgsha(cfg);root=args.project_root/'derived/replication/chooser_iv_expanded_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.run.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('This expanded-IV run is already active')
        if (root/'config.json').exists() and io.load(root/'config.json')!=cfg:raise RuntimeError('Run configuration changed')
        io.js(root/'config.json',cfg);io.js(root/'input_verification_PRIVATE.json',inputs['snapshots'])
        freeze=root/'DESIGN_FREEZE.json'
        if freeze.exists():
            if io.load(freeze).get('config_sha256')!=conf:raise RuntimeError('Design freeze differs')
        else:io.js(freeze,dict(config_sha256=conf,utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            first_exposure_results_already_known=True,new_expanded_effects_read_before_freeze=False,
            specifications=logic.specifications(),analysis_plan_sha256=cfg['analysis_plan_sha256']))
        io.log('DESIGN_FROZEN: '+conf);io.log('Output: '+str(root))
        io.log(f'Local work only: up to {args.workers} scan/history workers; one large model at a time. No Lichess requests or Stockfish searches.')
        def timed(name,fn):
            at=time.monotonic()
            with io.heartbeat(name):r=fn()
            timings[name+'_seconds']=time.monotonic()-at;io.js(root/'runtime_PROGRESS.json',timings);return r
        timed('prepare_and_reproduce',lambda:prepare(inputs,root,conf,args.memory_gb*.6))
        volumes=timed('expanded_playing_volume',lambda:volume_scan(inputs,root,conf,args.workers))
        jobs=[dict(month=m,parts=[r['path'] for r in inputs['projection'] if r['month']==m],
            comparison=str(root/'prepared/comparison.parquet'),conf=conf,out=str(root/'comparison_events'/m),memory=args.memory_per_worker) for m in MONTHS]
        months=timed('comparison_history_events',lambda:io.mapped(comparison_events_job,jobs,args.workers,'Comparison history months'))
        jobs=[dict(shard=s,parts=[str(p) for d in months for p in (Path(d)/'events'/f'bucket={s}').glob('*.parquet')],comparison=str(root/'prepared/comparison.parquet'),
                   conf=conf,out=str(root/'comparison_history'/f'shard_{s:02d}'),memory=args.memory_per_worker) for s in range(16)]
        hdirs=timed('comparison_histories',lambda:io.mapped(comparison_history_job,jobs,args.workers,'Comparison history'))
        timed('prospective_entry_denominator',lambda:make_comparison(root,conf,args.memory_gb*.6,hdirs))
        timed('assemble_and_recount',lambda:assemble_exposures(inputs,root,conf,args.memory_gb*.6,volumes))
        for spec in logic.specifications():
            timed(spec['name'],lambda s=spec:model(root,conf,s));gc.collect()
        for r in inputs['snapshots']:
            if io.sig(r['path'])!=r['signature']:raise RuntimeError('Source changed during run')
        for r in inputs['chron']:
            if io.sig(r['path'])!=r['signature']:raise RuntimeError('Chronology changed during run')
        timings['total_this_invocation_seconds']=time.monotonic()-t0
        export_report(root,conf,args.desktop,timings)


def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=0)
    args=p.parse_args()
    if not args.project_root.is_dir():p.error('Connect XT_Pro and check the project root')
    if not 1<=args.workers<=10:p.error('Workers must be 1–10')
    if sys.platform=='darwin':
        import subprocess
        ram=int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize']).strip())/1024**3
    else:ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/1024**3
    args.memory_gb=min(args.memory_gb,ram*.60) if args.memory_gb>0 else ram*.60
    args.workers=min(args.workers,max(1,int(args.memory_gb//2.5)))
    args.memory_per_worker=max(.5,args.memory_gb/args.workers-1.0)
    args.desktop.mkdir(parents=True,exist_ok=True)
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    for line in (PKG/'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest,name=line.split('  ',1);io.checked(io.child(PKG,name),digest)
    try:execute(args)
    except KeyboardInterrupt:io.log('Stopped; rerun the same command to resume completed checkpoints.');raise SystemExit(130)
    except Exception as exc:
        import traceback
        traceback.print_exc();io.log('STOPPED: '+str(exc));raise SystemExit(2)

if __name__=='__main__':main()
