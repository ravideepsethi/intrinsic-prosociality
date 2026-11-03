import sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import performance_cache as cache
import performance_histories as fast
import performance_screen as screen
import performance_chronology as chron
import performance_migration as migration
import phase_chronology as original
import cached_histories as slow
import test_cached as fixture
from performance_runtime import Runtime

put=fixture.put;T=fixture.T;CONF='synthetic-performance';IDS=[99,100]

def cached(job,root,kind='test',part=0,definition=None):
    return cache.attach(job,root/'cache',kind,definition or {'kind':kind,'scientific_sources':'test'},part)

def history(seed=105,n=12000):
    rng=np.random.default_rng(seed)
    # Include exact cutoffs, repeated pairs, unsupported cells and author rows.
    t=rng.choice(np.asarray(STARTS)-7*DAY,n)+rng.choice([-1,0,1],n)
    return dict(j=rng.integers(1,120,n),i=rng.integers(200,260,n),t=t,
        y=rng.random(n)<.2,arm=rng.random(n)<.8,fair=rng.random(n)<.7,cell=rng.integers(0,500,n))

class PerformanceTests(unittest.TestCase):
    def test_monthly_index_matches_original_all_cutoffs_pairs_and_missing_folds(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);h=history();hp=put(root,'h.parquet',h)
            fast.score_index_job(dict(parts=[hp],memory=.4,conf=CONF,output=str(root/'index')))
            index=fast.ScoreIndex(root/'index');rng=np.random.default_rng(45)
            j=np.r_[np.arange(1,125),999];i=rng.integers(200,265,len(j))
            for m in range(24):
                model=rng.random((4,4,500));model[2,1,17]=np.nan
                for ids in ([],IDS):
                    keep=h['arm']&~authors.author_mask(h['j'],h['i'],ids)
                    ref=num.score_month(h['j'][keep],h['i'][keep],h['t'][keep],h['y'][keep],h['cell'][keep],j,i,int(STARTS[m])-7*DAY,model)
                    actual=index.score(j,i,m,model,ids)
                    for short in ('n','counterparts','expected','adjusted'):
                        np.testing.assert_allclose(actual[short+'_7d'],ref[short],rtol=1e-10,atol=2e-11,equal_nan=True,err_msg=f'{m}/{ids}/{short}')

    def test_cached_scores_rebind_row_ids_and_compute_only_new_keys(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);h=history();hp=put(root,'h.parquet',h)
            fast.score_index_job(dict(parts=[hp],memory=.4,conf=CONF,output=str(root/'index')))
            q=fixture.queries(5);q['previous_frame'][:2]=True
            refdir=root/'reference';refdir.mkdir()
            np.save(refdir/'original.npy',np.full((2,24,4,4,500),.25));np.save(refdir/'clean.npy',np.full((2,24,4,4,500),.2))
            keep=h['arm']&~authors.author_mask(h['j'],h['i'],IDS)
            q['expected_n7']=num.score_month(h['j'][keep],h['i'][keep],h['t'][keep],h['y'][keep],h['cell'][keep],q['opponent_id'],q['recipient_id'],int(STARTS[6])-7*DAY,np.full((4,4,500),.2))['n']
            p=put(root,'q.parquet',{k:v[:4] for k,v in q.items()})
            job=cached(dict(queries=p,index=str(root/'index'),reference=str(refdir),authors=IDS,memory=.4,conf=CONF,output=str(root/'first')),root,'scores')
            r=fast.score_job(job);self.assertEqual(r['computed_rows'],4)
            old=io.read(root/'first/scores.parquet');self.assertEqual(old['original_n_7d'].null_count,2)
            q['row_id']=q['row_id']+5000;p2=put(root,'q2.parquet',q)
            job2=dict(job,queries=p2,output=str(root/'second'))
            real=fast.ScoreIndex.score;calls=[]
            def score(obj,qj,qi,*args):calls.append(len(qj));return real(obj,qj,qi,*args)
            with mock.patch.object(fast.ScoreIndex,'score',score):r=fast.score_job(job2)
            self.assertEqual(r['cache_hits'],4);self.assertEqual(r['computed_rows'],1);self.assertEqual(calls,[1])
            data=arrays(io.read(root/'second/scores.parquet'));np.testing.assert_array_equal(data['row_id'],q['row_id'])
            np.testing.assert_allclose(data['adjusted_7d'][:4],io.arr(old,'adjusted_7d'),equal_nan=True)
            block=next(Path(job['cache']).glob('blocks/*/records.parquet'));block.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):fast.score_job(dict(job2,output=str(root/'third')))

    def test_future_and_history_indexes_match_original_and_reuse_new_phase(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(5);q['previous_frame'][:2]=True
            qp=put(root,'q.parquet',q)
            rows=[]
            for k,person in enumerate(q['recipient_id']):
                for d in (98,97,96,38,37,36,8,7,6):
                    rows.append(dict(j=int(person),i=99 if d==38 else 501,t=T-d*DAY,y=d%2==0,fair=True,arm=True,cell=0))
                    rows.append(dict(j=502,i=int(person),t=T-d*DAY,y=d%3==0,fair=False,arm=d%2==0,cell=0))
            hp=put(root,'hist.parquet',pa.Table.from_pylist(rows))
            fast.history_index_job(dict(parts=[hp],authors=IDS,memory=.4,conf=CONF,output=str(root/'hi')))
            slow.history_month_job(dict(queries=qp,parts=[hp],authors=IDS,memory=.4,month=MONTHS[6],conf=CONF,output=str(root/'slowhi')))
            events=[]
            for k,person in enumerate(q['recipient_id']):
                for d in (1,2,91):events.append(dict(game_id=f'F{k:03d}{d:04d}',chooser_user_id=int(person),disconnected_user_id=99 if d==1 else 501,utc_ms=T+d*DAY,api_last_move_at_ms=T+d*DAY+20,archive_ordinal=d,kind_draw=d==1,fair_competitive=True,tournament_like_event=False,timeout_chooser_win=d!=1))
            main=put(root,'main.parquet',pa.Table.from_pylist(events))
            fast.main_index_job(dict(panel=main,memory=.4,conf=CONF,output=str(root/'mi')))
            slow.future_month_job(dict(queries=qp,panel=main,memory=.4,conf=CONF,output=str(root/'slowfi')))
            # Combine physical shards to test vectorized calculations across people.
            oj=dict(queries=qp,authors=IDS,memory=.4,conf=CONF,
                histories=[str(root/'hi'/f'{s:02}.parquet') for s in range(16)],futures=[str(root/'mi'/f'{s:02}.parquet') for s in range(16)],output=str(root/'fast'))
            oj=cached(oj,root,'outcomes');fast.outcome_job(oj)
            parts=[]
            for s in range(16):
                out=root/'slow'/str(s);slow.outcomes_job(dict(queries=qp,shard=s,authors=IDS,conf=CONF,
                    original_histories=[str(root/'slowhi'/f'original_{s:02}.parquet')],clean_histories=[str(root/'slowhi'/f'clean_{s:02}.parquet')],
                    futures=[str(root/'slowfi'/f'{s:02}.parquet')],output=str(out)))
                parts.append(io.read(out/'outcomes.parquet'))
            ref=arrays(pa.concat_tables(parts));order=np.argsort(ref['row_id']);ref={k:v[order] for k,v in ref.items()}
            got=arrays(io.read(root/'fast/outcomes.parquet'))
            for name in ref:
                mask=q['previous_frame'] if name.startswith('original_') else np.ones(5,bool)
                np.testing.assert_array_equal(got[name][mask],ref[name][mask],err_msg=name)
            self.assertEqual(io.read(root/'fast/outcomes.parquet')['original_y'].null_count,3)
            q['row_id']+=100;qp2=put(root,'q2.parquet',q)
            with mock.patch('performance_histories.sorted_later_outcomes',side_effect=AssertionError('must reuse cached outcomes')):
                info=fast.outcome_job(dict(oj,queries=qp2,output=str(root/'second')))
            self.assertEqual(info['cache_hits'],5)
            # A real old output has a different column order. Adoption followed
            # by computing new rows must use names, never positional unions.
            def old_build(tmp):io.table(tmp/'outcomes.parquet',pa.table(ref))
            io.stage(root/'legacy',CONF,old_build)
            q['row_id']-=100
            subset=put(root,'subset.parquet',{k:v[:4] for k,v in q.items()})
            ij=cached(dict(queries=subset,legacy_feature=str(root/'legacy/outcomes.parquet'),legacy_conf=CONF,
                filename='outcomes.parquet',memory=.4,conf=CONF,output=str(root/'imported')),root,'adopted_outcomes')
            migration.import_job(ij)
            mixed=dict(oj,queries=qp,output=str(root/'mixed'),cache=ij['cache'],cache_conf=ij['cache_conf'],cache_definition=ij['cache_definition'])
            report=fast.outcome_job(mixed);self.assertEqual(report['cache_hits'],4);self.assertEqual(report['computed_rows'],1)
            mixed=arrays(io.read(root/'mixed/outcomes.parquet'))
            for name in ref:
                mask=q['previous_frame'] if name.startswith('original_') else np.ones(5,bool)
                np.testing.assert_array_equal(mixed[name][mask],ref[name][mask],err_msg=name)

    def test_indexed_features_preserve_regression_and_clustered_standard_error(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rng=np.random.default_rng(741);q=fixture.fake_model(5000);h=history(n=30000)
            h['j']=rng.integers(1000,1600,len(h['j']));h['i']=rng.integers(1,900,len(h['i']))
            h['t']=np.full(len(h['j']),int(STARTS[6])-7*DAY-1);h['arm'][:]=True
            path=put(root,'h.parquet',h);fast.score_index_job(dict(parts=[path],memory=.4,conf=CONF,output=str(root/'index')))
            model=rng.uniform(.01,.1,(4,4,500));index=fast.ScoreIndex(root/'index')
            old=num.score_month(h['j'],h['i'],h['t'],h['y'],h['cell'],q['opponent_id'],q['recipient_id'],int(STARTS[6])-7*DAY,model)
            new=index.score(q['opponent_id'],q['recipient_id'],6,model,[])
            left=dict(q,**{k+'_7d':old[k] for k in ['n','counterparts','expected','adjusted']});right=dict(q,**new)
            a=stats.estimate(left,SPEC);b=stats.estimate(right,SPEC)
            for x,y in zip(a['estimates'],b['estimates']):
                self.assertEqual(x['row_set_sha256'],y['row_set_sha256'])
                for field in ('coefficient_pp','standard_error_pp'):self.assertAlmostEqual(x[field],y[field],places=9)

    def test_early_filter_matches_frozen_final_eligibility_without_using_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(12);q['previous_frame'][:2]=True;q['active_timeout']=np.zeros(12,bool)
            q['archive_start_ms'][2]=int(STARTS[0])+50*DAY;q['anchor_ms'][2]=q['archive_start_ms'][2]+1000
            q['recipient_id'][3]=99;q['expected_n7'][4]=4;q['tc_base_s'][5]=0
            stream=dict(recipient_id=q['recipient_id'][[6]],archive_start_ms=q['archive_start_ms'][[6]]-2*DAY,anchor_ms=q['archive_start_ms'][[6]]-DAY)
            sp=put(root,'stream.parquet',stream);qp=put(root,'q.parquet',q)
            d=dict(q,n_7d=q['expected_n7'].copy(),adjusted_7d=np.full(12,.1),expected_7d=np.full(12,.2),
                history_complete=q['archive_start_ms']-97*DAY>=int(STARTS[0]),at_risk_90=design.prospective_risk(stream,q,90)['at_risk'])
            d['eligible_main']=np.ones(12,bool);d['first_observed_pair']=np.ones(12,bool)
            d['expected_7d'][7]=np.nan;d['eligible_main'][8]=False;d['first_observed_pair'][9]=False
            expected,_=design.entry_mask(d,90);expected&=~authors.author_mask(q['recipient_id'],q['opponent_id'],IDS)
            a,ai=screen.cheap(qp,sp,IDS,root/'early',CONF,.4)
            scores=put(root,'scores.parquet',{k:d[k] for k in ['row_id']+SCORE_COLS if k in d} | {'counterparts_7d':np.full(12,6)})
            b,bi=screen.supported(a/'queries.parquet',[scores],root/'support',CONF,.4)
            use=np.isin(q['row_id'],io.arr(io.read(b/'chron_queries.parquet'),'row_id'))
            cp=put(root,'chron.parquet',dict(row_id=q['row_id'][use],eligible_main=d['eligible_main'][use],first_observed_pair=d['first_observed_pair'][use],
                previous_classification_status=np.where(d['eligible_main'][use],rebuild.NONADJ,'mutually_adjacent'),pre_games_30d=np.full(use.sum(),5)))
            out,info=screen.after_chronology(b/'queries.parquet',cp,root/'work',CONF,.4)
            got=io.arr(io.read(out/'queries.parquet'),'row_id')
            np.testing.assert_array_equal(got,q['row_id'][expected|q['previous_frame']])
            self.assertEqual(ai['total_queries'],12);self.assertEqual(ai['new_rows_skipped'],5)
            self.assertEqual(bi['new_rows_without_score_support'],1);self.assertEqual(info['new_rows_skipped_by_chronology'],2)
            labels=put(root,'entry.parquet',dict(row_id=q['row_id'],matched_main=np.arange(12)==8))
            with self.assertRaisesRegex(RuntimeError,'before eligibility filtering'):
                screen.after_chronology(b/'queries.parquet',cp,root/'bad_work',CONF,.4,labels)

    def test_bounded_sort_matches_original_on_ancient_history_and_cross_file_ties(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(6);q['archive_start_ms'][3:]+=10*DAY
            qp=put(root,'q.parquet',q);prep,_=original.prepare_chronology(qp,root/'plan',CONF,.4)
            rng=np.random.default_rng(82);rows=[]
            for k in range(3000):
                a,b=rng.choice(np.arange(5,60),2,replace=False)
                rows.append(dict(game_id=f'H{k:07d}',utc_ms=int(T-rng.choice([1,29,30,31,100,1000,2000])*DAY),white_id=int(a),black_id=int(b)))
            for k in range(6):rows.append(dict(game_id=str(q['game_id'][k]),utc_ms=int(q['archive_start_ms'][k]),white_id=int(q['recipient_id'][k]),black_id=int(q['opponent_id'][k])))
            oldparts=[];newparts=[];sortedn=unsortedn=0
            for s in range(3):
                path=put(root,f'events{s}.parquet',pa.Table.from_pylist(rows[s::3]))
                job=dict(path=path,signature=io.sig(path),people=str(prep/'people.parquet'),pairs=str(prep/'pairs.parquet'),focal=str(prep/'focal.parquet'),roles=str(prep/'roles.parquet'),latest=T+10*DAY,rows=len(rows[s::3]),file_index=s,memory=.4,conf=CONF)
                original.chronology_job(dict(job,output=str(root/'old'/str(s))))
                r=chron.chronology_job(dict(job,output=str(root/'new'/str(s))));sortedn+=r['retained_person_moments'];unsortedn+=r['unsorted_person_events']
                oldparts.append(root/'old'/str(s));newparts.append(root/'new'/str(s))
            a,_=original.merge_chronology(qp,prep,oldparts,root/'oldmerged',CONF,.5,2)
            b,_=original.merge_chronology(qp,prep,newparts,root/'newmerged',CONF,.5,2)
            aa=arrays(io.read(a/'features.parquet'));bb=arrays(io.read(b/'features.parquet'))
            for k in aa:np.testing.assert_array_equal(aa[k][np.argsort(aa['row_id'])],bb[k][np.argsort(bb['row_id'])],err_msg=k)
            self.assertLess(sortedn,unsortedn)
            # A completed old file part must be remapped, with no new raw scan.
            subset={k:v[[1,4]] for k,v in q.items()};subset['row_id']+=123
            sub=put(root,'subset.parquet',subset);sp,_=original.prepare_chronology(sub,root/'subplan',CONF,.4)
            job.update(people=str(sp/'people.parquet'),pairs=str(sp/'pairs.parquet'),focal=str(sp/'focal.parquet'),roles=str(sp/'roles.parquet'),
                legacy_part=str(oldparts[2]),legacy_conf=CONF,legacy_queries=qp,output=str(root/'adopted'))
            reused=chron.chronology_job(job);self.assertTrue(reused['adopted_v102'])
            self.assertTrue(set(io.arr(io.read(root/'adopted/candidates.parquet'),'sample_row'))<=set(subset['row_id']))

    def test_chronology_feature_cache_and_spawned_scheduler(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(2);qp=put(root,'q.parquet',q);rows=[]
            for k in range(2):
                rows.extend([dict(game_id=str(q['game_id'][k]),utc_ms=T,white_id=int(q['recipient_id'][k]),black_id=int(q['opponent_id'][k])),
                    dict(game_id=f'A{k:07d}',utc_ms=T-DAY,white_id=int(q['recipient_id'][k]),black_id=501),dict(game_id=f'B{k:07d}',utc_ms=T-2*DAY,white_id=int(q['opponent_id'][k]),black_id=502)])
            path=put(root,'events.parquet',pa.Table.from_pylist(rows));source=[dict(path=path,signature=io.sig(path),rows=len(rows),file_index=0,minimum=T-2*DAY)]
            runtime=Runtime(root)
            job=cached(dict(queries=qp,memory=.5,worker_memory=.3,conf=CONF,output=str(root/'chron'),parts_root=str(root/'parts')),root,'chronology')
            r=chron.run(job,source,2,runtime);self.assertEqual(r['computed_rows'],2)
            q['row_id']+=100;qp2=put(root,'q2.parquet',q)
            with mock.patch.object(runtime,'mapped',side_effect=AssertionError('no repeat archive scan')):
                r=chron.run(dict(job,queries=qp2,output=str(root/'again')),source,2,runtime)
            self.assertEqual(r['cache_hits'],2);self.assertEqual(r['computed_rows'],0)
            self.assertTrue((root/'performance.json').is_file())

if __name__=='__main__':unittest.main()
