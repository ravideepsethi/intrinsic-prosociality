"""Frozen estimators, isolated material inputs and a single resource policy."""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[name]='1'
sys.path.insert(0,str(ROOT/'vendor/uniform'))
sys.path.insert(0,str(ROOT/'vendor'))
import fast_bootstrap as c
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import gc,json,time,hashlib
from util import require,log,heartbeat,read,save,sha,digest,signature,record,verify,MONTHS
DAY=c.DAY
PARENT='af114813b1add1405ce5f4a40d6968648f6dbc79ffa49199b185085371411ab3'
MATERIAL='aa7e95f275c18f43d9ad95af523b9b0d769704ddebf4aea4d3655a2e1b07ef5d'

def connect(folder,memory=4.): return c.conn(Path(folder),memory)
def stage(folder,conf,fn,deps=()): return c.stage(Path(folder),conf,fn,list(deps))
def view(db,name,paths):return c.view(db,name,paths)
def copy(db,sql,path):return c.copy_query(db,sql,Path(path))
def rows(path):return pq.ParquetFile(path).metadata.num_rows

def authenticate(a,run,conf):
    import material_inputs
    expected=read(ROOT/'authority/REVIEW.json')
    ma=material_inputs.authenticate(a.material_manifest,expected,min(a.workers,3))
    manifest=read(a.material_manifest)
    # The same reviewed contract also authenticates the donor universe.
    donors=[]
    for r in manifest['datasets']['all_source']:
        before=signature(r['path']);verify(r)
        require(rows(r['path'])==r['rows'],'Broad material footer differs')
        require(Path(r['path']).resolve().is_relative_to(a.material_manifest.parent/'PRIVATE/panels/all_source'),'Broad material path outside reviewed build')
        require(before==signature(r['path']),'Broad material input changed during authentication')
        donors.append(dict(r,signature=before))
    old=a.legacy_root
    require(c.key(c.load(old/'config.json'))==PARENT,'Wrong completed Uniform90 configuration')
    # Bind the exact report returned and reviewed, then authenticate private outputs
    # through the original producer's per-stage checksum receipts.
    authority=ROOT/'authority/uniform90'
    for branch,target in [('receipt',old/'report'),('comparisons',old/'comparisons/report')]:
        for f in (authority/branch).rglob('*'):
            if f.is_file():require(sha(target/f.relative_to(authority/branch))==sha(f),'Completed Uniform90 report changed: '+f.name)
    require(read(old/'report/STATUS.json')['status']=='COMPLETE','Uniform90 parent is incomplete')
    legacy=run/'legacy_auth';(legacy/'report').mkdir(parents=True,exist_ok=True)
    b=c.primary.bind(a,legacy,conf)
    oldframes=read(old/'PRIVATE/FRAMES90.json')
    for p in oldframes.values(): c.check_stage(p,PARENT)
    require(rows(oldframes['source'])==9736182,'Uniform90 primary row count differs')
    require(c.frozen.r.design.row_digest(c.frozen.col(oldframes['source'],'row_id'))=='fdb12d9955b1005f3df61738499d279aa4da07d1bb126d0db040b9f53a9b487f','Uniform90 primary IDs differ')
    result=dict(material=ma,donors=donors,legacy=b,legacy_frames=oldframes)
    save(run/'PRIVATE/AUTHENTICATED.json',result)
    return result

def guard(auth):
    import material_inputs
    material_inputs.guard(auth['material'])
    for r in auth['donors']:require(signature(r['path'])==r['signature'],'A material donor input changed')

def no_network():
    # Called after the separately recorded 15-game metadata cache completion.
    # Every analytical stage, including metadata reconciliation, blocks sockets.
    import socket
    def blocked(*args,**kwargs):raise RuntimeError('Production network access is disabled; cached inputs only')
    socket.create_connection=blocked
    socket.socket.connect=blocked
    socket.socket.connect_ex=blocked
