"""Two explicit history universes; exact old-reference count bridge."""
from common import *
from history_logic import empty_deltas,add_deltas,assert_reference_bridge,num

def build_references(old,months,deltas,work,auth_root,code_sha,expected_total=63525555):
    records=list(old)
    inputs=[]
    for r in old:inputs.append(dict(**r,fingerprint=stamp(r['path'])))
    for r in months:
        if r['month'] not in NEW_MONTHS:continue
        done=load(Path(r['root'])/'_DONE.json')
        entries={x['path']:x for x in done['files']}
        for shard in range(16):
            name=f'shard-{shard:02d}.parquet';e=entries[name]
            path=Path(r['root'])/name
            records.append(dict(month=r['month'],shard=shard,path=str(path),sha256=e['sha256'],bytes=e['bytes'],rows=e['rows']))
            inputs.append(dict(path=str(path),sha256=e['sha256'],fingerprint=stamp(path)))
    if len(records)!=512 or {(r['month'],r['shard']) for r in records}!={(m,s) for m in MONTHS for s in range(16)}:
        raise RuntimeError('The extended history manifest is incomplete')
    if sum(r['rows'] for r in records)!=expected_total:raise RuntimeError('Extended history row total differs')
    inputs.extend(deltas)
    key=digest(dict(code=code_sha,inputs=inputs,history_boundaries=['2023-11-01','2023-09-01']))
    def build(tmp):
        n_old,s_old=empty_deltas();n_all,s_all=empty_deltas()
        bymonth=[]
        with heartbeat('Extending historical cross-fit state references'):
            for month in MONTHS:
                nr=training=0
                for r in sorted((x for x in records if x['month']==month),key=lambda x:x['shard']):
                    for b in pq.ParquetFile(r['path']).iter_batches(batch_size=131072,use_threads=False):
                        t=pa.Table.from_batches([b]);nr+=len(t);training+=int(arr(t,'arm',bool).sum())
                        add_deltas(n_all,s_all,t)
                        if month>='2023-11':add_deltas(n_old,s_old,t)
                bymonth.append(dict(month=month,all_source_rows=nr,training_rows=training,
                    historical_projection_reused=(month in OLD_MONTHS)))
                log(f'Reference counts {month}: {nr:,} rows')
        pn=np.zeros((2,25,4,4,500),np.int64);ps=np.zeros_like(pn)
        for r in deltas:
            with np.load(r['path'],allow_pickle=False) as z:
                if z['n'].shape!=pn.shape or z['s'].shape!=pn.shape:raise RuntimeError('Historical delta shape changed')
                pn+=z['n'];ps+=z['s']
        bridge=assert_reference_bridge(n_old,s_old,pn,ps)
        np.savez_compressed(tmp/'reference_deltas_old_boundary.npz',n=n_old,s=s_old)
        np.savez_compressed(tmp/'reference_deltas_extended_boundary.npz',n=n_all,s=s_all)
        np.save(tmp/'reference_old_boundary.npy',num.expanding_reference(n_old[:,:-1],s_old[:,:-1]),allow_pickle=False)
        np.save(tmp/'reference_extended_boundary.npy',num.expanding_reference(n_all[:,:-1],s_all[:,:-1]),allow_pickle=False)
        write_json(tmp/'HISTORY_INPUT_MANIFEST_PRIVATE.json',dict(months=list(MONTHS),records=records,
            rows=sum(r['rows'] for r in records),original_months_reused=24,new_months_projected=8,
            old_history_boundary='2023-11-01T00:00:00Z',extended_history_boundary='2023-09-01T00:00:00Z',
            roles='j=chooser; i=disconnected player; score history is all-source, not pool-only',
            outcome_scope='An all-source history manifest is not the main-sample outcome frame',
            model_array_shape=[2,32,4,4,500],lags_days=[7,30],cutoff='strictly before target month start minus lag',
            new_scores_estimated=False,final_iv_eligible_n=None))
        write_json(tmp/'REFERENCE_BRIDGE.json',bridge)
        return dict(bridge=bridge,monthly_counts=bymonth,rows=sum(r['rows'] for r in records),
            shards=512,models=['old_boundary','extended_boundary'],new_effect_estimates=False)
    root,r=stage(Path(work)/'references'/key,key,inputs,build,auth_root)
    return root,r
