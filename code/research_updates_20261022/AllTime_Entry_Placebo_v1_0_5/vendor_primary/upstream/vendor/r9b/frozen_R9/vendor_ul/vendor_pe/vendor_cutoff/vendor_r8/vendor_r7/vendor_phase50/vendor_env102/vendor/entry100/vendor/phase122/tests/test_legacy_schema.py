"""Exercise the production schema omission, independent parent and fail-closed joins."""
import sys,tempfile,unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import phase_features as pf
import legacy_schema as ls
from cached_common import *
import test_phase_analysis as fixture

def old_rows(n=3):
    d=fixture.entry_model(n)
    d.update(outcome_gid=np.array([f'F{k:07d}' for k in range(n)]),
             outcome_t=d['anchor_ms']+DAY,outcome_start=d['anchor_ms']+1,
             outcome_opponent=np.full(n,5000,np.int64))
    parent={k:v for k,v in d.items()}
    # Exact required normalized contract; no fixture-only metadata/outcome fields.
    normalized={k:v for k,v in d.items() if k in set(pf.OLD_COLUMNS)-set(ls.DETAILS)}
    return normalized,parent

class LegacySchemaTests(unittest.TestCase):
    def test_numerical_bridge_then_prepare_production_shaped_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d,parent=old_rows(5000)
            source=fixture.put(root,'normalized.parquet',d)
            # Parent row order and row IDs must not drive the game/player join.
            parent={k:v[::-1] for k,v in parent.items()};parent['row_id']=np.arange(5000)+99999
            pp=fixture.put(root,'parent.parquet',parent)
            expected=[]
            for family,spec in pf.SPECS.items():
                mask=d['ordinary_narrow'] if family=='ordinary' else np.ones(5000,bool)
                expected+=stats.estimate({k:v[mask] for k,v in d.items()},spec)['estimates']
            q=fixture.fixture.queries(1);q['game_id']=np.array(['NEW00000'])
            cols=['game_id','archive_start_ms','anchor_ms','recipient_id','opponent_id','recipient_rating','opponent_rating','recipient_username','opponent_username','tc_base_s','tc_inc_s','status','expected_n7','month_code']
            new=fixture.put(root,'new.parquet',{k:q[k] for k in cols})
            real_load=io.load
            def read(path):
                if Path(path).name=='expanded_estimates.json':return expected
                return real_load(path)
            with mock.patch('phase_features.io.load',side_effect=read):
                out,info=pf.prepare_queries([new],source,root/'prepared','schema-test',.5,legacy_outcomes=pp)
            self.assertEqual(info['old_frozen_rows'],5000)
            restored=arrays(io.read(out/'baseline_original.parquet'))
            np.testing.assert_array_equal(restored['outcome_gid'],np.array([f'F{k:07d}' for k in range(5000)]))
            for name in ['status','recipient_username','opponent_username']:
                self.assertEqual(io.read(out/'baseline_queries.parquet')[name].null_count,5000)
            report=io.load(out/'legacy_schema.json')
            self.assertEqual(report['recovery']['restored_columns'],ls.DETAILS)
            self.assertEqual(report['recovery']['fabricated_values'],0)
            # Exact checkpoint resume does not rerun numerical fits or preparation.
            with mock.patch('phase_features.verify_original',side_effect=AssertionError('must reuse')):
                _,again=pf.prepare_queries([new],source,root/'prepared','schema-test',.5,legacy_outcomes=pp)
            self.assertEqual(again,info)

    def test_all_missing_required_columns_reported_before_regression(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d,parent=old_rows();del d['claim_30'];del d['recipient_rating']
            p=fixture.put(root,'bad.parquet',d)
            with self.assertRaisesRegex(RuntimeError,'claim_30, recipient_rating'):
                ls.preflight(p,None,pf.OLD_COLUMNS)

    def test_missing_parent_does_not_fabricate_outcomes(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d,parent=old_rows();p=fixture.put(root,'source.parquet',d)
            with self.assertRaisesRegex(RuntimeError,'authenticated parent'):
                ls.preflight(p,None,pf.OLD_COLUMNS)

    def test_wrong_parent_values_missing_rows_and_duplicates_rejected(self):
        for mode in ('outcome','identity','missing','duplicate'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
                root=Path(td);d,parent=old_rows()
                if mode=='outcome':parent['y']=~parent['y']
                elif mode=='identity':parent['opponent_id']=parent['opponent_id']+1
                elif mode=='missing':parent={k:v[:2] for k,v in parent.items()}
                else:parent={k:np.r_[v,v[:1]] for k,v in parent.items()}
                p=fixture.put(root,'bad.parquet',parent)
                with self.assertRaises(RuntimeError):ls.restore(d,p,root,.4)

    def test_existing_outcome_detail_must_agree_with_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d,parent=old_rows();d['outcome_t']=parent['outcome_t']+1
            p=fixture.put(root,'parent.parquet',parent)
            with self.assertRaisesRegex(RuntimeError,'Existing original outcome detail'):
                ls.restore(d,p,root,.4)

    def test_parent_hash_and_schema_are_required(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);_,d=old_rows();p=Path(fixture.put(root,'parent/analysis/comparison.parquet',d))
            config=dict(test='original-parent');io.js(root/'parent/config.json',config)
            authority=dict(root_relative='parent',config_sha256=io.cfgsha(config),relative_path='analysis/comparison.parquet',
                rows=3,sha256=io.sha(p),bytes=p.stat().st_size)
            real=io.load
            def load(path):return authority if Path(path).name=='legacy_outcome_authority.json' else real(path)
            with mock.patch('legacy_schema.io.load',side_effect=load):
                self.assertEqual(ls.authenticate_parent(root)['sha256'],authority['sha256'])
                d['y']=~d['y'];io.table(p,pa.table(d))
                with self.assertRaises(RuntimeError):ls.authenticate_parent(root)

    def test_early_original_feature_check_rejects_changed_later_game(self):
        d,saved=old_rows();d=dict(row_id=saved['row_id'],previous_frame=np.ones(3,bool),
            **{k:saved[k] for k in pf.ENTRY_COLUMNS},
            **{'original_'+k:saved[k] for k in SCORE_COLS+COUNT_COLUMNS+['y','reached']+ls.DETAILS})
        pf.verify_original_features(d,saved)
        d['original_outcome_gid']=np.full(3,'WRONG000')
        with self.assertRaisesRegex(RuntimeError,'outcome_gid'):pf.verify_original_features(d,saved)

if __name__=='__main__':unittest.main()
