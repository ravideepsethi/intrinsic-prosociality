"""End-to-end estimator/report exercise on generated data, not research results."""
import sys,tempfile,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_core import fixture
from common import *
from support import make_support,surface,estimate_cost,mechanical_curves
from models import compare,prediction_profiles,decision
from extras import index_scaling,cue_data
from recovery import prepare_recovery,recovery_task,summarize_recovery
from policy import run_policy
from figures import figures

def main():
    start=time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);work=p/'work';report=p/'report';report.mkdir();work.mkdir()
        d=fixture(800)
        # Add settled and mildly varying own RD so both K branches have support.
        rng=np.random.default_rng(3);d.loc[d.chooser%3==0,'rd']=rng.uniform(45.02,70,(d.chooser%3==0).sum())
        from design import counterfactual
        d=counterfactual(d)
        s=make_support(d,report,'regular_equal')
        mechanical_curves(d,np.quantile(2*d.loc[d.rd>=45.01,'ki'],[.25,.5,.75]),report)
        fits,scores=compare(d,work/'models',report,'regular_equal')
        assert all(f['status']=='ESTIMATED' for f in fits.values()),{k:v['status'] for k,v in fits.items()}
        assert len(scores)==7*12,len(scores)
        surface(d,np.quantile(2*d.loc[d.rd>=45.01,'ki'],[.25,.5,.75]),report,'regular_equal')
        index_scaling(d,report,'regular_equal');prediction_profiles(d,fits,report,'regular_equal')
        estimate_cost(d,s,report,'regular_equal');run_policy(d,fits,p,work,report)
        cd,m=cue_data(p,work,d,report);assert cd is None and m is None
        data,probs=prepare_recovery(d,fits,work)
        model,pr=next((m,pr) for m,pr in probs if m=='cost')
        result=recovery_task((data,pr,model,0,str(work),2026092601))
        result2=recovery_task((data,pr,model,0,str(work),2026092601))
        assert result==result2
        summarize_recovery([result],report,1)
        figures(report)
        assert (report/'Figure_M1.pdf').is_file()
        before={p.name:p.stat().st_mtime_ns for p in (work/'models').glob('*.json')}
        again,_=compare(d,work/'models',report,'regular_equal')
        after={p.name:p.stat().st_mtime_ns for p in (work/'models').glob('*.json')}
        assert before==after,'Completed model fits were rerun'
        print('SYNTHETIC_PIPELINE_OK',dict(rows=len(d),models=len(fits),heldout_month_model_cells=len(scores),
              selected=decision(scores),recovery=result['selected'],elapsed_seconds=round(time.monotonic()-start,2)),flush=True)

if __name__=='__main__':main()
