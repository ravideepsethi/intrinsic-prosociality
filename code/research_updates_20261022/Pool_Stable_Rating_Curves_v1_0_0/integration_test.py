#!/usr/bin/env python3
"""Small synthetic end-to-end run including process workers, plots and restart.

Test-only mock sample counts; production source authentication is not bypassed
by any run_stable.py option. Outputs are temporary synthetic test artifacts.
"""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import json,tempfile
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from self_test import synthetic
from pooled_engine import PooledMoments
import run_stable

def main():
    f,edges=synthetic(seed=9052,accounts=48)
    m=PooledMoments(edges);m.add(f)
    def check(counts):
        assert counts['estimation_rows']==m.N
        assert counts['chooser_clusters']==m.G
        assert counts['absorbed_chooser_state_units']==m.H
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);paths=[]
        for k in range(2):
            mask=f['chooser']%2==k;path=root/f'shard{k}.parquet'
            pq.write_table(pa.table({name:v[mask] for name,v in f.items() if name!='normalized'}),path,row_group_size=51);paths.append(path)
        report=root/'report';report.mkdir()
        with patch.object(run_stable,'validate_retained_counts',check),patch.dict(run_stable.EXPECTED,{'fair_rows':len(f['y']),'fair_kind_draws':int(f['y'].sum())}),patch.dict(run_stable.SUPPORT,{'min_n':1,'min_choosers':1,'min_months':1}):
            counts=run_stable.estimate(paths,edges,'synthetic-integration',2,73,report)
            assert len(counts)==5
            assert len(list((report/'figures').glob('*.png')))==5
            first=(report/'curves.csv').read_bytes();zeros=(report/'zero_diagnostics.csv').read_bytes()
            counts2=run_stable.estimate(paths,edges,'synthetic-integration',2,73,report)
            assert first==(report/'curves.csv').read_bytes()
            assert zeros==(report/'zero_diagnostics.csv').read_bytes()
            assert counts==counts2
            # Persist figures only if explicitly requested for development QA.
            if os.environ.get('STABLE_TEST_COPY_TO'):
                import shutil
                shutil.copytree(report,Path(os.environ['STABLE_TEST_COPY_TO']),dirs_exist_ok=True)
        print('INTEGRATION_OK: five samples, all three axes, process workers, figures, verified identical restart')

if __name__=='__main__':main()
