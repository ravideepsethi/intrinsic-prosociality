"""Synthetic regression checks of the archived producer functions; no model fits.

Run with the existing NumPy/PyArrow/DuckDB environment if desired.
The function bodies are loaded unchanged from evidence/code, without importing
the private-data runners or running any of their entry points.
"""
import ast
from pathlib import Path
import typing, unittest
import numpy as np
import pyarrow as pa
import duckdb

ROOT=Path(__file__).resolve().parents[2]
CODE=ROOT/'results/research_updates_20261102/closing_audit/evidence/code'
def read_source(file):
    p=CODE/file
    if not p.exists():p=CODE/(file+'.in')
    return p.read_text()
DAY=86400000
def require(ok,message):
    if not ok:raise RuntimeError(message)
def functions(file,names,**extra):
    tree=ast.parse(read_source(file))
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
    assert {n.name for n in nodes}==set(names)
    env=dict(np=np,pa=pa,Any=typing.Any,DAY=DAY,require=require,**extra)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(CODE/file),'exec'),env)
    return env
def sql(file,starts):
    constants=[n.value for n in ast.walk(ast.parse(read_source(file))) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
    hits=[s for s in constants if s.startswith(starts)]
    assert len(hits)==1,(file,starts,len(hits))
    return hits[0]

class SentinelAudit(unittest.TestCase):
    def test_real_nullable_integer_loader(self):
        f=functions('receipt_loader.py',['arrow_column_numpy'],NULLABLE_BOOLEAN_OUTCOMES={'first_subsequent_kind_draw'})['arrow_column_numpy']
        t=pa.table({'timestamp':pa.array([None,200],type=pa.int64()),'first_subsequent_kind_draw':pa.array([None,True],type=pa.bool_())})
        np.testing.assert_array_equal(f(t,'timestamp',np,pa),[-1,200])
        self.assertTrue(np.isnan(f(t,'first_subsequent_kind_draw',np,pa)[0]))

    def test_original_zero_coded_censor_retains_absent_integer_time(self):
        f=functions('matched.py',['censored_outcome'])['censored_outcome']
        # absent int, absent float, future censor, exact tie, earlier censor,
        # and no later choice: these cover every branch of the recorded rule.
        out=f(np.array([1,1,1,1,1,0],bool),np.ones(6),np.full(6,100),np.full(6,50),np.array([-1,np.nan,200,150,125,-1]))
        np.testing.assert_array_equal(out,[1,1,1,0,0,0])

    def test_corrected_conditional_rule_retains_missing_and_ties(self):
        f=functions('receipt_numerics.py',['conditional_censor_mask'])['conditional_censor_mask']
        out=f(np.array([1,1,1,1,1,0],bool),np.full(6,100),np.full(6,50),np.array([-1,np.nan,200,150,125,-1]),np.ones(6,bool))
        np.testing.assert_array_equal(out,[1,1,1,1,0,0])

    def test_invalid_positive_censor_fails(self):
        for file,name,args in [('matched.py','censored_outcome',(np.array([1],bool),np.ones(1),np.array([100]),np.array([50]),np.array([99]))),
                               ('receipt_numerics.py','conditional_censor_mask',(np.array([1],bool),np.array([100]),np.array([50]),np.array([99]),np.ones(1,bool)))]:
            with self.assertRaises(RuntimeError):functions(file,[name])[name](*args)

    def test_sql_reach_any_and_count_nulls(self):
        source=read_source('receipt_panel.py')
        for expr in ['COALESCE(f.reached_fair_chooser_within_90d,FALSE)',
                     'COALESCE(f.any_fair_kind_grant_within_90d,FALSE)',
                     'COALESCE(fd.recipient_future_mercy_receipts_90d,0)']:
            # Check the actual producer expressions, not a rewritten estimator.
            self.assertIn(expr,source)
        c=duckdb.connect()
        try:
            row=c.execute('SELECT COALESCE(f.reached_fair_chooser_within_90d,FALSE), COALESCE(f.any_fair_kind_grant_within_90d,FALSE), COALESCE(fd.recipient_future_mercy_receipts_90d,0)::BIGINT FROM (SELECT NULL::BOOLEAN reached_fair_chooser_within_90d,NULL::BOOLEAN any_fair_kind_grant_within_90d) f CROSS JOIN (SELECT NULL::BIGINT recipient_future_mercy_receipts_90d) fd').fetchone()
            self.assertEqual(row,(False,False,0))
        finally:c.close()

    def test_iv_missing_choice_has_negative_times_but_false_flags(self):
        env=functions('iv_audit_logic.py',['moments','later_outcomes'])
        h=dict(gid=np.array(['future01']),ord=np.array([1]),t=np.array([250]),j=np.array([1]),start=np.array([200]),i=np.array([3]),y=np.array([True]))
        q=dict(row_id=np.array([0,1]),recipient_id=np.array([1,2]),opponent_id=np.array([4,4]),anchor_ms=np.array([100,100]),game_id=np.array(['index001','index002']))
        out=env['later_outcomes'](h,q)
        np.testing.assert_array_equal(out['reached'],[True,False])
        np.testing.assert_array_equal(out['observed_y'],[True,False])
        np.testing.assert_array_equal(out['outcome_t'],[250,-1])
        np.testing.assert_array_equal(out['outcome_start'],[200,-1])

    def test_iv_spacing_uses_anchor_not_optional_future_event(self):
        f=functions('iv_audit_logic.py',['spaced'])['spaced']
        person=np.array([1,1,1,2]);start=np.array([100,100+90*DAY,101+90*DAY,100]);anchor=start.copy()
        np.testing.assert_array_equal(f(person,start,anchor,np.ones(4,bool),90),[True,False,True,True])
        np.testing.assert_array_equal(f(person,start,anchor,np.ones(4,bool),0),np.ones(4,bool))
        np.testing.assert_array_equal(f(person,start,anchor,np.array([False,True,True,True]),90),[False,True,False,True])

    def test_iv_sql_next_exposure_null_is_not_an_event(self):
        query=sql('iv_model_kernel.py','SELECT count(*) FILTER(WHERE next_start<outcome_start)')
        c=duckdb.connect()
        try:
            c.execute('CREATE TABLE q (row_id BIGINT,recipient_id BIGINT,archive_start_ms BIGINT,outcome_start BIGINT,outcome_t BIGINT,reached BOOLEAN)')
            c.execute('INSERT INTO q VALUES (0,1,100,300,310,TRUE),(1,1,200,400,410,TRUE),(2,2,100,-1,-1,FALSE)')
            self.assertEqual(c.execute(query).fetchone(),(1,1))
        finally:c.close()

    def test_reputation_invalid_raw_chronology_is_filtered(self):
        tree=ast.parse(read_source('reputation_history.py'))
        matches=[n.value for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='valid' for t in n.targets) and 'bl' in ast.unparse(n.value)]
        self.assertEqual(len(matches),1)
        t=np.array([-1,100,100,100]);w=np.array([1,-1,1,1]);bl=np.array([2,2,-1,2])
        valid=eval(compile(ast.Expression(matches[0]),'actual_validity_expression','eval'),dict(t=t,w=w,bl=bl))
        np.testing.assert_array_equal(valid,[False,False,False,True])

    def test_reputation_prior_counts_are_nonnegative_integers(self):
        moments=functions('reputation_core.py',['moments'])['moments']
        f=functions('reputation_analysis.py',['pair_counts'],moments=moments)['pair_counts']
        times=np.array([69,70,99,100,111,140,200])*DAY
        out=f(np.full(7,7,np.uint64),times,np.array([7],np.uint64),np.array([100*DAY]),np.array([101*DAY]))
        self.assertEqual([int(out[k][0]) for k in ['prior30','prior90','meet30','meet90','meet180']],[2,3,1,2,3])
        for a in out.values():self.assertTrue(np.issubdtype(a.dtype,np.integer));self.assertTrue(np.all(a>=0))

    def test_reputation_missing_first_meeting_fails_guard(self):
        query=sql('reputation_history.py','SELECT count(*) FROM q LEFT JOIN f USING(pair_key) WHERE first_t IS NULL')
        c=duckdb.connect()
        try:
            c.execute('CREATE TABLE q AS SELECT 1 pair_key,100 AS "start" UNION ALL SELECT 2,100')
            c.execute('CREATE TABLE f AS SELECT 1 pair_key,50 first_t')
            self.assertEqual(c.execute(query).fetchone()[0],1)
        finally:c.close()

    def test_patron_returned_profile_requires_timestamp(self):
        guard=sql('patron_link_badge.py','SELECT count(*) FROM linked WHERE NOT coalesce(identity_resolved')
        c=duckdb.connect()
        try:
            c.execute('CREATE TABLE linked(identity_resolved BOOLEAN,profile_returned BOOLEAN,patron BOOLEAN,positive_support BOOLEAN,query_ms BIGINT,archive_start_ms BIGINT)')
            c.execute('INSERT INTO linked VALUES (TRUE,TRUE,FALSE,TRUE,NULL,100),(TRUE,TRUE,FALSE,TRUE,-1,100),(TRUE,FALSE,NULL,FALSE,NULL,100),(TRUE,TRUE,FALSE,TRUE,200,100)')
            self.assertEqual(c.execute(guard).fetchone()[0],2)
        finally:c.close()

    def test_rating_negative_one_is_real_outcome_null_is_nan(self):
        env=functions('validate_ratings.py',['extract'],FIELDS=[
         'chooser_color','outcome_kind_draw','timeout_chooser_win','timeout_chooser_loss','chooser_has_mating_material',
         'white_rating_diff_pgn','black_rating_diff_pgn','chooser_draw_payoff_v2','chooser_win_payoff_v2',
         'white_realized_pred_ratingdiff_v2','black_realized_pred_ratingdiff_v2'])
        t=pa.table(dict(chooser_color=['white','white'],outcome_kind_draw=[True,True],timeout_chooser_win=[False,False],
          timeout_chooser_loss=[False,False],chooser_has_mating_material=[True,True],white_rating_diff_pgn=pa.array([None,-1],type=pa.int64()),
          black_rating_diff_pgn=[1,1],chooser_draw_payoff_v2=[-1.,-1.],chooser_win_payoff_v2=[1.,1.],
          white_realized_pred_ratingdiff_v2=[-1.,-1.],black_realized_pred_ratingdiff_v2=[1.,1.]))
        out=env['extract'](t.to_batches()[0]);self.assertTrue(np.isnan(out['observed'][0]));self.assertEqual(out['observed'][1],-1)

if __name__=='__main__':unittest.main(verbosity=2)
