#!/usr/bin/env python3
"""Synthetic tests only. --require-io refuses skipped Arrow tests before production."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import sys
import unittest
from types import SimpleNamespace
import numpy as np
import preliminary_core as c
import iv_numerics as num
import run_preliminary as r

HAS_ARROW=importlib.util.find_spec('pyarrow') is not None
START=int(c.STARTS[6])+123000

def export(gid='aBcD1234',status='mate'):
    return dict(id=gid,source='pool',status=status,createdAt=START,lastMoveAt=START+60000,
       rated=True,variant='standard',speed='blitz',clock={'initial':180,'increment':0},winner='white',
       players={'white':{'user':{'id':'recipient','name':'Recipient'},'rating':1500},
                'black':{'user':{'id':'opponent','name':'Opponent'},'rating':1501}})

def frame(gid='aBcD1234'):
    return dict(game_id=gid,utc_ms=START,month='2024-05',speed_partition='blitz',
                recipient_id=1,opponent_id=2,recipient_color='white',white_id=1,black_id=2,archive_ordinal=1)

def ledger(gid='aBcD1234'):
    return dict(game_id=gid,source='pool',source_conflict=False,api_status='mate',metadata_usable_records=1,
                stage07_identity_agrees=True,in_certified_stage07=False)

def htable(rows):
    keys=['j','i','t','start','ord','gid','y','arm','fair','cell']
    return {k:np.array([x[k] for x in rows],dtype=('U8' if k=='gid' else bool if k in ('y','arm','fair') else np.int64)) for k in keys}

def hist(j,i,t,start,gid,y=False,ord=0,fair=True):
    return dict(j=j,i=i,t=t,start=start,ord=ord,gid=gid,y=y,arm=True,fair=fair,cell=0)

def qtable(rows):
    return {k:np.array([r[k] for r in rows],dtype='U8' if k=='game_id' else np.int64) for k in rows[0]}

class Pure(unittest.TestCase):
    def test_case_sensitive_ids(self):
        ids=['abcdefgh','Abcdefgh','abcDefgh','1234abcd']; self.assertEqual(len(c.independent_indices(ids,4)),4)
    def test_invalid_duplicate_ids(self):
        for ids in [['bad'],['abcdefgh','abcdefgh']]:
            with self.assertRaises(ValueError): c.independent_indices(ids,1)
    def test_sampling_order_invariance(self):
        ids=[f'g{k:07d}' for k in range(1000)]
        a={ids[i] for i in c.independent_indices(ids,100)}; rev=list(reversed(ids))
        b={rev[i] for i in c.independent_indices(rev,100)}; self.assertEqual(a,b)
    def test_sampling_never_reads_status(self):
        ids=[f'g{k:07d}' for k in range(100)]; first=c.independent_indices(ids,20)
        arbitrary_status=['timeout']*100; arbitrary_status[:50]=['mate']*50
        np.testing.assert_array_equal(first,c.independent_indices(ids,20))
    def test_sampling_full_sha_reference(self):
        ids=[f'g{k:07d}' for k in range(100)]
        expected=sorted(range(100),key=lambda i:(hashlib.sha256(c.PILOT_SAMPLE_SEED+ids[i].encode()).hexdigest(),ids[i]))[:13]
        self.assertEqual(c.independent_indices(ids,13).tolist(),expected)
    def test_status_narrow_and_broad(self):
        for s in ('timeout','outoftime','aborted','nostart',None):
            self.assertFalse(c.normal_group(s)); self.assertFalse(c.normal_group(s,True))
        for s in ('mate','resign','stalemate'): self.assertTrue(c.normal_group(s))
        self.assertFalse(c.normal_group('draw')); self.assertTrue(c.normal_group('draw',True))
    def test_source_missing_not_pool(self):
        self.assertEqual(c.safe_source(None),'MISSING'); self.assertEqual(c.safe_source('sensitivevalue'),'OTHER_EXPLICIT_SOURCE')
    def test_normalization_complete(self):
        v,e=c.normalize_export(export(),'aBcD1234'); self.assertFalse(e)
        self.assertEqual(v['white_username'],'recipient'); self.assertIsNone(v['white_provisional'])
        self.assertFalse(c.validate_metadata(v,frame(),ledger(),e))
    def test_speed_normalized(self):
        x=export(); x['speed']='ultraBullet'; v,_=c.normalize_export(x,'aBcD1234'); self.assertEqual(v['speed'],'ultrabullet')
    def test_no_chat_absence_inference(self):
        v,_=c.normalize_export(export(),'aBcD1234')
        self.assertNotIn('no_chat',v); self.assertNotIn('no_takebacks',v)
    def test_wrong_game_id_is_error(self):
        _,e=c.normalize_export(export('AbCd1234'),'aBcD1234'); self.assertIn('GAME_ID_MISMATCH',e)
    def test_source_conflict_is_error(self):
        x=export(); x['api_source']='friend'; _,e=c.normalize_export(x,'aBcD1234'); self.assertIn('ROW_SOURCE_CONFLICT',e)
    def test_username_conflict_is_error(self):
        x=export(); x['players']['white']['user']['name']='different'; _,e=c.normalize_export(x,'aBcD1234'); self.assertIn('WHITE_USERNAME_CONFLICT',e)
    def test_missing_fields_not_zero(self):
        x=export(); del x['players']['white']['rating']
        v,e=c.normalize_export(x,'aBcD1234'); errors=c.validate_metadata(v,frame(),ledger(),e)
        self.assertIn('MISSING_WHITE_RATING',errors); self.assertIsNone(v['white_rating'])
    def test_archive_second_precision(self):
        x=export(); x['createdAt']+=950; v,e=c.normalize_export(x,'aBcD1234')
        self.assertNotIn('CREATED_TIME_FRAME_DISAGREEMENT',c.validate_metadata(v,frame(),ledger(),e))
        x['createdAt']+=100; v,e=c.normalize_export(x,'aBcD1234')
        self.assertIn('CREATED_TIME_FRAME_DISAGREEMENT',c.validate_metadata(v,frame(),ledger(),e))
    def test_duplicate_consensus(self):
        a=c.normalize_export(export(),'aBcD1234'); merged,errors=c.merge_records([a,a],'aBcD1234')
        self.assertEqual(merged['metadata_records_audited'],2); self.assertFalse(errors)
    def test_duplicate_conflict_not_voted_away(self):
        a=c.normalize_export(export(),'aBcD1234'); b=export(); b['players']['white']['rating']=1600
        merged,errors=c.merge_records([a,a,c.normalize_export(b,'aBcD1234')],'aBcD1234')
        self.assertIn('CONFLICT_WHITE_RATING',errors); self.assertIsNone(merged['white_rating'])
    def test_empty_metadata_pool_pending_nonpool_known(self):
        v,e=c.merge_records([],'aBcD1234'); self.assertIn('MISSING_ANCHOR_MS',c.validate_metadata(v,frame(),ledger(),e))
        l=ledger(); l['source']='friend'; v,e=c.merge_records([],'aBcD1234'); self.assertFalse(c.validate_metadata(v,frame(),l,e))
    def test_inconsistent_stage07_normal_blocked(self):
        v,e=c.normalize_export(export(),'aBcD1234'); l=ledger(); l['in_certified_stage07']=True
        self.assertIn('NORMAL_END_IN_STAGE07',c.validate_metadata(v,frame(),l,e))
    def test_multiple_exposures_skip_game_not_person(self):
        h=htable([hist(1,2,110,101,'game0001',True),hist(1,3,120,111,'game0002',False),hist(1,4,130,121,'game0003',True)])
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=100,archive_start_ms=90,game_id='focal001'),
                  dict(sample_row=1,recipient_id=1,opponent_id=3,anchor_ms=115,archive_start_ms=105,game_id='focal002')])
        a=c.first_other_and_history(h,q); np.testing.assert_array_equal(a['y'],[False,True]); np.testing.assert_array_equal(a['outcome_t'],[120,130])
    def test_started_before_anchor_skipped(self):
        h=htable([hist(1,4,110,99,'game0001',True),hist(1,5,120,111,'game0002',False)])
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=100,archive_start_ms=90,game_id='focal001')])
        self.assertEqual(c.first_other_and_history(h,q)['outcome_t'][0],120)
    def test_strict_anchor_and_90day_boundary(self):
        h=htable([hist(1,4,100,101,'game0001',True),hist(1,5,100+90*c.DAY+1,111,'game0002',True)])
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=100,archive_start_ms=90,game_id='focal001')])
        a=c.first_other_and_history(h,q); self.assertFalse(a['reached'][0]); self.assertFalse(a['y'][0])
    def test_ties_use_archive_order_and_gid(self):
        h=htable([hist(1,4,120,110,'game0002',True,ord=1),hist(1,4,120,110,'game0001',False,ord=1)])
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=100,archive_start_ms=90,game_id='focal001')])
        self.assertFalse(c.first_other_and_history(h,q)['y'][0])
    def test_empty_history(self):
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=100,archive_start_ms=90,game_id='focal001')])
        out=c.first_other_and_history(htable([]),q); self.assertFalse(out['reached'][0]); self.assertEqual(out['own_fair90'][0],0)
    def test_lead_ends_seven_days_before_start(self):
        start=200*c.DAY; end=start-7*c.DAY
        h=htable([hist(1,2,end-100,end-200,'game0001',True),hist(1,4,end-200,end-300,'game0002',False),hist(1,4,end,end-1,'game0003',True)])
        q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=start+100,archive_start_ms=start,game_id='focal001')])
        out=c.first_other_and_history(h,q); self.assertEqual(out['own_fair90'][0],2); self.assertTrue(out['lead_present'][0]); self.assertFalse(out['lead_y'][0])
    def test_reused_score_excludes_all_pair_and_future(self):
        hj=np.array([2]*8); hi=np.array([1,1,3,4,5,6,7,8]); ht=np.arange(8); yy=np.array([1,1,0,0,1,0,1,1]); hc=np.zeros(8,int)
        model=np.zeros((4,4,500))+0.1
        out=num.score_month(hj,hi,ht,yy,hc,np.array([2]),np.array([1]),6,model)
        self.assertEqual(out['n'][0],4); self.assertEqual(out['pair_removed'][0],2); self.assertAlmostEqual(out['raw'][0],.25)
    def test_score_history_absence_is_nan(self):
        out=num.score_month(np.array([],int),np.array([],int),np.array([],int),np.array([],int),np.array([],int),np.array([2]),np.array([1]),10,np.zeros((4,4,500)))
        self.assertTrue(np.isnan(out['adjusted'][0])); self.assertEqual(out['n'][0],0)
    def test_shared_account_meat_against_bruteforce(self):
        rng=np.random.default_rng(44)
        for withday in (False,True):
            for repeat in range(10):
                n=50; i=rng.integers(1,15,n); j=rng.integers(1,15,n); j[j==i]+=20
                day=rng.integers(0,5,n); s=rng.normal(size=n)
                adjacency=(i[:,None]==i)|(i[:,None]==j)|(j[:,None]==i)|(j[:,None]==j)
                if withday: adjacency|=day[:,None]==day
                direct=float(np.sum(s[:,None]*s*adjacency))
                self.assertAlmostEqual(c.dependent_meat(s,i,j,day if withday else None),direct,places=9)
    def test_cross_role_dependence(self):
        s=np.array([2.,3.]); i=np.array([1,2]); j=np.array([2,3])
        self.assertAlmostEqual(c.dependent_meat(s,i,j),25.)
    def test_self_pair_rejected(self):
        with self.assertRaises(ValueError): c.dependent_meat([1.],[1],[1])
    def test_regression_common_scale(self):
        rng=np.random.default_rng(3); n=2000; z=rng.normal(size=n); e=rng.normal(size=n); y=.003*z+e
        i=np.arange(n); j=np.arange(n)+n; day=np.arange(n)
        a=c.fit_reduced_form(y,z,i,j,day,False); direct=float(z@y/(z@z))
        self.assertAlmostEqual(a['coefficient_pp_per_pilot_SD'],100*c.PILOT_Z_SD*direct)
        self.assertFalse(a['exclusion_certified'])
    def test_model_partialling_matches_dummies(self):
        rng=np.random.default_rng(99); n=60; X=rng.normal(size=(n,2)); v=rng.normal(size=(n,3)); g=np.arange(n)%4
        residual,_=num.partial_out(np.c_[X,v],[g],2)
        design=np.c_[np.eye(4)[g],X]; expected=v-design@np.linalg.lstsq(design,v,rcond=None)[0]
        np.testing.assert_allclose(residual,expected,atol=1e-9)
    def test_no_variation_not_null_finding(self):
        a=c.fit_reduced_form(np.ones(100),np.zeros(100),np.arange(100),np.arange(100)+100,np.arange(100),False)
        self.assertFalse(a['supported']); self.assertEqual(a['reason'],'NO_RESIDUAL_SCORE_VARIATION')
    def test_unresolved_ledger_not_silently_overridden(self):
        v,e=c.normalize_export(export(),'aBcD1234'); l=ledger(); l['api_status']=None
        self.assertIn('LEDGER_STATUS_UNRESOLVED',c.validate_metadata(v,frame(),l,e))
        v,e=c.normalize_export(export(),'aBcD1234'); l=ledger(); l['created_at_ms']=None
        self.assertIn('LEDGER_CREATED_TIME_UNRESOLVED',c.validate_metadata(v,frame(),l,e))
    def test_complete_numerical_model_ladder(self):
        rng=np.random.default_rng(817); n=3000; start=int(c.STARTS[6])
        day=rng.integers(0,25,n); hour=rng.integers(0,24,n)
        d=dict(sample_row=np.arange(n),status=np.array(['mate']*n),
             recipient_id=np.arange(n),opponent_id=np.arange(n)+n,
             archive_start_ms=start+day*c.DAY+hour*3600000,month_code=np.full(n,6),
             tc_base_s=np.full(n,180),tc_inc_s=np.zeros(n,int),
             recipient_rating=1500+rng.normal(0,80,n),opponent_rating=1500+rng.normal(0,80,n),
             y=rng.random(n)<.025,reached=rng.random(n)<.45,
             own_fair90=rng.integers(0,10,n),own_kind90=rng.integers(0,2,n))
        d['reached']|=d['y']
        for lag in (7,30):
            d[f'n_{lag}d']=rng.integers(10,40,n); d[f'counterparts_{lag}d']=rng.integers(8,10,n)
            d[f'expected_{lag}d']=rng.uniform(.01,.05,n); d[f'adjusted_{lag}d']=rng.normal(0,.07,n)
        with tempfile.TemporaryDirectory() as td:
            count=r.estimate(d,Path(td)); self.assertEqual(count,24)
            import csv
            vals=list(csv.DictReader((Path(td)/'exploratory_placebos.csv').open()))
            self.assertEqual(len(vals),24); self.assertTrue(all(v['sample_is_availability_selected']=='True' for v in vals))
    def test_evidence_archives_authenticated(self):
        package=Path(__file__).parent
        a=r.report_evidence(package,'VALIDITY_REPORT.zip',r.VALIDITY_SHA,'CHOOSER_LENIENCY_VALIDITY_LOCAL_REPORT')
        self.assertEqual(a['run_id'],r.VALIDITY_ID)
        b=r.report_evidence(package,'IV_PILOT_REPORT.zip',r.IV_SHA,'CHOOSER_LENIENCY_IV_PILOT_REPORT')
        self.assertEqual(b['run_id'],r.IV_ID)
    def test_manifest_corruption_detected_without_arrow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'a.txt').write_text('ok'); h=r.sha(root/'a.txt')
            r.js(root/'_COMPLETE.json',{'config_sha256':'test','files':[{'path':'a.txt','bytes':2,'sha256':h}]})
            r.receipt_file(root,'test','a.txt'); (root/'a.txt').write_text('NO')
            with self.assertRaises(RuntimeError): r.receipt_file(root,'test','a.txt')
    def test_report_excludes_private_rows(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); public=root/'public'; public.mkdir(); desktop=root/'desktop'; desktop.mkdir()
            (public/'REPORT.md').write_text('aggregate'); (public/'PRIVATE_secret.txt').write_text('PRIVATE_IDENTIFIER')
            dest=r.zipreport(public,desktop,'test')
            with zipfile.ZipFile(dest) as z:
                self.assertFalse(any('PRIVATE' in n for n in z.namelist())); self.assertFalse(any(b'PRIVATE_IDENTIFIER' in z.read(n) for n in z.namelist()))

@unittest.skipUnless(HAS_ARROW,'PyArrow is unavailable in this environment')
class ArrowIntegration(unittest.TestCase):
    def test_roundtrip_empty_and_populated_metadata(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'empty.parquet'; r.write(p,pa.Table.from_pylist([],schema=r.audited_schema())); self.assertEqual(len(r.read(p)),0)
            m,e=c.merge_records([c.normalize_export(export(),'aBcD1234')],'aBcD1234')
            p=Path(td)/'nonempty.parquet'; r.write(p,pa.Table.from_pylist([m],schema=r.audited_schema())); self.assertEqual(r.read(p)['game_id'].to_pylist(),['aBcD1234'])
    def test_checkpoint_hash_and_no_overwrite(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            final=Path(td)/'out'; tmp=r.newdir(final); r.write(tmp/'data.parquet',pa.table({'x':[1,2]})); r.finish(tmp,final,'conf')
            self.assertTrue(r.done(final,'conf'))
            with self.assertRaises(RuntimeError): r.write(final/'data.parquet',pa.table({'x':[3]}))
    def test_cached_metadata_reader(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'metadata.parquet'; r.write(p,pa.table({'game_id':['aBcD1234'],'metadata_json':[json.dumps(export())]}))
            got,_=r.read_metadata_job({'path':str(p),'sha256':r.sha(p),'rows':1})
            self.assertEqual(got[0][0]['white_rating'],1500)
    def test_identity_projection_uses_both_name_and_id(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'panel.parquet'
            r.write(p,pa.table({'chooser_user_id':[1,9],'disconnected_user_id':[2,8],
                 'chooser_username_norm':['recipient','alias'],'disconnected_username_norm':['opponent','other']}))
            out=r.identity_month({'path':str(p),'sha':r.sha(p),'ids':[1],'names':['opponent']})
            self.assertEqual(out,[(1,'recipient'),(2,'opponent')])
    def test_history_projection_filter(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            h=htable([hist(1,2,10,1,'game0001',True),hist(9,8,20,11,'game0002')])
            p=Path(td)/'hist.parquet'; r.write(p,pa.table(h)); out=r.load_histories([p],np.array([1]))
            self.assertEqual(out['j'].tolist(),[1]); self.assertEqual(out['gid'].tolist(),['game0001'])
    def test_full_shard_handles_repeated_recipient(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); anchor=START; j=2
            shard=int(num.user_hash([j])[0]%np.uint64(16))
            i=next(v for v in range(3,1000) if int(num.user_hash([v])[0]%np.uint64(16))==shard)
            rows=[hist(j,k,START-60*c.DAY+k,START-60*c.DAY-100,f'h{k:07d}',k%2==0) for k in range(30,36)]
            rows += [hist(i,j,anchor+10000,anchor+100,'same0001',True),hist(i,99,anchor+20000,anchor+15000,'othr0001',False)]
            hp=root/'h.parquet'; r.write(hp,pa.table(htable(rows)))
            qq=qtable([dict(sample_row=0,recipient_id=i,opponent_id=j,anchor_ms=anchor,archive_start_ms=anchor-100,game_id='focal001',month_code=6),
                       dict(sample_row=1,recipient_id=i,opponent_id=j,anchor_ms=anchor+5000,archive_start_ms=anchor-100,game_id='focal002',month_code=6)])
            qp=root/'q.parquet'; r.write(qp,pa.table(qq)); ref=root/'ref.npy'; np.save(ref,np.full((2,24,4,4,500),.1))
            job=dict(out=str(root/'output'),conf='test',queries=str(qp),parts=[str(hp)],reference=str(ref),shard=shard)
            out=r.history_shard(job); self.assertEqual(out['score_queries'],2); self.assertEqual(out['outcome_queries'],2)
            yy=r.read(root/'output/outcomes.parquet'); self.assertEqual(yy['reached'].to_pylist(),[True,True]); self.assertEqual(yy['y'].to_pylist(),[False,False])
            sc=r.read(root/'output/scores.parquet'); self.assertEqual(sc['n_7d'].to_pylist(),[6,6])
    def test_consolidation_keeps_independent_denominator(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); old=root/'old'; old.mkdir(); private=root/'private'; private.mkdir(); public=root/'public'; public.mkdir()
            part=old/'source_scan_files/unit000'; part.parent.mkdir(parents=True)
            temp=r.newdir(part); r.write(temp/'metadata.parquet',pa.table({'game_id':['aBcD1234'],'metadata_json':[json.dumps(export())]}))
            r.finish(temp,part,r.VALIDITY_CONFIG,{'metadata_rows':1}); r.js(old/'source_scan_jobs_PRIVATE.json',[{'out':str(part)}])
            f1=frame(); l1=ledger(); f2=frame('NoData01'); l2=ledger('NoData01'); l2.update(source=None,api_status=None,metadata_usable_records=0)
            args=SimpleNamespace(conf='test',workers=2,pilot_size=2)
            rows,queries,pending=r.consolidate(args,old,{'aBcD1234':(f1,l1),'NoData01':(f2,l2)},{'aBcD1234','NoData01'},private,public)
            self.assertEqual(len(rows),2); self.assertEqual(len(queries),1); self.assertEqual(pending,1)
            targets=r.read(private/'pilot200k_readiness/pending_API_targets.parquet'); self.assertEqual(targets['game_id'].to_pylist(),['NoData01'])
    def test_empty_shard_outputs_have_stable_schema(self):
        pa,_=r.deps()
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); q=qtable([dict(sample_row=0,recipient_id=1,opponent_id=2,anchor_ms=START,archive_start_ms=START-100,game_id='focal001',month_code=6)])
            qp=root/'q.parquet'; r.write(qp,pa.table(q)); ref=root/'ref.npy'; np.save(ref,np.full((2,24,4,4,500),.1))
            occupied={int(x) for x in (num.user_hash([1,2])%np.uint64(16))}; shard=next(s for s in range(16) if s not in occupied)
            out=r.history_shard(dict(out=str(root/'out'),conf='test',queries=str(qp),parts=[],reference=str(ref),shard=shard))
            self.assertEqual(out['outcome_queries'],0); self.assertEqual(out['score_queries'],0)
            self.assertEqual(len(r.read(root/'out/scores.parquet')),0)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--require-io',action='store_true'); args=p.parse_args()
    if args.require_io and not HAS_ARROW: raise SystemExit('ERROR: PyArrow integration tests are mandatory; no production input was opened.')
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or (args.require_io and result.skipped): raise SystemExit(2)
    print('PRELIMINARY_SYNTHETIC_TESTS_OK tests='+str(result.testsRun)+' skipped='+str(len(result.skipped)))
