"""Strictly pre-start history features. Legacy start-only chronology is insufficient."""
import hashlib, json, math
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.special import expit
from common import *
from fe_core import iter_blocks

GAME_COLUMNS={'game_id','speed','start_ms','end_ms','white_id','black_id','white_rating','black_rating',
              'white_rd','black_rd','white_rating_diff','black_rating_diff','white_score','status'}
ORDINARY=['mate','resign','draw','stalemate']
FEATURES=['prior_count','inactivity_days','history_days','first_observed_completion_ms','left_truncation_possible','peak','peak365','dperf','dperf15','dperf60',
          'dperf200','dperf800','missing_post_updates','lookback_tie']

def inspect_history(project, explicit, report):
    p=Path(explicit) if explicit else Path(project)/'derived/replication/rating_motives_history_inputs_v100.json'
    inventory=[]
    legacy=Path(project)/'derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time'
    if legacy.exists():
        first=next(legacy.glob('speed=*/month=*/*.parquet'),None)
        if first:
            cols=pq.ParquetFile(first).schema_arrow.names
            inventory.append(dict(source='legacy_replay_chronology',example=str(first),columns=cols,
                                  usable=False,reason='No authenticated completion timestamp, historical RD or completion status'))
    if not p.is_file():
        status=dict(status='HISTORY_INPUTS_NOT_AVAILABLE',requested_manifest=str(p),inventory=inventory,
                    primary_tests_waiting=['T1 (recipient completed-game count)','T2 (recipient completed-game count)',
                                           'T3 (performance/history)','T4 (peak/history)'],
                    action='Provide an enriched history producer receipt and canonical manifest; do not relabel start or last-move timestamps as completion.')
        save_json(Path(report)/'history_readiness.json',status);return None
    m=json.loads(p.read_text())
    required=dict(format='RATING_MOTIVES_HISTORY_V1',source_scope='all_standard_rated_all_sources',
                  account_id_namespace='certified_panel_user_id',timestamp_unit='unix_milliseconds',
                  end_time_semantics='game_completion',score_semantics='white_score_0_half_1',
                  coverage='all_accounts_in_source_interval',status_semantics='canonical_lichess_status')
    for k,v in required.items():
        if m.get(k)!=v: raise RuntimeError('History contract mismatch: '+k)
    if m.get('ordinary_statuses')!=ORDINARY: raise RuntimeError('History ordinary status mapping differs from frozen rule')
    if not isinstance(m.get('coverage_start_ms'),int) or not isinstance(m.get('coverage_end_ms'),int):
        raise RuntimeError('History coverage timestamps required')
    if m['coverage_start_ms']>=m['coverage_end_ms']: raise RuntimeError('Invalid history interval')
    def resolve(item):
        q=Path(item['path']);q=q if q.is_absolute() else p.parent/q
        if sha256_file(q)!=item['sha256']: raise RuntimeError('History/producer checksum mismatch: '+str(q))
        return str(q)
    m['producer_receipt']['resolved_path']=resolve(m['producer_receipt'])
    files=m.get('files',[])
    if not files: raise RuntimeError('History manifest has no files')
    for i,f in enumerate(files):
        log(f'Authenticating history file {i+1}/{len(files)}')
        f['resolved_path']=resolve(f);pf=pq.ParquetFile(f['resolved_path'])
        if not GAME_COLUMNS<=set(pf.schema_arrow.names): raise RuntimeError('Enriched history lacks required columns')
        if pf.metadata.num_rows!=f['rows']: raise RuntimeError('History row count mismatch')
    if len({f['resolved_path'] for f in files})!=len(files): raise RuntimeError('Duplicate history file in manifest')
    m['manifest_sha256']=sha256_file(p);m['manifest_path']=str(p)
    save_json(Path(report)/'history_readiness.json',dict(status='HISTORY_INPUTS_AUTHENTICATED',
       manifest_sha256=m['manifest_sha256'],files=len(files),rows=sum(f['rows'] for f in files),
       coverage_start_ms=m['coverage_start_ms'],coverage_end_ms=m['coverage_end_ms'],
       warning='Authenticated producer declarations establish source semantics; observed counts/peaks remain left truncated.',inventory=inventory))
    return m

def performance(current, opp_rating, opp_rd, score, valid, tau=400.):
    """Vectorized strictly concave, regularized fractional-logistic score solve."""
    current=np.asarray(current,float)
    a=1/173.7178/np.sqrt(1+3*(np.nan_to_num(opp_rd,nan=0)/173.7178)**2/np.pi**2)
    rr=np.nan_to_num(opp_rating,nan=0); ss=np.nan_to_num(score,nan=0)
    a=np.where(valid,a,0.)
    # |sum a(s-p)| <= sum a gives a rigorous bracket around the prior mean.
    width=tau*tau*np.sum(a,axis=1)+1
    lo=current-width;hi=current+width
    for _ in range(64):
        mid=(lo+hi)/2
        grad=np.sum(a*(ss-expit(a*(mid[:,None]-rr))),axis=1)-(mid-current)/tau**2
        lo=np.where(grad>0,mid,lo);hi=np.where(grad<=0,mid,hi)
        if np.max(hi-lo,initial=0)<=1e-6: break
    if np.any(hi-lo>1e-6): raise RuntimeError('Performance solve did not reach 1e-6 point tolerance')
    return current-(lo+hi)/2

def features_for_user(h, anchors,extended=True):
    """h sorted by completion; anchors can be in any order. Never uses anchor outcomes."""
    n=len(anchors['start_ms']);out={k:np.full(n,np.nan) for k in FEATURES}
    ends=np.asarray(h['end_ms']);starts=np.asarray(anchors['start_ms'])
    count=np.searchsorted(ends,starts,side='left');out['prior_count']=count.astype(float)
    if not len(ends): return out
    seen=count>0
    out['inactivity_days'][seen]=(starts[seen]-ends[count[seen]-1])/DAY
    out['history_days'][seen]=(starts[seen]-ends[0])/DAY
    out['first_observed_completion_ms'][seen]=ends[0]
    stable=np.isfinite(h['rd'])&(h['rd']>0)&(h['rd']<=110)&np.isfinite(h['rating'])
    val=np.where(stable,np.fmax(h['rating'],h['rating']+h['rating_diff']),-np.inf)
    # np.fmax retains the observed pre-game rating when the observed update is missing.
    pref=np.maximum.accumulate(val);out['peak'][seen]=pref[count[seen]-1]
    out['peak'][~np.isfinite(out['peak'])]=np.nan
    missing=np.cumsum(~np.isfinite(h['rating_diff']));out['missing_post_updates'][seen]=missing[count[seen]-1]
    left=np.searchsorted(ends,starts-365*DAY,side='left')
    for i in (np.flatnonzero(seen) if extended else []):
        z=val[left[i]:count[i]]
        if len(z) and np.isfinite(z).any():out['peak365'][i]=np.max(z)
    for a in range(0,n,256):
        ix=np.arange(a,min(a+256,n));counts=count[ix]
        for look,minimum,key in ([(30,15,'dperf'),(15,15,'dperf15'),(60,30,'dperf60')] if extended else [(30,15,'dperf')]):
            indices=counts[:,None]-np.arange(look,0,-1)[None,:]
            indices=np.clip(indices,0,len(ends)-1)
            order_ok=np.all(np.diff(ends[indices],axis=1)>0,axis=1)
            # Exclude a tied completion straddling the start of a lookback too.
            boundary=counts-look
            tied_boundary=(boundary>0)&(ends[np.clip(boundary,0,len(ends)-1)]==ends[np.clip(boundary-1,0,len(ends)-1)])
            good=(counts>=look)&np.all(stable[indices],axis=1)&order_ok&~tied_boundary
            ordinary=h['ordinary'][indices].astype(bool)
            known=(np.isfinite(h['opp_rating'][indices])&np.isfinite(h['opp_rd'][indices])&(h['opp_rd'][indices]>0)
                   &np.isin(h['score'][indices],[0,.5,1]))
            # Unknown data on an otherwise ordinary game invalidates the lookback, not silently drops it.
            good &= np.all(~ordinary|known,axis=1)&(np.sum(ordinary,axis=1)>=minimum)
            if look==30:out['lookback_tie'][ix]=((counts>=look)&(~order_ok|tied_boundary)).astype(float)
            if not good.any():continue
            gix=ix[good]; jj=indices[good]
            args=(anchors['rating'][gix],h['opp_rating'][jj],h['opp_rd'][jj],h['score'][jj],ordinary[good])
            out[key][gix]=performance(*args)
            if look==30 and extended:
                out['dperf200'][gix]=performance(*args,tau=200.)
                out['dperf800'][gix]=performance(*args,tau=800.)
    return out

def selected_validation(username):
    return int(hashlib.sha256(('rating-motives-v1.1-validation|'+username.strip().lower()).encode()).hexdigest()[:16],16)%10==0

def validation_rows(user,speed,username,h,coverage_end):
    if not selected_validation(username):return []
    candidate=np.flatnonzero(h['ordinary'].astype(bool)&np.isfinite(h['rating'])&np.isfinite(h['rd'])&(h['rd']>0)
        &np.isfinite(h['opp_rating'])&np.isfinite(h['opp_rd'])&(h['opp_rd']>0)&np.isin(h['score'],[0,.5,1]))
    if not len(candidate):return []
    candidate=candidate[np.argsort(h['start_ms'][candidate],kind='stable')]
    # Unresolved simultaneous starts cannot establish which was first.
    st=h['start_ms'][candidate];unique=np.r_[True,np.diff(st)!=0]&np.r_[np.diff(st)!=0,True]
    candidate=candidate[unique]
    months=np.asarray(h['start_ms'][candidate],dtype='datetime64[ms]').astype('datetime64[M]').astype(str)
    rows=[]
    for month in np.unique(months[(months>='2023-11')&(months<='2025-10')]):
        possible=candidate[months==month];chosen=None
        # Stop at the first eligible start in each month; never evaluate future scores to choose it.
        for offset in range(0,len(possible),16):
            cc=possible[offset:offset+16];aa={k:h[k][cc] for k in ['start_ms','rating']}
            ff=features_for_user(h,aa,extended=False)
            good=np.flatnonzero(np.isfinite(ff['dperf'])&np.isfinite(ff['peak']))
            if len(good):chosen=(int(cc[good[0]]),float(ff['dperf'][good[0]]));break
        if chosen is None:continue
        i,gap=chosen
        j=int(np.searchsorted(h['start_ms'][candidate],h['end_ms'][i],side='right'))
        nxt=candidate[j:j+1];nxt=nxt[h['start_ms'][nxt]<=h['end_ms'][i]+30*DAY]
        row=dict(chooser=int(user),speed=int(speed),month=str(month),dperf=gap,residual=np.nan,
                 followup_30d_covered=bool(h['end_ms'][i]+30*DAY<=coverage_end))
        if len(nxt):
            k=int(nxt[0]);ro=h['opp_rating'][k];rdo=h['opp_rd'][k]
            if np.isfinite(ro) and np.isfinite(rdo) and rdo>0 and np.isin(h['score'][k],[0,.5,1]):
                expected=expit((h['rating'][k]-ro)/173.7178/np.sqrt(1+3*(rdo/173.7178)**2/np.pi**2))
                row['residual']=h['score'][k]-expected
        rows.append(row)
    return rows

def make_features(con, base, manifest, work, report, identity,buckets=16):
    work,report=Path(work),Path(report);out=work/'history_features.parquet';vr=work/'validation_private.parquet'
    receipt=work/'history_receipt.json'
    if checkpoint_ok(receipt,identity):return out,vr
    src=parquet([f['resolved_path'] for f in manifest['files']]);b=parquet(base)
    con.execute(f'CREATE OR REPLACE TEMP VIEW hg AS SELECT * FROM {src}')
    stats=records(con,"""SELECT count(*) AS rows,count(*)-count(DISTINCT game_id) duplicates,
      count(*) FILTER(WHERE game_id IS NULL OR white_id IS NULL OR black_id IS NULL OR white_id<0 OR black_id<0 OR white_id=black_id OR start_ms IS NULL OR end_ms IS NULL OR start_ms<=0 OR end_ms<start_ms OR speed IS NULL OR speed NOT IN('ultraBullet','bullet','blitz','rapid','classical','correspondence')) invalid_identity_time,
      count(*) FILTER(WHERE white_score IS NOT NULL AND white_score NOT IN(0,.5,1)) bad_score,
      count(*) FILTER(WHERE white_rating_diff IS NOT NULL AND white_rating_diff<>round(white_rating_diff) OR black_rating_diff IS NOT NULL AND black_rating_diff<>round(black_rating_diff)) noninteger_observed_update,
      min(start_ms) min_start,max(end_ms) max_end FROM hg""")[0]
    if stats['duplicates'] or stats['invalid_identity_time'] or stats['bad_score'] or stats['noninteger_observed_update']:
        raise RuntimeError('History validation failed: '+str(stats))
    con.execute(f'CREATE TEMP TABLE needed_users AS SELECT chooser user_id,max(username) username FROM {b} GROUP BY 1')
    con.execute(f'INSERT INTO needed_users SELECT DISTINCT recipient,NULL FROM {b} WHERE recipient NOT IN(SELECT user_id FROM needed_users)')
    con.execute(f'CREATE TEMP TABLE targets AS SELECT game_id,chooser user_id,speed,start_ms,rating,created_ms,1 player_role FROM {b} UNION ALL SELECT game_id,recipient,speed,start_ms,opp_rating,NULL::BIGINT,0 FROM {b}')
    counts=records(con,f"""SELECT count(*) targets,count(*) FILTER(WHERE start_ms<{manifest['coverage_start_ms']} OR start_ms>={manifest['coverage_end_ms']}) outside_history_interval FROM targets""")[0]
    if counts['outside_history_interval']:raise RuntimeError('History coverage does not contain every target game start')
    # Namespace/speed/rating cross-check on overlapping opportunity games; do not use them as prior history.
    speedcode='CASE h.speed '+' '.join(f'WHEN {sqlstr(s)} THEN {i}' for i,s in enumerate(SPEEDS))+' ELSE -1 END'
    align=records(con,f"""SELECT count(*) overlap,count(*) FILTER(WHERE
      (t.user_id NOT IN(h.white_id,h.black_id)) OR t.speed<>({speedcode}) OR
      t.rating<>CASE WHEN t.user_id=h.white_id THEN h.white_rating ELSE h.black_rating END OR abs(t.start_ms-h.start_ms)>1000) mismatch
      FROM targets t JOIN hg h USING(game_id)""")[0]
    if not align['overlap'] or align['mismatch']:raise RuntimeError('History does not reconcile with certified target identities/ratings/times: '+str(align))
    raw=work/'history_long';raw.mkdir(exist_ok=True)
    longreceipt=work/'history_long_receipt.json'
    files=sorted(raw.glob('bucket=*/*.parquet'))
    if not checkpoint_ok(longreceipt,identity):
        import shutil
        for q in raw.glob('bucket=*'):shutil.rmtree(q)
        parts=[]
        for own,opp in [('white','black'),('black','white')]:
            sc='white_score' if own=='white' else '1-white_score'
            parts.append(f"""SELECT h.{own}_id chooser,({speedcode})::SMALLINT speed,h.game_id,h.start_ms,h.end_ms,
              h.{own}_rating::DOUBLE rating,h.{opp}_rating::DOUBLE opp_rating,
              h.{own}_rd::DOUBLE rd,h.{opp}_rd::DOUBLE opp_rd,h.{own}_rating_diff::DOUBLE rating_diff,
              ({sc})::DOUBLE score,(h.status IN ('mate','resign','draw','stalemate')) ordinary,
              n.username,h.{own}_id%{buckets} bucket FROM hg h JOIN needed_users n ON h.{own}_id=n.user_id
              WHERE h.end_ms<{manifest['coverage_end_ms']}""")
        log('Building relevant all-source history shards (may be large)')
        con.execute(f"COPY ({' UNION ALL '.join(parts)}) TO {sqlstr(raw)} (FORMAT PARQUET,COMPRESSION ZSTD,PARTITION_BY(bucket))")
        files=sorted(raw.glob('bucket=*/*.parquet'));finish_checkpoint(longreceipt,identity,files)
    save_json(report/'history_construction_audit.json',dict(input=stats,targets=counts,alignment=align,
         rule='Strict end_ms < start_ms; all source same-speed rated; ambiguous completion order invalidates performance lookbacks; peaks are order invariant',
         coverage_start_ms=manifest['coverage_start_ms'],coverage_end_ms=manifest['coverage_end_ms'],
         counts_are_observed=True,left_truncation='Possible for every account whose creation predates source coverage; no claim of lifetime peak/count completeness'))
    featureparts=[];validationparts=[]
    for bucket in range(buckets):
        fp=work/'features'/f'{bucket:03d}.parquet';vp=work/'validation'/f'{bucket:03d}.parquet';rr=fp.with_suffix('.json')
        featureparts.append(fp);validationparts.append(vp)
        if checkpoint_ok(rr,identity):continue
        log(f'Constructing past-only features: account shard {bucket+1}/{buckets}')
        hfiles=sorted((raw/f'bucket={bucket}').glob('*.parquet'))
        # Union targets and history into complete-user blocks; end order is only needed inside each speed.
        hp=work/f'history_sorted_{bucket:03d}.parquet'
        hq=f'SELECT *,false is_target,0::INTEGER player_role FROM {parquet(hfiles)}' if hfiles else None
        tq=f"""SELECT user_id chooser,speed,game_id,start_ms,NULL::BIGINT end_ms,rating,
           NULL::DOUBLE opp_rating,NULL::DOUBLE rd,NULL::DOUBLE opp_rd,NULL::DOUBLE rating_diff,
           NULL::DOUBLE score,false ordinary,NULL::VARCHAR username,user_id%{buckets} bucket,
           true is_target,created_ms,player_role FROM targets WHERE user_id%{buckets}={bucket}"""
        q=tq if hq is None else hq+' UNION ALL BY NAME '+tq
        copy_parquet(con,f'SELECT * FROM ({q}) ORDER BY chooser,speed,end_ms NULLS LAST,start_ms',hp)
        fw=vw=None; fbuffer=[];vbuffer=[]
        fs=pa.schema([('game_id',pa.string()),('player_role',pa.int32())]+[(k,pa.float64()) for k in FEATURES])
        vs=pa.schema([('chooser',pa.int64()),('speed',pa.int32()),('month',pa.string()),('dperf',pa.float64()),('residual',pa.float64()),('followup_30d_covered',pa.bool_())])
        fp.parent.mkdir(exist_ok=True);vp.parent.mkdir(exist_ok=True)
        ft=fp.with_suffix('.partial.parquet');vt=vp.with_suffix('.partial.parquet')
        with pq.ParquetWriter(ft,fs,compression='zstd') as fw,pq.ParquetWriter(vt,vs,compression='zstd') as vw:
            for block in iter_blocks(hp):
                uid=block['chooser'];split=np.r_[0,np.flatnonzero(uid[1:]!=uid[:-1])+1,len(uid)]
                for lo,hi in zip(split[:-1],split[1:]):
                    us={k:v[lo:hi] for k,v in block.items()}
                    for speed in np.unique(us['speed']):
                        same=us['speed']==speed;hh=same&~us['is_target'];tt=same&us['is_target']
                        h={k:v[hh] for k,v in us.items()};a={k:v[tt] for k,v in us.items()}
                        f=features_for_user(h,a)
                        f['left_truncation_possible']=np.where(np.isfinite(a['created_ms']),a['created_ms']<manifest['coverage_start_ms'],np.nan)
                        fbuffer.extend(dict(game_id=str(g),player_role=int(role),**{k:float(f[k][j]) for k in FEATURES}) for j,(g,role) in enumerate(zip(a['game_id'],a['player_role'])))
                        names=[x for x in h['username'] if x]
                        if names:vbuffer.extend(validation_rows(uid[lo],speed,names[0],h,manifest['coverage_end_ms']))
                if fbuffer:fw.write_table(pa.Table.from_pylist(fbuffer,schema=fs));fbuffer=[]
                if vbuffer:vw.write_table(pa.Table.from_pylist(vbuffer,schema=vs));vbuffer=[]
        ft.replace(fp);vt.replace(vp);finish_checkpoint(rr,identity,[fp,vp]);hp.unlink(missing_ok=True)
    copy_parquet(con,f'SELECT * FROM {parquet(featureparts)}',out)
    copy_parquet(con,f'SELECT * FROM {parquet(validationparts)}',vr)
    write_csv(report/'history_feature_coverage.csv',records(con,f"SELECT player_role,count(*) opportunities,count(dperf) FILTER(WHERE isfinite(dperf)) valid_performance,count(peak) FILTER(WHERE isfinite(peak)) valid_peak,sum(lookback_tie) lookback_ties,count(*) FILTER(WHERE left_truncation_possible=1) possible_left_truncation,count(*) FILTER(WHERE NOT coalesce(isfinite(left_truncation_possible),false)) truncation_unknown,min(first_observed_completion_ms) earliest_observed_completion_ms FROM {parquet(out)} GROUP BY player_role"))
    finish_checkpoint(receipt,identity,[out,vr]);return out,vr

def join_features(con,base,featurepath,work,identity):
    out=[]
    for i,b in enumerate(base):
        p=Path(work)/'analysis'/f'bucket_{i:03d}.parquet';out.append(p);r=p.with_suffix('.json')
        if checkpoint_ok(r,identity):continue
        if featurepath:
            hs=parquet(featurepath)
            cols=','.join('c.'+k for k in FEATURES)
            query=f"SELECT b.*,{cols},j.prior_count opp_prior_count FROM {parquet(b)} b LEFT JOIN {hs} c ON b.game_id=c.game_id AND c.player_role=1 LEFT JOIN {hs} j ON b.game_id=j.game_id AND j.player_role=0 ORDER BY chooser,start_ms,game_id"
        else:
            cols=','.join('NULL::DOUBLE '+k for k in FEATURES+['opp_prior_count'])
            query=f'SELECT *,{cols} FROM {parquet(b)} ORDER BY chooser,start_ms,game_id'
        copy_parquet(con,query,p)
        if pq.ParquetFile(p).metadata.num_rows!=pq.ParquetFile(b).metadata.num_rows:raise RuntimeError('History join multiplied/dropped opportunities')
        finish_checkpoint(r,identity,[p])
    return out
