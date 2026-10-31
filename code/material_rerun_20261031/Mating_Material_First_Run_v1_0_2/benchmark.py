#!/usr/bin/env python3
"""Reproducible kernel benchmark; synthetic, not a whole-panel runtime forecast."""
import os
for k in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","VECLIB_MAXIMUM_THREADS"):
    os.environ[k]="1"
import argparse
import json
from pathlib import Path
import platform
import sys
import time
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
sys.path.insert(0,str(Path(__file__).resolve().parent/"tests"))
from fixtures import row,FIXTURES
from mmrerun.material import classify,lacks_mating_material


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--rows",type=int,default=250000)
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    ordinary="rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
    prototypes=[row("ordinary",ordinary,False)]+[row(*x,index=i+1) for i,x in enumerate(FIXTURES)]
    source=pa.Table.from_pylist(prototypes)
    index=np.zeros(a.rows,dtype=np.int32)
    index[::2048]=1+(np.arange(len(index[::2048]))%len(FIXTURES))
    data=pc.take(source,pa.array(index)).combine_chunks().to_batches(max_chunksize=a.rows)[0]
    white=np.ones(a.rows,bool)
    classify(data.slice(0,min(1000,a.rows)),white[:min(1000,a.rows)])
    start=time.perf_counter();old,cases,checked=classify(data,white);vector=time.perf_counter()-start
    fens=data.column(data.schema.get_field_index("fen_after_last_move")).to_pylist()
    start=time.perf_counter();scalar=np.array([lacks_mating_material(fen,"white") for fen in fens]);plain=time.perf_counter()-start
    assert np.array_equal(cases!=0,scalar)
    out=dict(rows=a.rows,material_boundary_fraction=1/2048,vector_seconds=vector,scalar_seconds=plain,
        kernel_speedup=plain/vector,vector_rows_per_second=a.rows/vector,fully_parsed_fens=checked,
        exact_equal=True,python=platform.python_version(),platform=platform.platform(),
        numpy=np.__version__,pyarrow=pa.__version__,scope="synthetic predicate only; excludes hash, I/O, full-width copies and account aggregations")
    text=json.dumps(out,indent=2)+"\n"
    print(text,end="")
    if a.output:a.output.write_text(text)


if __name__=="__main__":main()
