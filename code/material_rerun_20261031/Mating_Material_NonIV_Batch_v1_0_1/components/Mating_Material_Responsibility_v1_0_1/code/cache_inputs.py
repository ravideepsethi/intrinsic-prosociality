"""Authenticate the frozen target and repaired projections without engine work."""
from util import *
from concurrent.futures import ThreadPoolExecutor
import math

def legacy_digest(x):
    return hashlib.sha256(json.dumps(x,sort_keys=True,default=str).encode()).hexdigest()

def checked(path,key=None):
    path=Path(path);require(path.is_file(),'Required cached input missing: '+str(path))
    sidecars=[Path(str(path)+s) for s in ('.ok.json','.receipt.json') if Path(str(path)+s).is_file()]
    require(sidecars,'Producer receipt missing: '+str(path))
    before=signature(path);checksum=sha(path)
    for p in sidecars:
        r=read(p);require(r.get('sha256')==checksum,'Producer receipt checksum differs: '+str(path))
        if key is not None:require(r.get('key')==key,'Producer receipt belongs to another cache: '+str(path))
    require(before==signature(path),'Cache changed during authentication')
    return dict(path=str(path),bytes=before[2],sha256=checksum,signature=before,receipts=[dict(record(p),signature=signature(p)) for p in sidecars])

def authenticate_cache(project,workers,authority=None,reference=None):
    import pyarrow.parquet as pq
    reference=Path(reference or ROOT/'evidence/a2_reference');authority=authority or read(ROOT/'authority/SOURCES.json')
    lineage=read(reference/'LINEAGE.json');target=Path(project)/authority['frozen_target_relative']
    old=Path(project)/authority['repaired_root_relative'];report=old/'report'
    expected_hashes=read(reference/'REPORT_HASHES.json');records=[]
    # The reviewed result hash manifest binds the original 53 estimates and diagnostics.
    for name,checksum in sorted(expected_hashes.items()):
        p=(report/name).resolve();require(p.is_relative_to(report.resolve()),'Unsafe report member')
        require(p.is_file() and sha(p)==checksum,'Reviewed repaired report differs: '+str(p))
        records.append(dict(record(p),signature=signature(p)))
    require(read(report/'LINEAGE.json')==lineage,'Repaired feature lineage changed')
    done=read(report/'COMPLETION.json')
    require(done['status']=='A2_SCORE_REPAIR_COMPLETE_REVIEW_REQUIRED' and done['models']==53,'Repaired A2 run was not completed')
    tr=checked(target,lineage['legacy_run']);require(tr['sha256']==lineage['target_sha256'],'Frozen target hash differs')
    ids=pq.ParquetFile(target).read(columns=['game_id','chooser','y','sf100k_stockfish_sha256'],use_threads=False).to_pandas()
    require(len(ids)==lineage['opportunities'] and ids.game_id.notna().all() and ids.game_id.nunique()==len(ids),'Frozen target game roster differs')
    require(ids.chooser.nunique()==lineage['choosers'] and int(ids.y.sum())==lineage['grants'],'Frozen target census differs')
    require(set(ids.sf100k_stockfish_sha256)=={lineage['engine_sha256']},'Frozen target engine differs')
    game_ids=ids.game_id.tolist();expected_names=[f'{i:06d}.parquet' for i in range(math.ceil(len(ids)/300))]
    actual=sorted(p.name for p in (old/'PRIVATE/projected').glob('*.parquet'))
    require(actual==expected_names,'Repaired projection inventory incomplete or unexpected')
    def check_unit(i):
        name=expected_names[i];subset=game_ids[i*300:(i+1)*300]
        overlay=checked(old/'PRIVATE/overlay_shards'/name)
        unit=legacy_digest([lineage['legacy_run'],subset,lineage['engine_sha256']])
        key=legacy_digest([lineage['key'],unit,'projection',overlay['sha256']])
        feature=checked(old/'PRIVATE/projected'/name,key)
        actual_ids=pq.ParquetFile(feature['path']).read(columns=['game_id'],use_threads=False).column('game_id').to_pylist()
        require(len(actual_ids)==len(subset) and len(set(actual_ids))==len(subset) and set(actual_ids)==set(subset),'Projection game membership differs: '+name)
        return dict(feature=feature,overlay=overlay)
    with heartbeat('Authenticating repaired engine-feature caches'),ThreadPoolExecutor(max_workers=min(10,workers)) as pool:
        units=list(pool.map(check_unit,range(len(expected_names))))
    records.append(tr)
    for item in units:records.extend([item['feature'],item['overlay']])
    key=digest(dict(lineage=lineage,files=[{k:r[k] for k in ('path','bytes','sha256')} for r in records]))
    return dict(key=key,target=str(target),features=[x['feature']['path'] for x in units],lineage=lineage,records=records)

def guard_cache(cache):
    for r in cache['records']:
        require(signature(r['path'])==r['signature'],'A frozen feature input changed during the run')
        for receipt in r.get('receipts',[]):
            require(signature(receipt['path'])==receipt['signature'],'An input receipt changed during the run')
