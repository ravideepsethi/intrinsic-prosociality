#!/usr/bin/env python3
"""Synthetic two-worker test of the actual estimator, report and restart paths."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
import tempfile,shutil
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from self_test import synthetic
from pooled_engine import PooledMoments
import run_split

def main():
    f,edges=synthetic(seed=4424,accounts=64)
    m=PooledMoments(edges);m.add(f)
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);paths=[]
        for k in range(2):
            keep=f['chooser']%2==k;path=root/f'shard{k}.parquet'
            pq.write_table(pa.table({name:v[keep] for name,v in f.items()}),path,row_group_size=53);paths.append(path)
        report=root/'report';report.mkdir()
        with patch.dict(run_split.SUPPORT,{'min_n':1,'min_choosers':1,'min_months':1}):
            counts=run_split.estimate(paths,edges,'synthetic-split-zero',2,73,report,production=False)
            assert counts['estimation_rows']==m.N
            assert counts['chooser_clusters']==m.G
            assert len(list((report/'figures').glob('*.png')))==4
            before=(report/'curves.csv').read_bytes()
            checks=(report/'near_zero_contrasts.csv').read_bytes()
            again=run_split.estimate(paths,edges,'synthetic-split-zero',2,73,report,production=False)
            assert before==(report/'curves.csv').read_bytes()
            assert checks==(report/'near_zero_contrasts.csv').read_bytes()
            assert counts==again
        if os.environ.get('SPLIT_ZERO_TEST_COPY_TO'):
            shutil.copytree(report,Path(os.environ['SPLIT_ZERO_TEST_COPY_TO']),dirs_exist_ok=True)
        print('INTEGRATION_OK: two workers, separate zero bins, plots, sample counts and identical checkpoint restart')

if __name__=='__main__':main()
