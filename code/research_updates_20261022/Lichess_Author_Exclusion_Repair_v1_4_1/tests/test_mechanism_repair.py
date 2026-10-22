"""Small synthetic integration: cohort preparation, frozen roster, fits, restart."""
import sys,tempfile,unittest,importlib.util
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import engine as e
import mechanism_excluded as m

class MechanismRepairTests(unittest.TestCase):
    def test_refit_and_frozen_roster(self):
        common,inputs,*_=m.imports()
        spec=importlib.util.spec_from_file_location('mechanism_fixture',e.ROOT/'vendor/mechanism/tests/fixture.py')
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=fixture.fixture(accounts=40)
            eligible=d.loc[d.regular & (d.rd<=110) & (d.opp_rd<=110)]
            frozen=eligible.sample(n=100,random_state=123).copy();roster=root/'roster.parquet';frozen.to_parquet(roster,index=False)
            removed=frozen.game_id.iloc[0];d=d.loc[(d.game_id!=removed)&(d.chooser!=2)]
            source=root/'analysis.parquet';d.to_parquet(source,index=False)
            prepared=m.prepare_frozen([source],'equal',root/'private',root/'report','fixture',1,768,roster)
            actual=e.pd.read_parquet(prepared['cohorts']['rd110']['standardization'])
            self.assertEqual(set(actual.game_id),set(frozen.game_id)&set(d.game_id))
            self.assertLess(len(actual),100)
            expected=d.loc[d.regular]
            self.assertEqual(prepared['cohorts']['original']['meta']['n'],len(expected))
            task=('equal','strength',prepared,str(root/'private'),str(root/'report'),'fixture-job')
            result=m.model_job(task);self.assertEqual(result['status'],'COMPLETE',result)
            before={str(p):p.stat().st_mtime_ns for p in (root/'private/fits').glob('*.json')}
            self.assertEqual(m.model_job(task),result)
            self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in (root/'private/fits').glob('*.json')})
            diagnostic=m.unrestricted_job(('equal','strength','rd110',prepared,str(root/'private'),str(root/'report'),'fixture-unrestricted'))
            self.assertEqual(diagnostic['status'],'ESTIMATED')
            coefficients=e.pd.read_csv(root/'report/models/equal/strength/coefficients.csv')
            self.assertEqual(set(coefficients.training),{'original','rd110'})
            self.assertEqual(set(coefficients.stage),{'full','fold0','fold1'})
            scores=e.pd.read_csv(root/'report/models/equal/strength/heldout_scores.csv')
            self.assertEqual(set(scores.comparison),{'original_train_original_test','original_train_rd110_test','rd110_train_rd110_test'})

if __name__=='__main__':unittest.main(verbosity=2)
