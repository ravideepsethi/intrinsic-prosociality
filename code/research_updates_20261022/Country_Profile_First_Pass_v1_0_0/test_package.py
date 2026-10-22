#!/usr/bin/env python3
"""Synthetic tests only. This does not relax production authentication."""
import os
os.environ['OPENBLAS_NUM_THREADS']='1'
import csv,json,sys,tempfile,concurrent.futures,multiprocessing
from pathlib import Path
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from utils import *
from core import *
from models import all_models,matrix,solve
from activity import phase,distance,band,worker,finalize_proxy,LOW,SPLIT,HIGH

def test():
    passed=[]; rng=np.random.default_rng(20260923)
    with tempfile.TemporaryDirectory(prefix='country_test_') as td:
        base=Path(td); run=base/'run'; (run/'report').mkdir(parents=True); (run/'PRIVATE').mkdir()
        dump(run/'RUN_IDENTITY.json',{'identity':'synthetic_only'})
        profiles=[]
        for uid in range(1,301):
            returned=uid not in [299,300]; disabled=uid in [295,296]
            flag=['US','CA','GB-ENG','_earth',None,None][uid%6]
            raw={'id':f'u{uid}','username':f'u{uid}','playTime':{'total':10000,'tv':60 if uid%4==0 else 0}}
            if flag: raw['profile']={'flag':flag}
            if uid==10: raw['profile']={'country':'CA'}; flag=None
            if uid==11: raw['profile']={'flag':'US','country':'CA'}; flag='US'
            if uid==12: raw['profile']={'flag':'  '}; flag=' '
            if uid==13: raw['profile']={'flag':'gb-eng'}; flag='GB-ENG'
            if disabled: raw={'id':f'u{uid}','username':f'u{uid}','disabled':True}; flag=None
            profiles.append(dict(username_norm=f'u{uid}',returned=returned,raw_user_json=json.dumps(raw) if returned else None,
              profile_flag=flag,profile_country='CA' if uid in [10,11] else None,profile_present='profile' in raw,
              acquisition_role='kind' if uid%4==0 else 'control',match_cell=f'cell{uid%7}',queried_at_utc='2026-08-26T12:00:00Z',
              play_time_tv_seconds=raw.get('playTime',{}).get('tv')))
        pp=base/'profiles.parquet'; pq.write_table(pa.Table.from_pylist(profiles),pp)
        db=connection('1GB',2,base/'spill'); normalize_profiles(db,[('august',pp)],run)
        assert db.execute("SELECT flag_code FROM profile_lookup WHERE username='u10'").fetchone()[0]=='CA'
        assert db.execute("SELECT flag_conflict,iso_code FROM profile_lookup WHERE username='u11'").fetchone()==(True,None)
        assert db.execute("SELECT flag_present FROM profile_lookup WHERE username='u12'").fetchone()==(False,)
        assert db.execute("SELECT flag_conflict,parent_code FROM profile_lookup WHERE username='u13'").fetchone()==(False,'GB')
        assert db.execute("SELECT flag_status FROM profile_lookup WHERE username='u295'").fetchone()[0]=='closed_profile_unavailable'
        assert db.execute("SELECT flag_status FROM profile_lookup WHERE username='u299'").fetchone()[0]=='unreturned'
        passed+=['modern/legacy fallback','blank and case normalization','conflict excluded from geography','closed vs unreturned profiles']
        month_records=[]; totals=dict(rows=0,kind_draws=0,fair_rows=0,fair_kind_draws=0,choosers=320)
        for month in ['2023-11','2024-01','2024-08','2024-11','2025-01','2025-08']:
            N=3200; ids=np.tile(np.arange(1,321),10); recipient=(ids+rng.integers(1,319,N)-1)%320+1
            assert (ids!=recipient).all()
            board=rng.choice([-600,-200,0,200,500],N); rawflag=np.array([i<=300 and bool(profiles[i-1]['profile_flag']) for i in ids])
            y=rng.random(N)<(.03+.06*(board>=-100)+.025*rawflag)
            ratings=rng.integers(900,2600,N); t=int(np.datetime64(month+'-10T12:00','ms').astype(np.int64))
            d=dict(chooser_user_id=ids,disconnected_user_id=recipient,chooser_username_norm=[f'u{i}' for i in ids],
              disconnected_username_norm=[f'u{i}' for i in recipient],outcome_kind_draw=y,engine_eval_cp_disconnected=board,
              chooser_elo=ratings,disconnected_elo=ratings+rng.integers(-600,601,N),ply_count=rng.integers(2,110,N),
              month=[month]*N,api_speed=rng.choice(['blitz','rapid'],N),utc_ms=np.full(N,t),
              chooser_draw_payoff_v2=rng.normal(0,5,N),chooser_win_premium_v2=rng.uniform(1,20,N),
              chooser_pre_rd_v2=rng.uniform(40,110,N),disconnected_pre_rd_v2=rng.uniform(40,110,N),
              chooser_clock_last_obs_s=rng.uniform(5,90,N),disconnected_clock_last_obs_s=rng.uniform(5,90,N))
            d['chooser_clock_last_obs_s'][0]=float('nan')
            path=base/(month+'.parquet'); pq.write_table(pa.table(d),path); month_records.append({'path':path,'month':month})
            totals['rows']+=N;totals['kind_draws']+=int(y.sum());totals['fair_rows']+=int((board>=-100).sum());totals['fair_kind_draws']+=int(y[board>=-100].sum())
        prepare_panel(db,run,dict(month_records=month_records,authority=totals),'synthetic_only')
        core_tables(db,run)
        assert db.execute('SELECT sum(fair_grants) FROM accounts').fetchone()[0]==totals['fair_kind_draws']
        assert db.execute("SELECT count(*) FROM accounts_model WHERE flag_status='not_acquired'").fetchone()[0]==20
        assert db.execute('SELECT count(*) FROM joined').fetchone()[0]==totals['rows']
        assert db.execute('SELECT sum(n) FROM accounts').fetchone()[0]==totals['rows']
        assert db.execute('SELECT sum(cc_missing) FROM panel').fetchone()[0]==6
        passed+=['clock missingness explicitly controlled','current account histories','non-acquired status preserved','joins conserve opportunities','support/rate/gradient queries execute']
        # Independently validate descriptive clustered mean and gradient SEs.
        g=db.execute("SELECT chooser,y,board FROM joined WHERE flag_status='active_no_flag'").fetchnumpy()
        fm=g['board']>=-100;lm=g['board']<=-300
        fi=g['chooser'][fm];fy=g['y'][fm];li=g['chooser'][lm];ly=g['y'][lm]
        fids,finv=np.unique(fi,return_inverse=True);mu=fy.mean()
        scores=np.bincount(finv,weights=fy-mu)/len(fy);ng=len(scores)
        expected_se=np.sqrt((scores@scores)*ng/(ng-1))*100
        rates=list(csv.DictReader((run/'report/02_flag_state_rates.csv').open()))
        observed=float(next(r for r in rates if r['flag_status']=='active_no_flag' and r['state']=='competitive')['chooser_cluster_se_pp'])
        assert abs(observed-expected_se)<1e-8
        ids=np.unique(np.concatenate([fi,li])); scores=np.zeros(len(ids))
        np.add.at(scores,np.searchsorted(ids,fi),(fy-fy.mean())/len(fy))
        np.add.at(scores,np.searchsorted(ids,li),-(ly-ly.mean())/len(ly))
        ng=len(scores);se=np.sqrt((scores@scores)*ng/(ng-1))*100
        gr=list(csv.DictReader((run/'report/02_flag_board_gradient.csv').open()))
        observed=float(next(r for r in gr if r['flag_status']=='active_no_flag')['chooser_cluster_se_pp'])
        assert abs(observed-se)<1e-8; passed+=['clustered descriptive mean SE','competitive-minus-losing covariance SE']
        all_models(db,run)
        r=read(run/'report/model_flag_competitive.json'); spec=r['specification']
        sel=list(dict.fromkeys(['chooser',spec['target']]+spec['cats']+spec['nums']))
        d=db.execute('SELECT '+','.join(qi(c) for c in sel)+',y::DOUBLE AS y FROM model_data WHERE '+spec['where']).fetch_arrow_table().to_pydict()
        X=matrix(d,spec).toarray(); y=np.array(d['y']); beta=np.linalg.lstsq(X,y,rcond=1e-10)[0]
        row=np.linalg.pinv(X,rcond=1e-10)[0,:]; influence=row*(y-X@beta)
        ids,inv=np.unique(d['chooser'],return_inverse=True); s=np.bincount(inv,weights=influence)
        rank=np.linalg.matrix_rank(X); n=len(y); gg=len(ids)
        se=np.sqrt((s@s)*gg/(gg-1)*(n-1)/(n-rank))*100
        assert abs(beta[0]*100-r['coefficient_pp'])<1e-7,(beta[0],r)
        assert abs(se-r['standard_error_pp'])<1e-7,(se,r['standard_error_pp'])
        passed+=['sparse adjusted LPM matches dense least squares','cluster SE sums across months and matches dense reference']
        all_models(db,run)
        assert read(run/'report/model_flag_competitive.json')['coefficient_pp']==r['coefficient_pp']
        passed+=['model checkpoint resume preserves coefficients']
        # Non-estimable target and cyclic phase edge cases.
        x=np.ones((10,2)); assert solve(x.T@x,x.T@np.arange(10))[0] is None
        h,R=phase(np.array([2]),np.cos(np.array([23.5,.5])*np.pi/12).sum(),np.sin(np.array([23.5,.5])*np.pi/12).sum())
        assert min(abs(float(h[0])),abs(float(h[0])-24))<1e-8
        assert float(distance(23,1))==2
        assert band(np.array([20.,8.]),np.array([True,False])).tolist()==['proxy_UTC+0','unclassified']
        passed+=['nonidentified target rejected','circular midnight wraparound','unsupported activity unclassified']
        parts=[]; jobs=[]
        for period,months in [(1,['2023-11','2024-01','2024-08']),(2,['2024-11','2025-01','2025-08'])]:
            for k,month in enumerate(months):
                ms=int(np.datetime64(month+'-15T20:00','ms').astype(np.int64))
                # Target chooser 1 appears as White and Black; foreign opponent is not in chooser frame.
                t=pa.table({'utc_ms':[ms]*60,'white_id':[1]*30+[999]*30,'black_id':[999]*30+[1]*30})
                inp=base/f'chron_{period}_{k}.parquet';pq.write_table(t,inp);out=run/'PRIVATE'/f'act_{period}_{k}.parquet'
                rec=dict(path=str(inp),bytes=inp.stat().st_size,month=month)
                jobs.append((rec,str(run/'PRIVATE/accounts.parquet'),str(out),'activity_test','256MB'));parts.append(out)
        with concurrent.futures.ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as pool:
            list(pool.map(worker,jobs))
        finalize_proxy(db,run,parts)
        z=db.execute('SELECT games,games_year1,games_year2,full_supported,stable_years,activity_band FROM activity_proxy WHERE chooser=1').fetchone()
        assert z==(360,180,180,True,True,'proxy_UTC+0'),z
        assert db.execute('SELECT count(*) FROM activity_proxy').fetchone()[0]==320
        assert db.execute('SELECT count(*) FROM activity_proxy WHERE full_supported').fetchone()[0]==1
        passed+=['ordinary-game worker counts both roles once','year-split activity stability','all choosers retained in proxy output','activity and held-out report tables execute']
        assert worker(jobs[0])['reused']
        passed+=['activity checkpoint resume','spawn-based multiprocessing']
        cp=base/'check.bin';cp.write_bytes(b'good');certify(cp,'x');cp.write_bytes(b'changed')
        try: valid(cp,'x'); raise AssertionError('corrupt checkpoint accepted')
        except RuntimeError: pass
        passed+=['corrupted checkpoint rejected']
        report_zip(run,'TEST'); db.close()
    from source.pool_wave1_common import verify_report_package
    authority,report=verify_report_package();assert authority['rows']==41534331
    passed+=['bundled current-panel authority and report checksums']
    result=dict(status='SYNTHETIC_TESTS_PASSED',tests=passed,production_data_run=False)
    dump(ROOT/'TEST_REPORT.json',result);print(json.dumps(result,indent=2))

if __name__=='__main__': test()
