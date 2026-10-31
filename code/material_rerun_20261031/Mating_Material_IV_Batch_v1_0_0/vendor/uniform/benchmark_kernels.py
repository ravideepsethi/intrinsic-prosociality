"""Optional synthetic kernel benchmark; does not touch private project data."""
from fast_bootstrap import *
import tempfile,contextlib,io,platform
import uniform_features as oldf
import fast_features as newf
import rebuild_models as oldm
import fast_models as newm
import finish_covariance as oldcov
import fast_covariance as newcov

def main():
    rng=np.random.default_rng(164);result=dict(environment=platform.platform(),numpy=np.__version__,
        warning='Synthetic kernels on this machine; not a full-run or Mac runtime estimate')
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);q=root/'query';q.mkdir();n=500000;events=1000000
        people=rng.integers(0,100000,n);times=rng.integers(90,731,n)*DAY
        keys=oldf.moments(people,times);order=np.argsort(keys,kind='stable');keys=keys[order];ids=np.unique(people)
        for name,value in [('keys',keys),('people',ids),('order',order)]:np.save(q/(name+'.npy'),value)
        save(q/'meta.json',dict(minimum=int(times.min()),maximum=int(times.max())))
        packed=newf.prepare_packed(q,'benchmark');meta=load(packed/'meta.json');pk=np.load(packed/'packed.npy')
        t=rng.integers(0,730,events)*DAY;w=rng.integers(0,200000,events);b=rng.integers(0,200000,events)
        a=np.zeros(n+1,np.int64);bb=a.copy()
        start=time.monotonic();oldf.accumulate90(t,w,b,keys,ids,a);old=time.monotonic()-start
        start=time.monotonic();newf.accumulate_packed(t,w,b,pk,ids,bb,meta);new=time.monotonic()-start
        np.testing.assert_array_equal(a,bb)
        result['volume_lookup']=dict(queries=n,games=events,old_seconds=old,new_seconds=new,speedup=old/new,integer_results_identical=True)
        del keys,pk,a,bb,people,times,order,t,w,b;gc.collect()
        n=500000;people=rng.integers(0,200000,n);opponent=rng.integers(200000,400000,n);dates=rng.integers(0,730,n)
        score=rng.normal(0,1e-6,(n,4));cols=['v0','v1','v2','v3'];p=root/'influence.parquet'
        pq.write_table(pa.table(dict(recipient_id=people,opponent_id=opponent,date=dates,**{k:score[:,j] for j,k in enumerate(cols)})),p)
        with contextlib.redirect_stdout(io.StringIO()):
            start=time.monotonic();a=oldcov.covariance(p,cols,root/'oldcov');old=time.monotonic()-start
            start=time.monotonic();b=newcov.covariance(p,cols,root/'newcov');new=time.monotonic()-start
        np.testing.assert_allclose(a,b,rtol=1e-9,atol=1e-16)
        result['covariance']=dict(rows=n,terms=4,old_seconds=old,new_seconds=new,speedup=old/new,max_absolute_difference=float(abs(a-b).max()))
        del people,opponent,dates,score;gc.collect()
        n=300000;p=24;v=np.array(rng.normal(size=(n,p)),order='F')
        groups=[rng.integers(0,5000,n),rng.integers(0,730,n),rng.integers(0,168,n)]
        before=oldm.disk_matrix(root/'design.dat',n,p);before[:]=v
        with contextlib.redirect_stdout(io.StringIO()):
            start=time.monotonic();a,ar,ad=oldm.project(before,groups,4,root);old=time.monotonic()-start
            start=time.monotonic();b,br,bd=newm.project(v,groups,4,root);new=time.monotonic()-start
        np.testing.assert_allclose(a,b,rtol=1e-7,atol=2e-9);assert ar==br
        result['projection']=dict(rows=n,columns=p,threads=bd['threads'],old_seconds=old,new_seconds=new,speedup=old/new,max_absolute_difference=float(abs(a-b).max()))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
