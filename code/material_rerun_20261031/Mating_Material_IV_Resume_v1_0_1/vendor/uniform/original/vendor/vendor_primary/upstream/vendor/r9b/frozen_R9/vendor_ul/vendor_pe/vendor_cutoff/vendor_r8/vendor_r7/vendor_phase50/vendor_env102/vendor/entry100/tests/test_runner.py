"""Exercise the real cached orchestration and spawned work, then resume it."""
from test_entry import *
del ScientificTests,OperationalTests

class RunnerTests(unittest.TestCase):
    def test_complete_entry_run_uses_only_finished_parquets_and_indexes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);project=root/'project';parent=project/'parent';split=parent/'split'
            shared=project/CACHE_REL;indexconf='synthetic-index';refconf='synthetic-reference';rng=np.random.default_rng(191)
            d=data(9000);ids=[999991,999992]
            opp=np.unique(d['opponent_id']);nh=len(opp)*18
            h=dict(j=np.repeat(opp,18),i=rng.integers(1,900,nh),t=np.full(nh,STARTS[6]-7*DAY-1),
                cell=np.resize(np.array([100,300,400]),nh),y=rng.random(nh)<.12,arm=np.ones(nh,bool))
            refroot=shared/'reference'/refconf/'models'
            io.stage(refroot,refconf,lambda p:np.save(p/'clean.npy',np.full((2,24,4,4,500),.05)))
            model=np.full((4,4,500),.05);indexjobs=[]
            for s in range(16):
                mask=num.user_hash(h['j'])%np.uint64(16)==s
                path=root/f'h{s:02}.parquet';io.table(path,pa.table({k:v[mask] for k,v in h.items()}))
                job=dict(parts=[str(path)],output=str(shared/'score_index'/indexconf/f'{s:02}'),conf=indexconf,memory=.5)
                fast.score_index_job(job);indexjobs.append(job)
                use=num.user_hash(d['opponent_id'])%np.uint64(16)==s
                idx=fast.ScoreIndex(job['output']);scores=idx.score(d['opponent_id'][use],d['recipient_id'][use],6,model,ids)
                for k,v in scores.items():d[k][use]=v
            # The existing entry table is the only source of labels/controls.
            masks=dict(new_phase25=np.arange(9000)<6000,new_phase10=np.arange(9000)<2400,
                increment_10_25=(np.arange(9000)>=2400)&(np.arange(9000)<6000),
                old_author_clean=np.arange(9000)>=6000,pooled=np.ones(9000,bool))
            targets=[]
            for cohort,mask in masks.items():
                sample={k:v[mask] for k,v in d.items() if not k.startswith('comp_')}
                io.table(split/('entry_'+cohort+'.parquet'),pa.table(sample));targets+=expected(sample,cohort)
            target=root/'expected.json';io.js(target,targets)
            definition=dict(kind='test_pooled',source=dict(index=indexconf,reference=refconf,authors=ids))
            compdef=feature_cache.definition('competitive_history_author_clean_v1',dict(pooled_definition=definition,cp_cutoff=-100,minimum_decisions=5),[Path(secondary.__file__)])
            binding=dict(parent=str(parent),parent_config_sha256='synthetic-parent',entry_files=[],score_definition=definition,
                competitive_definition=compdef,index_conf=indexconf,reference_conf=refconf,author_ids=ids,quarantine=dict(quarantined_rows=2))
            # Prepopulate the genuine upstream competitive cache for a subset.
            s=0;use=(num.user_hash(d['opponent_id'])%np.uint64(16)==s)&(np.arange(9000)<1000)
            seedq=root/'seed.parquet';io.table(seedq,pa.table({k:d[k][use] for k in list(dict.fromkeys(['row_id']+feature_cache.BEHAVIOR_KEYS+SCORE_COLS))}))
            j=dict(queries=str(seedq),index=indexjobs[s]['output'],index_conf=indexconf,reference=str(refroot),authors=ids,memory=.5,conf='seed',output=str(root/'seed_scores'))
            score_job(feature_cache.attach(j,shared,'competitive_scores',compdef,s))
            args=SimpleNamespace(project_root=project,desktop=root/'desktop',parent=None,workers=2,memory_gb=5)
            original_map=runner.model_map
            def mapped(jobs,*args,**kwargs):
                return original_map([dict(j,expected=str(target)) for j in jobs],*args,**kwargs)
            with mock.patch.object(runner,'authenticate',return_value=binding),mock.patch.object(runner,'model_map',side_effect=mapped),mock.patch.object(runner,'no_network'):
                out=runner.execute(args)
                summary=io.load(out/'report/summary.json')
                self.assertEqual(summary['status'],'ENTRY_DIAGNOSTICS_COMPLETE')
                self.assertEqual(summary['reproduced_original_entry_estimates'],25)
                self.assertFalse(summary['receipt_IV_reestimated']);self.assertEqual(summary['chronology_scans'],0)
                self.assertGreater(io.load(out/'scores/00/_DONE.json')['cache_hits'],0)
                saved=io.sha(out/'models/new_phase25_competitive_supported/result.json')
                # Delete all synthetic raw events: rerun must rely on completed indexes.
                for p in root.glob('h*.parquet'):p.unlink()
                runner.execute(args)
                self.assertEqual(saved,io.sha(out/'models/new_phase25_competitive_supported/result.json'))
                self.assertEqual(len(list((out/'models').glob('*/_DONE.json'))),10)

if __name__=='__main__':unittest.main()
