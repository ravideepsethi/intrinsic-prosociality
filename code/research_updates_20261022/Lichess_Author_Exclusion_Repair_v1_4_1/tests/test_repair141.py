"""Regressions for actual v140 failures; no production data in this test suite."""
import unittest,tempfile,sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from engine import *
import remaining_common as rc
from compare import compare_frames
from first_repeat_remaining import validate_model_statuses
from state_persistence import weighted_hc1,hc1
import remaining
from types import SimpleNamespace

class Repair141Tests(unittest.TestCase):
    def test_completed_v140_stages_and_audits_adopt_without_refit(self):
        with tempfile.TemporaryDirectory() as td:
            project=Path(td)/'project';source=Path(td)/'source';run=Path(td)/'new'
            cfg={'code':{'first_repeat_remaining.py':'old'}};rid=digest(cfg)[:16]
            old=project/'derived/replication/author_exclusion_remaining_v140_PRIVATE'/rid
            write(old/'PRIVATE/CONFIG.json',cfg);statuses={}
            for v in ('included','excluded'):
                d=dict(stage='arena',variant=v,sample_fingerprint=v,result={'status':'done'})
                p=old/'PRIVATE/stage_receipts'/v/'arena.json';write(p,d)
                write(old/'report/stage_summaries'/v/'arena.json',d)
                a=old/'report/tables'/v/'arena/table.csv';a.parent.mkdir(parents=True);a.write_text('estimate\n1\n')
                statuses[v+'/arena']=dict(status='COMPLETE',receipt=record(p),aggregate_files=[record(a)])
                write(run/'PRIVATE/inputs'/(v+'_AUTH.json'),{'fingerprint':v})
            write(old/'PRIVATE/STAGES.json',statuses)
            write(old/'report/current_audits/iv_remaining.json',{'status':'verified'})
            write(old/'report/audit_tables/entry/evidence.json',{'checked':True})
            manifest=[dict(file=str(p.relative_to(old/'report')),bytes=p.stat().st_size,sha256=sha(p)) for p in (old/'report').rglob('*') if p.is_file()]
            write(old/'report/REPORT_HASHES.json',manifest);write(source/'evidence/returned_v140/REPORT_HASHES.json',manifest)
            authority=dict(run_id=rid,code=cfg['code'],report_sha256=sha(old/'report/REPORT_HASHES.json'),completed_families=['arena'])
            adopted={}
            with patch.object(remaining,'ROOT',source),patch.object(remaining,'PARENT141',authority),patch.object(remaining,'child',side_effect=AssertionError('A fit was scheduled')):
                remaining.adopt_remaining(SimpleNamespace(project=project),run,adopted)
                self.assertEqual(set(adopted),{'included/arena','excluded/arena'})
                self.assertEqual(read(run/'report/current_audits/iv_remaining.json')['status'],'verified')
                write(old/'report/current_audits/iv_remaining.json',{'status':'mutated'})
                with self.assertRaisesRegex(RuntimeError,'report differs'):remaining.adopt_remaining(SimpleNamespace(project=project),run,{})
    def test_weighted_joint_covariance_against_independent_sandwich(self):
        rng=np.random.default_rng(17);n=900;k=4
        X=np.column_stack([np.ones(n),rng.normal(size=(n,k-1))]);Y=rng.normal(size=(n,2));W=rng.integers(4,55,size=(n,2)).astype(float)
        b,V=weighted_hc1(X,Y,W)
        breads=[];scores=[]
        for j in range(2):
            z=X*np.sqrt(W[:,j,None]);t=Y[:,j]*np.sqrt(W[:,j]);want=np.linalg.lstsq(z,t,rcond=None)[0]
            np.testing.assert_allclose(b[:,j],want,atol=1e-12)
            breads.append(np.linalg.inv(z.T@z));scores.append(X*(W[:,j]*(Y[:,j]-X@want))[:,None])
        for i in range(2):
            for j in range(2):
                want=breads[i]@scores[i].T@scores[j]@breads[j]*(n/(n-k))
                np.testing.assert_allclose(V[i*k:(i+1)*k,j*k:(j+1)*k],want,rtol=1e-11,atol=1e-13)
        b0,v0=hc1(X,Y);b1,v1=weighted_hc1(X,Y,np.ones_like(W))
        np.testing.assert_allclose(b0,b1,atol=1e-12);np.testing.assert_allclose(v0,v1,atol=1e-12)
        b2,v2=weighted_hc1(X,Y,W*np.array([2.,11.]))
        np.testing.assert_allclose(b,b2,atol=1e-12);np.testing.assert_allclose(V,v2,atol=1e-12)
    def test_first_repeat_only_original_auxiliary_failures_allowed(self):
        baseline=read(ROOT/'evidence/first_repeat_baseline.json');validate_model_statuses(baseline,baseline)
        self.assertEqual(sum(x['status']!='ESTIMATED' for x in baseline),3)
        bad=deepcopy(baseline);bad[3]['status']='ESTIMATION_FAILURE_RETAINED'
        with self.assertRaisesRegex(RuntimeError,'status changed'):validate_model_statuses(bad,baseline)
        bad=deepcopy(baseline);bad[2]['error_message']='different failure'
        with self.assertRaisesRegex(RuntimeError,'Unexpected'):validate_model_statuses(bad,baseline)
    def test_temporal_horizons_and_merit_counts_align(self):
        a=pd.DataFrame(dict(analysis=['B2']*3,horizon_hours=[6.,24.,168.],excess_percentage_points=[1.,2.,3.]))
        rows,coverage=compare_frames(a,a.iloc[::-1],'temporal','b2.csv')
        self.assertEqual(coverage['status'],'COMPARED');self.assertEqual(coverage['matched_rows'],3)
        a=pd.DataFrame(dict(month=['2023-11','2023-12'],competitive=[100,90],grants=[4,5]))
        b=a.copy();b.loc[0,'competitive']=99
        rows,coverage=compare_frames(a,b,'merit','report/monthly_validation.csv')
        self.assertEqual(coverage['matched_rows'],2);self.assertEqual(coverage['included_only'],0)
        self.assertIn(-1,[x['change'] for x in rows if x['metric']=='competitive'])
    def test_copied_receipt_resolves_original_and_rejects_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rep=root/'derived/replication';parent=rep/'author_exclusion_repair_v130_PRIVATE/p130';copied=rep/'author_exclusion_continue_v120_PRIVATE/p120'
            cfg={'code':{'code/adapters.py':'fixture'},'upstream_manifest':'fixture'};rid=digest(cfg)[:16]
            original=rep/'author_exclusion_reestimate_v100_PRIVATE'/rid
            write(original/'PRIVATE/CONFIG.json',cfg)
            out=original/'PRIVATE/results/excluded/receipt';out.mkdir(parents=True)
            raw=out/'PRIVATE/cache';raw.parent.mkdir();raw.write_bytes(b'data')
            receipt=original/'PRIVATE/stage_receipts/excluded/receipt.json';write(receipt,{'sample':'same','result':'done'})
            agg=original/'report/aggregate.csv';agg.parent.mkdir();agg.write_text('n\n5\n')
            record0=dict(status='COMPLETE',receipt=record(receipt),aggregate_files=[record(agg)])
            write(original/'PRIVATE/STAGES.json',{'excluded/receipt':record0})
            dest=copied/'PRIVATE/stage_receipts/excluded/receipt.json';write(dest,read(receipt))
            copied_record=dict(record0,receipt=record(dest));write(parent/'PRIVATE/STAGES.json',{'excluded/receipt':copied_record})
            fixture=root/'source';write(fixture/'PARENT_AUTHORITY.json',dict(run_id=rid,v100_code=cfg['code'],v100_upstream='fixture'))
            with patch.object(rc,'ROOT',fixture):
                self.assertEqual(rc.stage_output(parent,'excluded','receipt'),out)
                receipt.write_text('{}')
                with self.assertRaises(RuntimeError):rc.stage_output(parent,'excluded','receipt')
    def test_tenure_reserved_month_projection_binds(self):
        import ast
        source=ROOT/'vendor/tenure/prepare.py';tree=ast.parse(source.read_text());fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='project_query')
        ns={'qs':q};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(source),'exec'),ns)
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'p.parquet';columns=['game_id','chooser_user_id','disconnected_user_id','chooser_username_norm','disconnected_username_norm','outcome_kind_draw','engine_eval_cp_disconnected','ply_count','month','api_speed','time_control','chooser_elo','disconnected_elo','chooser_draw_payoff_v2','chooser_win_premium_v2','chooser_pre_rd_v2','disconnected_pre_rd_v2','chooser_clock_last_obs_s','disconnected_clock_last_obs_s','api_created_at_ms','api_last_move_at_ms','fen_after_last_move','disconnected_color','chooser_color','api_winner','api_variant','api_status','api_rated','sf100k_stockfish_sha256','engine_eval_is_mate']
            d={x:[1] for x in columns}
            for x in ['game_id','chooser_username_norm','disconnected_username_norm','month','api_speed','time_control','fen_after_last_move','disconnected_color','chooser_color','api_winner','api_variant','api_status','sf100k_stockfish_sha256']:d[x]=['x']
            d['month']=['2023-11'];pd.DataFrame(d).to_parquet(p,index=False)
            sql=ns['project_query'](p).replace('month::VARCHAR month','month::VARCHAR AS "month"')
            con=duckdb.connect();res=con.execute(sql).fetchdf();con.close();self.assertEqual(res.loc[0,'month'],'2023-11')
if __name__=='__main__':unittest.main(verbosity=2)
