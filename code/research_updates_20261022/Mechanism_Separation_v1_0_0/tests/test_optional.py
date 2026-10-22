"""Authenticated optional adapters; policy predictions must ignore post outcomes."""
import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from test_core import fixture
from common import *
from design import design
from extras import cue_data
from policy import run_policy,IMPLEMENTED

class OptionalInputs(unittest.TestCase):
    def test_cues_preserve_unknown_and_reject_nonhistorical(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);d=fixture(4)
            receipt=p/'producer.txt';receipt.write_text('SYNTHETIC game-time producer evidence')
            cues=pd.DataFrame(dict(game_id=d.game_id,provisional=np.arange(len(d))%2,patron=np.nan))
            data=p/'cues.parquet';frame(cues,data)
            m=dict(format='MECHANISM_GAME_TIME_CUES_V1',key='game_id',role='disconnected_opponent',unknown_is_false=False,
                   producer_receipt=dict(path=str(receipt),sha256=sha(receipt)),
                   files=[dict(path=str(data),sha256=sha(data),rows=len(cues))],
                   semantics=dict(provisional=dict(historical_at_game=True),patron=dict(historical_at_game=True)))
            manifest=p/'manifest.json';write(manifest,m)
            joined,_=cue_data(p,p/'work',d,p/'report',manifest)
            self.assertEqual(len(joined),len(d));self.assertTrue(joined.patron.isna().all())
            m['semantics']['provisional']['historical_at_game']=False;write(manifest,m)
            with self.assertRaisesRegex(RuntimeError,'Nonhistorical cue'):
                cue_data(p,p/'work',d,p/'report',manifest)

    def test_actual_policy_predictions_do_not_use_post_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);training=fixture(60);target=training.copy()
            weeks=(np.arange(len(target))//2)%80
            start=int(pd.Timestamp('2024-09-02T12:00:00Z').timestamp()*1000)
            target['t']=start+weeks*7*DAY
            target['month']=pd.to_datetime(target.t,unit='ms').dt.to_period('M').astype(str)
            target['color']=np.where(np.arange(len(target))%2,'white','black')
            target['fixed_regular_cohort']=True;target['pool_main']=True
            fits={}
            for model in ('cost','framing'):
                X,names,_=design(training,model);b=np.zeros(X.shape[1]);b[names.index('own_cost')]=.02
                if model=='framing':b[names.index('draw_frame')]=.2
                fits[model]=dict(status='ESTIMATED',beta=b,curvature=.5)
            receipt=p/'producer.txt';receipt.write_text('SYNTHETIC calibration, cohort and censor evidence')
            evidence=dict(path=str(receipt),sha256=sha(receipt))
            m=dict(format='MECHANISM_COLOR_INPUTS_V1',pool_and_previous_adjacency_certified=True,
                chronology_through='2026-04',cohort_uses_only_preimplementation_information=True,
                actual_stratum_calibration_reviewed=True,missing_clock_and_material_rules_aligned=True,
                producer_receipt=evidence,calibration_review=evidence,censor_source=evidence,
                censor_utc='2026-01-30T00:00:00Z')
            data=p/'target.parquet';manifest=p/'manifest.json'
            outputs=[]
            for branch in (0,1):
                if branch:target.loc[target.t>=IMPLEMENTED,'y']=1-target.loc[target.t>=IMPLEMENTED,'y']
                frame(target,data);m['files']=[dict(path=str(data),sha256=sha(data),rows=len(target))];write(manifest,m)
                report=p/('report'+str(branch))
                run_policy(training,fits,p,p/'work',report,manifest)
                status=read(report/'POLICY_STATUS.json')
                self.assertFalse(status['post_outcomes_used']);self.assertGreaterEqual(status['pre_complete_weeks'],32)
                pred=pd.read_parquet(report/'color_model_predictions.parquet')
                power=pd.read_parquet(report/'color_pairwise_power.parquet')
                self.assertTrue(pred.actual_frozen_cohort.all());self.assertEqual(len(pred),4)
                self.assertGreater(len(power),0);outputs.append((pred,power))
            for i in (0,1):pd.testing.assert_frame_equal(outputs[0][i],outputs[1][i])

if __name__=='__main__':unittest.main()
