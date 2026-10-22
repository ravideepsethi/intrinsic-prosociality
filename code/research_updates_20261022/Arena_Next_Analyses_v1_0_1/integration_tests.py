"""Synthetic integration of the new receipt/IV adapter and targeted rank repair."""
import tempfile, unittest
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from next_common import *

class IntegrationTests(unittest.TestCase):
    def test_full_rank_repair_driver_on_source_derived_fixture(self):
        from unittest.mock import patch
        import rank_stage
        from tests import fixture
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);sample,_=fixture(root/'inputs');c=db(root/'counts','512MB',1)
            original=read(ROOT/'authority/V102_RANK_FLAGS.json');flags=[]
            for r in original:
                first=r['model_id'].startswith('primary_')
                lo,hi=(-100,100) if r['model_id'].endswith('m100_p100') else (100,300) if r['model_id'].endswith('p100_p300') else (300,600.0000001)
                cut='ply_count<=10' if first else "ply_count>10 AND month>='2024-11'"
                n,g=c.execute(f'''SELECT count(*),count(DISTINCT chooser_user_id) FROM {parq(sample['panels'])}
                  WHERE ({cut}) AND engine_eval_cp_disconnected>={lo} AND engine_eval_cp_disconnected<{hi}
                  AND floor((disconnected_elo-chooser_elo+25.0)/50.0) BETWEEN -11 AND 11''').fetchone()
                flags.append({**r,'rows':n,'clusters':g})
            c.close();original_read=rank_stage.read
            def source(p):return flags if Path(p).name=='V102_RANK_FLAGS.json' else original_read(p)
            with patch.object(rank_stage,'read',side_effect=source):
                result=rank_stage.run(sample,root,SimpleNamespace(memory='1GB',threads=2))
            self.assertEqual(result['flagged_models'],4)
            self.assertEqual(result['reestimated']+result['unsupported'],4)
            self.assertGreaterEqual(result['reestimated'],1)

    def test_iv_adapter_build_score_and_assemble(self):
        import iv_stage as iv
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);state=root/'state';state.mkdir();(state/'targets').mkdir()
            start=int(iv.STARTS[3])+1000000
            targets=[]
            for i in [1,2]:
                targets.append({'target_row':i-1,'game_id':f'exp0000{i}','recipient_id':i,'chooser_id':10+i,
                  'archive_start_ms':start+i*1000,'anchor_ms':start+i*1000+60000,'month_code':3,
                  'received':i==1,'arm_eligible':True,'speed':'blitz','tc_base_s':180.,'tc_inc_s':2.,
                  'exposure_chooser_elo':1500.,'exposure_recipient_elo':1480.,'exposure_chooser_rd':50.,'exposure_recipient_rd':50.,
                  'exposure_eval_cp':0.,'exposure_ply_count':30.,'exposure_chooser_clock_s':50.,'exposure_recipient_clock_s':40.,
                  'exposure_claimed_win':i==2,'exposure_draw_payoff':-1.,'exposure_win_premium':5.,'exposure_material_advantage':0.})
            iv.io.table(state/'targets/first_exposures.parquet',pa.Table.from_pylist(targets))
            chronological=pa.table({'utc_ms':[start-iv.DAY,start+1000,start+2000], 'white_id':[1,1,2], 'black_id':[30,11,12]})
            cp=root/'chron.parquet';pq.write_table(chronological,cp)
            rec={'path':str(cp),'signature':iv.io.sig(cp),'rows':3}
            d=iv.chronology_job({'input':rec,'targets':str(state/'targets/first_exposures.parquet'),'out':str(state/'chron/0'),'conf':'TEST'})
            _,cohort=iv.build_cohort(state,'TEST',[d],1);self.assertEqual(cohort['cohort_rows'],2)
            score_input=state/'score_inputs';score_input.mkdir()
            queries=pa.table({'target_row':[0,1],'sample_row':[0,1],'game_id':['exp00001','exp00002'],'recipient_id':[1,2],
              'opponent_id':[11,12],'archive_start_ms':[start+1000,start+2000],'anchor_ms':[start+61000,start+62000],'month_code':[3,3]})
            for role in ['outcomes','scores']:iv.io.table(score_input/(role+'.parquet'),queries)
            hist=[]
            for k,(j,i,y,gid,delta) in enumerate([(1,30,False,'pool0001',100000),(1,31,True,'arena001',200000),(2,32,True,'arena002',150000),
                                              (11,41,True,'prior001',-40*iv.DAY),(12,42,False,'prior002',-40*iv.DAY)]):
                hist.append({'j':j,'i':i,'y':y,'gid':gid,'ord':k,'start':start+delta,'t':start+delta+1000,'fair':True,'arm':True,'cell':0})
            hp=root/'history.parquet';pq.write_table(pa.Table.from_pylist(hist),hp)
            keys=score_input/'arena_keys.parquet';pq.write_table(pa.table({'game_id':['arena001','arena002'],'chooser':[1,2]}),keys)
            ref=score_input/'reference.npy';np.save(ref,np.full((2,24,4,4,500),.1))
            d=iv.score_job({'parts':[str(hp)],'keys':str(keys),'outcomes':str(score_input/'outcomes.parquet'),
              'scores':str(score_input/'scores.parquet'),'reference':str(ref),'cohort':str(state/'cohort/cohort.parquet'),
              'out':str(state/'scores/0'),'conf':'TEST'})
            iv.assemble(state,'TEST',[d]);tab=iv.io.read(state/'analysis/iv.parquet')
            self.assertEqual(tab['other_started_after_y'].to_pylist(),[False,True])
            self.assertEqual(tab['all_source_next_reached'].to_pylist(),[True,True])
            self.assertEqual(tab['pre_games_30d'].to_pylist(),[1,0])
            self.assertEqual(tab['n_7d'].to_pylist(),[1,1])
            result=iv.receipt_models(state,root/'public',SimpleNamespace(memory='1GB',threads=1))
            self.assertEqual(result['status'],'UNSUPPORTED_COMMON_SUPPORT_RETENTION')
            r=iv.upstream.estimate_iv(state,'TEST')
            self.assertTrue(all(not x['supported'] for x in r['estimates']))

    def test_targeted_month_rebase_preserves_identified_curve(self):
        from rank_stage import within_gram
        mod=load(ROOT/'source/structural/rating_gap_nonparametric_closure_parallel.py','test_rank_source')
        rng=np.random.default_rng(750);n=4000;group=np.arange(n)%100;month=rng.integers(0,12,n);x=rng.normal(size=n)
        y=.03*x+rng.normal(size=100)[group]*.03+rng.normal(size=12)[month]*.01+rng.normal(0,.1,n)
        frame=pd.DataFrame({'chooser':group,'kind':y,'month_code':month,'x':x})
        with tempfile.TemporaryDirectory() as t:
            c=db(t,'512MB',1);c.register('data',frame)
            terms=[('gap_target','x')]+[(f'm_{i}',f'CASE WHEN month_code={i} THEN 1.0 ELSE 0.0 END') for i in range(12)]
            full,_,_=within_gram(mod,c,'data','TRUE',terms,'test')
            self.assertEqual(np.linalg.matrix_rank(full),12)
            reduced=[terms[0]]+terms[2:];fits,receipt=mod.fit_fe_targeted(c,'data','TRUE',reduced,['gap_target'],'synthetic_month_rebase')
            explicit=np.column_stack([x,pd.get_dummies(month,drop_first=True,dtype=float),pd.get_dummies(group,dtype=float)])
            expected=np.linalg.lstsq(explicit,y,rcond=None)[0][0]
            actual=fits.loc[fits.term=='gap_target','coef_pp'].iloc[0]/100
            self.assertAlmostEqual(actual,expected,places=10);self.assertEqual(receipt['rank'],receipt['terms_kept']);c.close()
