#!/usr/bin/env python3
"""Regression cases for errors seen only with multiple files per account bucket."""
from run_tests import *
from types import SimpleNamespace
import fw_repair

class RepairTests(unittest.TestCase):
    def test_multifile_buckets_match_global_history_and_FE_moments(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);d=synthetic_panel(24);source=root/'source.parquet';parquet(source,d)
            fragments=[]
            for bucket in range(4):
                rows=d.loc[d.chooser%4==bucket].sample(frac=1,random_state=bucket)
                for i,part in enumerate(np.array_split(np.arange(len(rows)),7)):
                    p=root/f'fragments/bucket={bucket}/{i}.parquet';parquet(p,rows.iloc[part]);fragments.append(p)
            parts=fw_inputs.consolidate_buckets(fragments,[source],root/'whole','whole',4,4)
            self.assertEqual(len(parts),4)
            expected,hist=fw_b.sample(d,{})
            X,_,groups=fw_design.b_design(expected,{})
            W=demean(X,expected.chooser.to_numpy());Y=demean(100*expected.y.to_numpy(float),expected.chooser.to_numpy())
            xx=np.zeros((W.shape[1],W.shape[1]));xy=np.zeros(W.shape[1]);seen=set();h=[]
            for i,p in enumerate(parts):
                ids=set(frame(p).chooser);self.assertFalse(ids&seen);seen|=ids
                _,hp=fw_b.sample(frame(p),{});h.append(hp)
                result=fw_b.stage1(dict(out=str(root/'moments'/str(i)),key=str(i),path=str(p),spec={}))
                with np.load(result) as z:xx+=z['xx'];xy+=z['xy']
            self.assertEqual(seen,set(d.chooser))
            pd.testing.assert_frame_equal(pd.concat(h).sort_values('chooser').reset_index(drop=True),hist.sort_values('chooser').reset_index(drop=True))
            np.testing.assert_allclose(xx,W.T@W,rtol=1e-10,atol=1e-8)
            np.testing.assert_allclose(xy,W.T@Y,rtol=1e-10,atol=1e-8)
            self.assertEqual(parts,fw_inputs.consolidate_buckets(fragments,[source],root/'whole','whole',4,4))

    def test_saved_fragment_scores_repair_matches_raw_and_reuses_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);parent=root/'parent';run=root/'new';d=synthetic_panel(8)
            p=root/'source.parquet';parquet(p,d)
            raw=fw_inputs.aggregate_accounts([p],root/'raw','raw',4)
            partial=[]
            for piece in np.array_split(np.arange(len(d)),13):
                v=d.iloc[piece].copy();v['residual']=100*(v.y-.03)
                for late in (False,True):
                    for state in ('C','N','L'):
                        use=v.ply>10 if late else np.ones(len(v),bool)
                        use &= v.board>=-100 if state=='C' else v.board< -100 if state=='N' else v.board<=-300
                        q=v.loc[use].groupby(['chooser','year']).agg(n=('y','size'),adjusted_sum=('residual','sum')).reset_index()
                        q['late']=late;q['state']=state;partial.append(q)
            old=parent/'F/adjustment';original=old/'adjusted_accounts.parquet';parquet(original,pd.concat(partial))
            (old/'report').mkdir();certify(old,digest(['oldkey','nuisance']),[p])
            save(run/'REUSE_PRIVATE.json',dict(parent=str(parent),parent_key='oldkey'))
            prior=stamp(original)
            result=fw_repair.adjusted(SimpleNamespace(memory_gb=4),run,'newkey')
            self.assertEqual(stamp(original),prior)
            out=frame(result).sort_values(['chooser','year','late','state']).reset_index(drop=True)
            expected=frame(raw).sort_values(['chooser','year','late','state']).reset_index(drop=True)
            pd.testing.assert_frame_equal(expected.drop(columns='y'),out.drop(columns=['adjusted_sum','adjusted']),check_dtype=False)
            np.testing.assert_allclose(out.adjusted,100*expected.y/expected.n-3,atol=1e-12)
            fw_f.wide_panel(raw,result,root/'wide','wide','N',False,4)
            self.assertEqual(result,fw_repair.adjusted(SimpleNamespace(memory_gb=4),run,'newkey'))

    def test_duplicate_adjusted_cells_are_rejected_even_if_counts_equal(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'p.parquet';parquet(src,synthetic_panel(4))
            raw=fw_inputs.aggregate_accounts([src],root/'raw','raw',4);d=frame(raw);d['adjusted']=0.
            adj=root/'adj.parquet';parquet(adj,pd.concat([d,d.iloc[[0]]]))
            with self.assertRaisesRegex(RuntimeError,'Duplicate account'):
                fw_f.wide_panel(raw,adj,root/'wide','w','N',False,4)

    def test_S0_timestamp_contract_without_F50_flag(self):
        end=1761955200000;anchor=end-91*fw_e.DAY
        d=dict(anchor_ms=np.array([anchor]),archive_start_ms=np.array([anchor-1000]),
            received=np.array([1]),y=np.array([0]),reached=np.array([1]))
        fw_e.validate_iv_followup(d,end)
        for bad in [dict(d,anchor_ms=np.array([end-90*fw_e.DAY])),dict(d,complete90=np.array([False])),dict(d,y=np.array([np.nan]))]:
            with self.assertRaises(RuntimeError):fw_e.validate_iv_followup(bad,end)

    def test_logit_column_units_do_not_change_fit(self):
        rng=np.random.default_rng(911);groups=[]
        for _ in range(70):
            x=rng.normal(size=(8,2));x-=x.mean(axis=0);y=rng.binomial(1,1/(1+np.exp(-x@np.array([.5,-.3]))))
            if 0<y.sum()<8:groups.append((x,y))
        b,V,_,info=fw_b_extra.conditional_fit(groups,['x','z'])
        units=np.array([1e6,1e-6])
        bb,VV,_,info2=fw_b_extra.conditional_fit([(x*units,y) for x,y in groups],['x','z'])
        np.testing.assert_allclose(bb*units,b,atol=1e-6)
        np.testing.assert_allclose(VV*units[:,None]*units[None,:],V,atol=1e-6)
        self.assertLess(info['max_log_odds_newton_correction'],1e-5)
        self.assertLess(info2['max_log_odds_newton_correction'],1e-5)

if __name__=='__main__':unittest.main()
