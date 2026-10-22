"""Use the exact scientific producer that certified R9, not its older namesake."""
from pathlib import Path
import sys
from release100 import PACKAGE, VERSION, verify_release, zip_report
sys.path.insert(0,str(PACKAGE/'vendor_r9_resume/code'))
import r9_env_resume as repair
from r9_common import *
import r9_inputs as inputs
import r9_scores as scores_code
import r9_models as fits

CERTIFIED_CONF='4028bf3e185783a17679ed3d5fee5b376028f37141e1e5ce09b93b068a6a6e0b'
COMMON_SD=0.04979005187533171
SCIENTIFIC_MANIFEST='450837fec023b0b4157345b640d9997b2779da71daa7f003d7562d17867e8874'
EVIDENCE=PACKAGE/'evidence/completed_r9'

def bind_certified(project):
    base=project/'derived/replication/r9_certified_leave_pair_out_v100_PRIVATE'/CERTIFIED_CONF[:12]
    config=u.load(base/'config.json');summary=u.load(base/'report/summary.json')
    u.require(r.io.cfgsha(config)==CERTIFIED_CONF,'Completed R9 configuration differs')
    u.require(config['package_sha256']==SCIENTIFIC_MANIFEST and config['definition']==DEFINITION,'Certified scientific definition differs')
    u.require(summary==u.load(EVIDENCE/'summary.json'),'Completed R9 report changed')
    u.require(summary['status']=='R9_COMPLETE' and summary['completed_model_count']==24,'R9 is not the reviewed completed run')
    for v in u.load(EVIDENCE/'REPORT_MANIFEST.json'):
        r.io.checked(base/'report'/v['path'],v['sha256'],v['bytes'])
    scale=u.load(base/'common_scale.json')
    u.require(scale['common_score_SD']==COMMON_SD,'Frozen Score A scale differs')
    prepared=u.load(base/'PREPARED_INPUTS_PRIVATE.json')
    paths={k:u.relocate(v,project) for k,v in prepared.items()}
    for sample in ('F','O'):stage_file(paths[sample],CERTIFIED_CONF)
    for sample in ('S0','F'):stage_file(base/'scores_combined'/(sample+'.parquet'),CERTIFIED_CONF)
    stage_file(base/'ordinary_scores/scores.parquet',CERTIFIED_CONF)
    stage_file(base/'environment/combined_rates/rates.parquet',CERTIFIED_CONF)
    oldfits={};verified_dependencies={}
    for level in LEVELS:
        for sample,name in [('S0','S0__full__A__'),('F','F75__A__'),('O','O75__A__')]:
            out=base/'fits'/(name+level)
            old.prior.check_stage(out,CERTIFIED_CONF,['result.json','influence_PRIVATE.parquet','dependencies_PRIVATE.json'])
            for dep in u.load(out/'dependencies_PRIVATE.json'):
                p=u.relocate(dep['path'],project).resolve()
                if p in verified_dependencies:
                    u.require(verified_dependencies[p]==(dep['sha256'],r.io.sig(p)),'Archived dependency changed between model checks')
                else:
                    r.io.checked(p,dep['sha256']);verified_dependencies[p]=(dep['sha256'],r.io.sig(p))
            result=u.load(out/'result.json')
            u.require(result['estimates'][0]['score']=='A' and result['estimates'][0]['control_mode']=='matched','Wrong archived model')
            oldfits[(sample,level)]=out
    return base,paths,oldfits,summary

def compare_score_overlap(new_frame,new_scores,old_frame,old_scores,root,conf,memory):
    """Bind frozen scores by game identity, including donor controls and diagnostics."""
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            for name,path in [('nf',new_frame),('ns',new_scores),('ofr',old_frame),('osr',old_scores)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
                u.require(c.execute('SELECT count(*)-count(DISTINCT row_id) FROM '+name).fetchone()[0]==0,'Duplicate score bridge keys')
            c.execute('CREATE VIEW a AS SELECT ofr.row_id,ns.* EXCLUDE(row_id) FROM nf JOIN ns USING(row_id) JOIN ofr USING(game_id)')
            n=pq.ParquetFile(old_scores).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT row_id) FROM a JOIN osr USING(row_id)').fetchone()==(n,n),'Score bridge lost old games')
            for field in pq.ParquetFile(old_scores).schema_arrow:
                k=field.name
                if k=='row_id':continue
                bad=f'a."{k}" IS DISTINCT FROM osr."{k}"'
                if pa.types.is_floating(field.type):bad='('+bad+f') AND NOT coalesce(abs(a."{k}"-osr."{k}")<=2e-10,FALSE)'
                u.require(c.execute('SELECT count(*) FROM a JOIN osr USING(row_id) WHERE '+bad).fetchone()[0]==0,'Certified score changed: '+k)
            return dict(rows_checked=n,all_score_columns_reproduced=True,game_identity_checked=True)
        finally:r.finish_connection(c,tmp/'spill')
    return r.stable_stage(root,conf,build,[new_frame,new_scores,old_frame,old_scores])[1]

def select_band(source,scores,membership,root,conf,memory):
    """Select prespecified added games without deriving a new score or scale."""
    def build(tmp):
        c=u.conn(tmp/'spill',memory,1)
        try:
            for name,path in [('a',source),('s',scores),('b',membership)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
                u.require(c.execute('SELECT count(*)-count(DISTINCT row_id) FROM '+name).fetchone()[0]==0,'Duplicate band row IDs')
            n=pq.ParquetFile(membership).metadata.num_rows
            u.require(c.execute('SELECT count(*),count(DISTINCT a.game_id) FROM a JOIN b USING(row_id,game_id)').fetchone()==(n,n),'Added band identity differs')
            rows=r.io.copy(c,'SELECT a.* FROM a SEMI JOIN b USING(row_id,game_id) ORDER BY row_id',tmp/'model.parquet')
            scored=r.io.copy(c,'SELECT s.* FROM s SEMI JOIN b USING(row_id) ORDER BY row_id',tmp/'scores.parquet')
            u.require(rows==scored==n,'Band score attachment lost rows')
            return dict(rows=n,frozen_hash_band='75_to_100',score_reused=True)
        finally:r.finish_connection(c,tmp/'spill')
    folder,info=r.stable_stage(root,conf,build,[source,scores,membership])
    return folder/'model.parquet',folder/'scores.parquet',public(info)

def extend_environment(paths,binding,certified_root,root,conf,workers,memory):
    """Identical ENV producers; reuse the larger completed 75% rate cache."""
    oldrates=stage_file(certified_root/'environment/combined_rates/rates.parquet',CERTIFIED_CONF)
    req,info=inputs.upstream_inputs.missing_requests([paths['F'],paths['O']],oldrates,root/'requests',conf,memory-2)
    ratepaths=[oldrates];scan={};schedule={}
    if info['missing_requests']:
        e=Path(binding['environment']['root']);ec=binding['environment']['conf'];panels=[]
        for folder in sorted((e/'rate_panels').iterdir()):
            if not folder.is_dir() or not (folder/'_DONE.json').exists():continue
            p=stage_file(folder/'events.parquet',ec);meta=u.load(folder/'_DONE.json')
            panels.append(dict(path=str(p),minimum=meta['minimum'],maximum=meta['maximum']))
        u.require(bool(panels),'ENV numerator caches missing')
        jobs,scan=r.env_rates.chronology_jobs(binding['source']['chron'],info['windows'],panels,req,root/'rate_parts',conf,3.)
        for job in jobs:job.update(authors=binding['author_ids'],memory_gb=4.5)
        repair.map_environment(jobs,workers,memory,'New ENV pair/month requests',40,55,audit=schedule)
        rates,_=r.env_rates.combine(req,[v['output'] for v in jobs],[v['path'] for v in panels],root/'fresh_rates',conf,memory-2,1)
        ratepaths.append(rates/'rates.parquet')
    def union(tmp):
        c=u.conn(tmp/'spill',memory-2,1)
        try:
            c.execute('CREATE VIEW a AS '+' UNION ALL '.join('SELECT * FROM '+u.parq([p]) for p in ratepaths))
            u.require(c.execute('SELECT count(*)-count(DISTINCT (person,partner,month_code)) FROM a').fetchone()[0]==0,'Duplicate ENV keys')
            return dict(rows=r.io.copy(c,'SELECT * FROM a ORDER BY person,partner,month_code',tmp/'rates.parquet'))
        finally:r.finish_connection(c,tmp/'spill')
    rates=r.stable_stage(root/'combined_rates',conf,union,ratepaths)[0]/'rates.parquet'
    result=dict(paths)
    for sample in ('F','O'):
        dest,_=r.env_rates.attach(paths[sample],rates,root/sample,conf,memory-2);result[sample]=dest/'model.parquet'
    return result,dict(public(info),scan=scan,certified75_rates_reused=True,environment_scheduler=schedule)
