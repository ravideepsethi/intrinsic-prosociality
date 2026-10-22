"""Columnar aggregate outputs; retain small CSV companions for compatibility."""
import bootstrap_path
import os
from pathlib import Path
import pandas as pd
from io_utils import csv_write as write_csv


def csv_write(path,rows):
    path=Path(path);frame=pd.DataFrame(rows)
    write_csv(path,frame)
    # Empty schema cannot be useful in Parquet; keep the ordinary empty CSV.
    if not len(frame.columns):
        path.with_suffix('.parquet').unlink(missing_ok=True)
        return
    target=path.with_suffix('.parquet');part=target.with_suffix('.parquet.partial')
    frame.to_parquet(part,engine='pyarrow',compression='zstd',index=False,row_group_size=65536)
    os.replace(part,target)
