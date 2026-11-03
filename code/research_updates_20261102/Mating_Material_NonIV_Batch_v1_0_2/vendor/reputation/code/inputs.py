"""Explicit producer-bound adapters for the existing 24-month files."""
import csv
from core import *

MAIN='derived/replication/analysis_panel_pool_nonadjacent_24m_v100_PRIVATE'
CHRON='output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/chronology_input_manifest.tsv'
OLD='derived/replication/chooser_iv_repeated_audit_v100_PRIVATE/4c63c67300ee'
OLD_CONFIG='4c63c67300eeecd9873fdf27b99e5821dbb2fffeddd32a8a8b86efce2f2ef156'
REQUIRED={'game_id','month','chooser_user_id','disconnected_user_id','utc_ms','api_last_move_at_ms',
 'chooser_color','kind_draw','fair_competitive','clearly_worse','engine_eval_cp_disconnected',
 'chooser_elo','disconnected_elo','chooser_pre_rd_v2','disconnected_pre_rd_v2','chooser_draw_payoff_v2',
 'chooser_win_premium_v2','white_win_premium_v2','black_win_premium_v2',
 'chooser_clock_last_obs_s','disconnected_clock_last_obs_s','ply_count','api_speed','tc_base_s','tc_inc_s',
 'chooser_username_norm','disconnected_username_norm','timeout_chooser_win','white_id','black_id'}
BROAD_REQUIRED={'game_id','chooser_user_id','disconnected_user_id','utc_ms','api_last_move_at_ms','chooser_color',
    'white_win_premium_v2','black_win_premium_v2','chooser_username_norm','disconnected_username_norm','timeout_chooser_win'}

def recursive_records(x):
    if isinstance(x,dict):
        if ('path' in x or 'relative_path' in x) and ('sha256' in x):yield x
        for v in x.values():yield from recursive_records(v)
    elif isinstance(x,list):
        for v in x:yield from recursive_records(v)

def discover(project,work):
    project=Path(project);auth=Path(work)/'authentication';report=load(PACKAGE/'authority/main_sample_report.json')
    main=project/MAIN;out=[]
    for r in report['panel_outputs']:
        p=main/r['relative_path'];verify(p,r['sha256'],auth)
        if pq.ParquetFile(p).metadata.num_rows!=r['rows'] or not REQUIRED<=columns(p):
            raise RuntimeError('Main-panel schema/count differs: '+str(p))
        out.append(dict(path=str(p),month=r['month'],rows=r['rows'],fingerprint=stamp(p)))
    if len(out)!=24 or sum(x['rows'] for x in out)!=41534331:raise RuntimeError('Wrong main panel')
    fp=load(PACKAGE/'authority/first_pair_authority.json');mp=project/CHRON
    verify(mp,fp['chronology_manifest_sha256'],auth)
    with mp.open() as f:records=list(csv.DictReader(f,delimiter='\t'))
    if len(records)!=852 or sum(int(x['rows']) for x in records)!=7763847245:raise RuntimeError('Historical chronology scope changed')
    chron=[]
    for k,r in enumerate(records):
        p=relocate(r['path'],project)
        speed=next((x.split('=',1)[1] for x in p.parts if x.startswith('speed=')),None)
        month=next((x.split('=',1)[1] for x in p.parts if x.startswith('month=')),None)
        if not speed or not month:raise RuntimeError('Chronology partition metadata absent')
        if speed not in SPEEDS or month>'2025-10':continue
        pf=pq.ParquetFile(p)
        if p.stat().st_size!=int(r['bytes']) or pf.metadata.num_rows!=int(r['rows']) or not {'utc_ms','white_id','black_id','game_id'}<=columns(p):
            raise RuntimeError('Chronology metadata differs: '+str(p))
        chron.append(dict(path=str(p),rows=int(r['rows']),month=month,speed=speed,index=int(r['file_index']),fingerprint=stamp(p)))
    required={(m,s) for m in ['2023-08','2023-09','2023-10']+[r['month'] for r in out] for s in SPEEDS}
    if required-{(r['month'],r['speed']) for r in chron}:raise RuntimeError('Current all-speed history has a missing month')
    # A byte-pinned input manifest can provide the all-source repayment panel.
    broad=[];bstatus='NOT_RESOLVED_FROM_PINNED_INPUT_MANIFEST'
    entry=next(r for r in report['files'] if r['relative_path']=='INPUT_FILES.json');mf=main/'INPUT_FILES.json'
    if mf.is_file():
        verify(mf,entry['sha256'],auth)
        unique={}
        for r in recursive_records(load(mf)):
            raw=r.get('path',r.get('relative_path'));p=relocate(raw,project)
            if not p.is_absolute():p=project/p
            if p.suffix=='.parquet' and 'analysis_panel_24m_sf100k' in p.parts:
                unique[str(p)]=r
        for p0,r in unique.items():
            p=Path(p0)
            if not p.is_file():
                bstatus='PINNED_ALL_SOURCE_FILE_UNAVAILABLE; MAIN_PANEL_FALLBACK'
                broad=[]
                break
            present=columns(p)
            if not BROAD_REQUIRED<=present or not {'kind_draw','outcome_kind_draw'}&present:continue
            verify(p,r['sha256'],auth)
            broad.append(dict(path=str(p),rows=pq.ParquetFile(p).metadata.num_rows,fingerprint=stamp(p)))
        if broad and sum(r['rows'] for r in broad)==47587020:bstatus='PINNED_ALL_SOURCE_24M_PANEL'
        else:broad=[]
    # Earliest-pair answers only; these cannot replace complete later encounters.
    old=None;oldroot=project/OLD
    if (oldroot/'config.json').is_file() and digest(load(oldroot/'config.json'))==OLD_CONFIG:
        done=oldroot/'prepared/_DONE.json';kp=oldroot/'prepared/pair_keys.npy'
        if done.is_file() and kp.is_file():
            rr=load(done)
            matches=[r for r in rr.get('files',[]) if r.get('path',r.get('relative_path'))=='pair_keys.npy']
            if rr.get('config_sha256')==OLD_CONFIG and len(matches)==1:
                verify(kp,matches[0]['sha256'],auth);old=dict(root=str(oldroot),keys=str(kp),config=OLD_CONFIG)
    result=dict(panels=out,chronology=chron,broad=broad,broad_status=bstatus,old_cache=old,
        source_identity='Main panel bytes pinned; chronology original manifest/metadata plus fresh fingerprints; not new full-byte hashes of all chronology',
        historical_first_month=min(r['month'] for r in chron))
    dump(Path(work)/'INPUTS_PRIVATE.json',result);return result

def projection_job(job):
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
    p=Path(job['source']['path']);folder=Path(job['folder']);old=cached(folder)
    if old:return dict(**old,reused=True,folder=str(folder))
    if stamp(p)!=job['source']['fingerprint']:raise RuntimeError('Panel changed')
    folder.mkdir(parents=True,exist_ok=True)
    if job['broad']:return broad_projection(job)
    cols=sorted(REQUIRED);pf=pq.ParquetFile(p);writer=None
    counts=dict(source_rows=0,author_rows=0,sampled_rows=0);census=[]
    try:
        for b in pf.iter_batches(columns=cols,batch_size=131072,use_threads=False):
            t=pa.Table.from_batches([b]);n=len(t);counts['source_rows']+=n
            if any(t[k].null_count for k in ('chooser_user_id','disconnected_user_id','utc_ms','api_last_move_at_ms','kind_draw','fair_competitive','clearly_worse','chooser_username_norm','disconnected_username_norm')):
                raise RuntimeError('Missing identity/time/outcome in source panel')
            j=array(t,'chooser_user_id',np.int64);i=array(t,'disconnected_user_id',np.int64);pk=pairs(j,i)
            namesj=np.asarray([str(x).strip().lower() for x in t['chooser_username_norm'].to_pylist()]);namesi=np.asarray([str(x).strip().lower() for x in t['disconnected_username_norm'].to_pylist()])
            author=np.isin(namesj,AUTHORS)|np.isin(namesi,AUTHORS);counts['author_rows']+=int(author.sum())
            y=array(t,'kind_draw',bool);fair=array(t,'fair_competitive',bool);lost=array(t,'clearly_worse',bool)
            start=array(t,'utc_ms',np.int64);anchor=array(t,'api_last_move_at_ms',np.int64)
            if np.any((start<START)|(start>=END)|(anchor<start)):raise RuntimeError('Invalid start/last-move timing')
            color=np.asarray(t['chooser_color'].to_pylist());white=array(t,'white_id',np.int64);black=array(t,'black_id',np.int64)
            if np.any(~np.isin(color,['white','black'])) or np.any(j!=np.where(color=='white',white,black)) or np.any(i!=np.where(color=='white',black,white)):
                raise RuntimeError('Role/identity conflict')
            cp=array(t,'engine_eval_cp_disconnected',float)
            if not np.isfinite(cp).all() or np.any(fair!=(cp>=-100)) or np.any(lost!=(cp<=-300)):
                raise RuntimeError('Engine merit flags differ from declared definition')
            if not job['broad']:
                for label,mask in [('all',np.ones(n,bool)),('competitive',fair),('clearly_worse',lost)]:
                    use=mask&~author;census.append(dict(month=job['source'].get('month'),region=label,n=int(use.sum()),grants=int(y[use].sum())))
            keep=(mix(pk)%np.uint64(job['denominator'])==0)&~author
            counts['sampled_rows']+=int(keep.sum())
            speed=np.asarray(t['api_speed'].to_pylist());speedcode=np.array([SPEEDS.index(s) if s in SPEEDS else -1 for s in speed],np.int8)
            if np.any(speedcode<0):raise RuntimeError('Unsupported speed in opportunity panel')
            out=dict(gid=t['game_id'],pair_key=pk,j=j,i=i,start=start,anchor=anchor,y=y,cp=cp,
                fair=fair,lost=lost,speed=speedcode,month=np.full(n,job.get('month_code',-1),np.int16),
                rating=array(t,'chooser_elo',float),opp_rating=array(t,'disconnected_elo',float),
                rd=array(t,'chooser_pre_rd_v2',float),opp_rd=array(t,'disconnected_pre_rd_v2',float),
                draw_payoff=array(t,'chooser_draw_payoff_v2',float),cost=array(t,'chooser_win_premium_v2',float),
                recipient_gain=np.where(color=='white',array(t,'black_win_premium_v2',float),array(t,'white_win_premium_v2',float)),
                clock=array(t,'chooser_clock_last_obs_s',float),opp_clock=array(t,'disconnected_clock_last_obs_s',float),
                ply=array(t,'ply_count',float),base=array(t,'tc_base_s',float),inc=array(t,'tc_inc_s',float))
            tab=pa.table(out).filter(pa.array(keep))
            if writer is None:writer=pq.ParquetWriter(folder/'panel.parquet',tab.schema,compression='zstd')
            writer.write_table(tab)
    finally:
        if writer:writer.close()
    if stamp(p)!=job['source']['fingerprint']:raise RuntimeError('Panel changed during projection')
    dump(folder/'census.json',census);finish(folder,counts)
    return dict(**counts,reused=False,folder=str(folder))

def broad_projection(job):
    p=Path(job['source']['path']);folder=Path(job['folder']);present=columns(p)
    yn='kind_draw' if 'kind_draw' in present else 'outcome_kind_draw'
    cols=sorted(BROAD_REQUIRED|{yn});writer=None;counts=dict(source_rows=0,author_rows=0,sampled_rows=0,ineligible_arms=0)
    try:
        for b in pq.ParquetFile(p).iter_batches(columns=cols,batch_size=131072,use_threads=False):
            t=pa.Table.from_batches([b]);counts['source_rows']+=len(t)
            for k in ['chooser_user_id','disconnected_user_id','utc_ms','api_last_move_at_ms','chooser_username_norm','disconnected_username_norm',yn,'timeout_chooser_win']:
                if t[k].null_count:raise RuntimeError('Missing identity/outcome in all-source repayment panel')
            j=array(t,'chooser_user_id',np.int64);i=array(t,'disconnected_user_id',np.int64);pk=pairs(j,i)
            author=np.zeros(len(t),bool)
            for k in ['chooser_username_norm','disconnected_username_norm']:
                author|=np.isin(np.array([str(x).strip().lower() for x in t[k].to_pylist()]),AUTHORS)
            counts['author_rows']+=int(author.sum());y=array(t,yn,bool);arm=y|array(t,'timeout_chooser_win',bool)
            counts['ineligible_arms']+=int((~arm).sum());keep=(mix(pk)%np.uint64(job['denominator'])==0)&~author&arm
            start=array(t,'utc_ms',np.int64);anchor=array(t,'api_last_move_at_ms',np.int64);color=np.array(t['chooser_color'].to_pylist())
            if np.any((start<START)|(start>=END)|(anchor<start)) or np.any(~np.isin(color,['white','black'])):raise RuntimeError('All-source repayment timing/color invalid')
            gain=np.where(color=='white',array(t,'black_win_premium_v2',float),array(t,'white_win_premium_v2',float))
            tab=pa.table(dict(gid=t['game_id'],j=j,i=i,pair_key=pk,start=start,anchor=anchor,y=y,recipient_gain=gain)).filter(pa.array(keep))
            if writer is None:writer=pq.ParquetWriter(folder/'panel.parquet',tab.schema,compression='zstd')
            writer.write_table(tab);counts['sampled_rows']+=len(tab)
    finally:
        if writer:writer.close()
    if stamp(p)!=job['source']['fingerprint']:raise RuntimeError('All-source repayment panel changed')
    finish(folder,counts);return dict(**counts,reused=False,folder=str(folder))
