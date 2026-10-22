#!/usr/bin/env python3
"""Numerical tests for the new likelihoods; synthetic observations only."""
import bootstrap_path
import itertools,unittest,tempfile
from pathlib import Path
from dataclasses import asdict
import numpy as np
from scipy.special import expit
from scipy.optimize._numdiff import approx_derivative
from fixture import fixture
from prepare import encode,subset,C0,C1
from engine import Model,Spec,SWITCHING,CHALLENGE,predict,simulate,transfer
from switching import SwitchingModel,forward_backward
from parent_audit import manifest
from io_utils import digest
from followup_analysis import fit_order,compatible_sources


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        arrays,cls.meta=encode(fixture(100,100,36),1)
        cls.data=subset(arrays['development'],arrays['development']['ids']<8)

    def result(self,m,v):return dict(spec=asdict(m.spec),J=m.J,bound=m.bound,parameters=v.tolist())

    def test_gradients_all_switching_families(self):
        for s in SWITCHING[1:]:
            with self.subTest(name=s.name):
                m=Model(s,2,self.meta);v=m.start(5)
                d=dict(self.data,aw=np.arange(len(self.data['ptr'])-1)%3)
                _,g=m.objective(v,d,.002)
                n=approx_derivative(lambda x:m.objective(x,d,.002)[0],v).ravel()
                np.testing.assert_allclose(g,n,rtol=2e-5,atol=2e-6)

    def test_forward_equals_joint_likelihood(self):
        for s in SWITCHING[1:]:
            m=Model(s,2,self.meta);v=m.start(8)
            p,ll,_=m.predict(v,self.data)
            obj=m.objective(v,self.data,0)[0]
            self.assertAlmostEqual(-obj*(len(self.data['ptr'])-1),ll.sum(),places=9)
            self.assertTrue(np.all((p>=0)&(p<=1)))

    def test_tiny_sequence_enumeration(self):
        data=subset(self.data,(self.data['ids']==0)&(np.arange(len(self.data['y']))<3))
        data=dict(data,y=np.array([0.,1.,0.]))
        m=Model(Spec('hmm_unrestricted','desert'),2,self.meta);v=m.start(2);U,d=m.utilities(v,data)
        total=0.
        for k in range(2):
            for states in itertools.product(range(2),repeat=3):
                prob=np.exp(d['lp'][0,k]+d['loginit'][states[0]])
                for r,h in enumerate(states):
                    if r:prob*=np.exp(d['logT'][states[r-1],h])
                    p=expit(U[r,k,h]);prob*=p if data['y'][r] else 1-p
                total+=prob
        self.assertAlmostEqual(np.log(total),m.predict(v,data)[1].sum(),places=12)

    def test_no_future_outcomes_in_forecasts(self):
        m=Model(Spec('hmm_gate','desert'),2,self.meta);v=m.start(3)
        orig=m.predict(v,self.data)[0];d=dict(self.data);d['y']=d['y'].copy();d['y'][8]=1-d['y'][8]
        changed=m.predict(v,d)[0];np.testing.assert_array_equal(orig[:9],changed[:9])

    def test_static_exactly_embeds(self):
        static=Model(Spec('desert','desert'),2,self.meta);v=static.start(4);r=self.result(static,v)
        for kind in ['hmm','iid']:
            for family in ['willingness','unrestricted']:
                m=Model(Spec(kind+'_'+family,'desert'),2,self.meta);w=transfer(r,m,self.meta)
                a,b=predict(r,self.data,self.meta);c,e=m.predict(w,self.data)[:2]
                np.testing.assert_allclose(a,c,atol=1e-13);np.testing.assert_allclose(b,e,atol=1e-13)
                self.assertAlmostEqual(static.objective(v,self.data,.003)[0],m.objective(w,self.data,.003)[0],places=11)

    def test_iid_embeds_in_markov(self):
        for f in ['willingness','gate','gatecost','unrestricted']:
            src=Model(Spec('iid_'+f,'desert'),2,self.meta);v=src.start(3)
            dst=Model(Spec('hmm_'+f,'desert'),2,self.meta);w=transfer(self.result(src,v),dst,self.meta)
            np.testing.assert_allclose(src.predict(v,self.data)[1],dst.predict(w,self.data)[1],atol=1e-13)

    def test_gate_embeds_in_unrestricted(self):
        for f in ['gate','gatecost','willingness']:
            src=Model(Spec('hmm_'+f,'desert'),2,self.meta);v=src.start(3)
            dst=Model(Spec('hmm_unrestricted','desert'),2,self.meta);w=transfer(self.result(src,v),dst,self.meta)
            np.testing.assert_allclose(src.predict(v,self.data)[1],dst.predict(w,self.data)[1],atol=1e-13)

    def test_restrictions_and_anchors(self):
        for name in ['board_only','no_stage','no_expected']:
            m=Model(Spec(name,'desert'),2,self.meta);lo,hi=np.array(m.bounds).T;v=np.clip(m.start(3),lo,hi)
            A=m.decode(v)['A'].reshape(5,4,5)
            self.assertAlmostEqual(A.ravel()[C0],0);self.assertAlmostEqual(A.ravel()[C1],1)
            if name in ['board_only','no_stage']:np.testing.assert_allclose(A,np.repeat(A[:,2:3,:],4,axis=1))
            if name in ['board_only','no_expected']:np.testing.assert_allclose(A,np.repeat(A[:,:,2:3],5,axis=2))

    def test_extreme_utilities_stay_finite(self):
        m=Model(Spec('hmm_unrestricted','desert'),2,self.meta);v=m.start(4)
        v[m.slices['theta']]=12.;v[m.slices['g']]=12.;v[m.slices['h']]=12.
        obj,g=m.objective(v,self.data);p,ll,_=m.predict(v,self.data)
        self.assertTrue(np.isfinite(obj) and np.all(np.isfinite(g)) and np.all(np.isfinite(ll)))

    def test_simulation_reproducible(self):
        m=Model(Spec('hmm_gate','desert'),2,self.meta);r=self.result(m,m.start(4))
        a,t,p=simulate(r,self.data,self.meta,np.random.default_rng(8));b,u,q=simulate(r,self.data,self.meta,np.random.default_rng(8))
        np.testing.assert_array_equal(a['y'],b['y']);np.testing.assert_array_equal(t,u);np.testing.assert_array_equal(p,q)

    def test_manifest_rejects_changed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'data';p.write_text('original')
            (root/'MANIFEST').write_text(digest(p)+'  data\n')
            self.assertEqual(manifest(root,'MANIFEST')['data'],digest(p))
            p.write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'Checksum mismatch'):manifest(root,'MANIFEST')

    def test_manifest_rejects_parent_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'MANIFEST').write_text('0'*64+'  ../outside\n')
            with self.assertRaisesRegex(RuntimeError,'Invalid manifest path'):manifest(root,'MANIFEST')

    def test_nested_static_objectives_equal_at_same_penalty(self):
        # This is the condition violated by the returned six-type full refit.
        for source,target in [('desert','both'),('no_cost','both'),('premium_only','both'),
                              ('both','separate_costs'),('separate_costs','signed_costs')]:
            specs={s.name:s for s in CHALLENGE}
            src=Model(specs[source],2,self.meta);v=src.start(17)
            dst=Model(specs[target],2,self.meta)
            w=transfer(self.result(src,v),dst,self.meta)
            self.assertAlmostEqual(src.objective(v,self.data,.001)[0],dst.objective(w,self.data,.001)[0],places=10)

    def test_dependency_order_and_support_matching(self):
        specs={s.name:s for s in CHALLENGE+SWITCHING}
        fits={n:dict(spec=asdict(s),J=2) for n,s in specs.items()}
        order=fit_order(fits)
        for n in order:
            for source,_ in compatible_sources(n,fits[n],fits):self.assertLess(order.index(source),order.index(n))
        fits['desert']['J']=3
        self.assertNotIn('desert',[n for n,_ in compatible_sources('both',fits['both'],fits)])


if __name__=='__main__':unittest.main(verbosity=2)
