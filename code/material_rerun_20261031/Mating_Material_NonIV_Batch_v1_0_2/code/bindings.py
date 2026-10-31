"""Material eligibility and fresh labels; never treat old decisions as factual history."""
from engine import *
from remaining_common import unique_path

def guarded_join(c,old,fresh,target,*,old_id='game_id',new_id='game_id',replacements=None,
                 checks=None,cover_fresh=False,where='TRUE'):
    """Retain a frozen factual roster, replacing every specified decision field.

    Unique identities and exact factual agreement are checked before any output
    is committed. Coverage of the fresh source is optional for frozen subsamples.
    """
    replacements=replacements or {};checks=checks or {}
    c.execute('CREATE OR REPLACE TEMP VIEW old_bridge AS SELECT * FROM '+scan(old))
    c.execute('CREATE OR REPLACE TEMP VIEW fresh_bridge AS SELECT * FROM '+scan(fresh)+' WHERE '+where)
    for view,col in [('old_bridge',old_id),('fresh_bridge',new_id)]:
        n,u,missing=c.execute(f'SELECT count(*),count(DISTINCT {ident(col)}),count(*) FILTER(WHERE {ident(col)} IS NULL) FROM {view}').fetchone()
        require(n==u and missing==0,'Duplicate or missing bridge identity: '+view)
    on=f'o.{ident(old_id)}=n.{ident(new_id)}'
    if cover_fresh:
        missing=c.execute('SELECT count(*) FROM fresh_bridge n ANTI JOIN old_bridge o ON '+on).fetchone()[0]
        require(missing==0,f'Factual cache lacks {missing} newly eligible rows')
    if checks:
        bad=c.execute('SELECT count(*) FROM old_bridge o JOIN fresh_bridge n ON '+on+' WHERE '+
            ' OR '.join(f'o.{ident(k)} IS DISTINCT FROM ({v})' for k,v in checks.items())).fetchone()[0]
        require(bad==0,'Factual bridge mismatch; refusing an outcome-only update')
    cols=[r[0] for r in c.execute('DESCRIBE old_bridge').fetchall()]
    require(set(replacements)<=set(cols),'Replacement field absent in frozen cache')
    select=','.join((f'({replacements[k]}) AS {ident(k)}' if k in replacements else 'o.'+ident(k)) for k in cols)
    n=copy(c,'SELECT '+select+' FROM old_bridge o JOIN fresh_bridge n ON '+on,target)
    oldn=c.execute('SELECT count(*) FROM old_bridge').fetchone()[0]
    changes={k:c.execute('SELECT count(*) FROM old_bridge o JOIN fresh_bridge n ON '+on+
                        f' WHERE o.{ident(k)} IS DISTINCT FROM ({v})').fetchone()[0] for k,v in replacements.items()}
    return dict(before=oldn,after=n,removed=oldn-n,relabelled=changes)

def reviewed_stage(project,family):
    review=read(ROOT/'authority'/f'{family}_review.json')
    root=Path(project)/f'derived/replication/mating_material_{family}_v100_PRIVATE'/review['run_id'][:16]
    success=read(root/'_SUCCESS.json')
    for k in ('run_id','parent_run_id','status'):
        require(success[k]==review[k],'Reviewed '+family+' identity differs')
    require(sha(root/'report/RESULTS.json')==sha(ROOT/'authority'/f'{family}_review.json'),'Reviewed results changed')
    for r in success['files']:
        rel=Path(r['path']);require(not rel.is_absolute() and '..' not in rel.parts,'Unsafe stage receipt')
        verify(dict(r,path=str(root/rel)))
    return root

def public_copy(source,target):
    """Only producer aggregate directories, excluding private rows and caches."""
    source,target=Path(source),Path(target)
    for p in sorted(source.rglob('*')):
        rel=p.relative_to(source)
        if not p.is_file() or any('private' in x.lower() or x.lower() in ('scratch','spill','tmp') for x in rel.parts):continue
        if p.suffix not in ('.json','.csv','.txt','.pdf','.png','.tex','.npz'):continue
        dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)

def import_vendor(name,sub=''):
    path=ROOT/'vendor'/name/sub;sys.path.insert(0,str(path));return path
