"""Independent LSDV covariance reference and synthetic SQL-to-table tests."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import joint_state_ply as j


def fixture():
    rng=np.random.default_rng(18643)
    groups=93
    sizes=rng.integers(4,31,groups)
    sizes[:3]=1
    sizes[6]=201  # Must span many tiny read batches without splitting.
    ids=np.repeat(np.arange(groups),sizes)
    n=len(ids)
    board=rng.integers(0,5,n)
    ply=rng.integers(0,8,n)
    month=rng.integers(0,4,n)
    speed=rng.integers(0,3,n)
    premium=rng.uniform(0,4,n)
    lc=rng.uniform(0,7,n)
    ld=rng.uniform(0,7,n)
    missing=(rng.uniform(size=n)<.03).astype(float)
    effect=rng.normal(0,.10,groups)
    prob=np.clip(.25+.045*board-.018*ply+.025*premium+effect[ids],.02,.95)
    y=(rng.uniform(size=n)<prob).astype(float)
    y[ids==4]=0  # Never-granter retained.
    y[ids==5]=1
    return dict(chooser=ids.astype(np.int64),y=y,board=board.astype(np.int8),ply=ply.astype(np.int8),
                month_code=month.astype(np.int16),speed_code=speed.astype(np.int8),winprem10=premium,
                log_chooser_clock=lc,log_disconnected_clock=ld,clock_missing=missing)


def independent_design(d,meta):
    columns=[(d["board"]==k).astype(float) for k in range(1,5)]
    columns += [(d["ply"]==k).astype(float) for k in range(1,8)]
    columns += [d[k] for k in ["winprem10","log_chooser_clock","log_disconnected_clock","clock_missing"]]
    columns += [(d["month_code"]==k).astype(float) for k in range(1,len(meta["months"]))]
    columns += [(d["speed_code"]==k).astype(float) for k in range(1,len(meta["speeds"]))]
    return np.column_stack(columns)


def check_dummy_reference(d,meta,fits):
    X=independent_design(d,meta)
    ids=d["chooser"]
    unique,inverse=np.unique(ids,return_inverse=True)
    D=np.eye(len(unique))[inverse]
    max_beta=max_cov=0.
    for f in fits:
        # Full least-squares dummy-variable design, no within transform.
        A=np.column_stack([X[:,f["active"]],D])
        beta=np.linalg.lstsq(A,d["y"],rcond=None)[0]
        residual=d["y"]-A@beta
        bread=np.linalg.inv(A.T@A)
        scores=np.zeros((len(unique),A.shape[1]))
        np.add.at(scores,inverse,A*residual[:,None])
        V=len(unique)/(len(unique)-1)*bread@(scores.T@scores)@bread
        k=len(f["active"])
        np.testing.assert_allclose(f["beta"],beta[:k],atol=2e-10,rtol=2e-8)
        np.testing.assert_allclose(f["cov"],V[:k,:k],atol=2e-11,rtol=2e-8)
        max_beta=max(max_beta,float(np.max(np.abs(f["beta"]-beta[:k]))))
        max_cov=max(max_cov,float(np.max(np.abs(f["cov"]-V[:k,:k]))))
    return max_beta,max_cov


def run_tests():
    d=fixture()
    meta={"rows":len(d["y"]),"months":["2023-11","2023-12","2024-01","2024-02"],
          "speeds":["blitz","bullet","rapid"]}
    checks=[]
    with tempfile.TemporaryDirectory(prefix="joint_state_ply_test_") as td:
        root=Path(td)
        cache=root/"synthetic_PRIVATE.parquet"
        pq.write_table(pa.table(d),cache,row_group_size=71)
        batches=list(j.complete_group_batches(cache,32))
        np.testing.assert_array_equal(np.concatenate([b["chooser"] for b in batches]),d["chooser"])
        all_groups=[set(b["chooser"].tolist()) for b in batches]
        assert sum(map(len,all_groups))==len(np.unique(d["chooser"]))
        fits,counters,variation=j.fit_models(cache,meta,root,batch_size=32)
        b_err,v_err=check_dummy_reference(d,meta,fits)
        assert counters["rows"]==meta["rows"] and counters["choosers"]==93
        assert counters["singleton_choosers"]==3 and counters["zero_grant_choosers"]>=1
        checks.append({"test":"streamed_vs_full_dummy_LSDV","max_coef_error":b_err,"max_covariance_error":v_err})
        other,_,_=j.fit_models(cache,meta,root,batch_size=337)
        for a,b in zip(fits,other):
            np.testing.assert_allclose(a["beta"],b["beta"],atol=1e-11)
            np.testing.assert_allclose(a["cov"],b["cov"],atol=1e-11)
        # Clocks-missing can be constant: drop that nuisance explicitly, not targets.
        constant=dict(d,clock_missing=np.zeros(meta["rows"]))
        p2=root/"constant.parquet"
        pq.write_table(pa.table(constant),p2)
        f2,_,_=j.fit_models(p2,meta,root,63)
        assert f2[1]["dropped"]==["clock_missing"]
        check_dummy_reference(constant,meta,f2)
        checks.append({"test":"batch_invariance_zero_variation_control_and_zero_granters","passed":True})
        # Boundary and deterministic SQL checks; independent expected labels.
        con=duckdb.connect()
        cp=np.array([-301,-300,-299,-101,-100,0,100,101,299,300,301])
        boundary=pa.table({"engine_eval_cp_disconnected":cp})
        con.register("boundaries",boundary)
        observed=[r[0] for r in con.execute("SELECT "+j.board_sql()+" FROM boundaries").fetchall()]
        assert observed==[0,0,1,1,2,2,2,3,3,4,4]
        pl=np.array([0,4,5,6,7,8,9,10,11,20,21,40,41,80,81])
        con.register("ply_boundaries",pa.table({"ply_count":pl}))
        assert [r[0] for r in con.execute("SELECT "+j.ply_sql()+" FROM ply_boundaries").fetchall()]==[0,0,1,1,2,2,3,3,4,4,5,5,6,6,7]
        con.close()
        # Exercise the production SQL and outputs on shuffled, synthetic raw rows.
        evals=np.array([-350,-200,0,200,350])[d["board"]]
        plies=np.array([2,5,7,9,15,25,60,100])[d["ply"]]
        premiums=d["winprem10"]*10
        premiums=premiums.copy(); premiums[12]=np.nan
        clocks=np.expm1(d["log_chooser_clock"])
        clocks=clocks.copy(); clocks[13]=np.nan; clocks[14]=-1
        raw={"chooser_user_id":d["chooser"],"outcome_kind_draw":d["y"].astype(bool),
             "engine_fairness_bin":np.array(j.BOARD)[d["board"]],"engine_eval_cp_disconnected":evals,
             "ply_count":plies,"month":np.array(meta["months"])[d["month_code"]],
             "api_speed":np.array(meta["speeds"])[d["speed_code"]],
             "chooser_win_premium_v2":premiums,"chooser_clock_last_obs_s":clocks,
             "disconnected_clock_last_obs_s":np.expm1(d["log_disconnected_clock"])}
        rawtable=pa.table(raw).take(pa.array(np.random.default_rng(27).permutation(meta["rows"])))
        rawpath=root/"panel.parquet"; pq.write_table(rawtable,rawpath)
        original=(j.EXPECTED_HEADLINES,j.EXPECTED_BINS,j.EXPECTED_DRAWS)
        j.EXPECTED_HEADLINES={"rows":meta["rows"],"kind_draws":int(d["y"].sum()),"choosers":93}
        j.EXPECTED_BINS={b:int(np.sum(d["board"]==i)) for i,b in enumerate(j.BOARD)}
        j.EXPECTED_DRAWS={b:int(d["y"][d["board"]==i].sum()) for i,b in enumerate(j.BOARD)}
        public=root/"public"; public.mkdir()
        try:
            con=duckdb.connect(); con.execute("SET threads=3")
            cache2,meta2=j.prepare_cache(con,[rawpath],root,public)
            con.close()
        finally:
            j.EXPECTED_HEADLINES,j.EXPECTED_BINS,j.EXPECTED_DRAWS=original
        assert meta2["rows"]==meta["rows"]-1
        fits2,c2,v2=j.fit_models(cache2,meta2,root,89)
        j.export_results(fits2,c2,v2,meta2,public)
        assert (public/"regression_table_full.tex").read_text().count("(reference:")==2
        assert "ply_81_plus" in (public/"coefficients.csv").read_text()
        assert len((public/"joint_tests.csv").read_text().splitlines())==5
        checks.append({"test":"SQL_cache_boundaries_missingness_common_sample_tables","passed":True})
        # Target nonidentification and unsorted caches must fail rather than fake coefficients.
        failed=False
        try:
            j.solve_system(np.zeros((11,11)),np.zeros(11),j.CORE)
        except RuntimeError:
            failed=True
        assert failed
        reversed_cache=root/"unsorted.parquet"
        pq.write_table(pa.table({n:x[::-1] for n,x in d.items()}),reversed_cache)
        try:
            list(j.complete_group_batches(reversed_cache,32))
        except RuntimeError:
            pass
        else:
            raise AssertionError("Unsorted input accepted")
        checks.append({"test":"unidentified_targets_and_unsorted_input_fail_closed","passed":True})
    print(json.dumps({"status":"SELF_TEST_OK","checks":checks},indent=2),flush=True)
    return checks


if __name__=="__main__":
    run_tests()
