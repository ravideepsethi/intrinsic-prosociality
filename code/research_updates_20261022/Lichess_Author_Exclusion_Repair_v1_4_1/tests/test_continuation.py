import os,sys,tempfile,unittest,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import engine as e
import continuation as c
import session_reuse as s
from compare import compare_frames,export_tables

class ContinuationTests(unittest.TestCase):
    def test_nullable_string_keys_numeric_dimensions_and_metadata(self):
        a=e.pd.DataFrame({'split_design':e.pd.Series(['hash','hash','year','year'],dtype='string'),
                        'first_half_rate_pct_bin':[0,1,0,1],'second_half_rate_pct_bin':[0,0,1,1],
                        'choosers':[1,2,3,4],'sample_specification_sha256':['old']*4})
        b=a.iloc[::-1].copy();b['sample_specification_sha256']='new';b.loc[0,'choosers']=0
        rows,audit=compare_frames(a,b,'core','grid.csv')
        self.assertEqual(audit['matched_rows'],4);self.assertEqual(audit['included_only'],0)
        self.assertEqual(next(r for r in rows if r['included']==1)['change'],-1)
        bad=e.pd.concat([a,a.iloc[:1]])
        self.assertEqual(compare_frames(bad,bad,'core','grid.csv')[1]['status'],'DUPLICATE_COMPARISON_KEYS')

    def test_rating_root_export_exact_whitelist_private_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=Path(tmp);p=run/'PRIVATE/results/included/rating_gap';p.mkdir(parents=True)
            e.pd.DataFrame([{'model_id':'x','coef_pp':1.}]).to_csv(p/'fe_model_coefficients.csv',index=False)
            e.pd.DataFrame([{'chooser':123}]).to_csv(p/'random.csv',index=False)
            self.assertEqual(len(export_tables(run,'included','rating_gap')),1)
            e.pd.DataFrame([{'chooser':123}]).to_csv(p/'fe_model_coefficients.csv',index=False)
            with self.assertRaisesRegex(RuntimeError,'Private identifiers'):export_tables(run,'included','rating_gap')

    def test_completed_adoption_never_fits_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);old=base/'old';new=base/'new';statuses={};prior={};auths={v:{'fingerprint':v} for v in ('included','excluded')}
            for v in auths:
                a=old/'report/tables'/v/'core/report/fit.csv';a.parent.mkdir(parents=True);a.write_text('estimate,se\n1,.2\n')
                r=old/'PRIVATE/receipts'/v/'core.json';e.write(r,dict(stage='core',variant=v,sample_fingerprint=v))
                prior[v+'/core']=dict(status='COMPLETE',seconds=4,receipt=e.record(r),aggregate_files=[e.record(a)])
            with patch.object(c,'COMPLETED',['core']),patch.object(c,'run_stage',side_effect=AssertionError('refit')):
                c.adopt_completed(old,new,prior,statuses,auths)
                self.assertEqual(len(statuses),2)
                (old/'report/tables/excluded/core/report/fit.csv').write_text('altered')
                with self.assertRaisesRegex(RuntimeError,'Changed'):c.adopt_completed(old,new,prior,{},auths)

    def test_history_exclusion_preserves_positions_and_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'AUTHOR_EXCLUSION_SESSION':'test'}),patch.object(s,'MONTHS',['2023-11']):
            root=Path(tmp);old=root/'old';run=root/'run';shared=run/'shared';authority=root/'authority';authority.mkdir()
            e.write(authority/'SESSION_AUTHORITY.json',{'fixture':True})
            for m in ('2023-10','2023-11'):
                d=old/'PRIVATE/history'/m;d.mkdir(parents=True)
                e.pd.DataFrame({'chooser':[1,2],'start30':[0,0],'observed_session_length':[4,5]}).to_parquet(d/'sessions30.parquet',index=False)
                if m=='2023-11':
                    e.pd.DataFrame({'game_id':['a','b','c'],'chooser':[1,1,2],'y':[0,1,0],'pos30':[1,4,8],'prior_same_speed':[3,7,30]}).to_parquet(d/'focal_history.parquet',index=False)
                files=[dict(path=p.name,sha256=e.sha(p),bytes=p.stat().st_size) for p in d.glob('*.parquet')];e.write(d/'_DONE.json',{'files':files})
            panel=e.pd.DataFrame({'game_id':['a','b','c'],'chooser_user_id':[1,1,2],'outcome_kind_draw':[0,1,0]})
            for v,data in [('included',panel),('excluded',panel.iloc[[0,2]])]:
                p=root/(v+'.parquet');data.to_parquet(p,index=False)
                e.write(run/'PRIVATE/inputs'/(v+'_AUTH.json'),{'fingerprint':v,'month_records':[{'path':str(p),'rows':len(data)}]})
            args=SimpleNamespace(run=run,memory_gb=2,workers=2)
            with patch.object(s,'ROOT',authority):
                z=s.bind_history(args,old,shared)
                out=e.pd.read_parquet(shared/'excluded/2023-11/focal_history.parquet').sort_values('game_id')
                self.assertEqual(list(out.game_id),['a','c']);self.assertEqual(list(out.pos30),[1,8]);self.assertEqual(list(out.prior_same_speed),[3,30])
                self.assertEqual(z['audits'][0]['removed'],1)
                self.assertEqual(s.bind_history(args,old,shared)['key'],z['key'])
                (old/'PRIVATE/history/2023-11/focal_history.parquet').write_bytes(b'altered')
                with self.assertRaisesRegex(RuntimeError,'changed'):s.bind_history(args,old,shared)

    def test_rating_recovery_uses_fingerprint_key_and_captures_without_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);old=base/'old';new=base/'new';source=old/'PRIVATE/results/included/rating_gap';source.mkdir(parents=True)
            (source/'private_cache').mkdir();e.pd.DataFrame({'chooser':[1]}).to_parquet(source/'private_cache/rating_gap_krd_derived_private.parquet')
            names=['mechanical_validation','rating_gap_broad_rates','rating_gap_u_metrics','rating_gap_curves','expected_score_curves','krd_descriptives','fe_model_coefficients','fe_model_receipts','fe_model_band_contrasts']
            for n in names:e.pd.DataFrame({'n':[1]}).to_csv(source/(n+'.csv'),index=False)
            settings=dict(status='POOL_MAIN_RATING_GAP_KRD_DECOMPOSITION_OK',sample_authority={'fingerprint':'fixture'})
            for field,rel in [('source_program','source/structural/rating_gap_krd_decomposition.py'),('render_program','source/structural/render_rating_gap_krd.py'),('adapter','runner/run_krd.py')]:settings[field]={'sha256':e.sha(e.ROOT/'vendor/wave1'/rel)}
            e.write(source/'settings.json',settings);e.write(old/'PRIVATE/stage_receipts/included/rating_gap.json',{'result':settings,'sample_fingerprint':'fixture'})
            statuses={};self.assertTrue(c.recover_rating(old,new,{'fingerprint':'fixture'},statuses))
            self.assertEqual(len(statuses['included/rating_gap']['aggregate_files']),9)
            self.assertTrue((new/'PRIVATE/results/included/rating_gap').is_symlink())
            settings['sample_authority']['fingerprint']='wrong';e.write(source/'settings.json',settings)
            with self.assertRaisesRegex(RuntimeError,'disagree'):c.recover_rating(old,new,{'fingerprint':'fixture'},{})

    def test_exact_estimate_standard_error_pairing(self):
        a=e.pd.DataFrame([dict(window_half_width=1,beta_plus_pp_per_rating_point=1.,se_beta_plus=.1,beta_minus_pp_per_rating_point=2.,se_beta_minus=.5)])
        b=a.copy();b['beta_minus_pp_per_rating_point']=2.1
        rows,_=compare_frames(a,b,'core','slopes.csv');r=next(r for r in rows if r['metric']=='beta_minus_pp_per_rating_point')
        self.assertAlmostEqual(r['absolute_change_in_included_se_units'],.2)

if __name__=='__main__':unittest.main(verbosity=2)
