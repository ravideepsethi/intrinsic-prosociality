"""Real spawned end-to-end execution on physical synthetic Parquets, then resume.
Only the production input authority and its real-data coefficient targets are
substituted. Producers, cache joins, count scan, models and report are real.
"""
from test_environment import *
del ModelTests,RateTests,OperationalTests

class PipelineTests(unittest.TestCase):
    def test_complete_runner_and_checkpoint_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);project=p/'project';project.mkdir();parent=project/'parent';entry=project/'entry';shared=project/CACHE_REL
            ids=[999991,999992];conf='fixture-parent';entryconf='fixture-entry';idxconf='fixture-index';refconf='fixture-reference';hc='fixture-history';mc='fixture-main'
            rng=np.random.default_rng(196);d=model_data(9000);n=len(d['row_id'])
            for key in ENV_NAMES+['environment_supported','games','own','chooser']:d.pop(key)
            d['row_id']=np.arange(n,dtype=np.int64);d['anchor_ms']=d['archive_start_ms']+1000
            # Match the already frozen q95 numerically for the source-binding test.
            cutoff=io.load(ENTRY/'evidence/secondary_scale.json')['upper_5pct_raw_competitive_cutoff']
            new=np.arange(n)<int(n*2/3);first=np.arange(n)<int(n*.27)
            d['comp_adjusted_7d']+=cutoff-np.quantile(d['comp_adjusted_7d'][new],.95)
            d['previous_frame']=~new
            d['status'][~new]=None
            masks=dict(new_phase25=new,new_phase10=first,increment_10_25=new&~first,old_author_clean=~new,pooled=np.ones(n,bool))
            def splitbuild(tmp):
                for cohort,use in masks.items():io.table(tmp/('entry_'+cohort+'.parquet'),pa.table(selected(d,use)))
            io.stage(parent/'split',conf,splitbuild)
            def smallbuild(tmp):
                for cohort,use in masks.items():io.table(tmp/(cohort+'.parquet'),pa.table({k:d[k][use] for k in MODEL_COLUMNS+COMP_COLUMNS}))
            io.stage(entry/'prepared',entryconf,smallbuild)
            def ordinarybuild(tmp):
                io.table(tmp/'new_phase25.parquet',pa.table(selected(d,new)));io.js(tmp/'scale.json',{})
            io.stage(parent/'secondary_prepared',conf,ordinarybuild)
            # Full-state historical chooser events plus future choices, with one author event.
            people=np.arange(1000,1600);j=np.repeat(people,18);nh=len(j);cut=int(STARTS[6])-7*DAY
            h=dict(j=j,i=rng.integers(9000,9200,nh),t=cut-rng.integers(DAY,70*DAY,nh),cell=np.resize(np.array([100,300,400]),nh),
                y=rng.random(nh)<.17,arm=np.ones(nh,bool),fair=np.ones(nh,bool))
            # Some modeled opponents also appear as the disconnected player.
            hh=dict(j=np.arange(2000,2200),i=rng.choice(people,200),t=np.full(200,cut-20*DAY),cell=np.full(200,300),y=rng.random(200)<.2,arm=np.ones(200,bool),fair=np.ones(200,bool))
            h={k:np.r_[v,hh[k]] for k,v in h.items()};histn=len(h['j'])
            future_j=np.r_[np.arange(1,900),1];nf=len(future_j)
            fy=rng.random(nf)<.1;future_i=np.full(nf,4000);future_i[0]=ids[0];fy[0]=True;fy[-1]=False
            future_t=np.full(nf,int(STARTS[6])+60*DAY);future_t[-1]+=100
            histgid=np.array([f'H{k:07}' for k in range(histn)]);futuregid=np.array([f'F{k:07}' for k in range(nf)])
            main=dict(game_id=np.r_[histgid,futuregid],utc_ms=np.r_[h['t']-100,future_t-10],api_last_move_at_ms=np.r_[h['t'],future_t],
                chooser_user_id=np.r_[h['j'],future_j],disconnected_user_id=np.r_[h['i'],future_i],archive_ordinal=np.arange(histn+nf),
                kind_draw=np.r_[h['y'],fy],fair_competitive=np.ones(histn+nf,bool),timeout_chooser_win=~np.r_[h['y'],fy],tournament_like_event=np.zeros(histn+nf,bool))
            mainpath=p/'main.parquet';io.table(mainpath,pa.table(main))
            future_root=shared/'main_index'/mc/'00';fast.main_index_job(dict(panel=str(mainpath),memory=.5,conf=mc,output=str(future_root)))
            historypath=p/'history.parquet';io.table(historypath,pa.table(h))
            historyroot=shared/'history_index'/hc/'2024-01';fast.history_index_job(dict(parts=[str(historypath)],authors=ids,memory=.5,conf=hc,output=str(historyroot)))
            ref=shared/'reference'/refconf/'models'
            def refbuild(tmp):
                for key in ('clean','original'):np.save(tmp/(key+'.npy'),np.full((2,24,4,4,500),.1))
            io.stage(ref,refconf,refbuild)
            iv=selected(d,new);iv['row_id']=np.arange(len(iv['row_id']))+100000;iv['previous_frame']=np.ones(len(iv['row_id']),bool)
            for s in range(16):
                sh=num.user_hash(h['j'])%np.uint64(16)==s;part=p/f'h{s}.parquet';io.table(part,pa.table(selected(h,sh)))
                idxpath=shared/'score_index'/idxconf/f'{s:02}';fast.score_index_job(dict(parts=[str(part)],output=str(idxpath),conf=idxconf,memory=.5))
                idx=fast.ScoreIndex(idxpath);use=num.user_hash(iv['opponent_id'])%np.uint64(16)==s
                sc=idx.score(iv['opponent_id'][use],iv['recipient_id'][use],6,np.full((4,4,500),.1),[])
                for k,v in sc.items():iv[k][use]=v
            for key in COUNT_COLUMNS:iv[key]=np.zeros(len(iv['row_id']),np.int64)
            fh=dict(j=future_j,i=future_i,t=future_t,start=future_t-10,ord=np.arange(nf),gid=futuregid,y=fy)
            order=np.lexsort((fh['gid'],fh['ord'],fh['t'],fh['j']));fh=selected(fh,order)
            original_out=fast.sorted_later_outcomes(fh,iv)
            for key in ('y','reached'):iv[key]=original_out[key]
            src=p/'spaced.parquet';io.table(src,pa.table(iv))
            extra_n=10000;extra=dict(game_id=np.array([f'G{k:07}' for k in range(extra_n)]),utc_ms=cut-rng.integers(DAY,85*DAY,extra_n),white_id=rng.choice(people,extra_n),black_id=rng.integers(5000,6000,extra_n))
            chron=dict(game_id=np.r_[main['game_id'],extra['game_id']],utc_ms=np.r_[main['utc_ms'],extra['utc_ms']],white_id=np.r_[main['chooser_user_id'],extra['white_id']],black_id=np.r_[main['disconnected_user_id'],extra['black_id']])
            cp=p/'chron.parquet';io.table(cp,pa.table(chron))
            binding=dict(entry=str(entry),parent=str(parent),entry_config=entryconf,parent_config_sha256=conf,
                author_ids=ids,index_conf=idxconf,reference_conf=refconf,histories=[str(historyroot)],futures=[str(future_root)],history_conf=hc,main_conf=mc,
                source=dict(spaced=str(src),panels=[dict(path=str(mainpath),sha256=io.sha(mainpath),bytes=mainpath.stat().st_size)],chron=[dict(path=str(cp),signature=io.sig(cp),rows=len(chron['game_id']),file_index=0)]))
            # Reproduce the actual legacy null -> DuckDB integer -> NumPy NaN path
            # in a completed v1.0.0 preparation and adopt it without changing bytes.
            oldconfig=runner.env_recovery.previous_config(binding);oldconf=io.cfgsha(oldconfig)
            oldroot=project/OUTPUT_REL/oldconf[:12];oldroot.mkdir(parents=True)
            io.js(oldroot/'config.json',oldconfig)
            oldprepared,_=prepare.entry_prepare(binding,oldroot/'prepared_entry',oldconf,4)
            legacy=arrays(io.read(oldprepared/'old_author_clean.parquet'))
            self.assertTrue(np.isnan(legacy['status']).all())
            oldreceipt=io.sha(oldprepared/'_DONE.json')
            oldparquet=io.sha(oldprepared/'pooled.parquet')
            a=SimpleNamespace(project_root=project,desktop=p/'desktop',workers=2,memory_gb=5,parent=None,entry_parent=None,quick_only=False)
            original_map=runner.model_map
            def synthetic_map(jobs,*args,**kwargs):return original_map([dict(j,reproduce=False) for j in jobs],*args,**kwargs)
            with mock.patch.object(runner,'bind',return_value=binding),mock.patch.object(runner,'model_map',side_effect=synthetic_map),mock.patch.object(runner,'no_network'):
                out=runner.execute(a)
                summary=io.load(out/'report/summary.json');self.assertEqual(summary['status'],'ENVIRONMENT_DIAGNOSTICS_COMPLETE')
                self.assertTrue(io.load(out/'recovery.json')['adopted'])
                self.assertEqual(io.sha(out/'prepared_entry/pooled.parquet'),oldparquet)
                self.assertEqual(io.sha(oldprepared/'_DONE.json'),oldreceipt)
                status=io.load(out/'report/status_coverage.json')
                sr=next(x for x in status if x['cohort']=='old_author_clean')
                self.assertGreater(sr['missing_as_numeric_NaN'],0);self.assertTrue(sr['valid'])
                self.assertFalse(sr['ending_regressions_available'])
                result=io.load(out/'models/quick_old_author_clean/result.json')
                self.assertFalse(any(x.get('outcome','').startswith('ending_') for x in result['estimates']))
                self.assertTrue(summary['receipt_IV_reestimated']);self.assertTrue(summary['environment_controls_completed'])
                clean=arrays(io.read(out/'iv_assembled/receipt_iv.parquet'))
                self.assertFalse(np.isin(clean['outcome_opponent'],ids).any())
                self.assertTrue(io.load(out/'iv_assembled/reproduction.json')['original_histories_and_outcomes_reproduced'])
                models_sha=io.sha(out/'models/environment_receipt_original_author_clean/result.json')
                chron_done=io.sha(out/'rate_chron_parts/0000/_DONE.json')
                runner.execute(a)
                self.assertEqual(models_sha,io.sha(out/'models/environment_receipt_original_author_clean/result.json'))
                self.assertEqual(chron_done,io.sha(out/'rate_chron_parts/0000/_DONE.json'))
                self.assertGreater(sum(r.get('reused_checkpoints',0) for r in io.load(out/'performance.json')),0)

if __name__=='__main__':unittest.main()
