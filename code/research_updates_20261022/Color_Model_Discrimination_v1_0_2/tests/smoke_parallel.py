"""Expected runtime: 5–20 seconds. Exercise spawn workers and restart receipts."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from test_science import fixture
from io_utils import *
from predict import prediction_job
from run import run_jobs,bundle

def main():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);frame(fixture(nweeks=52),p/'train.parquet')
        jobs=[(str(p/'train.parquet'),str(p/'train.parquet'),str(ROOT/'authority/fits'/f'{m}_full.json'),m,'full','smoke',str(p/'work'),'synthetic') for m in ('framing','curved','strength')]
        first=run_jobs(prediction_job,jobs,2);second=run_jobs(prediction_job,jobs,2)
        assert sorted(first,key=lambda x:x['model'])==sorted(second,key=lambda x:x['model'])
        report=p/'COLOR_MODEL_RESULT_SYNTHETIC';report.mkdir();write(report/'SUMMARY.json',{'synthetic':True,'parallel_restart':'PASS'})
        z=bundle(report,p/'desktop');assert sha(z)==Path(str(z)+'.sha256').read_text().split()[0]
        print('PARALLEL_RESUME_AND_RESULT_BUNDLE_PASS')

if __name__=='__main__':main()
