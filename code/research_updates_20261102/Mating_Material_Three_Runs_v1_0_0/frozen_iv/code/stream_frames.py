"""Bounded, exact row-ID merges; no whole-frame hash join or wide sort.

Inputs must be strictly increasing by signed integer row_id. Each input is
checked while it is consumed. Missing, duplicate and extra rows are errors.
Only one left batch and small right-reader buffers are resident at once.
"""
from pathlib import Path
from contextlib import contextmanager
import gc
import os
import tempfile
import time
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from util import require, log

BATCH_ROWS = 65536
RIGHT_ROWS = 8192
MAX_RIGHT_ROW_GROUP_ROWS = 65536
MAX_TOTAL_RIGHT_ROW_GROUP_ROWS = 1048576


@contextmanager
def bounded_right_inputs(parts, output, fields, row_group_rows):
    """Parquet readers may retain entire column chunks despite small batches.

    Normalize large right-hand row groups sequentially before opening all
    shard readers together. Originals and their checksum receipts are untouched.
    Temporary files disappear on both successful completion and exceptions.
    """
    parent = Path(output).parent
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.stream_inputs_', dir=parent) as folder:
        prepared = []
        for k, path in enumerate(parts):
            pf = pq.ParquetFile(path)
            if all(pf.metadata.row_group(g).num_rows <= row_group_rows
                   for g in range(pf.metadata.num_row_groups)):
                prepared.append(Path(path))
                pf.close()
                continue
            columns = ['row_id'] + fields
            schema = pa.schema([pf.schema_arrow.field(c) for c in columns])
            target = Path(folder) / f'{k:03}.parquet'
            writer = pq.ParquetWriter(target, schema, compression='zstd',
                                      use_dictionary=False)
            try:
                for batch in pf.iter_batches(batch_size=row_group_rows,
                                              columns=columns, use_threads=False):
                    writer.write_batch(batch, row_group_size=row_group_rows)
            finally:
                writer.close()
                pf.close()
            prepared.append(target)
            gc.collect()
            pa.default_memory_pool().release_unused()
            log(f'Prepared bounded row groups: {k+1}/{len(parts)} input shards')
        yield prepared


class Cursor:
    def __init__(self, path, columns=None, batch_rows=RIGHT_ROWS):
        self.path = Path(path)
        self.file = pq.ParquetFile(path)
        self.schema = self.file.schema_arrow
        if columns is not None:
            self.schema = pa.schema([self.schema.field(k) for k in columns])
        require('row_id' in self.schema.names, 'Missing row_id: ' + str(path))
        require(pa.types.is_signed_integer(self.schema.field('row_id').type),
                'row_id must be a signed integer: ' + str(path))
        self.it = self.file.iter_batches(batch_size=batch_rows, columns=columns,
                                         use_threads=False)
        self.table = None
        self.ids = None
        self.offset = 0
        self.last = None
        self.exhausted = False
        self.advance()

    def advance(self):
        while True:
            try:
                batch = next(self.it)
            except StopIteration:
                self.table = self.ids = None
                self.exhausted = True
                return
            if batch.num_rows:
                break
        require(batch.column('row_id').null_count == 0, 'Null row_id: ' + str(self.path))
        ids = batch.column('row_id').to_numpy(zero_copy_only=False)
        require(np.all(ids[1:] > ids[:-1]) and
                (self.last is None or int(ids[0]) > self.last),
                'Unsorted or duplicate row_id: ' + str(self.path))
        self.last = int(ids[-1])
        self.table = pa.Table.from_batches([batch])
        self.ids = ids
        self.offset = 0

    def through(self, maximum, limit):
        pieces = []
        size = 0
        while not self.exhausted and self.ids[self.offset] <= maximum:
            end = int(np.searchsorted(self.ids, maximum, side='right'))
            size += end - self.offset
            require(size <= limit, 'Extra right-hand rows exceed the bounded merge batch')
            pieces.append(self.table.slice(self.offset, end - self.offset))
            self.offset = end
            if end == len(self.ids):
                self.advance()
        return pieces


def atomic_writer(path, schema, produce):
    path = Path(path)
    require(not path.exists(), 'Refusing to overwrite an existing frame: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.stream_partial')
    writer = pq.ParquetWriter(temporary, schema, compression='zstd')
    try:
        result = produce(writer)
        writer.close()
        os.replace(temporary, path)
        return result
    except BaseException:
        writer.close()
        temporary.unlink(missing_ok=True)
        raise


def attach(source, parts, output, fields=None, replace=True, batch_rows=BATCH_ROWS,
           right_rows=RIGHT_ROWS, label='Streaming frame merge'):
    """Exact 1:1 union of sorted right shards, with SQL-compatible field order."""
    parts = list(parts)
    require(bool(parts), 'A typed right-hand input is required, even when empty')
    require(all(Path(output).resolve() != Path(p).resolve() for p in [source]+list(parts)),
            'Frame output overlaps an input')
    require(not Path(output).exists(), 'Refusing to overwrite an existing frame: ' + str(output))
    first = pq.ParquetFile(parts[0]).schema_arrow
    fields = [k for k in first.names if k != 'row_id'] if fields is None else list(fields)
    require(len(fields) == len(set(fields)) and 'row_id' not in fields,
            'Invalid attached field list')
    cap = min(MAX_RIGHT_ROW_GROUP_ROWS, max(1, MAX_TOTAL_RIGHT_ROW_GROUP_ROWS//len(parts)))
    with bounded_right_inputs(parts, output, fields, cap) as prepared:
        return _attach_prepared(source, prepared, output, fields, replace,
                                batch_rows, min(right_rows,cap), label, cap)


def _attach_prepared(source, parts, output, fields, replace, batch_rows, right_rows, label, cap):
    left = Cursor(source, batch_rows=batch_rows)
    right = [Cursor(p, ['row_id']+fields, right_rows) for p in parts]
    require(all(r.schema.equals(right[0].schema, check_metadata=False) for r in right),
            'Right-hand shard schemas differ')
    collisions = set(fields) & set(left.schema.names)
    require(replace or not collisions, 'Unexpected existing columns: ' + str(sorted(collisions)))
    keep = [k for k in left.schema.names if k not in fields]
    schema = pa.schema([left.schema.field(k) for k in keep] +
                       [right[0].schema.field(k) for k in fields])
    started = time.monotonic()
    total = left.file.metadata.num_rows

    def produce(writer):
        count = 0
        checkpoint = started
        while not left.exhausted:
            q = left.table
            qids = left.ids
            pieces = []
            size = 0
            for r in right:
                got = r.through(int(qids[-1]), q.num_rows-size)
                pieces.extend(got)
                size += sum(t.num_rows for t in got)
            require(size == q.num_rows, 'Incomplete or extra row coverage in streaming merge')
            h = pa.concat_tables(pieces)
            # This sort is bounded by one left batch, never the entire frame.
            h = h.take(pc.sort_indices(h, sort_keys=[('row_id', 'ascending')]))
            require(np.array_equal(qids, h['row_id'].to_numpy()),
                    'Missing, duplicate or extra row_id in streaming merge')
            merged = pa.Table.from_arrays([q[k] for k in keep]+[h[k] for k in fields],
                                          schema=schema)
            writer.write_table(merged, row_group_size=batch_rows)
            count += q.num_rows
            left.advance()
            if time.monotonic()-checkpoint >= 30:
                log(f'{label}: {count:,}/{total:,} rows; '
                    f'{(time.monotonic()-started)/60:.1f} min')
                checkpoint = time.monotonic()
        require(all(r.exhausted for r in right), 'Extra right-hand rows after source ended')
        require(count == total, 'Source row count changed during streaming merge')
        return dict(rows=count, batch_rows=batch_rows, right_buffer_rows=right_rows,
                    max_right_row_group_rows=cap,
                    streaming_merge=True)
    result = atomic_writer(output, schema, produce)
    log(f'{label}: complete; {total:,} rows; {(time.monotonic()-started)/60:.1f} min')
    return result


def select(source, output, predicate=None, ids=None, invert=False, batch_rows=BATCH_ROWS,
           columns=None):
    """Copy/filter sorted rows; optional ID membership is an exact subset check."""
    require(not (predicate is not None and ids is not None), 'Choose one selection rule')
    q = Cursor(source, columns=columns, batch_rows=batch_rows)
    selected = Cursor(ids, ['row_id']) if ids is not None else None
    def produce(writer):
        count = 0
        while not q.exhausted:
            table = q.table
            if selected is not None:
                parts = selected.through(int(q.ids[-1]), table.num_rows)
                keys = pa.concat_tables(parts)['row_id'].to_numpy() if parts else np.empty(0,np.int64)
                pos = np.searchsorted(q.ids, keys)
                require(np.all(pos < len(q.ids)) and np.array_equal(q.ids[pos], keys),
                        'Selected IDs are not a subset of source IDs')
                mask = np.zeros(table.num_rows, bool)
                mask[pos] = True
                table = table.filter(pa.array(~mask if invert else mask))
            elif predicate is not None:
                table = table.filter(predicate(table))
            writer.write_table(table, row_group_size=batch_rows)
            count += table.num_rows
            q.advance()
        require(selected is None or selected.exhausted, 'Selected IDs extend past source')
        return dict(rows=count, streaming_selection=True)
    return atomic_writer(output, q.schema, produce)
