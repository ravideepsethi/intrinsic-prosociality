"""Authentication of the frozen responsibility targets and engine units."""
import hashlib,json
from pathlib import Path

RUN_KEY='c539ba215e708b2218662d0fcbe507655abbb705ed13c5179c6601329036ce40'
LEGACY_MANIFEST='592348c05857f0c542e33c8ff824aa5121f1fd9c257e61e89c3e9bc58e9f7c11'
ENGINE_SHA='ae4c93fa9676ca7750d0714342fd8a5b1d018000fc6e0f6cedf112067b5ef374'
SAMPLE='a17c89d750cb4fdfdf84f950859e45c58b19996efae02045def68285e305cf30'
def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(8*1024**2),b''):h.update(b)
    return h.hexdigest()
def signature(x):return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def require(ok,s):
    if not ok:raise RuntimeError(s)
def receipt(p,key):
    p=Path(p);r=Path(str(p)+'.receipt.json')
    if not p.is_file() or not r.is_file():return False
    d=read(r)
    require(d['key']==key and d['sha256']==digest(p),'Legacy checkpoint failed verification: '+str(p))
    return True
def verify(run,legacy):
    manifest=read(legacy/'PACKAGE_HASHES.json')
    require(signature(manifest)==LEGACY_MANIFEST,'Unrecognized legacy package')
    for n,h in manifest.items():require(digest(legacy/n)==h,'Changed legacy file: '+n)
    i=read(run/'IDENTITY.json')
    require(i['key']==RUN_KEY and signature(i['inputs'])==RUN_KEY,'Different frozen run identity')
    require(i['inputs']['sample']==SAMPLE,'Different main sample')
    p=run/'PRIVATE/trajectory_targets.parquet'
    require(receipt(p,RUN_KEY),'Frozen responsibility targets not found. No sample will be rebuilt.')
    import pyarrow.parquet as pq
    d=pq.ParquetFile(p).read(columns=['game_id','chooser','ply_count','y','sf100k_stockfish_sha256']).to_pandas()
    require(len(d)==260863 and d.game_id.nunique()==260863 and d.chooser.nunique()==20000,'Frozen target counts differ')
    require(int(d.y.sum())==3755,'Frozen grant count differs')
    require(set(d.sf100k_stockfish_sha256)=={ENGINE_SHA},'Target engine lineage differs')
    require(int((d.ply_count.clip(upper=4)+1).sum())==1292336,'Frozen position count differs')
    return d
def units(run,targets):
    ids=targets.game_id.tolist();out=[]
    for start in range(0,len(ids),300):
        k=signature([RUN_KEY,ids[start:start+300],ENGINE_SHA]);name=f'{start//300:06d}'
        replay=run/'PRIVATE/replay'/f'{name}.json';scores=run/'PRIVATE/engine'/f'{name}.scores.json.gz'
        feature=run/'PRIVATE/engine'/f'{name}.parquet'
        ready=receipt(replay,k) and receipt(feature,k) and receipt(scores,k)
        out.append(dict(name=name,key=k,replay=str(replay),scores=str(scores),feature=str(feature),ready=ready))
    return out
