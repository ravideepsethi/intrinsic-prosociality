import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
import r8_clocks as m
from r8_util import *
from self_test import fixture

class ClockTests(unittest.TestCase):
    def test_clock_boundaries_and_two_fast_speeds(self):
        codes=m.clock_codes([0,9.999,10,24.99,25,49.99,50,100,100.01,-1,np.nan,10],[100]*11+[0])
        self.assertEqual(codes.tolist(),[0,0,1,1,2,2,3,3,4,5,5,5])
        d=fixture(10,40);d['base']=60.;d['author_game']=False
        s=dict(name='cats',kind='spline',sample='competitive_late',controls='clock_categories_by_speed')
        a=m.select(d,s);X,names,p,groups,ng=m.design(a,s)
        self.assertEqual(len(names),76);self.assertEqual(p,6)
        col=names.index('clock_c_lt10pct:ultrabullet_bullet')
        both=a.speed_code.isin([0,1]).to_numpy()&(m.clock_codes(a.clock_c,a.base)==0)
        np.testing.assert_array_equal(X[:,col],both)

    def test_new_design_and_chooser_covariance_against_explicit_dummy_OLS(self):
        d=fixture(70,45);d['base']=np.tile([60,180,600],len(d)//3+1)[:len(d)]
        d['author_game']=np.arange(len(d))%67==0
        d.loc[np.arange(len(d))%19==0,'clock_c']=np.nan
        d.loc[np.arange(len(d))%29==0,'clock_d']=-1
        for control in ('base','clock_categories_by_speed','clock_log_by_speed'):
            s=dict(name='author_clean_'+control,kind='spline',sample='competitive_late',controls=control)
            a=m.select(d,s);X,names,p,group,ng=m.design(a,s);y=a.y.to_numpy(float)*100
            mm,_,_,_=m.me.moments(d,s);beta,inv,scale,null,rank=m.me.solve(mm['xx'],mm['xy'])
            f=dict(beta=beta,inverse=inv,scale=scale,null=null,rank=rank,names=names,p=p,ng=ng,
                mean_y=float(mm['y_sum']/mm['n']),mean_f=mm['f_sum']/mm['n'],group_share=mm['group_sum']/mm['n'],
                n=int(mm['n']),g=int(mm['g']))
            starts,counts=m.me.grouped(a.chooser.to_numpy());codes=np.repeat(np.arange(len(starts)),counts)
            D=np.column_stack([np.eye(len(starts))[codes],X]);b=np.linalg.lstsq(D,y,rcond=1e-11)[0]
            W,v,_,_=m.me.within(X,y,a.chooser.to_numpy())
            np.testing.assert_allclose(W@beta,W@b[len(starts):],atol=2e-7)
            residual=y-D@b;scores=np.add.reduceat(D*residual[:,None],starts,axis=0)
            bread=np.linalg.pinv(D.T@D,rcond=1e-11);direct=bread@(scores.T@scores)@bread*len(starts)/(len(starts)-1)
            M=m.me.meat(d,s,f);V=m.me.coefficient_cov(f,M)
            delta=np.zeros(len(beta));delta[:p]=(m.md.counterfocal(s,dict(cp=300),1)-m.md.counterfocal(s,dict(cp=0),1))[0]
            R=np.r_[np.zeros(len(starts)),delta]
            np.testing.assert_allclose(delta@V@delta,R@direct@R,rtol=3e-7,atol=3e-7)
            chunks=[d.loc[d.chooser%3==j] for j in range(3)]
            for name in mm:np.testing.assert_allclose(sum(m.me.moments(chunk,s)[0][name] for chunk in chunks),mm[name],rtol=1e-10,atol=1e-7)
            np.testing.assert_allclose(sum(m.me.meat(chunk,s,f) for chunk in chunks),M,rtol=1e-8,atol=1e-5)

    def test_partition_checkpoint_reuse_and_tamper_rejection(self):
        d=fixture(20,20);d['base']=60.;d['author_game']=False
        s=[dict(name='author_clean_base',kind='spline',sample='competitive_late',controls='base')]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);src=root/'d.parquet';d.to_parquet(src,index=False)
            task=dict(key='fixture',phase=1,bucket=0,specs=s,files=[str(src)],folder=str(root/'fit'))
            out=Path(m.bucket(task));before=out.stat().st_mtime_ns;self.assertEqual(m.bucket(task),str(out));self.assertEqual(before,out.stat().st_mtime_ns)
            with out.open('ab') as f:f.write(b'changed')
            with self.assertRaisesRegex(RuntimeError,'Checkpoint output changed'):m.bucket(task)

    def test_spawned_two_pass_chooser_partitions_equal_whole_fit(self):
        d=fixture(30,40);d['base']=60.;d['author_game']=False
        specs=[dict(name='author_clean_cats',kind='spline',sample='competitive_late',controls='clock_categories_by_speed')]
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);parts=[]
            for j in range(2):
                z=d.loc[d.chooser%2==j];src=root/f'part{j}.parquet';z.to_parquet(src,index=False)
                parts.append(dict(bucket=j,files=[str(src)],rows=len(z)))
            fits,meats=m.fit_set(parts,specs,root/'two_pass','fixture',2)
            M,_,_,_=m.me.moments(d,specs[0]);expected=m.me.solve(M['xx'],M['xy'])[0]
            np.testing.assert_allclose(fits[0]['beta'],expected,rtol=1e-7,atol=1e-7)
            np.testing.assert_allclose(meats[0],m.me.meat(d,specs[0],fits[0]),rtol=1e-8,atol=1e-5)

if __name__=='__main__':unittest.main(verbosity=2)
