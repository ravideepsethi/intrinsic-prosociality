"""Shared, read-only source authentication and immutable continuation helpers."""
from engine import *
import argparse

PARENT=read(ROOT/'REMAINING_PARENT.json')

def parent_root(project):
    return project/'derived/replication/author_exclusion_repair_v130_PRIVATE'/PARENT['run_id']

def stage_output(parent,variant,family):
    r=read(parent/'PRIVATE/STAGES.json')[variant+'/'+family]
    require(r['status']=='COMPLETE','Prior stage incomplete: '+family)
    receipt=verify(r['receipt'])
    local=receipt.parents[3]/'PRIVATE/results'/variant/family
    if local.is_dir():return local
    # v120 copied completion receipts and aggregate tables, not private caches.
    # Resolve only the pinned v100 ancestor, with identical completion lineage.
    authority=read(ROOT/'PARENT_AUTHORITY.json')
    original=parent.parent.parent/'author_exclusion_reestimate_v100_PRIVATE'/authority['run_id']
    cfg=read(original/'PRIVATE/CONFIG.json')
    require(digest(cfg)[:16]==authority['run_id'] and cfg['code']==authority['v100_code'] and cfg['upstream_manifest']==authority['v100_upstream'],'Original cache configuration changed')
    source=read(original/'PRIVATE/STAGES.json')[variant+'/'+family]
    require(source['status']=='COMPLETE','Original cache stage incomplete')
    source_receipt=verify(source['receipt'])
    require(sha(source_receipt)==sha(receipt),'Copied receipt differs from original cache receipt')
    for item in source['aggregate_files']:verify(item)
    path=original/'PRIVATE/results'/variant/family
    require(path.is_dir(),'Authenticated original private cache missing: '+str(path))
    return path

def verify_report(expected,actual):
    records=[]
    for p in sorted(expected.rglob('*')):
        if not p.is_file():continue
        target=actual/p.relative_to(expected)
        require(target.is_file() and sha(target)==sha(p),'Reviewed report differs: '+str(target))
        records.append(record(target))
    require(records,'Empty report authority')
    return records

def checked_sidecar(path):
    """Verify a producer-owned leaf receipt; do not manufacture certification."""
    path=Path(path)
    for suffix in ('.ok.json','.receipt.json'):
        p=Path(str(path)+suffix)
        if p.exists():
            r=read(p);require(r.get('sha256')==sha(path),'Leaf checkpoint checksum differs: '+str(path))
            return record(path)
    raise RuntimeError('Required leaf receipt missing: '+str(path))

def removed_games(auths,c):
    inc=[x['path'] for x in auths['included']['month_records']]
    pair=names_pair(inc[0])
    c.execute('CREATE OR REPLACE TEMP TABLE author_games AS SELECT DISTINCT game_id FROM '+scan(inc)+' s WHERE '+author_sql(pair))
    n=c.execute('SELECT count(*) FROM author_games').fetchone()[0]
    require(n==42,'Reviewed 42-game author exclusion set changed')
    return n

def game_filter(c,path,target,variant):
    cols=pq.ParquetFile(path).schema_arrow.names
    require('game_id' in cols,'Source requires a game-identity bridge')
    query='SELECT s.* FROM '+scan(path)+' s'
    n=pq.ParquetFile(path).metadata.num_rows
    if variant=='excluded':query+=' ANTI JOIN author_games a USING(game_id)'
    kept=copy(c,query,target)
    return dict(before=n,after=kept,removed=n-kept)

def csv_reports(source,target):
    for p in source.rglob('*.csv'):
        rel=p.relative_to(source);table((target/rel).with_suffix(''),pd.read_csv(p))

def unique_path(paths,label):
    paths=sorted(set(Path(p).resolve() for p in paths if Path(p).is_file()))
    require(len(paths)==1,f'{label}: expected exactly one source, found {len(paths)}')
    return paths[0]

