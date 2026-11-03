"""Reuse activity only at identical factual exposures; scan unmatched windows."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,time
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from result_common import require,key,save,load,checkpoint,log,heartbeat,DAY

class Targets:
    def __init__(self,ids,anchors):
        self.ids=np.asarray(ids,np.int64);self.anchors=np.asarray(anchors,np.int64)
        require(len(self.ids)>0 and len(np.unique(self.ids))==len(self.ids),'Activity targets must be unique accounts')
        require((self.ids>=0).all() and (self.anchors>0).all(),'Invalid activity targets')
        self.order=np.argsort(self.ids);self.sorted=self.ids[self.order];self.dense=None
        if int(self.ids.max())<64_000_000:
            self.dense=np.full(int(self.ids.max())+1,-1,dtype=np.int32)
            self.dense[self.ids]=np.arange(len(self.ids),dtype=np.int32)
        self.low=int(self.anchors.min());self.high=int(self.anchors.max())+30*DAY
    def lookup(self,ids):
        ids=np.asarray(ids,np.int64);out=np.full(len(ids),-1,np.int64)
        if self.dense is not None:
            ok=(ids>=0)&(ids<len(self.dense));out[ok]=self.dense[ids[ok]]
        else:
            ix=np.searchsorted(self.sorted,ids);ok=ix<len(self.sorted)
            ok[ok]&=self.sorted[ix[ok]]==ids[ok];out[ok]=self.order[ix[ok]]
        return out

def scan_windows(path,targets,output,history,batch_size=262144):
    f=pq.ParquetFile(path);field=f.schema_arrow.get_field_index('utc_ms')
    require(field>=0,'Chronology timestamp column missing')
    selected=[];skipped=0
    for g in range(f.metadata.num_row_groups):
        rg=f.metadata.row_group(g);s=rg.column(field).statistics
        if s and s.has_min_max and (s.max<=targets.low or s.min>targets.high):skipped+=rg.num_rows
        else:selected.append(g)
    counts=np.zeros(len(targets.ids),np.int64);first=np.full(len(counts),np.iinfo(np.int64).max,np.int64)
    scanned=invalid=0
    for b in f.iter_batches(batch_size=batch_size,columns=['utc_ms','white_id','black_id'],row_groups=selected,use_threads=False):
        t,a,bid=[history.integers(c) for c in b.columns];scanned+=len(t)
        valid=(t>targets.low)&(t<=targets.high)&(a>=0)&(bid>=0)&(a!=bid)
        invalid+=int(((t<=0)|(a<0)|(bid<0)|(a==bid)).sum())
        t=t[valid];a=a[valid];bid=bid[valid]
        for role in (a,bid):
            pos=targets.lookup(role);hit=pos>=0
            pp=pos[hit];tt=t[hit];use=(tt>targets.anchors[pp])&(tt<=targets.anchors[pp]+30*DAY)
            pp=pp[use];tt=tt[use]
            counts+=np.bincount(pp,minlength=len(counts))
            np.minimum.at(first,pp,tt)
    require(scanned+skipped==f.metadata.num_rows,'Activity scan row accounting differs')
    np.savez_compressed(output,counts=counts,first=first)
    return dict(rows=f.metadata.num_rows,scanned_rows=scanned,skipped_rows=skipped,invalid_rows_excluded=invalid,
                target_game_links=int(counts.sum()),active_target_accounts=int((counts>0).sum()))

def activity_join_sql(recipient,old,parquet):
    return '''SELECT e.cohort_row_id,e.recipient_user_id,e.exposure_anchor_utc_ms,
        o.games_within_30d,o.first_next_game_utc_ms
        FROM '''+parquet([recipient])+''' e INNER JOIN selected_ids s USING(cohort_row_id)
        LEFT JOIN '''+parquet([old])+''' o ON e.recipient_user_id=o.recipient_user_id
          AND e.exposure_game_id=o.exposure_game_id
          AND e.exposure_anchor_utc_ms=o.exposure_anchor_utc_ms
        ORDER BY e.cohort_row_id'''

def build_activity(folder,state,recipient,d,support,project,workers,memory,fingerprint,history,util):
    old=history.authenticate_old(project)
    # The frozen chronology extends to April 2026, beyond every 30-day window.
    catalog=history.chronology_catalog(project,workers)
    import csv
    with (history.ROOT/'authority/chronology.tsv').open() as f:manifest=list(csv.DictReader(f,delimiter='\t'))
    end=max(int(r['utc_ms_max']) for r in manifest)
    indices=np.flatnonzero(support['eligible'])
    c=util.db(folder/'spill',memory,workers)
    try:
        c.register('selected_ids',pa.table({'cohort_row_id':d['cohort_row_id'][indices]}))
        query=activity_join_sql(recipient,old['path'],util.parquet)
        joined=c.execute(query).fetch_arrow_table()
    finally:c.close()
    require(len(joined)==len(indices),'Activity join changed the supported cohort')
    def arr(n):return joined[n].to_numpy(zero_copy_only=False)
    ids=arr('cohort_row_id').astype(np.int64);recipients=arr('recipient_user_id').astype(np.int64)
    anchors=arr('exposure_anchor_utc_ms').astype(np.int64)
    require(np.array_equal(ids,d['cohort_row_id'][indices]),'Activity join reordered or duplicated exposures')
    require(len(np.unique(recipients))==len(ids),'Engagement design is not one exposure per account')
    require((anchors+30*DAY<=end).all(),'Incomplete 30-day chronology; no absent window is coded zero')
    raw_counts=arr('games_within_30d').astype(float);raw_first=arr('first_next_game_utc_ms').astype(float)
    known=np.isfinite(raw_counts)
    require(((raw_counts[known]>=0)&(raw_counts[known]==np.floor(raw_counts[known]))).all(),'Invalid cached activity counts')
    has_first=np.isfinite(raw_first)&(raw_first>anchors)&(raw_first<=anchors+30*DAY)
    require(np.array_equal(raw_counts[known]>0,has_first[known]),'Cached counts and first-event timestamp disagree')
    counts=np.where(known,raw_counts,0).astype(np.int64)
    first=np.full(len(ids),np.iinfo(np.int64).max,np.int64)
    first[known&has_first]=raw_first[known&has_first].astype(np.int64)
    unknown=np.flatnonzero(~known);summaries=[]
    log(f'Engagement cohort: {len(ids):,}; exact-exposure activity reused for {int(known.sum()):,}; new windows {len(unknown):,}')
    if len(unknown):
        targets=Targets(recipients[unknown],anchors[unknown])
        selection=[r for r,m in zip(catalog,manifest) if int(m['utc_ms_max'])>targets.low and int(m['utc_ms_min'])<=targets.high]
        target_hash=hashlib.sha256(np.column_stack([targets.ids,targets.anchors]).astype('<i8').tobytes()).hexdigest()
        total=sum(r['rows'] for r in selection);done=0;start=time.monotonic()
        def work(r):
            fp=key(dict(job=fingerprint,targets=target_hash,source=r))
            def build(out):
                require(history.signature(r['path'])==r['signature'],'Chronology changed before activity scan')
                result=scan_windows(r['path'],targets,out/'activity_PRIVATE.npz',history)
                require(history.signature(r['path'])==r['signature'] and history.raw_footer_hash(r['path'])==r['raw_footer_sha256'],'Chronology changed during scan')
                return dict(result,file_index=r['file_index'])
            return checkpoint(state/'activity_files',f"file_{r['file_index']:04d}",fp,build)
        with heartbeat('Counting unmatched 30-day activity windows'),ThreadPoolExecutor(max_workers=workers) as pool:
            futures=[pool.submit(work,r) for r in selection]
            for fut in as_completed(futures):
                loc,summary=fut.result();summaries.append(summary)
                with np.load(loc/'activity_PRIVATE.npz') as f:
                    counts[unknown]+=f['counts'];first[unknown]=np.minimum(first[unknown],f['first'])
                done+=summary['rows'];elapsed=time.monotonic()-start
                if len(summaries)%10==0 or len(summaries)==len(selection):
                    log(f'Activity files {len(summaries)}/{len(selection)}; estimated remaining {elapsed*(total-done)/max(done,1)/60:.1f} min')
    require(np.array_equal(counts>0,first<np.iinfo(np.int64).max),'Completed activity counts and first events disagree')
    history.guard_old(old);history.guard_catalog(catalog)
    pq.write_table(pa.table(dict(cohort_row_id=ids,games_within_30d=counts,
          first_next_game_utc_ms=first,exposure_anchor_utc_ms=anchors)),folder/'activity_PRIVATE.parquet',compression='zstd')
    result=dict(rows=len(ids),reused_exact_exposures=int(known.sum()),scanned_exposures=len(unknown),
        positive_30d=int((counts>0).sum()),chronology_end_ms=end,complete_followup=True,
        old_activity_source=old,chronology_files_scanned=len(summaries),file_summaries=summaries,
        definition='Every rated-standard game start strictly after exposure last move and at most 30 days later; all speeds; true chronology retained.')
    save(folder/'SUMMARY.json',result)
    # Spill is never part of a checkpoint or return artifact.
    __import__('shutil').rmtree(folder/'spill',ignore_errors=True)
    return result
