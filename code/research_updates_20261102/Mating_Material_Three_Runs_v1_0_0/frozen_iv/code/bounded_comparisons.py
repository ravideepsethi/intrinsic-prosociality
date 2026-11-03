"""Bounded, restartable chronology joins; identical row and eligibility rules.

Do not join the 45-million-row frames in one hash table. Materialize each
integer-ID range BEFORE joining, then concatenate sorted ranges with Arrow.
Every old/new identity, uniqueness and exact-coverage gate remains active.
"""
from bootstrap import *

RANGE_WIDTH = 1_000_000
JOIN_MEMORY_GB = 3.
IDENTITY = ['game_id', 'recipient_id', 'opponent_id', 'archive_start_ms']


def ranges_for(db, sources, width):
    """One-column scans; include old-only ranges so extra rows cannot hide."""
    require(isinstance(width, int) and width > 0, 'Invalid chronology range width')
    minima, maxima, counts = [], [], {}
    for name, paths in sources.items():
        if isinstance(paths, (str, Path)):
            paths = [paths]
        require(bool(paths), 'Empty chronology source list')
        for path in paths:
            schema = pq.ParquetFile(path).schema_arrow
            require('row_id' in schema.names and pa.types.is_integer(schema.field('row_id').type),
                    'Chronology row_id must be an integer: ' + str(path))
        view(db, name, paths)
        n, nonnull, lo, hi = db.execute(
            'SELECT count(*),count(row_id),min(row_id),max(row_id) FROM ' + name).fetchone()
        require(n == nonnull, 'Null chronology row IDs in ' + name)
        counts[name] = int(n)
        if n:
            minima.append(int(lo)); maxima.append(int(hi))
    if not minima:
        return [(0, width)], counts  # still emit the original typed empty schemas
    lo = min(minima); hi = max(maxima)
    return [(start, min(start + width, hi + 1)) for start in range(lo, hi + 1, width)], counts


def materialize(db, name, paths, lo, hi):
    """A TEMP TABLE is deliberate: no optimizer can build a global join first."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    db.execute('CREATE TEMP TABLE ' + name + ' AS SELECT * FROM ' + c.parq(paths) +
               f' WHERE row_id >= {lo} AND row_id < {hi}')
    return c.ensure_unique(db, name)


def append_sorted(paths, target, expected):
    """Bounded buffer; strict monotone IDs certify uniqueness across chunks."""
    require(bool(paths), 'No chronology chunks to assemble')
    schema = pq.ParquetFile(paths[0]).schema_arrow.remove_metadata()
    previous = None; count = 0
    with pq.ParquetWriter(target, schema, compression='zstd') as writer:
        for path in paths:
            pf = pq.ParquetFile(path)
            require(pf.schema_arrow.equals(schema, check_metadata=False),
                    'Chronology chunk schema changed: ' + str(path))
            for batch in pf.iter_batches(batch_size=65536, use_threads=False):
                values = batch.column(batch.schema.get_field_index('row_id'))
                require(values.null_count == 0, 'Null assembled chronology key')
                ids = values.to_numpy(zero_copy_only=False)
                if len(ids):
                    require(bool(np.all(ids[1:] > ids[:-1])) and
                            (previous is None or int(ids[0]) > previous),
                            'Chronology chunks overlap or are not strictly sorted')
                    previous = int(ids[-1])
                writer.write_batch(batch); count += len(batch)
    require(count == expected == rows(target), 'Assembled chronology row count changed')
    return count


def reuse_plan(run, conf, query, oldq, oldx, width=RANGE_WIDTH, memory=JOIN_MEMORY_GB):
    deps = [query, oldq, oldx]
    def build(tmp):
        db = connect(tmp, memory)
        try:
            ranges, totals = ranges_for(db, dict(q=query, oq=oldq, ox=oldx), width)
        finally:
            db.close()
        chunks = []; infos = []
        for index, (lo, hi) in enumerate(ranges):
            def chunk(work, lo=lo, hi=hi):
                db = connect(work, memory)
                try:
                    n = materialize(db, 'q', query, lo, hi)
                    oldn = materialize(db, 'oq', oldq, lo, hi)
                    materialize(db, 'ox', oldx, lo, hi)
                    c.assert_coverage(db, 'oq', 'ox')
                    overlap = c.bridge(db, 'q', 'oq', IDENTITY, 'Chronology reusable identity')
                    # oq and ox have exactly the same unique keys, proven above.
                    copy(db, 'SELECT q.row_id,ox.* EXCLUDE(row_id) FROM q JOIN ox USING(row_id) ORDER BY q.row_id', work/'hits.parquet')
                    copy(db, 'SELECT q.* FROM q ANTI JOIN oq USING(row_id) ORDER BY q.row_id', work/'missing.parquet')
                    hits = rows(work/'hits.parquet'); missing = rows(work/'missing.parquet')
                    require(hits == overlap and hits + missing == n, 'Chronology reuse lost or duplicated rows')
                    return dict(rows=n, old_rows=oldn, reused=hits, missing=missing, lo=lo, hi=hi)
                finally:
                    db.close()
            part, info = stage(run/'PRIVATE/chronology_plan102_parts'/f'{lo}_{hi}',
                               c.key([conf, 'bounded_chronology_plan_v102', lo, hi]), chunk, deps)
            chunks.append(part); infos.append(info)
            log(f'Chronology reuse: chunk {index+1}/{len(ranges)}, {info["rows"]:,} queries verified')
        require(sum(i['rows'] for i in infos) == totals['q'] and
                sum(i['old_rows'] for i in infos) == totals['oq'] == totals['ox'],
                'Chronology range coverage differs from source counts')
        reused = sum(i['reused'] for i in infos); missing = sum(i['missing'] for i in infos)
        append_sorted([p/'hits.parquet' for p in chunks], tmp/'hits.parquet', reused)
        append_sorted([p/'missing.parquet' for p in chunks], tmp/'missing.parquet', missing)
        save(tmp/'bounded_execution.json', dict(version='1.0.2', ranges=len(ranges),
             maximum_ids_per_range=width, duckdb_memory_gb=memory,
             arrow_batch_rows=65536, exact_coverage=True, identity_bridge=True))
        return dict(rows=totals['q'], reused=reused, missing=missing)
    return stage(run/'PRIVATE/chronology_plan90', conf, build, deps)


def eligible_queries(run, conf, query, parts, width=RANGE_WIDTH, memory=JOIN_MEMORY_GB):
    deps = [query] + list(parts)
    def build(tmp):
        db = connect(tmp, memory)
        try:
            ranges, totals = ranges_for(db, dict(q=query, x=parts), width)
        finally:
            db.close()
        outputs = []; infos = []
        for index, (lo, hi) in enumerate(ranges):
            def chunk(work, lo=lo, hi=hi):
                db = connect(work, memory)
                try:
                    n = materialize(db, 'q', query, lo, hi)
                    materialize(db, 'x', parts, lo, hi)
                    c.assert_coverage(db, 'q', 'x')
                    copy(db, 'SELECT q.*,x.* EXCLUDE(row_id) FROM q JOIN x USING(row_id) '
                         'WHERE eligible_main AND first_observed_pair ORDER BY q.row_id', work/'queries.parquet')
                    return dict(source_rows=n, rows=rows(work/'queries.parquet'), lo=lo, hi=hi)
                finally:
                    db.close()
            part, info = stage(run/'PRIVATE/locally_eligible102_parts'/f'{lo}_{hi}',
                               c.key([conf, 'bounded_chronology_eligible_v102', lo, hi]), chunk, deps)
            outputs.append(part/'queries.parquet'); infos.append(info)
            log(f'Chronology eligibility: chunk {index+1}/{len(ranges)}, {info["rows"]:,} retained')
        require(sum(i['source_rows'] for i in infos) == totals['q'] == totals['x'],
                'Chronology eligibility coverage differs from source counts')
        n = sum(i['rows'] for i in infos)
        append_sorted(outputs, tmp/'queries.parquet', n)
        return dict(rows=n)
    return stage(run/'PRIVATE/locally_eligible', conf, build, deps)


def chronology90(a, run, conf, b):
    # Scan/repair/merge of genuinely new query rows uses the original factual
    # chronology kernel. Only the two large relational joins are replaced.
    import fast_comparisons as fc
    query = run/'PRIVATE/supported/queries.parquet'
    oldq = Path(b['legacy_candidate_run'])/'PRIVATE/supported/queries.parquet'
    oldx = Path(b['legacy_chronology_run'])/'PRIVATE/chronology/features.parquet'
    for path, key in ((query, conf), (oldq, PARENT), (oldx, conf)):
        c.check_stage(path, key)
    prep, info = reuse_plan(run, conf, query, oldq, oldx)
    parts = [prep/'hits.parquet']
    if info['missing']:
        q = prep/'missing.parquet'
        p, stats = fc.chron.previous.prepare_chronology(q, run/'PRIVATE/chronology_scan_plan90', conf, 4.)
        scanconf = c.key([conf, 'new_comparison_chronology', c.sha(q)])
        jobs = [dict(r, latest=stats['latest_start'], people=str(p/'people.parquet'),
                     pairs=str(p/'pairs.parquet'), focal=str(p/'focal.parquet'), roles=str(p/'roles.parquet'),
                     memory=3., conf=scanconf, output=str(run/'PRIVATE/chronology_scans90'/f"{r['file_index']:04}"))
                for r in b['source']['chron'] if r['minimum'] is None or r['minimum'] <= stats['latest_start']]
        from fast_chronology_parallel import resume_scans
        from fast_chronology_repair import validated_parts
        from fast_chronology_merge import bounded_merge
        resume_scans(jobs, a.workers)
        checked = validated_parts(jobs, run/'PRIVATE/chronology_scan_repair104', conf, run/'report')
        folder, stats = bounded_merge(q, checked, run/'PRIVATE/chronology_merge90', conf, 4.)
        parts.append(folder/'features.parquet')
    eligible_queries(run, conf, query, parts)
    save(run/'report/chronology90.json', info)
