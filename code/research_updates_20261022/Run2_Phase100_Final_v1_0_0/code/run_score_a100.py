"""Extend only comparison models around the certified current receipt IV."""
from score_a100_common import *
import score_a100_report as report
import argparse, fcntl, time

def verify_same_score_rows(left,right,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            for name,path in [('a',left),('b',right)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
            n=pq.ParquetFile(left).metadata.num_rows
            u.require(n==pq.ParquetFile(right).metadata.num_rows,'S0 score count changed')
            u.require(c.execute('SELECT count(*),count(DISTINCT a.row_id) FROM a JOIN b USING(row_id)').fetchone()==(n,n),'S0 score identities changed')
            for field in pq.ParquetFile(right).schema_arrow:
                k=field.name;bad=f'a."{k}" IS DISTINCT FROM b."{k}"'
                if pa.types.is_floating(field.type):bad='('+bad+f') AND NOT coalesce(abs(a."{k}"-b."{k}")<=2e-10,FALSE)'
                u.require(c.execute('SELECT count(*) FROM a JOIN b USING(row_id) WHERE '+bad).fetchone()[0]==0,'Certified S0 score changed: '+k)
            return dict(rows=n,all_score_columns_reproduced=True,receipt_models_reusable=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[left,right])[1]

def verify_env_overlap(new,previous,root,conf,memory):
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            for name,path in [('a',new),('b',previous)]:c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
            n=pq.ParquetFile(previous).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT a.game_id) FROM a JOIN b USING(game_id)').fetchone()==(n,n),'ENV bridge lost games')
            for name in r.ENV+['environment_supported']:
                bad=f'a."{name}" IS DISTINCT FROM b."{name}"'
                if name!='environment_supported':bad='('+bad+f') AND NOT coalesce(abs(a."{name}"-b."{name}")<=2e-12,FALSE)'
                u.require(c.execute('SELECT count(*) FROM a JOIN b USING(game_id) WHERE '+bad).fetchone()[0]==0,'Frozen ENV values changed: '+name)
            return dict(rows=n,all_environment_controls_reproduced=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[new,previous])[1]

def execute(a):
    started=time.monotonic();verify_release();repair.verify_package();u.no_network();r.threads_one()
    project=a.project_root.expanduser().resolve();desktop=a.desktop.expanduser().resolve();desktop.mkdir(parents=True,exist_ok=True)
    with heartbeat('Authenticate completed R9 and final comparison frames',10,160):
        certified,oldpaths,oldfits,certsummary=bind_certified(project)
        paths,binding,parts,reference,cutoff,baseline=inputs.bind_baseline(project)
        frame_root=Path(u.load(desktop/'RUN2_PHASE_100_FRAMES_LATEST_PRIVATE.json')['root'])
        u.require(frame_root.resolve().is_relative_to(project),'Final frame path outside project')
        comparisons,phase,frame_root=inputs.bind_phase(project,desktop,frame_root);paths.update(comparisons)
        u.require(phase['phase_percent']==100,'Final analysis requires the completed 100% frames')
        source_check=inputs.verify_phase_source(frame_root,binding,parts)
        r.io.checked(paths['S0'],u.sha(oldpaths['S0']))
    config=dict(version='1.0.0',package_sha256=u.sha(PACKAGE/'PACKAGE_MANIFEST.sha256'),
        certified_configuration=CERTIFIED_CONF,comparison_phase=phase,reference_sha256=u.sha(reference),
        definition=DEFINITION,common_score_SD=COMMON_SD,
        comparison_cohorts=['fixed100','added75_to100'],controls=list(LEVELS),
        original_equivalence_margin=dict(pp=.015,fixed_score_SD=.0594),main_IV_reused=True)
    conf=r.io.cfgsha(config);root=project/'derived/replication/run2_phase100_score_a_v100_PRIVATE'/conf[:12]
    root.mkdir(parents=True,exist_ok=True);lock=(root/'RUN.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise RuntimeError('This final comparison run is already active')
    plan=[];contrasts=[]
    extra=dict(comparison_frame=phase,source_lineage_check=source_check,
        completed_receipt_models_reused=True,requested_workers=a.workers,total_memory_budget_gib=a.memory_gb,
        metadata_quarantine=u.load(frame_root/'report/summary.json').get('metadata_quarantine'))
    try:
        if (root/'config.json').exists():u.require(u.load(root/'config.json')==config,'Run definition changed')
        else:r.io.js(root/'config.json',config)
        r.io.js(desktop/'RUN2_PHASE_100_SCORE_A_LATEST_PRIVATE.json',dict(root=str(root),configuration_sha256=conf))
        r.io.js(root/'INPUTS_PRIVATE.json',dict(paths={k:str(v) for k,v in paths.items()},comparison_root=str(frame_root),certified_root=str(certified)))
        with heartbeat('Verify old feature overlap and prepare shared donor queries',6,145):
            extra['feature_bridges']=[public(inputs.verify_frame_bridge(paths[k],oldpaths[k],root/'frame_bridges'/k,conf,a.memory_gb-2)) for k in ('F','O')]
            for sample in ('F','O'):
                for role in ('recipient_id','opponent_id'):
                    u.require(not np.isin(col(paths[sample],role),binding['author_ids']).any(),'Author in final comparison')
            queries=scores_code.prepare_queries(paths,root/'queries',conf)
        jobs=[]
        for shard in range(16):
            chosen=[v for v in parts if v['shard']==shard];nq=pq.ParquetFile(queries/f'{shard:02}.parquet').metadata.num_rows
            jobs.append(dict(shard=shard,parts=chosen,queries=str(queries/f'{shard:02}.parquet'),authors=binding['author_ids'],reference=str(reference),
                output=str(root/'scores'/f'{shard:02}'),conf=conf,memory_gb=.9+(sum(v['rows'] for v in chosen)*530+nq*850)/1024**3))
        info=runtime.mapped(scores_code.score_job,jobs,a.workers,a.memory_gb,'Current Score A: one donor pass and independent replay',25,110)
        u.require(sum(v['source_rows'] for v in info)==47587020,'Donor source total changed')
        with heartbeat('Check certified scores and share entry scores with ordinary games',8,100):
            scores,scoreinfo=scores_code.combine(jobs,paths,baseline,root/'scores_combined',conf,a.memory_gb-2)
            extra['score_diagnostics']=scoreinfo['diagnostics'];extra['legacy_score_reproduction']=scoreinfo['baseline_scores_reproduced']
            extra['S0_score_bridge']=verify_same_score_rows(scores['S0'],certified/'scores_combined/S0.parquet',root/'certified_score_bridge/S0',conf,a.memory_gb-2)
            extra['F75_score_bridge']=compare_score_overlap(paths['F'],scores['F'],oldpaths['F'],certified/'scores_combined/F.parquet',root/'certified_score_bridge/F75',conf,a.memory_gb-2)
            scores['O'],extra['ordinary_score_subset']=scores_code.ordinary(paths,scores['F'],root/'ordinary_scores',conf,a.memory_gb-2)
        report.export(root,desktop,conf,'SCORES_VERIFIED_ENV_PENDING',extra,oldfits)
        with heartbeat('Reuse completed ENV histories; calculate only missing requests',40,80):
            paths,extra['environment_extension']=extend_environment(paths,binding,certified,root/'environment',conf,a.workers,a.memory_gb)
            extra['environment_bridges']=[public(verify_env_overlap(paths[k],oldpaths[k],root/'environment_bridges'/k,conf,a.memory_gb-2)) for k in ('F','O')]
        r.io.js(root/'PREPARED_INPUTS_PRIVATE.json',{k:str(v) for k,v in paths.items()})
        bands={}
        with heartbeat('Prepare fixed final-quarter comparisons',4,55):
            for sample,family in [('F','entry'),('O','ordinary')]:
                src,sc,meta=select_band(paths[sample],scores[sample],frame_root/'split'/(family+'_increment_75_100.parquet'),root/'bands'/sample,conf,a.memory_gb-2)
                bands[sample]=(src,sc)
        for label in ('100','75_100'):
            for sample,kind in [('F','entry'),('O','ordinary')]:
                src,sc=(paths[sample],scores[sample]) if label=='100' else bands[sample]
                for level in LEVELS:
                    plan.append(fits.make_job(src,sc,root/'fits'/(sample+label+'__A__'+level),conf,sample+label,kind,level))
        r.io.js(root/'MODEL_PLAN_PRIVATE.json',plan)
        report.export(root,desktop,conf,'FROZEN_MODELS_READY',extra,oldfits,plan)
        def update(*_):report.export(root,desktop,conf,'MODEL_RESULTS_PARTIAL',extra,oldfits,plan)
        runtime.mapped(fits.fit_job,plan,a.workers,a.memory_gb,'Final and added-quarter ordinary/entry models',40,15,update)
        lookup={(j['sample'],j['level']):j['output'] for j in plan}
        for level in LEVELS:
            contrasts.append(dict(left=str(oldfits[('S0',level)]),right=lookup[('O100',level)],label='S0_minus_ordinary100',outcomes=['y','reached'],
                level=level,conf=conf,output=str(root/'contrasts'/('S0_minus_ordinary100__'+level)),memory_gb=9.3))
            for sample,outcomes in [('F',['analysis_entry_90','recipient_disconnect_main','active_timeout']),('O',['y','reached'])]:
                contrasts.append(dict(left=lookup[(sample+'75_100',level)],right=str(oldfits[(sample,level)]),label=sample+'_added75_100_minus_first75',
                    outcomes=outcomes,level=level,conf=conf,output=str(root/'contrasts'/(sample+'_added_minus75__'+level)),memory_gb=9.3))
        runtime.mapped(fits.contrast_job,contrasts,a.workers,a.memory_gb,'Joint account/date covariance for all comparisons',15)
        extra['elapsed_seconds']=time.monotonic()-started
        report.export(root,desktop,conf,'PHASE_100_SCORE_A_COMPLETE',extra,oldfits,plan,contrasts)
        u.log('COMPLETE. Return RUN2_PHASE_100_SCORE_A_REPORT_*.zip, its sidecar, and this log.')
    except BaseException as exc:
        extra['error_type']=type(exc).__name__
        try:report.export(root,desktop,conf,'STOPPED_RETURN_LOG',extra,oldfits,plan,contrasts)
        except Exception as failure:u.log('Stopped report could not be refreshed: '+str(failure))
        raise
    finally:lock.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project-root',type=Path,default=Path('/Volumes/XT_Pro/lichess_kindness'))
    p.add_argument('--desktop',type=Path,default=Path.home()/'Desktop/Lichess_Desktop')
    p.add_argument('--workers',type=int,default=10);p.add_argument('--memory-gb',type=float,default=11)
    a=p.parse_args();u.require(1<=a.workers<=10 and a.memory_gb==11,'Use 1–10 workers and --memory-gb 11')
    execute(a)

if __name__=='__main__':main()
