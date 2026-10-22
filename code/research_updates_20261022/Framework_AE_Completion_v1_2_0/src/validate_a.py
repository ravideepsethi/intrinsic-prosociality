#!/usr/bin/env python3
"""Flag sensitivities have an exact paper cohort and a transparent regressor reconstruction.

Calibrate unflagged point estimates against Table 3; never silently call a new
control vector the original estimated design if its estimates do not match.
"""
import argparse,json,math
from pathlib import Path
import pandas as pd
ap=argparse.ArgumentParser();ap.add_argument('--table',required=True);ap.add_argument('--out',required=True)
a=ap.parse_args()
df=pd.read_csv(a.table)
anchors={('A','focal_competitive_granter'):0.277,
 ('B','ever_competitive_grant'):0.388,('B','ever_lost_grant'):-0.195}
checks=[]
for (p,t),ref in anchors.items():
 sub=df[(df.panel==p)&(df.restriction=='all')&(df.estimand==t)]
 if len(sub)!=1:raise ValueError(f'Unable to find one Panel {p} baseline {t}: {len(sub)} rows')
 val=float(sub.iloc[0]['estimate_pp']);checks.append(dict(panel=p,estimand=t,paper_estimate_pp=ref,
        reconstructed_estimate_pp=val,absolute_difference_pp=abs(val-ref),
        baseline_close=abs(val-ref)<0.035))
result={'checks':checks,'baseline_close_all':all(q['baseline_close'] for q in checks),
 'status':'RECONSTRUCTED_CONTROLS_CLOSE_TO_MANUSCRIPT' if all(q['baseline_close'] for q in checks)
          else 'ALTERNATIVE_CONTROL_RECONSTRUCTION_ONLY',
 'caution':'Same frozen cohorts and August flags; baseline control engineering reconstructed from source features and may differ from original executed source. HC1 and cell-cluster SEs sensitivity only. A3 recipient-side analysis not included.'}
out=Path(a.out);out.write_text(json.dumps(result,indent=2)+'\n')
print('A baseline calibration:',result['status'])
for r in checks:print(r)
