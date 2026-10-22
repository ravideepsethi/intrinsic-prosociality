"""Exact 75% snapshot inside the existing, unchanged 50-to-100% journal."""
from continuous_common import *
import collections
import math


def month75(job):
    threads_one()
    def build(out):
        c = io.conn(out / 'spill', job['memory'], 1)
        try:
            c.execute('CREATE VIEW f AS SELECT * FROM ' + io.parq([job['ledger']]))
            if job['refresh']:
                c.execute('CREATE VIEW m AS SELECT * FROM ' + io.parq(job['metadata']))
                if job['nonreturns']:
                    c.execute('CREATE VIEW a AS SELECT DISTINCT game_id FROM ' + io.parq(job['nonreturns']))
                else:
                    c.execute('CREATE VIEW a AS SELECT NULL::VARCHAR AS game_id WHERE FALSE')
                ready = original_plan.readiness_sql()
                disposition = f"""CASE WHEN f.local_eligibility<>'POTENTIALLY_ELIGIBLE' THEN 'LOCAL_RULE_EXCLUSION'
                    WHEN ({ready})='CACHED_NONPOOL' THEN 'EXPLICIT_NONPOOL'
                    WHEN ({ready})='CACHED_POOL_METADATA' THEN 'LOCAL_POOL_METADATA_READY'
                    WHEN a.game_id IS NOT NULL THEN 'PRIOR_API_NONRETURN_GAP'
                    ELSE 'NEEDS_API' END"""
                source = 'f LEFT JOIN m USING(game_id) LEFT JOIN a USING(game_id)'
            else:
                disposition = 'f.retrieval_disposition'
                source = 'f'
            where = ("NOT f.previous_frame AND f.retrieval_rank>=from_hex('" + pc.threshold(50).hex() +
                     "') AND f.retrieval_rank<from_hex('" + LIMIT75.hex() + "')")
            rows = [dict(month=job['month'], phase_percent=75, disposition=d, rows=int(n))
                for d, n in c.execute('SELECT ' + disposition + ',count(*) FROM ' + source +
                                      ' WHERE ' + where + ' GROUP BY 1').fetchall()]
            count = c.execute('SELECT count(*) FROM ' + io.parq([job['legacy_target']]) +
                              " WHERE retrieval_rank<from_hex('" + LIMIT75.hex() + "')").fetchone()[0]
            actual = sum(r['rows'] for r in rows if r['disposition'] == 'NEEDS_API')
            if actual != count:
                raise RuntimeError('75% selection disagrees with the frozen monthly API list')
            io.js(out / 'counts.json', rows)
            return dict(rows=rows, prefix_targets=int(count))
        finally:
            finish_connection(c, out / 'spill')
    inputs = [job['ledger'], job['legacy_target']] + job['metadata'] + job['nonreturns']
    return stable_stage(Path(job['output']), job['conf'], build, inputs)[1]


def prepare(up, state, root, addon, a, conf):
    audit = io.load(root / 'SQLITE_AUDIT.json')
    refresh = sum(r['reused_records'] + r['prior_nonreturns'] for r in audit) > 0
    metadata = Path(state['metadata'])
    def for_month(month):
        if not refresh:
            return []
        if (metadata.parent / 'empty_metadata.parquet').exists():
            parts = sorted((metadata.parent / 'by_month' / ('month=' + month)).glob('*.parquet'))
            return list(map(str, parts)) or [str(metadata.parent / 'empty_metadata.parquet')]
        return [str(metadata)]
    jobs = [dict(ledger=ledger, month=month, metadata=for_month(month),
        nonreturns=state['nonreturns'] if refresh else [], refresh=refresh,
        legacy_target=str(root / 'months' / month / 'targets_100.parquet'),
        output=str(addon / 'plan75_months' / month), conf=conf, memory=a.memory_gb/a.workers)
        for month, ledger in zip(ex.MONTHS, up['ledgers'])]
    results = io.mapped(month75, jobs, a.workers, 'Preparing the exact 75% checkpoint')
    rows = [r for result in results for r in result['rows']]
    counts = collections.Counter()
    for r in rows:
        counts[r['disposition']] += r['rows']
    before = next(r for r in state['summary']['phases'] if r['through_percent'] == 50)
    prefix = sum(r['prefix_targets'] for r in results)
    total100 = next(r for r in state['summary']['phases'] if r['through_percent'] == 100)
    if not 0 <= prefix <= total100['incremental_targets']:
        raise RuntimeError('Invalid 75% prefix length')
    summary = dict(through_percent=75, incremental_targets=prefix,
        cumulative_targets=before['cumulative_targets']+prefix,
        additional_frame_rows=before['additional_frame_rows']+sum(counts.values()),
        original_frame_rows=before['original_frame_rows'],
        cached_pool_rows=before['cached_pool_rows']+counts['LOCAL_POOL_METADATA_READY'],
        prior_nonreturn_gaps=before['prior_nonreturn_gaps']+counts['PRIOR_API_NONRETURN_GAP'])
    io.js(addon / 'PLAN75.json', dict(summary=summary, by_month=rows, prefix_targets=prefix))
    return dict(summary=summary, by_month=rows, prefix_targets=prefix)


def prefix_available(db, count):
    needed = math.ceil(count / 300)
    actual = db.execute('SELECT count(*) FROM batches WHERE batch>=0 AND batch<?', (needed,)).fetchone()[0]
    return actual == needed


def export_prefix(db, target, count, folder, conf):
    """Read full original batches, then exclude any records beyond the exact boundary.

    The boundary batch can contain up to 299 games above 75%. Their responses
    stay committed in the parent journal and are reused on the way to 100%.
    No target file, batch, or response binding is rewritten.
    """
    if not prefix_available(db, count):
        raise RuntimeError('The complete request prefix for 75% has not been retrieved')
    def build(out):
        metadata = pq.ParquetWriter(out / 'downloaded_metadata.parquet', ex.metadata_schema(), compression='zstd')
        absent_schema = pa.schema([('game_id', pa.string())])
        absent = pq.ParquetWriter(out / 'not_returned.parquet', absent_schema, compression='zstd')
        records = []; missing_records = []; position = returned = flagged = 0
        total = pq.ParquetFile(target).metadata.num_rows
        boundary_checked = count == total
        try:
            for k, rows in enumerate(dl.batches(target)):
                if position >= count:
                    if rows and hashlib.sha256(ex.ORDER_SEED + rows[0]['game_id'].encode('ascii')).digest() < LIMIT75:
                        raise RuntimeError('75% prefix omits an eligible rank')
                    boundary_checked = True
                    break
                take = min(len(rows), count-position)
                included = rows[:take]
                # Validate membership throughout the snapshot, not merely its last row.
                if any(not (pc.threshold(50) <= hashlib.sha256(ex.ORDER_SEED+r['game_id'].encode('ascii')).digest() < LIMIT75)
                       for r in included):
                    raise RuntimeError('Saved target order does not match the exact 50-to-75% rank interval')
                if take < len(rows):
                    if hashlib.sha256(ex.ORDER_SEED + rows[take]['game_id'].encode('ascii')).digest() < LIMIT75:
                        raise RuntimeError('75% prefix cuts off an eligible rank')
                    boundary_checked = True
                nr, nm, _, _ = dl.process_batch(db, k, rows, None)
                wanted = {r['game_id'] for r in included}
                nr = [r for r in nr if r['game_id'] in wanted]
                nm = [r for r in nm if r['game_id'] in wanted]
                if len(nr)+len(nm) != take:
                    raise RuntimeError('75% snapshot denominator differs')
                position += take; returned += len(nr)
                flagged += sum(bool(r['record_errors']) for r in nr)
                records.extend(nr); missing_records.extend(nm)
                if len(records) >= 30000:
                    metadata.write_table(pa.Table.from_pylist(records, schema=ex.metadata_schema())); records = []
                if len(missing_records) >= 30000:
                    absent.write_table(pa.Table.from_pylist(missing_records, schema=absent_schema)); missing_records = []
            if records:
                metadata.write_table(pa.Table.from_pylist(records, schema=ex.metadata_schema()))
            if missing_records:
                absent.write_table(pa.Table.from_pylist(missing_records, schema=absent_schema))
        finally:
            metadata.close(); absent.close()
        if position != count or not boundary_checked:
            raise RuntimeError('The 75% request prefix is incomplete')
        summary = dict(config_sha256=conf, requested=count, returned=returned, not_returned=count-returned,
            returned_with_metadata_flags=flagged, all_targets_accounted=True,
            exact_rank_threshold_percent=75, parent_target_rows=total,
            boundary_batch_excess_excluded=True, estimates_run=False, stockfish_searches=0)
        io.js(out / 'SUMMARY.json', summary)
        return {k:v for k,v in summary.items() if k != 'config_sha256'}
    return io.stage(folder, conf, build)
