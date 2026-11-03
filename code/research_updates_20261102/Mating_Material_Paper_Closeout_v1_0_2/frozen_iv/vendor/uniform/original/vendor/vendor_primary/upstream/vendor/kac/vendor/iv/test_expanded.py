#!/usr/bin/env python3
"""Synthetic-only correctness tests. No API calls, Stockfish or private data."""
import json, math, tempfile, unittest
from pathlib import Path
import numpy as np
import pyarrow as pa
import duckdb
import local_io as io
import audit_logic as audit
import expanded_logic as logic
import expanded_stats as stats
import followup_stats as prior
import followup_logic as volumes
import comparison_core as cmp
import iv_numerics as num
import run_expanded as run
from preliminary_core import DAY, STARTS, PANEL_END


def brute_history(hist,person,start):
    out={}
    for days in (90,30):
        selected=[r for r in hist if start-(days+7)*DAY<=r['t']<start-7*DAY]
        chooser=[r for r in selected if r['j']==person and r['fair']]
        recipient=[r for r in selected if r['i']==person]
        out.update({f'fair_{days}':len(chooser),f'kind_{days}':sum(r['y'] for r in chooser),
                    f'disconnect_{days}':len(recipient),f'receipt_{days}':sum(r['y'] for r in recipient),
                    f'claim_{days}':sum(r['arm'] and not r['y'] for r in recipient)})
    return out


def fixture(directory):
    start=int(STARTS[0]);hist=[]
    for i in range(1,5):
        for offset in (20,80,100,140,210,300,430,520,600):
            for role in (0,1):
                hist.append(dict(j=i if role==0 else 900+i,i=800+i if role==0 else i,
                    t=start+offset*DAY,y=offset%3==1,arm=offset%4!=0,fair=role==0))
    hp=directory/'history.parquet';io.table(hp,pa.Table.from_pylist(hist))
    rows=[]
    for i in range(1,5):
        for k,offset in enumerate((80,130,150,240,330,430,540,650)):
            t=start+offset*DAY;idx=len(rows)
            row=dict(row_id=idx,game_id=f'E{idx:07d}',recipient_id=i,opponent_id=100+idx,
                archive_start_ms=t,anchor_ms=t+1000,archive_ordinal=idx,received=k%3==0,arm_eligible=True,
                tc_base_s=300,tc_inc_s=3,recipient_rating=1500.,opponent_rating=1600.,
                month_code=(offset//30),recipient_rd=70.,opponent_rd=80.,
                first_recipient=k==0,complete90=t+1000+90*DAY<PANEL_END,
                support7=k!=2,observed_y=k%4==0,reached=True,outcome_gid=f'Y{idx:07d}',
                outcome_t=t+DAY,outcome_start=t+DAY-1000,outcome_opponent=1000+idx,
                history_window_complete=t-97*DAY>=start)
            row['y']=row['observed_y'] if row['complete90'] else None
            row.update(brute_history(hist,i,t))
            for lag in (7,30):
                row.update({f'n_{lag}d':10 if k!=2 else 2,f'adjusted_{lag}d':.1+k*.01,
                    f'raw_{lag}d':.2+k*.01,f'expected_{lag}d':.1,f'counterparts_{lag}d':10,f'pair_removed_{lag}d':0})
            rows.append(row)
    for gap in (30,90):
        flag=audit.spaced(*[np.array([r[n] for r in rows]) for n in ('recipient_id','archive_start_ms','anchor_ms','support7')],gap)
        for r,v in zip(rows,flag):r[f'spaced{gap}']=bool(v)
    ap=directory/'audited.parquet';io.table(ap,pa.Table.from_pylist(rows))
    q=[]
    for row in rows:
        z={k:row[k] for k in ['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code',
            'tc_base_s','tc_inc_s','recipient_rating','opponent_rating','y','reached','complete90']+
            [f'{n}_{lag}d' for lag in (7,30) for n in ('n','adjusted','expected','counterparts')]+
            [f'{n}_{days}' for days in (90,30) for n in ('fair','kind','disconnect','receipt')]}
        z.update(eligible_main=True,first_observed_pair=True,history_complete=row['history_window_complete'],
            ordinary_narrow=False,active_timeout=True,recipient_disconnect_main=True,recipient_fair_arm_main=True,
            passive_outoftime=False,recipient_chooser_main=False,actual_iv_exposure=row['first_recipient'])
        q.append(z)
    # Ordinary games include a never-exposed person and past/future timing cases.
    for i,offset in [(1,129),(1,131),(1,225),(1,239),(1,331),(9,130),(9,200),(9,350)]:
        z=dict(q[1]);z.update(game_id=f'Q{len(q):07d}',recipient_id=i,opponent_id=777,
            archive_start_ms=start+offset*DAY,anchor_ms=start+offset*DAY+1000,
            month_code=offset//30,history_complete=True,complete90=True,ordinary_narrow=True,
            active_timeout=False,recipient_disconnect_main=False,recipient_fair_arm_main=False,actual_iv_exposure=False)
        z.update({k:v for k,v in brute_history(hist,i,z['archive_start_ms']).items() if not k.startswith('claim')});q.append(z)
    chronology=[]
    for k,row in enumerate(q):
        chronology.extend([dict(utc_ms=row['archive_start_ms'],white_id=row['recipient_id'],black_id=row['opponent_id']),
            dict(utc_ms=row['archive_start_ms']-10*DAY,white_id=row['recipient_id'],black_id=8888+k)])
    chronology.append(dict(utc_ms=start-200*DAY,white_id=1,black_id=2))
    paths=[]
    for k,part in enumerate([chronology[::2],chronology[1::2]]):
        p=directory/f'chron_{k}.parquet';io.table(p,pa.Table.from_pylist(part))
        paths.append(dict(path=str(p),signature=io.sig(p),rows=len(part)))
    for k,r in enumerate(q):
        r['row_id']=k
        r['pre_games_30d']=sum(r['archive_start_ms']-30*DAY<=g['utc_ms']<r['archive_start_ms'] and
            r['recipient_id'] in (g['white_id'],g['black_id']) for g in chronology)
    qp=directory/'comparison.parquet';io.table(qp,pa.Table.from_pylist(q))
    return dict(audit=str(ap),followup_comparison=str(qp),iv=None,followup_iv=None,chron=paths),hp,chronology


def regression_data(n=2600):
    rng=np.random.default_rng(927);person=np.arange(n)%300;opponent=1000+rng.integers(0,500,n)
    t=int(STARTS[0])+DAY*(150+rng.integers(0,20,n));z=rng.normal(0,.05,n)
    d=dict(row_id=np.arange(n),recipient_id=person,opponent_id=opponent,archive_start_ms=t,
        recipient_rating=1400+rng.normal(0,80,n),opponent_rating=1400+rng.normal(0,80,n),
        month_code=np.full(n,5),tc_base_s=np.full(n,300),tc_inc_s=np.full(n,3),
        n_7d=rng.integers(5,50,n),counterparts_7d=rng.integers(5,20,n),expected_7d=np.full(n,.02),
        adjusted_7d=z,pre_games_30d=rng.integers(1,80,n))
    d['received']=rng.random(n)<np.clip(.2+2*z,.01,.99)
    d['y']=rng.random(n)<(.15+.05*d['received']);d['reached']=d['y']|(rng.random(n)<.7)
    for days in (90,30):
        d[f'fair_{days}']=rng.integers(0,30,n);d[f'kind_{days}']=rng.binomial(d[f'fair_{days}'],.1)
        d[f'disconnect_{days}']=rng.integers(0,50,n);d[f'receipt_{days}']=rng.binomial(d[f'disconnect_{days}'],.1)
        d[f'claim_{days}']=d[f'disconnect_{days}']-d[f'receipt_{days}']
    return d


class ExpandedTests(unittest.TestCase):
    def test_shared_account_date_covariance_matches_explicit_pairs(self):
        i=np.array([1,2,3,5,2,8]);j=np.array([2,1,2,6,7,1]);date=np.array([0,1,1,0,2,2])
        s=np.arange(18,dtype=float).reshape(6,3)/10
        mask=np.array([[bool({i[a],j[a]}&{i[b],j[b]}) or date[a]==date[b] for b in range(6)] for a in range(6)])
        got=prior.shared_meat(s,cmp.covariance_codes(i,j,date))
        np.testing.assert_allclose(got,s.T@mask@s,rtol=1e-12,atol=1e-12)

    def test_iv_matches_direct_2sls_after_absorption(self):
        rng=np.random.default_rng(21);n=400;g=np.arange(n)%9;x=rng.normal(size=n);z=rng.normal(size=n)
        d=.5*z+x+rng.normal(size=n);y=.7*d+2*x+rng.normal(size=n)
        a,info=num.partial_out(np.column_stack([x,z,d,y]),[g],1);zr,dr,yr=a.T
        r=stats.iv_result(yr,dr,zr,lambda s:np.atleast_2d(s).T@np.atleast_2d(s) if s.ndim==2 else np.array([[s@s]]))
        w=np.column_stack([np.eye(9)[g],x]);res=lambda a:a-w@np.linalg.lstsq(w,a,rcond=None)[0]
        expected=float(res(z)@res(y))/float(res(z)@res(d))
        self.assertAlmostEqual(r['iv_coefficient'],expected,places=10)

    def test_ar_set_matches_null_moment_test(self):
        rng=np.random.default_rng(89);z=rng.normal(size=200);d=.2*z+rng.normal(size=200);y=.4*d+rng.normal(size=200)
        meat=lambda s:s.T@s if s.ndim==2 else np.array([[s@s]])
        r=stats.iv_result(y,d,z,meat)
        for b in np.linspace(-5,5,101):
            score=z*(y-b*d);accepted=(score.sum()**2<=prior.CRIT**2*float(score@score)+1e-10)
            intervals=[(float(a),float(c)) for a,c in r['AR95_intervals_pp']]
            reported=any(a<=100*b<=c for a,c in intervals)
            self.assertEqual(accepted,reported)

    def test_fe_absorption_matches_explicit_dummies(self):
        rng=np.random.default_rng(12);n=180;i=np.arange(n)%20;date=rng.integers(0,5,n)
        a=rng.normal(size=(n,4));got,_=num.absorb(a,[i,date])
        w=np.column_stack([np.eye(20)[i],np.eye(5)[date]])
        expected=a-w@np.linalg.lstsq(w,a,rcond=None)[0]
        np.testing.assert_allclose(got,expected,atol=1e-9)

    def test_risk_strict_cutoff_no_future_or_ever_exposure_selection(self):
        e=dict(recipient_id=np.array([1,1,2]),archive_start_ms=np.array([10,130,400])*DAY,
               anchor_ms=np.array([11,131,401])*DAY)
        q=dict(recipient_id=np.array([1,1,1,1,1,2,9]),archive_start_ms=np.array([10,11,12,101,102,399,700])*DAY)
        r=logic.prospective_risk(e,q,90)
        np.testing.assert_array_equal(r['at_risk'],[True,True,False,False,True,True,True])
        self.assertTrue(r['anchor_tie'][1]);self.assertTrue(r['earlier_started_not_yet_anchored'][1])

    def test_early_history_selected_event_still_starts_cooldown(self):
        start=int(STARTS[0]);e=dict(recipient_id=np.array([1]),archive_start_ms=np.array([start+80*DAY]),anchor_ms=np.array([start+80*DAY+1000]))
        q=dict(recipient_id=np.array([1]),archive_start_ms=np.array([start+130*DAY]))
        self.assertFalse(logic.prospective_risk(e,q,90)['at_risk'][0])

    def test_spacing_not_recomputed_after_history_cut(self):
        i=np.ones(3,int);s=np.array([80,130,171])*DAY;a=s+1000;support=np.ones(3,bool)
        chosen=audit.spaced(i,s,a,support,90);history=np.array([False,True,True])
        np.testing.assert_array_equal(chosen&history,[False,False,True])
        self.assertFalse(np.array_equal(chosen&history,audit.spaced(i,s,a,support&history,90)))

    def test_volume_bounds_and_repeated_queries_match_brute_force(self):
        p=np.array([1,1,1,2]);s=np.array([40,40,55,50])*DAY
        t=np.array([10,11,39,40,49,55])*DAY;w=np.array([1,1,1,2,1,1]);b=np.array([8,8,2,1,9,2])
        keys,order,people=volumes.volume_plan(p,s);delta=np.zeros(len(p)+1,np.int64)
        volumes.accumulate_volume(t,w,b,keys,people,delta)
        got=volumes.finish_volume(delta,order)
        expected=[sum(ss-30*DAY<=tt<ss and pp in (ww,bb) for tt,ww,bb in zip(t,w,b)) for pp,ss in zip(p,s)]
        np.testing.assert_array_equal(got,expected)

    def test_no_opportunity_availability_retained_as_control(self):
        d=regression_data();xs,names,ts,tnames,groups,missing=stats.controls(d,True)
        self.assertIn('fair_history_present_90',names);self.assertIn('kind_rate_90',names)
        self.assertIn('log_claim_90',names);self.assertNotIn('log_claim_30',names)
        self.assertTrue(np.isfinite(np.column_stack(xs)).all())

    def test_primary_and_fe_keep_identical_repeat_rows(self):
        d=regression_data();d['recipient_id'][:7]=10000+np.arange(7)
        keep=logic.repeat_mask(d['recipient_id']);self.assertFalse(keep[:7].any())
        sub={k:v[keep] for k,v in d.items()}
        specs={s['name']:s for s in logic.specifications()}
        a=stats.estimate(sub,specs['main90_repeat_pooled']);b=stats.estimate(sub,specs['main90_repeat_FE_diagnostic'])
        self.assertEqual(a['design']['row_set_sha256'],b['design']['row_set_sha256'])
        self.assertEqual(a['design']['n'],b['design']['n'])
        self.assertTrue(any(r.get('estimator')=='2SLS' for r in a['estimates']))
        controlled=[r for r in b['balance'] if r['trait']=='log_claim_90'][0]
        self.assertEqual(controlled['reason'],'CONTROLLED_TRAIT_NOT_INDEPENDENT_BALANCE_EVIDENCE')

    def test_entry_and_placebo_estimators_preserve_units(self):
        d=regression_data();n=len(d['row_id']);rng=np.random.default_rng(771)
        for field in ('active_timeout','recipient_disconnect_main','recipient_fair_arm_main','selected_entry_90','analysis_entry_90'):
            d[field]=rng.random(n)<np.clip(.1+d['adjusted_7d'],.01,.9)
        specs={s['name']:s for s in logic.specifications()}
        for name in ('entry90_pooled','ordinary90_placebo'):
            r=stats.estimate(d,specs[name]);self.assertTrue(r['estimates'])
            supported=[v for v in r['estimates'] if v.get('supported')]
            self.assertTrue(supported)
            for fit in supported:
                self.assertAlmostEqual(fit['coefficient_pp'],100*stats.REFERENCE_SD*fit['coefficient'])
                self.assertEqual(fit['events'],int(d[fit['outcome']].sum()))

    def test_mismatched_spacing_and_duplicate_outcomes_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);inputs,h,chron=fixture(p);t=io.read(inputs['audit']);c=duckdb.connect()
            run.verify_audit_table(c,inputs['audit'],None,None)
            flag=io.arr(t,'spaced90').copy();flag[1]=not flag[1]
            t=t.set_column(t.schema.get_field_index('spaced90'),'spaced90',pa.array(flag));io.table(inputs['audit'],t)
            with self.assertRaises(RuntimeError):run.verify_audit_table(c,inputs['audit'],None,None)
            c.close()
        d=dict(recipient_id=np.array([1,2]),archive_start_ms=np.array([0,1]),anchor_ms=np.array([1,2]),
            reached=np.array([True,True]),outcome_gid=np.array(['same','same']))
        with self.assertRaises(ValueError):logic.validate_disjoint(d)

    def test_incomplete_followup_and_missing_history_not_imputed(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);inputs,h,chron=fixture(p);c=duckdb.connect()
            c.execute('CREATE VIEW a AS SELECT * FROM '+io.parq([inputs['audit']]))
            for candidate in logic.FLAGS:
                result=c.execute('SELECT * FROM a WHERE '+logic.sample_condition(candidate)).to_arrow_table()
                d=run.arrays(result)
                self.assertTrue(d['complete90'].all());self.assertTrue(d['history_window_complete'].all())
                self.assertFalse(any(v is None for v in d['y']))
            c.close()

    def test_checkpoint_resume_changed_config_and_tampering(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'stage';calls=[]
            def build(t):calls.append(1);(t/'value').write_text('test')
            io.stage(p,'abc',build);io.stage(p,'abc',build);self.assertEqual(len(calls),1)
            with self.assertRaises(RuntimeError):io.stage(p,'def',build)
            (p/'value').write_text('changed')
            with self.assertRaises(RuntimeError):io.stage(p,'abc',build)

    def test_end_to_end_parquet_joins_parallel_scan_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);root=p/'run';root.mkdir();inputs,h,chron=fixture(p);conf='synthetic'
            run.prepare(inputs,root,conf,.2,expected_counts=None,verify=False)
            v=run.volume_scan(inputs,root,conf,2);v2=run.volume_scan(inputs,root,conf,2);self.assertEqual(v,v2)
            ev=run.comparison_events_job(dict(month='fixture',parts=[str(h)],comparison=str(root/'prepared/comparison.parquet'),
                conf=conf,out=str(root/'events'),memory=.2))
            hs=[]
            for shard in range(16):
                hs.append(run.comparison_history_job(dict(shard=shard,parts=[str(p) for p in (Path(ev)/'events'/f'bucket={shard}').glob('*.parquet')],comparison=str(root/'prepared/comparison.parquet'),
                    conf=conf,out=str(root/'history'/str(shard)),memory=.2)))
            run.make_comparison(root,conf,.2,hs)
            run.assemble_exposures(inputs,root,conf,.2,v)
            a=run.arrays(io.read(root/'analysis/all.parquet'))
            expected=[sum(s-30*DAY<=g['utc_ms']<s and i in (g['white_id'],g['black_id']) for g in chron)
                      for i,s in zip(a['recipient_id'],a['archive_start_ms'])]
            np.testing.assert_array_equal(a['pre_games_30d'],expected)
            q=run.arrays(io.read(root/'comparison/comparison.parquet'))
            self.assertTrue(logic.entry_mask(q,90)[0][q['recipient_id']==9].all())
            self.assertTrue((q['analysis_entry_90']<=q['selected_entry_90']).all())
            self.assertEqual(len(q['row_id']),40)
            for spec in logic.specifications():run.model(root,conf,spec)
            io.js(root/'config.json',dict(config_sha256=conf));io.js(root/'DESIGN_FREEZE.json',dict(config_sha256=conf))
            desktop=p/'desktop';desktop.mkdir();run.export_report(root,conf,desktop,{})
            self.assertTrue((desktop/'CHOOSER_IV_EXPANDED_REPORT_synthetic.zip.sha256').is_file())
            summary=io.load(root/'report/summary.json')
            self.assertEqual(summary['network_requests_to_lichess'],0)
            self.assertFalse(summary['entry_denominator_is_all_game_census'])


if __name__=='__main__':
    result=unittest.main(verbosity=2,exit=False).result
    print(f'EXPANDED_IV_TESTS_OK tests={result.testsRun}; skips={len(result.skipped)}; no network requests' if result.wasSuccessful() else 'EXPANDED_IV_TESTS_FAILED')
    raise SystemExit(0 if result.wasSuccessful() else 1)
