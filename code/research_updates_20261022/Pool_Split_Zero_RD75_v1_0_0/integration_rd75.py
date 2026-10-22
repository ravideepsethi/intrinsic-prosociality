#!/usr/bin/env python3
"""Exercise actual two-process filtering, checkpoints, overlay, and reports."""
import os
for key in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):os.environ[key]='1'
from pathlib import Path
import tempfile,shutil,json
from unittest.mock import patch
import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np
from self_test import synthetic
from pooled_engine import PooledMoments
import run_split
from comparison_report import build_comparison,read_curves

def main():
    f,edges=synthetic(seed=12356,accounts=64)
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);paths=[]
        for j in range(2):
            ix=f['chooser']%2==j;p=root/f'shard{j}.parquet'
            pq.write_table(pa.table({k:v[ix] for k,v in f.items()}),p,row_group_size=53);paths.append(p)
        report=root/'report';report.mkdir()
        with patch.dict(run_split.SUPPORT,dict(min_n=1,min_choosers=1,min_months=1)):
            for sample in ('all','rd75'):
                dest=report/sample;dest.mkdir()
                m=PooledMoments(edges);m.add(run_split.select_sample(f,sample))
                counts=run_split.estimate(paths,edges,'rd75-integration-'+sample,2,73,dest,production=False,sample=sample)
                assert counts==run_split.count_record(m,sample)
            before=(report/'rd75/curves.csv').read_bytes()
            again=run_split.estimate(paths,edges,'rd75-integration-rd75',2,73,report/'rd75',production=False,sample='rd75')
            assert before==(report/'rd75/curves.csv').read_bytes()
        build_comparison(report,report/'all',report/'rd75')
        assert len(list((report/'figures').glob('*.png')))==4
        assert len(list((report/'figures').glob('*.pdf')))==4
        combined=read_curves(report/'curves.csv')
        original=read_curves(report/'all/curves.csv')
        assert [r for r in combined if r['sample']=='all']==original
        if os.environ.get('RD75_TEST_COPY_TO'):
            shutil.copytree(report,Path(os.environ['RD75_TEST_COPY_TO']),dirs_exist_ok=True)
        print('RD75_INTEGRATION_OK: two workers, sample-specific filter/counts, identical checkpoint restart, full-sample unchanged, paired figures')

if __name__=='__main__':main()
