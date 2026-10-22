"""Regression tests for the new statistic, conditional law and full run path."""
import ast
import contextlib
import io
import itertools
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from runner import common,run_c9 as prior,ply_engine as engine,checkpoints,run_ply
from runner.test_c9 import fixture_b2


class PlyTests(unittest.TestCase):
    def test_01_frozen_sources_and_exact_sampler_loop(self):
        for row in json.loads((run_ply.PACKAGE/'authority/SOURCE_BINDINGS.json').read_text()):
            self.assertEqual(common.sha256_file(run_ply.PACKAGE/row['path']),row['sha256'])
        old=ast.parse((run_ply.PACKAGE/'source/run_campaign1_c9_v100.py').read_text())
        old=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='worker_batch')
        old=next(n for n in ast.walk(old) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='position')
        new=ast.parse((run_ply.PACKAGE/'runner/ply_engine.py').read_text())
        new=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='draw_choices')
        new=next(n for n in ast.walk(new) if isinstance(n,ast.For))
        self.assertEqual(ast.dump(old,include_attributes=False),ast.dump(new,include_attributes=False))

    def test_02_real_completed_report_and_session_hash(self):
        report=run_ply.reference_report()
        self.assertEqual(len(report),15)
        mapping=json.loads(report['c9_session_mapping.json'])
        self.assertEqual(mapping['b1_rows'],832948)
        self.assertEqual(mapping['persisted_private_cache_sha256'],run_ply.SPEC['session_cache_sha256'])
        self.assertEqual(json.loads(report['c9_primary_later_session.json'])['observed_denominator'],22455)
        self.assertEqual(list(engine.RULES),run_ply.SPEC['outcome_rules'])
        self.assertEqual(list(engine.BAND_LABELS),run_ply.SPEC['ply_bands'])
        self.assertEqual(list(engine.STRATIFIED_SEED_TAG),run_ply.SPEC['conditioned_seed_tag'])

    def test_03_ply_boundaries_and_invalid_values(self):
        p=np.array([0,4,5,10,11,20,21,40,41,80,81,np.nan])
        np.testing.assert_array_equal(engine.ply_bands(p),[0,0,1,1,2,2,3,3,4,4,5,6])
        for invalid in [-1,4.5,np.inf,-np.inf]:
            with self.assertRaises(RuntimeError):engine.ply_bands([invalid])

    def test_04_each_draw_reanchors_and_matches_naive_counting(self):
        times=np.array([1,1,3600001,604800001,604800002,691200001],dtype=np.int64)
        sessions=np.array([1,1,2,3,3,4]);ply=np.array([4.,10.,11.,20.,21.,np.nan])
        choices=np.array([[1,0,1,0,0,1],[0,0,1,1,0,0],[0,1,0,1,1,0]],dtype=bool)
        got=engine.masked_totals(times,sessions,ply,choices)
        for draw,y in enumerate(choices):
            first=int(np.flatnonzero(y)[0])
            for rule in engine.RULES:
                threshold={'all':None,'outcome_gt4':4,'outcome_gt10':10,'outcome_gt20':20,
                           'anchor_and_outcome_gt10':10}[rule]
                anchor=(np.isfinite(ply[first]) and ply[first]>10) if rule=='anchor_and_outcome_gt10' else True
                eligible=[j for j in range(first+1,len(y)) if times[j]-times[first]<=604800000 and anchor
                          and (threshold is None or (np.isfinite(ply[j]) and ply[j]>threshold))]
                self.assertEqual(got[rule+'__eligible_anchor_users'][draw],int(anchor))
                for label,indices in [('total7',eligible),('same7',[j for j in eligible if sessions[j]==sessions[first]]),
                                      ('later7',[j for j in eligible if sessions[j]!=sessions[first]])]:
                    self.assertEqual(got[rule+'__'+label+'_den'][draw],len(indices))
                    self.assertEqual(got[rule+'__'+label+'_num'][draw],sum(y[j] for j in indices))
        # A short first grant excludes the sequence from the both-long statistic;
        # the later qualifying grant does not become a replacement first grant.
        self.assertEqual(got['anchor_and_outcome_gt10__total7_den'][0],0)
        self.assertGreater(got['outcome_gt10__total7_den'][0],0)
        self.assertEqual(got['all__total7_den'][0],3)
        with self.assertRaises(RuntimeError):engine.masked_totals(times,sessions,ply,np.zeros((1,6),dtype=bool))

    def test_05_band_conditional_law_and_fixed_counts(self):
        b2=common.load_source_module(prior.PACKAGE/'source/b2_reference.py','band_law_b2')
        odds=np.array([.1,.3,2.,1.,5.,9.]);bands=[np.array([0,2,4]),np.array([1,3,5])];totals=[1,2]
        tables=[b2.conditional_selection_probabilities(np.log(odds[ix]),k) for ix,k in zip(bands,totals)]
        full_probability=0.
        for a in itertools.combinations(range(3),1):
            for b in itertools.combinations(range(3),2):
                sequential=weighted=1.
                for ix,k,table,chosen in zip(bands,totals,tables,[a,b]):
                    remaining=k
                    for position in range(3):
                        probability=1. if remaining==3-position else table[position,remaining]
                        sequential*=probability if position in chosen else 1-probability
                        remaining-=int(position in chosen)
                    normalizer=sum(np.prod(odds[ix[list(c)]]) for c in itertools.combinations(range(3),k))
                    weighted*=np.prod(odds[ix[list(chosen)]])/normalizer
                self.assertAlmostEqual(sequential,weighted,places=13)
                full_probability+=sequential
        self.assertAlmostEqual(full_probability,1.,places=13)
        rng=np.random.default_rng(9123);sample=np.zeros((100,6),dtype=bool)
        for ix,k,table in zip(bands,totals,tables):
            sample[:,ix]=engine.draw_choices(table,k,100,rng)
            np.testing.assert_array_equal(sample[:,ix].sum(axis=1),np.full(100,k))
        np.testing.assert_array_equal(sample.sum(axis=1),np.full(100,3))
        for k in (0,3):
            table=b2.conditional_selection_probabilities(np.log(odds[:3]),k)
            values=engine.draw_choices(table,k,4,rng)
            np.testing.assert_array_equal(values,np.full((4,3),k==3))

    def test_06_missing_null_support_is_not_silently_dropped(self):
        c9=prior.load_c9();obs=engine.blank_totals(1);sim=engine.blank_totals(4)
        for law in engine.LAWS:
            for rule in engine.RULES:
                prefix=law+'__'+rule+'__'
                for cat in ('same7','later7'):
                    obs[prefix+cat+'_num'][:]=1;obs[prefix+cat+'_den'][:]=2
                    sim[prefix+cat+'_num'][:]=1;sim[prefix+cat+'_den'][:]=2
        sim['ply_band_conditioned__outcome_gt20__later7_den'][2]=0
        rows,_=run_ply.summarize(obs,sim,c9)
        failed=[r for r in rows if r['status']=='NOT_ESTIMABLE']
        self.assertEqual(len(failed),1);self.assertEqual(failed[0]['finite_null_rates'],3)
        self.assertNotIn('raw_randomization_p_two_sided',failed[0])

    def test_07_own_lock_and_shared_c9_patron_queue(self):
        import fcntl
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            project=Path(temp)
            shared=project/'derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_fresh_v100/runner.lock'
            shared.parent.mkdir(parents=True)
            with shared.open('a+') as handle:
                fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                def release(seconds):
                    self.assertEqual(seconds,30);fcntl.flock(handle,fcntl.LOCK_UN)
                with patch.object(run_ply.time,'sleep',side_effect=release) as waiting:
                    with run_ply.exclusive(project):
                        self.assertEqual(waiting.call_count,1)
                        with self.assertRaisesRegex(RuntimeError,'already active'):
                            with run_ply.exclusive(project):pass

    def test_08_full_4999_draw_run_publish_and_resume(self):
        with tempfile.TemporaryDirectory() as temp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(temp);b1=root/'b1.parquet';prop=root/'prop.parquet';sess=root/'session.parquet'
            users=6;n=8;total=users*n
            chooser=np.repeat(np.arange(users,dtype=np.int64),n);seq=np.tile(np.arange(n,dtype=np.int32),users)
            times=np.tile(np.array([0,0,600000,2400000,3600000,86400000,604800000,604800001],dtype=np.int64),users)+1700000000000
            y=np.tile(np.array([0,1,0,1,0,0,1,0],dtype=bool),users);y[:2*n]=True
            sessions=np.concatenate([np.ones(n,dtype=np.int64),np.arange(n,dtype=np.int64)]+[np.array([1,1,1,2,2,3,4,4])]*4)
            speed=np.tile(np.array(['blitz','blitz','rapid','rapid','blitz','rapid','blitz','blitz']),users)
            ply=np.tile(np.array([4.,5.,10.,11.,20.,21.,np.nan,80.]),users);ply[:2*n]=21
            pq.write_table(pa.table({'b1_row_id':np.arange(total),'chooser_index':chooser,'sequence_index':seq,
                'utc_ms':times,'kind_draw':y,'current_draw_payoff':np.tile([-1.,1.],total//2),'current_ply_count':ply}),b1)
            pq.write_table(pa.table({'b1_row_id':np.arange(total),'static_propensity':np.tile([.1,.2,.3,.4,.2,.1,.7,.2],users)}),prop)
            pq.write_table(pa.table({'b1_row_id':np.arange(total),'chooser_index':chooser,'sequence_index':seq,
                                    'session_id':sessions,'speed':speed}),sess)
            b2path,b2=fixture_b2(root,total,users,int(y.sum()))
            data,prob=b2.load_inputs(b1,prop)
            c9=prior.load_c9();reference_state=root/'original';(reference_state/'randomizations').mkdir(parents=True)
            original=c9.run_randomizations(b1,prop,sess,b2path,reference_state,'fixture-c9',2)
            b2_state=root/'b2';(b2_state/'randomizations').mkdir(parents=True)
            for start in range(0,4999,250):
                stop=min(start+250,4999)
                batch=b2.simulate_batch(data=data,probability=prob,simulations=stop-start,
                                      seed_components=[2026082201,start,stop],progress_label='fixture')
                np.savez_compressed(b2_state/'randomizations'/f'b2_{start:04d}_{stop-1:04d}.npz',**batch)
            obs=c9.observed_totals(data,sessions,speed)
            component_rows,_,_=c9.summarize_c9(obs,original)
            reference_public=root/'reference_public';reference_public.mkdir()
            prior.write_csv(reference_public/'c9_partition_components.csv',component_rows)
            horizon_rows=[]
            for index,hours in enumerate((6.,24.,168.)):
                rate=obs['b2_num'][0,index]/obs['b2_den'][0,index]
                null=c9.rate(original['b2_num'][:,index],original['b2_den'][:,index])
                horizon_rows.append({'horizon_hours':hours,'observed_numerator':int(obs['b2_num'][0,index]),
                  'observed_denominator':int(obs['b2_den'][0,index]),'observed_rate':float(rate),
                  'null_mean_rate':float(null.mean()),'randomization_p_two_sided':c9.randomization_tail_p(rate,null)[2]})
            prior.write_csv(reference_public/'b2_first_grant_horizons.csv',horizon_rows)
            paths={'b1':b1,'prop':prop,'b2_script':b2path,'b2_public':reference_public,'b2_state':b2_state}
            ref={'c9_state':str(reference_state),'b2_state':str(b2_state)}
            reference={'c9_partition_components.csv':(reference_public/'c9_partition_components.csv').read_bytes()}
            preflight={'fixture':True,'package':{'manifest_sha256':'fixture'},'runtime':{'fixture':'1'}}
            args=SimpleNamespace(project_root=root/'project',desktop=root/'desktop',workers=2,memory_gb=2.)
            returned=(paths,sess,c9,b2,reference,preflight,ref)
            with patch.object(run_ply,'authenticate',return_value=returned):run_ply.run(args)
            archives=list(args.desktop.glob('POOL_MAIN_C9_PLY_RESULTS_*.zip'))
            self.assertEqual(len(archives),1)
            with zipfile.ZipFile(archives[0]) as z:
                self.assertIsNone(z.testzip())
                self.assertFalse(any(n.endswith(('.parquet','.npz')) for n in z.namelist()))
                summary=json.loads(z.read(next(n for n in z.namelist() if n.endswith('/summary.json'))))
                self.assertEqual(summary['status'],'C9_PLY_SENSITIVITIES_COMPLETE')
                self.assertEqual(summary['unsupported_rows'],0)
            state=next((args.project_root/'derived/replication/pool_main_reanalysis_v100_PRIVATE/c9_ply_v100').glob('*/CONFIGURATION.json')).parent
            digest=common.load_json(state/'CONFIGURATION.json')['config_sha256']
            before={p:p.stat().st_mtime_ns for p in (state/'randomizations').iterdir()}
            self.assertEqual(len(before),40)
            with patch.object(run_ply,'authenticate',return_value=returned):run_ply.run(args)
            self.assertEqual(before,{p:p.stat().st_mtime_ns for p in (state/'randomizations').iterdir()})
            simulated,_,_=run_ply.run_batches(paths,sess,state,digest,ref,1)
            self.assertEqual(before,{p:p.stat().st_mtime_ns for p in (state/'randomizations').iterdir()})
            bad={k:v[:250].copy() for k,v in simulated.items()};bad['baseline__later7_num'][0]+=1
            with self.assertRaisesRegex(RuntimeError,'C9 draw reproduction failed'):
                checkpoints.compare_reference(bad,0,250,ref)
            # A full checkpoint with a wrong digest must fail; a one-sided
            # interrupted checkpoint is preserved and can be recomputed.
            with self.assertRaisesRegex(RuntimeError,'checkpoint mismatch'):
                checkpoints.authenticate(state,0,250,'wrong')
            separate=root/'interrupted';(separate/'randomizations').mkdir(parents=True)
            path,_=checkpoints.paths(separate,0,250);path.write_bytes(b'interrupted')
            preserved=checkpoints.preserve_incomplete(separate,250,250)
            self.assertEqual(len(preserved),1);self.assertFalse(path.exists())
            self.assertEqual((Path(preserved[0]['preserved_at'])/path.name).read_bytes(),b'interrupted')


if __name__=='__main__':unittest.main(verbosity=2)
