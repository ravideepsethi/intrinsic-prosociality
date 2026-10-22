#!/usr/bin/env python3
"""Synthetic two-worker end-to-end and restart validation; never a real run."""
import os
for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS'):
    os.environ[key] = '1'
from pathlib import Path
import argparse
from contextlib import nullcontext
import tempfile
import time
import pyarrow as pa
import pyarrow.parquet as pq
from self_test import synthetic
from run_followups import estimate
from followup_specs import definitions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', type=Path, help='Keep synthetic validation artifacts for visual inspection')
    args = parser.parse_args()
    start = time.monotonic()
    f, edges = synthetic(accounts=20, rows_per_state=28)
    if args.output_root: args.output_root.mkdir(parents=True, exist_ok=True)
    manager = nullcontext(str(args.output_root)) if args.output_root else tempfile.TemporaryDirectory(prefix='stable_zero_followups_synthetic_')
    with manager as tmp:
        root = Path(tmp); private = root/'PRIVATE'; private.mkdir(); report = root/'report'; report.mkdir()
        paths = []
        for j in range(2):
            mask = f['chooser'] % 2 == j; path = private/f'shard_{j}.parquet'
            pq.write_table(pa.table({k: v[mask] for k, v in f.items()}), path, row_group_size=67); paths.append(path)
        estimate(paths, edges, 'SYNTHETIC_TEST_ONLY', 2, 1024, private, report, definitions(), production=False)
        before = {str(p): p.stat().st_mtime_ns for p in (private/'estimation').rglob('*.npz')}
        table = (report/'local_estimates.csv').read_bytes()
        estimate(paths, edges, 'SYNTHETIC_TEST_ONLY', 2, 1024, private, report, definitions(), production=False)
        after = {str(p): p.stat().st_mtime_ns for p in (private/'estimation').rglob('*.npz')}
        assert before == after, 'Restart rewrote completed estimation checkpoints'
        assert table == (report/'local_estimates.csv').read_bytes(), 'Restart changed aggregate results'
        assert len(list((report/'figures').glob('*.png'))) == 5
        assert len(list(report.glob('*.parquet'))) == 6
        assert not (report/'_SUCCESS.json').exists(), 'Synthetic run must not receive a production receipt'
        print('INTEGRATION_AND_RESTART_OK elapsed_seconds='+str(round(time.monotonic()-start, 2)))


if __name__ == '__main__': main()
