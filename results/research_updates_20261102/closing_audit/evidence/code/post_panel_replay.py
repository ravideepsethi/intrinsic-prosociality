"""Resume November-January from authenticated October checkpoints.
Expected runtime: 1-6 h initially; completed months are reused on rerun.
"""
from __future__ import annotations
from concurrent.futures import ProcessPoolExecutor,as_completed
from types import SimpleNamespace
import traceback
from common import *
from engine import configure
from checkpoints import authenticate_checkpoint

def diagnostics(month,speed,df,pre):
    parts=[]
    for k,color in enumerate(("white","black")):
        obs=df[f"{color}_rating_diff"].to_numpy(float)
        pred=pre[:,8+k]; ok=np.isfinite(obs)
        if not ok.any(): continue
        r=df[f"{color}_elo"].to_numpy(float)
        opp=df[f"{'black' if k==0 else 'white'}_elo"].to_numpy(float)
        score=df.result_code.to_numpy()/2 if k==0 else 1-df.result_code.to_numpy()/2
        err=pred-obs; ab=np.abs(err)
        old=payoffs(r,opp,pre[:,k],pre[:,1-k],1 if k==0 else -1,0.)
        old_pred=old[1]*(score-old[0])
        frame=pd.DataFrame({"month":month,"speed":speed,"color":color,
          "phase":phase(df.utc_ms.to_numpy()),"outcome":score,
          "rd_bin":rd_bins(pre[:,k]),"gap_bin":gap_bins(opp-r),
          "n":np.ones(len(df),np.int64),"sum_error":err,"sum_abs_error":ab,
          "sum_squared_error":err*err,"abs_gt_1":(ab>1).astype(int),"abs_gt_2":(ab>2).astype(int),
          "sum_old_abs_error":np.abs(old_pred-obs),
          "nearest_integer_match":(np.floor(pred+.5)==obs).astype(int),
          "floor_integer_match":(np.floor(pred)==obs).astype(int),
          "near_equality_draw":((np.abs(opp-r)<=12)&(score==.5)).astype(int),
          "near_equality_draw_sign_mismatch":((np.abs(opp-r)<=12)&(score==.5)&(np.sign(pred)!=np.sign(obs))).astype(int)})
        group=["month","speed","color","phase","outcome","rd_bin","gap_bin"]
        parts.append(frame.loc[ok].groupby(group,observed=True,dropna=False).sum(numeric_only=True).reset_index())
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()

def aggregate(c,paths,out,keys):
    if not paths: return
    cols=list(pq.ParquetFile(paths[0]).schema_arrow.names)
    vals=[x for x in cols if x not in keys]
    sql="SELECT "+",".join(ident(k) for k in keys)+","+",".join(f"sum({ident(x)}) AS {ident(x)}" for x in vals)+f" FROM {scan(paths)} GROUP BY "+",".join(ident(k) for k in keys)
    copy_query(c,sql,out)

def speed_replay(task):
    project,work,speed,producer_path,allow_jit=task
    project,work=Path(project),Path(work)
    producer=load_stage06(producer_path)
    kernel,backend=configure(producer,allow_jit)
    log(f"{speed}: replay backend {backend}; resuming certified October 2025 state")
    authenticated=authenticate_checkpoint(project,work,speed,"2025-10")
    cp=Path(authenticated["data_path"]);m=authenticated["metadata"]
    dictionary=project/"derived/glicko2_replay/user_dictionary_v1/summary.json"
    n_users=int(read_json(dictionary)["total_global_users"])
    source_root=project/"derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time"
    chain={"original_checkpoint_sha256":m["sha256"],"dictionary_sha256":sha(dictionary),"producer_sha256":STAGE06_SHA,"version":DATA_CONTRACT_VERSION}
    state=None; results=[]
    for month in POST_MONTHS:
        event=source_root/f"speed={speed}"/f"month={month}"/"part-00000.parquet"
        base=work/"base"/f"month={month}"/"opportunities.parquet"
        dest=work/"replay"/f"speed={speed}"/f"month={month}"
        dest.mkdir(parents=True,exist_ok=True)
        rec_path=dest/"_SUCCESS.json"
        contract={**chain,"event":stamp(event),"base_sha256":sha(base),"month":month,"speed":speed}
        key=digest(contract)
        if rec_path.exists():
            rec=read_json(rec_path)
            if rec.get("key")!=key: raise RuntimeError(f"{speed}/{month}: saved replay inputs changed")
            for v in rec["outputs"].values():
                if sha(v["path"])!=v["sha256"]: raise RuntimeError(f"Corrupt replay output: {v['path']}")
            cp=Path(rec["outputs"]["checkpoint"]["path"])
            chain["previous_checkpoint_sha256"]=rec["outputs"]["checkpoint"]["sha256"]
            state=None; results.append(rec); log(f"{speed}/{month}: verified completed month reused")
            continue
        if state is None:
            state=producer.load_checkpoint(cp,n_users,SimpleNamespace(default_rd=500.,default_sigma=.09))
        c=connection(dest/"tmp")
        targets=set(c.execute(f"SELECT game_id FROM {scan(base)} WHERE speed={q(speed)}").fetchnumpy()["game_id"].tolist())
        c.close()
        event_hash=sha(event)
        columns=list(producer.REQUIRED_REPLAY_COLUMNS)
        pf=pq.ParquetFile(event)
        missing=set(columns)-set(pf.schema_arrow.names)
        if missing: raise RuntimeError(f"{event}: missing replay columns {missing}")
        t0=time.monotonic(); processed=0; previous=-1; target_hits=0
        diags=[]; hours=[]; writer=None; batches=0
        target_path=dest/"targets.parquet"; target_tmp=dest/"targets.tmp.parquet"
        target_tmp.unlink(missing_ok=True)
        for batch in pf.iter_batches(batch_size=100000,columns=columns,use_threads=False):
            df=batch.to_pandas(); ar=df.archive_ordinal.to_numpy(np.int64)
            df["white_rating_diff"]=df.white_rating_diff.astype(float)
            df["black_rating_diff"]=df.black_rating_diff.astype(float)
            if len(ar) and (ar[0]<=previous or np.any(np.diff(ar)<=0)): raise RuntimeError(f"{speed}/{month}: archive order or uniqueness failed")
            if len(ar): previous=int(ar[-1])
            pre=kernel(*state,df.white_id.to_numpy(np.int64),df.black_id.to_numpy(np.int64),
                df.white_elo.to_numpy(float),df.black_elo.to_numpy(float),df.utc_ms.to_numpy(np.int64),
                df.result_code.to_numpy(np.int8),df.white_rating_diff.to_numpy(float),df.black_rating_diff.to_numpy(float))
            d=diagnostics(month,speed,df,pre)
            if not d.empty:
                dp=dest/"partials"/f"diag_{batches:05d}.parquet";write_frame(d,dp);diags.append(dp)
            h=pd.DataFrame({"hour_ms":(df.utc_ms.to_numpy(np.int64)//3600000)*3600000,
              "speed":speed,"n_games":1,"both_null":(df.white_rating_diff.isna()&df.black_rating_diff.isna()).astype(int).to_numpy(),
              "negative_elapsed_sides":(pre[:,6]>df.utc_ms.to_numpy()).astype(int)+(pre[:,7]>df.utc_ms.to_numpy()).astype(int)})
            h=h.groupby(["hour_ms","speed"],observed=True).sum().reset_index()
            hp=dest/"partials"/f"hour_{batches:05d}.parquet";write_frame(h,hp);hours.append(hp)
            sel=df.game_id.isin(targets).to_numpy()
            if sel.any():
                target=df.loc[sel].copy()
                for k,name in enumerate(("white_pre_rd","black_pre_rd","white_pre_sigma","black_pre_sigma","white_prior_games","black_prior_games","white_last_ms","black_last_ms","white_pred","black_pred","white_previous_rd","black_previous_rd")):
                    target[name]=pre[sel,k]
                table=pa.Table.from_pandas(target,preserve_index=False)
                if writer is None: writer=pq.ParquetWriter(target_tmp,table.schema,compression="zstd")
                writer.write_table(table);target_hits+=int(sel.sum())
            processed+=len(df);batches+=1
            if batches%10==0 or batches==1:
                rate=processed/max(.001,time.monotonic()-t0)
                log(f"{speed}/{month}: {processed:,}/{pf.metadata.num_rows:,} games; month ETA {(pf.metadata.num_rows-processed)/rate/60:.1f} min")
        if writer is None:
            raise RuntimeError(f"{speed}/{month}: no target rows were found")
        writer.close();os.replace(target_tmp,target_path)
        if target_hits!=len(targets): raise RuntimeError(f"{speed}/{month}: target coverage {target_hits}/{len(targets)}")
        c=connection(dest/"tmp")
        if c.execute(f"SELECT count(*)-count(DISTINCT game_id) FROM {scan(target_path)}").fetchone()[0]: raise RuntimeError("Duplicate replay target ID")
        aggregate(c,diags,dest/"diagnostics.parquet",["month","speed","color","phase","outcome","rd_bin","gap_bin"])
        aggregate(c,hours,dest/"hourly_games.parquet",["hour_ms","speed"])
        c.close()
        rd,sigma,games,last=state;active=np.flatnonzero(games>0)
        cp=dest/"state_after.parquet"
        write_frame(pd.DataFrame({"user_id":active,"rd":rd[active],"sigma":sigma[active],"games_seen":games[active],"last_seen_ms":last[active]}),cp)
        outputs={name:parquet_receipt(dest/file) for name,file in {"checkpoint":"state_after.parquet","targets":"targets.parquet","diagnostics":"diagnostics.parquet","hourly":"hourly_games.parquet"}.items()}
        rec={"key":key,"contract":contract,"event_sha256":event_hash,"backend":backend,"rows":processed,"target_rows":target_hits,"elapsed_seconds":round(time.monotonic()-t0,2),"outputs":outputs}
        write_json(rec_path,rec);results.append(rec)
        chain["previous_checkpoint_sha256"]=outputs["checkpoint"]["sha256"]
        for p in diags+hours:p.unlink()
        log(f"{speed}/{month}: checkpoint and diagnostics complete")
    return results

def replay_all(project,work,workers,allow_jit=True):
    producer_path=Path(project)/"replication_package/code/06_build_glicko2_cost_layer.py"
    load_stage06(producer_path)
    results=[];failures=[]
    with ProcessPoolExecutor(max_workers=min(workers,len(SPEEDS))) as pool:
        fs={pool.submit(speed_replay,(str(project),str(work),s,str(producer_path),allow_jit)):s for s in SPEEDS}
        for f in as_completed(fs):
            try:results.extend(f.result())
            except Exception as exc:failures.append({"speed":fs[f],"error":str(exc),"traceback":traceback.format_exc()})
            write_json(Path(work)/"replay_status.json",{"completed_speed_months":[r["contract"]["speed"]+"/"+r["contract"]["month"] for r in results],"failures":failures})
    if failures:raise RuntimeError("Replay stopped in speed(s): "+", ".join(x["speed"] for x in failures)+"; see replay_status.json")
    return results
