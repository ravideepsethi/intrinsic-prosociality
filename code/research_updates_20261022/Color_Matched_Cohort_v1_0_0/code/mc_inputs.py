"""Join completed products by authenticated game identity; no new replay."""
from mc_io import *
import re

def catalog(project,work):
    project=Path(project);mech=project/MECH;ref=read(ROOT/'authority/mechanism_reference.json')
    if read(mech/'RUN_IDENTITY.json')['package_sha256']!=ref['mechanism_package_sha256']:
        raise RuntimeError('Mechanism cache is not the reviewed producer')
    pre=[];records=[]
    for r in ref['inputs']:
        p=mech/'analysis'/(r['month']+'.parquet');records.append(auth(p,work,r['sha256'],size=r['size']));pre.append(str(p))
    need=mech/'needed_users.parquet';nr=read(need.with_suffix('.json'));records.append(record_auth(need,nr['output'],work))
    chrono=[]
    for r in pd.read_csv(ROOT/'authority/chronology.tsv',sep='\t').to_dict('records'):
        speed=re.search('speed=([^/]+)',r['path'])[1];month=re.search('month=([^/]+)',r['path'])[1]
        if speed not in SPEEDS or month>'2025-10':continue
        p=relocated(r['path'],project)
        if p.stat().st_size!=r['bytes'] or pq.ParquetFile(p).metadata.num_rows!=r['rows']:
            raise RuntimeError('Historical chronology inventory changed: '+speed+'/'+month)
        chrono.append(dict(path=str(p),speed=speed,month=month,rows=int(r['rows']),size=int(r['bytes']),old_summary=str(mech/'history_summary'/f'{speed}_{month}.parquet')))
    extra=read(ROOT/'vendor/Receipt_IV_Cohort_Extension_v1_0_0/authority/chronology_metadata.json')
    for r in extra:
        if r['speed'] not in SPEEDS or r['month'] not in POST_MONTHS:continue
        folder=relocated(r['path'],project);ps=sorted(folder.glob('*.parquet'))
        if len(ps)!=1:raise RuntimeError('Expected the authenticated single-part speed/month chronology')
        if len(ps)!=r['parts'] or sum(pq.ParquetFile(p).metadata.num_rows for p in ps)!=r['rows']:
            raise RuntimeError('Post chronology inventory changed')
        for p in ps:chrono.append(dict(path=str(p),speed=r['speed'],month=r['month'],rows=pq.ParquetFile(p).metadata.num_rows,size=p.stat().st_size,old_summary=None))
    for s in SPEEDS:
        found={r['month'] for r in chrono if r['speed']==s}
        if not {str(m) for m in pd.period_range('2023-10','2026-01',freq='M')}<=found:raise RuntimeError('Missing activity chronology month for '+s)
    # Cardinality and schema establish the same-speed source contract. Hashes
    # are bound/checkpointed at consumption, not a duplicate startup pass.
    for r in chrono:
        if not {'game_id','utc_ms','white_id','black_id','archive_ordinal'}<=cols(r['path']):raise RuntimeError('Chronology schema changed')
    return dict(pre=pre,old_needed=str(need),chronology=chrono,snapshots=records)

def prepare_post(job):
    project,work,month,bridge,memory=job;project=Path(project);work=Path(work)
    first=project/FIRST;d=first/'dose'/f'month={month}'/'opportunities.parquet'
    dr=read(d.with_suffix('.json'));snaps=[record_auth(d,dr['output'],work)]
    h=Path(bridge['opportunities'][month]);hr=next(r for r in bridge['opportunity_receipts'] if r['path']==str(h))
    snaps.append(record_auth(h,hr,work))
    mr=Path(bridge['membership_root']);md=read(mr/'_DONE.json')
    rel=f'membership/month={month}/membership_PRIVATE.parquet';m=mr/rel
    er=next(r for r in md['files'] if r['path']==rel);snaps.append(record_auth(m,er,work))
    replay=[]
    for speed in SPEEDS:
        rp=first/'replay'/f'speed={speed}'/f'month={month}';receipt=read(rp/'_SUCCESS.json')
        p=rp/'targets.parquet';snaps.append(record_auth(p,receipt['outputs']['targets'],work));replay.append(p)
    key=digest(dict(version=VERSION,inputs=snaps,month=month,selection='board_stage_gap_no_RD_y_or_membership_selection'))
    out=work/'post_narrow'/(month+'.parquet')
    if cache(out,key,work):return str(out)
    c=connect(work/'tmp'/('post_'+month),2,memory)
    try:
        c.execute('CREATE VIEW d AS SELECT * FROM '+scan(d));c.execute('CREATE VIEW h AS SELECT * FROM '+scan(h))
        c.execute('CREATE VIEW m AS SELECT * FROM '+scan(m));c.execute('CREATE VIEW r AS SELECT * FROM '+scan(replay))
        # Validate the complete monthly key space before narrowing it.
        n,nu,bad=c.execute('''SELECT count(*),count(DISTINCT d.game_id),count(*) FILTER(WHERE
            h.game_id IS NULL OR m.game_id IS NULL OR r.game_id IS NULL OR
            d.chooser_user_id IS DISTINCT FROM h.chooser_user_id OR
            d.utc_ms IS NULL OR h.utc_ms IS NULL OR abs(d.utc_ms-h.utc_ms)>1000 OR d.utc_ms IS DISTINCT FROM r.utc_ms OR
            d.color IS DISTINCT FROM h.color OR d.grant IS DISTINCT FROM h.grant OR
            d.rating IS DISTINCT FROM h.rating OR d.opp_rating IS DISTINCT FROM h.opp_rating OR d.cp IS DISTINCT FROM h.cp OR
            d.ply IS DISTINCT FROM h.ply OR lower(d.speed) IS DISTINCT FROM lower(h.speed) OR
            d.chooser_user_id<>CASE WHEN d.color='white' THEN r.white_id ELSE r.black_id END OR
            h.disconnected_user_id<>CASE WHEN d.color='white' THEN r.black_id ELSE r.white_id END)
            FROM d LEFT JOIN h USING(game_id) LEFT JOIN m USING(game_id) LEFT JOIN r USING(game_id)''').fetchone()
        if n!=nu or bad or n!=pq.ParquetFile(d).metadata.num_rows:raise RuntimeError(month+': state/history/membership identity join failed')
        if c.execute("SELECT count(*) FROM m WHERE source_status='recovered' AND source='pool' AND ((previous_classification_status='not_mutually_adjacent_observed') IS DISTINCT FROM coalesce(pool_nonadjacent_eligible,FALSE))").fetchone()[0]:
            raise RuntimeError('Shared membership predicate disagrees with color predicate')
        # The parent opportunity producer already imposed timeout/material/5s
        # eligibility. Preserve missing clock values for the same model controls.
        q0=f'''SELECT d.game_id,d.chooser_user_id::BIGINT chooser,h.disconnected_user_id::BIGINT opponent,
            d.utc_ms::BIGINT t,lower(d.speed) speed,d.color,d.grant::TINYINT y,d.cp::DOUBLE cp,d.ply::INTEGER ply,
            d.rating::DOUBLE rating,d.opp_rating::DOUBLE opp_rating,d.g::DOUBLE g,d.rd::DOUBLE rd,d.opp_rd::DOUBLE opp_rd,
            d.draw_old::DOUBLE rg,d.win_old::DOUBLE rc,(d.K_old/2)::DOUBLE ki,
            d.chooser_clock::DOUBLE clock,d.opp_clock::DOUBLE opp_clock,{q(month)}::VARCHAR AS month,
            CASE WHEN d.cp>=-100 THEN 'equal' ELSE 'losing' END state,
            m.source,m.source_status,m.previous_classification_status,m.pool_nonadjacent_eligible::BOOLEAN pool_main,
            CASE WHEN d.color='white' THEN r.result_code/2.0 ELSE 1-r.result_code/2.0 END actual_score,
            CASE WHEN d.color='white' THEN r.white_rating_diff ELSE r.black_rating_diff END::DOUBLE observed,
            CASE WHEN d.color='white' THEN r.white_pred ELSE r.black_pred END::DOUBLE stored_pred,
            d.valid_state::BOOLEAN valid_state
            FROM d JOIN h USING(game_id) JOIN m USING(game_id) JOIN r USING(game_id)
            WHERE d.ply>10 AND ((d.cp>=-100 AND d.cp<100) OR d.cp<=-300) AND d.g>=-575 AND d.g<575
            AND d.chooser_user_id<>h.disconnected_user_id'''
        intermediate=out.with_name(month+'_sql.parquet');copy(c,q0,intermediate)
    finally:c.close()
    tmp=out.with_name(out.name+'.partial_'+uuid.uuid4().hex);writer=None;err=0.;numeric_bad=0
    try:
        for b in pq.ParquetFile(intermediate).iter_batches(batch_size=100000,use_threads=False):
            x=b.to_pandas();color=np.where(x.color.eq('white'),1.,-1.)
            if not x.valid_state.all() or not np.isfinite(x[['rd','opp_rd','rg','rc','ki','rating','opp_rating']]).all().all():raise RuntimeError('Post state missing')
            e,k,rg,rc=payoff(x.rating,x.opp_rating,x.rd,x.opp_rd,color,0.)
            _,ko,_,_=payoff(x.opp_rating,x.rating,x.opp_rd,x.rd,-color,0.)
            x['kj']=ko/2;err=max(err,float(np.max(np.abs(x.rg.to_numpy()-rg),initial=0)),float(np.max(np.abs(x.rc.to_numpy()-rc),initial=0)))
            x['pred_old']=k*(x.actual_score-e)
            en,kn,_,_=payoff(x.rating,x.opp_rating,x.rd,x.opp_rd,color,ADVANTAGE)
            x['pred_new']=kn*(x.actual_score-en)
            predicted=np.where(x.t>=IMPLEMENTED,x.pred_new,x.pred_old)
            if not np.isfinite(x.stored_pred).all() or np.max(abs(predicted-x.stored_pred.to_numpy()),initial=0)>1e-7:raise RuntimeError('Actual-stratum anchored replay parity failed')
            t=pa.Table.from_pandas(x,preserve_index=False)
            if writer is None:writer=pq.ParquetWriter(tmp,t.schema,compression='zstd')
            writer.write_table(t)
        if writer is None:raise RuntimeError('No post opportunity rows')
        writer.close();writer=None
        if err>1e-6:raise RuntimeError('Stored old payoff mismatch')
        unchanged(snaps);os.replace(tmp,out);intermediate.unlink()
        commit(out,key,month=month,source_rows=n,maximum_payoff_error=err,actual_replay_parity=True,input_snapshots=snaps)
    finally:
        if writer is not None:writer.close()
    log(month+': matched source/state join completed');return str(out)
