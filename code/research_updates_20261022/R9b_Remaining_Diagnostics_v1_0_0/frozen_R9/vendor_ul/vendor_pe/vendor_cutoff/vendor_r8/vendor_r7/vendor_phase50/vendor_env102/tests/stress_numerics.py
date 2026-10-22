"""Optional large synthetic numerical check; no production data or API calls.

Expected runtime: roughly 1–5 minutes on a laptop at 2,349,418 rows, unbenchmarked
on the user's Mac. Uses about 2–3 GiB RAM. Normal launcher tests are smaller.
Run: python tests/stress_numerics.py --output numerical_stress.json
"""
import argparse
import json
import sys
import time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from env_common import num
from env_numerics import absorb


def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',type=int,default=2349418)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    began=time.monotonic();rng=np.random.default_rng(651);n=args.rows
    day=rng.integers(0,630,n);month=day//30
    cell=month*40+rng.integers(0,40,n);hour=(day%7)*24+rng.integers(0,24,n)
    cell[-1]=99999
    groups=[cell,day,hour]
    a=rng.normal(size=(n,37));a[:,0]=1.;a[:,1]=day/630
    a[:,20:30]=(a[:,20:30]>1.8).astype(float)
    a[:,36]=a[:,3]+a[:,4]
    out,diagnostics=absorb(a,groups)
    # A different group accumulator, using only two columns, checks the large
    # fit without doubling the memory for a second full-width residual matrix.
    old,it=num.absorb(a[:,[18,36]],groups)
    err=float(np.max(np.abs(old-out[:,[18,36]])))
    if err>5e-8:raise AssertionError('Large independent-accumulator comparison failed')
    result=dict(synthetic_only=True,private_Mac_failure_trigger_reproduced=False,
                rows=n,columns=37,seconds=time.monotonic()-began,
                legacy_two_column_iterations=it,max_difference_vs_legacy_two_columns=err,
                diagnostics=diagnostics,status='PASSED')
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='diagnostics'},indent=2),flush=True)

if __name__=='__main__':main()
