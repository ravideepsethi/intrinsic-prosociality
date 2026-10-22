"""Monthly target snapshots with the original 300-game batch boundaries."""
from __future__ import annotations
import os,uuid
from pathlib import Path
import pyarrow.parquet as pq
import local_io as io

FORMAT='monthly_parquet_row_groups_v1'

def batch_sha(table):
    # Hash decoded values, including every target column. Parquet can rename
    # Arrow list children without changing the data, so schema-byte hashes
    # would spuriously disagree after a valid round trip.
    return io.cfgsha(table.to_pylist())

def write_month(path,table):
    """One file open/rename per nonempty month, one row group per API batch."""
    path=Path(path)
    if not table.num_rows:raise ValueError('Do not write an empty snapshot')
    temp=path.with_name(path.name+'.partial_'+uuid.uuid4().hex)
    pq.write_table(table,temp,compression='zstd',row_group_size=300)
    os.replace(temp,path)
    return {'target_format':FORMAT,'target_path':path.name,
            'file_sha256':io.sha(path),'file_bytes':path.stat().st_size}

class Reader:
    """Keep one monthly file open; verify its bytes once and each batch's data.

    The enclosing plan checkpoint authenticates the entire units manifest and
    every monthly file. This adds checks at use time and detects an input
    changing during the read. File signatures never replace the first hash.
    """
    def __init__(self,root):
        self.root=Path(root);self.file=None;self.key=None;self.signature=None
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if self.file is not None:self.file.close()
        self.file=None;self.key=None;self.signature=None
    def read(self,unit):
        path=io.child(self.root,unit['target_path'])
        fmt=unit.get('target_format')
        if fmt is None:
            # Explicit compatibility with the original per-batch plan format.
            io.checked(path,unit['sha256'])
            table=io.read(path)
        elif fmt==FORMAT:
            key=(path,unit['file_sha256'],int(unit['file_bytes']))
            if key!=self.key:
                self.close()
                record=io.checked(path,key[1],key[2])
                self.signature=record['signature']
                self.file=pq.ParquetFile(path);self.key=key
            if io.sig(path)!=self.signature:raise RuntimeError('Target snapshot changed during recovery')
            group=unit['row_group']
            if type(group) is not int or not 0<=group<self.file.num_row_groups:
                raise RuntimeError('Invalid target row-group index')
            table=self.file.read_row_group(group,use_threads=False)
            if io.sig(path)!=self.signature:raise RuntimeError('Target snapshot changed during recovery')
            if batch_sha(table)!=unit['sha256']:raise RuntimeError('Target batch values changed')
        else:raise RuntimeError('Unsupported target plan format')
        if table.num_rows!=unit['rows'] or not 1<=table.num_rows<=300:
            raise RuntimeError('Target batch row count changed')
        return table
