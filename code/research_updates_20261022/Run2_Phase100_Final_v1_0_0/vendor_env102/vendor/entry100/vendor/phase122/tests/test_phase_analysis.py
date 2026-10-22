import sys,tempfile,unittest,json,time
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from cached_common import *
import phase_features as pf
import phase_inputs as pi
import phase_reporting as pr
import run_phase_analysis as runner
import cached_histories as histories
import phase_chronology as chron
import test_cached as fixture

T=fixture.T;CONF='synthetic-phase10-v1';put=fixture.put

def entry_model(n=5000):
    d=fixture.fake_model(n);rng=np.random.default_rng(343)
    d['ordinary_narrow']=np.arange(n)%3!=0
    for k in pf.ENTRY_COLUMNS:d[k]=rng.random(n)<.05
    d['active_timeout']=~d['ordinary_narrow']
    return d

class PhaseTests(unittest.TestCase):
    def test_both_original_regressions_reproduced_and_tamper_stops(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=entry_model();path=put(root,'baseline.parquet',d)
            expected=[]
            for fam,spec in pf.SPECS.items():
                m=d['ordinary_narrow'] if fam=='ordinary' else np.ones(5000,bool)
                expected += stats.estimate({k:v[m] for k,v in d.items()},spec)['estimates']
            with mock.patch('phase_features.io.load',return_value=expected):
                data,fit=pf.verify_original(path);self.assertEqual(len(data['row_id']),5000)
                self.assertEqual(set(fit),{'entry','ordinary'})
            bad=[dict(r,standard_error_pp=r['standard_error_pp']+.1) if r['family']=='entry' else r for r in expected]
            with mock.patch('phase_features.io.load',return_value=bad),self.assertRaisesRegex(RuntimeError,'entry numerical bridge'):
                pf.verify_original(path)

    def test_hash_membership_cache_and_api_readiness_all_endings(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);n=7;q=fixture.queries(n)
            rows=[];meta=[]
            for k in range(n):
                rows.append(dict(game_id=str(q['game_id'][k]),utc_ms=T,speed_partition='blitz',
                    retrieval_rank=(threshold(10) if k==6 else bytes(32)),previous_frame=k==5,
                    local_eligibility='EXCLUDED' if k==4 else 'POTENTIALLY_ELIGIBLE',
                    recipient_color='black' if k==0 else 'white',recipient_id=int(q['recipient_id'][k]),opponent_id=int(q['opponent_id'][k]),n7_author_clean=6))
                meta.append(dict(game_id=str(q['game_id'][k]),source='pool' if k!=3 else 'lobby',status='timeout' if k==1 else 'resign',
                    api_start_ms=T,anchor_ms=T+1000,rated=True,variant='standard',speed='blitz',tc_base_s=180,tc_inc_s=0,
                    white_username='w',black_username='b',white_rating=1400.,black_rating=1500.,winner='white',cached_conflict_or_prior_flag=False))
            # Selected unresolved record stays counted; it does not become an exclusion or zero outcome.
            meta[2]['anchor_ms']=None
            lp=put(root,'ledger.parquet',pa.Table.from_pylist(rows));mp=put(root,'metadata.parquet',pa.Table.from_pylist(meta))
            j=dict(ledger=lp,metadata=[mp],month=MONTHS[6],memory=.4,output=str(root/'coverage'),conf=CONF)
            info=pi.coverage_job(j)
            self.assertEqual(info['selected_frame_rows'],5);self.assertEqual(info['pool_rows'],2)
            self.assertEqual(info['ordinary_rows'],1);self.assertEqual(info['unresolved_rows'],1)
            self.assertEqual(info['dispositions']['LOCAL_RULE_EXCLUSION'],1)
            d=arrays(io.read(root/'coverage/pool.parquet'))
            self.assertEqual(d['recipient_rating'][0],1500.);self.assertEqual(d['recipient_username'][0],'b')
            self.assertEqual(d['status'].tolist(),['resign','timeout'])

    def test_entry_labels_keep_random_role_and_full_stream_selection(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(3);q['ordinary_narrow'][:]=False;q['status']=np.full(3,'timeout')
            qp=put(root,'queries.parquet',q)
            main=[dict(game_id=str(q['game_id'][k]),chooser_user_id=int(q['opponent_id'][k]) if k!=1 else int(q['recipient_id'][k]),
                disconnected_user_id=int(q['recipient_id'][k]) if k!=1 else int(q['opponent_id'][k]),api_last_move_at_ms=T+1000,utc_ms=T,
                archive_ordinal=k,kind_draw=k==0,fair_competitive=k!=2,timeout_chooser_win=k!=0,tournament_like_event=k==2) for k in range(3)]
            pp=put(root,'main.parquet',pa.Table.from_pylist(main))
            job=dict(queries=qp,panel=pp,memory=.4,output=str(root/'future'),conf=CONF)
            pi.future_and_roles_job(job)
            ap=put(root,'audit.parquet',dict(game_id=q['game_id'],recipient_id=q['recipient_id'],spaced90=[True,False,False],history_window_complete=[True]*3,complete90=[True]*3))
            out,_=pi.entry_labels(qp,[str(root/'future/roles.parquet')],ap,root/'labels',CONF,.4)
            d=arrays(io.read(out/'entry.parquet'))
            self.assertEqual(d['recipient_disconnect_main'].tolist(),[True,False,True])
            self.assertEqual(d['recipient_fair_arm_main'].tolist(),[True,False,False])
            self.assertEqual(d['analysis_entry_90'].tolist(),[True,False,False])
            # Ordinary ending/main-panel contradiction must block, not be dropped.
            q['ordinary_narrow'][0]=True;qp2=put(root,'bad.parquet',q)
            with self.assertRaisesRegex(RuntimeError,'Ordinary focal'):pi.future_and_roles_job(dict(job,queries=qp2,output=str(root/'bad')))

    def test_precision_reports_benchmark_and_equivalence_separately(self):
        def result(b,s):return pr.precision_fields(dict(supported=True,coefficient_pp=b,standard_error_pp=s,ci_low_pp=b-1.96*s,ci_high_pp=b+1.96*s))
        broad=result(0,.02);self.assertTrue(broad['ci95_includes_direct_effect_benchmark']);self.assertFalse(broad['nominal_equivalence_90CI_inside_margin'])
        narrow=result(0,.005);self.assertTrue(narrow['nominal_equivalence_90CI_inside_margin']);self.assertLess(narrow['nominal_TOST_p'],.05)
        shifted=result(.025,.005);self.assertFalse(shifted['nominal_equivalence_90CI_inside_margin']);self.assertTrue(shifted['ci95_includes_direct_effect_benchmark'])
        self.assertFalse(narrow['abstract_gate_cleared']);self.assertEqual(pr.precision_fields(dict(supported=False)),{})

    def test_entry_calendar_does_not_condition_on_ending_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);base=entry_model(3)
            base.update(outcome_gid=np.full(3,''),outcome_t=np.full(3,-1,np.int64),outcome_start=np.full(3,-1,np.int64),outcome_opponent=np.full(3,-1,np.int64))
            new=fixture.queries(2);new['game_id']=np.array(['N0000000','N0000001'])
            new['anchor_ms'][0]=core.PANEL_END-89*DAY
            new['archive_start_ms'][1]=core.PANEL_END-90*DAY
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            bp=put(root,'base.parquet',base);npth=put(root,'pool.parquet',{k:new[k] for k in cols})
            with mock.patch('phase_features.verify_original',return_value=(base,{})):
                out,info=pf.prepare_queries([npth],bp,root/'prepared',CONF,.4)
            self.assertEqual(info['new_calendar_supported_queries'],1)
            q=arrays(io.read(out/'new_queries.parquet'));self.assertEqual(q['game_id'].tolist(),['N0000000'])
            self.assertGreater(q['anchor_ms'][0]+90*DAY,core.PANEL_END)

    def test_reports_use_measured_se_and_fixed_two_test_multiplicity(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);desktop=root/'desktop';desktop.mkdir();d=entry_model()
            for fam,spec in pf.SPECS.items():
                use=d['ordinary_narrow'] if fam=='ordinary' else np.ones(len(d['row_id']),bool)
                path=put(root,fam+'.parquet',{k:v[use] for k,v in d.items()})
                pr.model_job(dict(sample=path,family=fam,cohort='new_phase10',output=str(root/'models'/(fam+'_new_phase10')),conf=CONF))
            cov=[dict(month=MONTHS[6],selected_frame_rows=10000,pool_rows=5000,ordinary_rows=3333,unresolved_rows=0,ending_counts=[],dispositions=dict(CACHED_POOL_METADATA=5000,LOCAL_RULE_EXCLUSION=5000))]
            summary=pr.export(root,desktop,CONF,cov,'TEST_ONLY',time.monotonic())
            y=next(r for r in summary['estimates'] if r.get('outcome')=='y')
            self.assertEqual(y['multiplicity_family_size'],2);self.assertIn('measured_to_projected_SE_ratio',y)
            self.assertFalse(summary['abstract_gate_cleared']);self.assertFalse(summary['cache_selected_sample'])
            self.assertEqual(len(list(desktop.glob('*.zip'))),1)

    def test_compact_chronology_matches_original_with_cross_file_ties(self):
        import cached_chronology as original
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(5);qp=put(root,'q.parquet',q)
            cp,_=chron.prepare_chronology(qp,root/'plan',CONF,.4)
            rng=np.random.default_rng(89);rows=[]
            for k in range(200):
                a,b=rng.choice(np.arange(5,40),2,replace=False)
                rows.append(dict(game_id=f'H{k:07d}',utc_ms=int(T-rng.choice([1,1,2,29,30,31,100])*DAY),white_id=int(a),black_id=int(b)))
            for k in range(5):rows.append(dict(game_id=str(q['game_id'][k]),utc_ms=T,white_id=int(q['recipient_id'][k]),black_id=int(q['opponent_id'][k])))
            rows.append(dict(game_id='Tie00000',utc_ms=T,white_id=10,black_id=99))
            oldparts=[];newparts=[]
            for part in range(3):
                path=put(root,f'input{part}.parquet',pa.Table.from_pylist(rows[part::3]));job=dict(path=path,signature=io.sig(path),people=str(cp/'people.parquet'),pairs=str(cp/'pairs.parquet'),focal=str(cp/'focal.parquet'),roles=str(cp/'roles.parquet'),latest=T,rows=len(rows[part::3]),file_index=part,memory=.4,conf=CONF)
                old=root/f'old{part}';new=root/f'new{part}'
                original.chronology_job(dict(job,output=str(old)));chron.chronology_job(dict(job,output=str(new)))
                oldparts.append(old);newparts.append(new)
            op,_=original.merge_chronology(qp,cp,oldparts,root/'oldmerged',CONF,.5,2)
            npth,_=chron.merge_chronology(qp,cp,newparts,root/'newmerged',CONF,.5,2)
            a=arrays(io.read(op/'features.parquet'));b=arrays(io.read(npth/'features.parquet'))
            ai=np.argsort(a['row_id']);bi=np.argsort(b['row_id'])
            for k in a:np.testing.assert_array_equal(a[k][ai],b[k][bi],err_msg=k)
            for k,person in enumerate(q['recipient_id']):
                expected=sum(r['utc_ms']>=T-30*DAY and r['utc_ms']<T and person in (r['white_id'],r['black_id']) for r in rows)
                self.assertEqual(b['pre_games_30d'][bi[k]],expected)

    def test_mixed_ending_pipeline_author_cleaning_and_entry_labels(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);q=fixture.queries(4);q['ordinary_narrow'][[0,2]]=False;q['status']=q['status'].astype('U12');q['status'][[0,2]]='timeout';old={k:v[2:].copy() for k,v in q.items()};old['row_id']=np.arange(2)
            old.update(eligible_main=np.ones(2,bool),first_observed_pair=np.ones(2,bool),history_complete=np.ones(2,bool),
                at_risk_90=np.ones(2,bool),ordinary_narrow=q['ordinary_narrow'][2:].copy(),complete90=np.ones(2,bool),pre_games_30d=np.ones(2,np.int64),
                n_7d=np.full(2,7),counterparts_7d=np.full(2,7),expected_7d=np.full(2,.25),adjusted_7d=np.full(2,3/7-.25),
                y=np.ones(2,bool),reached=np.ones(2,bool),outcome_gid=np.array(['FAuth000','F0000003']),
                outcome_t=np.array([T+DAY+1,T+2*DAY+2]),outcome_start=np.array([T+DAY,T+2*DAY]),outcome_opponent=np.array([99,501]))
            for col in COUNT_COLUMNS:old[col]=np.zeros(2,np.int64)
            old.update(active_timeout=~old['ordinary_narrow'],recipient_disconnect_main=np.array([True,False]),recipient_fair_arm_main=np.array([True,False]),selected_entry_90=np.array([True,False]),analysis_entry_90=np.array([True,False]))
            # Match production: normalize() drops all four later-game fields
            # and the old API labels, while its authenticated parent retains them.
            parent=put(root,'parent.parquet',old)
            normalized={k:v for k,v in old.items() if k not in pf.legacy_schema.DETAILS+['status','recipient_username','opponent_username']}
            baseline=put(root,'baseline.parquet',normalized)
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            newpath=put(root,'new.parquet',{k:q[k][:2] for k in cols})
            with mock.patch('phase_features.verify_original',return_value=(normalized,{})):
                prepared,_=pf.prepare_queries([newpath],baseline,root/'prepared',CONF,.4,legacy_outcomes=parent)
            qp=str(prepared/'queries.parquet');cut=int(STARTS[6])-7*DAY
            records=[]
            for opp in q['opponent_id']:
                for k in range(7):records.append(dict(j=int(opp),i=200+k if k<6 else 99,t=cut-1,y=k in (0,1,6),arm=True,fair=True,cell=0))
            ht=pa.Table.from_pylist(records);hp=put(root,'history.parquet',ht)
            ref=root/'ref';ref.mkdir();np.save(ref/'original.npy',np.full((2,24,4,4,500),.25));np.save(ref/'clean.npy',np.full((2,24,4,4,500),.2))
            sjobs=[]
            hsh=num.user_hash(io.arr(ht,'j'))%np.uint64(16)
            for s in range(16):
                part=put(root,f'history{s}.parquet',ht.filter(pa.array(hsh==s)))
                sjobs.append(dict(queries=str(prepared/f'score_{s:02}.parquet'),parts=[part],shard=s,reference=str(ref),authors=[99,100],conf=CONF,output=str(root/'scores'/str(s))))
            io.mapped(histories.score_job,sjobs,2,'Synthetic score workers')
            histories.history_month_job(dict(queries=qp,parts=[hp],month=MONTHS[6],authors=[99,100],memory=.3,conf=CONF,output=str(root/'hist')))
            futures=[dict(game_id=f'F{k:07d}',chooser_user_id=int(p),disconnected_user_id=501,utc_ms=T+2*DAY,api_last_move_at_ms=T+2*DAY+2,archive_ordinal=k,kind_draw=k in (0,3),fair_competitive=True,tournament_like_event=False) for k,p in enumerate(q['recipient_id'])]
            futures.append(dict(game_id='FAuth000',chooser_user_id=14,disconnected_user_id=99,utc_ms=T+DAY,api_last_move_at_ms=T+DAY+1,archive_ordinal=9,kind_draw=True,fair_competitive=True,tournament_like_event=False))
            for k in (0,2):futures.append(dict(game_id=str(q['game_id'][k]),chooser_user_id=int(q['opponent_id'][k]),disconnected_user_id=int(q['recipient_id'][k]),utc_ms=T,api_last_move_at_ms=T+1000,archive_ordinal=20+k,kind_draw=True,fair_competitive=True,tournament_like_event=False))
            for r in futures:r['timeout_chooser_win']=not r['kind_draw']
            fp=put(root,'main.parquet',pa.Table.from_pylist(futures))
            pi.future_and_roles_job(dict(queries=qp,panel=fp,memory=.3,conf=CONF,output=str(root/'future')))
            ojobs=[]
            for s in range(16):ojobs.append(dict(queries=str(prepared/f'outcome_{s:02}.parquet'),shard=s,authors=[99,100],
                original_histories=[str(root/'hist'/f'original_{s:02}.parquet')],clean_histories=[str(root/'hist'/f'clean_{s:02}.parquet')],
                futures=[str(root/'future'/f'{s:02}.parquet')],output=str(root/'outcomes'/str(s)),conf=CONF))
            io.mapped(histories.outcomes_job,ojobs,2,'Synthetic outcome workers')
            cp,info=chron.prepare_chronology(qp,root/'chronplan',CONF,.3)
            erows=[]
            for k in range(2):
                a,b=int(q['recipient_id'][k]),int(q['opponent_id'][k])
                erows.extend([dict(game_id=f'A{k:07d}',utc_ms=T-DAY,white_id=a,black_id=99),dict(game_id=f'B{k:07d}',utc_ms=T-2*DAY,white_id=b,black_id=800),dict(game_id=q['game_id'][k],utc_ms=T,white_id=a,black_id=b)])
            ep=put(root,'chron.parquet',pa.Table.from_pylist(erows));cj=dict(path=ep,signature=io.sig(ep),people=str(cp/'people.parquet'),pairs=str(cp/'pairs.parquet'),focal=str(cp/'focal.parquet'),roles=str(cp/'roles.parquet'),latest=T,rows=len(erows),file_index=0,memory=.3,output=str(root/'chronpart'),conf=CONF)
            chron.chronology_job(cj);co,_=chron.merge_chronology(qp,cp,[root/'chronpart'],root/'chronology',CONF,.4,2)
            stream=put(root,'stream.parquet',dict(recipient_id=np.array([],np.int64),archive_start_ms=np.array([],np.int64),anchor_ms=np.array([],np.int64)))
            auditpath=put(root,'audit.parquet',dict(game_id=q['game_id'][[0,2]],recipient_id=q['recipient_id'][[0,2]],spaced90=[True,True],history_window_complete=[True,True],complete90=[True,True]))
            labels,_=pi.entry_labels(qp,[str(root/'future/roles.parquet')],auditpath,root/'entrylabels',CONF,.4)
            _,early=pf.check_before_chronology(qp,prepared/'baseline_original.parquet',
                [str(Path(j['output'])/'scores.parquet') for j in sjobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],labels/'entry.parquet',root/'early',CONF,.5)
            self.assertEqual(early['rows'],2)
            assembled,r=pf.combine(qp,prepared/'baseline_original.parquet',[str(Path(j['output'])/'scores.parquet') for j in sjobs],
                [str(Path(j['output'])/'outcomes.parquet') for j in ojobs],co/'features.parquet',stream,[99,100],root/'assembled',CONF,.5,labels/'entry.parquet')
            self.assertEqual(r['original_features_reproduced'],2)
            self.assertEqual(r['sample_accounting']['entry_new_phase10']['rows'],2)
            self.assertEqual(r['sample_accounting']['ordinary_new_phase10']['rows'],1)
            clean=arrays(io.read(assembled/'ordinary_old_author_clean.parquet'))
            self.assertEqual(clean['y'].tolist(),[True]);self.assertEqual(clean['n_7d'].tolist(),[6])
            features=arrays(io.read(assembled/'features.parquet'));self.assertEqual(features['y'][:2].tolist(),[False,True])
            ent=arrays(io.read(assembled/'entry_old_author_clean.parquet'));self.assertEqual(ent['analysis_entry_90'].tolist(),[True,False]);self.assertNotIn('y',ent)
            for family in pf.SPECS:
                label=family+'_new_phase10'
                pr.model_job(dict(sample=str(assembled/(label+'.parquet')),family=family,cohort='new_phase10',conf=CONF,output=str(root/'models'/label)))
                self.assertEqual(io.load(root/'models'/label/'result.json')['estimates'][0]['reason'],'FEWER_THAN_2000_ROWS')

if __name__=='__main__':unittest.main()
