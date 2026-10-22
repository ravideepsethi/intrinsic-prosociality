from util import *
import tempfile,multiprocessing
from self_test import focal_frame
from repetition import run

def main():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);files=[];d=focal_frame(6000)
  for j,m in enumerate(MONTHS):
   f=root/'PRIVATE/history'/m/'focal_history.parquet';f.parent.mkdir(parents=True)
   d.loc[d.month_code==j].to_parquet(f,index=False);files.append(str(f))
  for j,m in enumerate(['2023-10']+MONTHS):
   f=root/'PRIVATE/history'/m/'sessions30.parquet';f.parent.mkdir(parents=True,exist_ok=True)
   pd.DataFrame(dict(chooser=[1,2,3],start30=[1699000000000+j*100000000]*3,observed_session_length=[2,3,18],left_censored=[False]*3,last_t=[1699003000000+j*100000000]*3)).to_parquet(f,index=False)
  r=run(files,root,'testdriver',2,3)
  assert r['status']=='ESTIMATED'
  results=pd.read_csv(root/'report/repetition/coefficients.csv')
  assert len(results)==100 and results.estimable.all()
  assert len(load(root/'report/repetition/primary_family.json'))==4
  print('DRIVER_OK',len(results),'contrasts; all report tables built; spawn workers')
if __name__=='__main__':
 multiprocessing.set_start_method('spawn')
 main()
