"""Fill exactly the reviewed 15-game gap, then reconcile with networking blocked.

The frozen downloader retains raw responses transactionally. The frozen metadata
reconciler retains all original conflict, quarantine, pool and identity rules.
The completed audit and its public reports are read-only in this repair.
"""
from bootstrap import *
import fast_comparisons as fc
import resilient_metadata_http

md = fc.metadata
AUTHORITY = ROOT/'authority/iv_batch_partial/METADATA_PLAN.json'
EXPECTED_TARGETS = 15
ENDPOINT = ('https://lichess.org/api/games/export/_ids?moves=false&clocks=false&'
            'evals=false&opening=false&literate=false&pgnInJson=false&tags=true')
PLAN_FIELDS = ('locally_eligible', 'metadata_counts', 'missing_metadata_targets',
               'known_quarantine_candidates', 'leaf_groups', 'game_partition',
               'max_input_rows_per_leaf', 'duckdb_decimal_gb', 'bounded_metadata')


def cached_plan(a, run, conf, b):
    """Authenticate the finished audit; never fall back to rebuilding it."""
    root = run/'PRIVATE/metadata_plan'
    require((root/'_DONE.json').is_file(),
            'The reviewed completed metadata audit is missing; do not repeat its three-hour scan')
    dependencies = [run/'PRIVATE/locally_eligible/queries.parquet']
    dependencies += list(map(Path, b['metadata']+b['quarantine']))
    def forbidden(_):
        raise RuntimeError('The reviewed metadata audit must be reused, not rebuilt')
    out, _ = stage(root, conf, forbidden, dependencies)
    expected = read(AUTHORITY)
    actual = read(out/'summary.json')
    require(all(actual.get(k) == expected[k] for k in PLAN_FIELDS),
            'Cached audit differs from the reviewed metadata plan')
    target = out/'targets.parquet'
    require(rows(target) == expected['missing_metadata_targets'] == EXPECTED_TARGETS,
            'Metadata request scope must remain exactly the 15 reviewed games')
    records = pq.ParquetFile(target).read().to_pylist()
    ids = [r['game_id'] for r in records]
    require(len(set(ids)) == EXPECTED_TARGETS and
            all(isinstance(g, str) and md.metadata_http.GID.fullmatch(g) for g in ids),
            'Metadata targets contain duplicate or invalid game IDs')
    return out, records


class ScopedClient:
    """Only the certified IDs may reach the serialized HTTP client."""
    def __init__(self, ids, cooldown):
        require(md.metadata_http.URL == ENDPOINT, 'Metadata endpoint changed')
        self.ids = frozenset(ids)
        require(len(self.ids) == EXPECTED_TARGETS, 'Incorrect metadata allowlist')
        self.cooldown = cooldown
        self.client = None
        self.logical_requests = 0

    def get(self, ids):
        require(0 < len(ids) <= EXPECTED_TARGETS and len(set(ids)) == len(ids)
                and set(ids) <= self.ids, 'Request exceeds the reviewed 15-game scope')
        require(self.logical_requests < 3, 'Metadata request-pass limit reached')
        if self.client is None:
            self.client = resilient_metadata_http.Client(self.cooldown)
        self.logical_requests += 1
        return self.client.get(ids)

    def metrics(self):
        return dict(logical_requests=self.logical_requests,
                    http_attempts=self.client.requests if self.client else 0,
                    http_seconds=self.client.http_seconds if self.client else 0.,
                    server_wait_seconds=self.client.wait_seconds if self.client else 0.,
                    transient_errors=self.client.failure_history if self.client else [])


def verify_batch(sql, records, client):
    found, missing, flags, reused = md.download.process_batch(sql, 0, records, client)
    require(not missing and len(found) == EXPECTED_TARGETS,
            'Some reviewed metadata was not returned; saved responses retained and frames blocked')
    require(flags == 0,
            'New metadata has validation flags; saved responses retained and frames blocked')
    require({r['game_id'] for r in found} == {r['game_id'] for r in records},
            'Returned metadata identities differ from the reviewed targets')
    return reused


def prepare(a, run, conf, b):
    """Small cache-acquisition step before the analytical process blocks sockets."""
    root, records = cached_plan(a, run, conf, b)
    target = root/'targets.parquet'
    target_sha = sha(target)
    dc = c.key([conf, target_sha])
    out = run/'PRIVATE/download'
    out.mkdir(exist_ok=True)
    report_path = run/'report/METADATA_CACHE_COMPLETION.json'
    identity = dict(configuration=conf, target_sha256=target_sha,
                    approved_games=EXPECTED_TARGETS, endpoint=ENDPOINT)
    prior = read(report_path) if report_path.exists() else {}
    require(not prior or all(prior.get(k) == v for k, v in identity.items()),
            'Metadata cache-completion identity changed')
    report = dict(identity, execution_repair='1.0.4',
                  status='ACQUIRING_PUBLIC_METADATA', attempts=prior.get('attempts', []),
                  original_audit_reused=True, analytical_network=False,
                  historical_offline_hold='OFFLINE_HOLD.json', private_rows_exported=False)
    global_lock = Path.home()/'.cache/lichess_research_api'
    client = ScopedClient([r['game_id'] for r in records], global_lock/'cooldown.json')
    start = time.monotonic()
    attempt = dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   status='IN_PROGRESS')
    report['attempts'].append(attempt)
    save(report_path, report)
    log('Cache completion: 15 public game metadata records; one initial request, '
        'saved responses reused. HTTP 524 and other transient failures retry automatically. '
        'Allow a few minutes if the API responds; server outages extend this.')
    try:
        with md.download.exclusive(global_lock/'one_request.lock',
                'Another Lichess metadata downloader is running; resume after it finishes'):
            md.download.check_other_api_jobs(a.project)
            sql = md.download.connect(out/'checkpoint.sqlite3', dc, target_sha)
            try:
                require(sql.execute('PRAGMA quick_check').fetchone()[0] == 'ok',
                        'Metadata checkpoint damaged')
                attempt['reused_complete_batch'] = verify_batch(sql, records, client)
                md.download.export_saved(sql, target, out/'finished', dc)
                summary = read(out/'finished/SUMMARY.json')
                require(summary['requested'] == summary['returned'] == EXPECTED_TARGETS
                        and summary['not_returned'] == summary['returned_with_metadata_flags'] == 0,
                        'Metadata export is incomplete; frames remain blocked')
                require(sql.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] == 0,
                        'Metadata checkpoint is busy')
            finally:
                sql.close()
        require(sha(target) == target_sha, 'Metadata targets changed during acquisition')
        report.update(status='CACHE_READY', returned=EXPECTED_TARGETS,
                      missing=0, metadata_flags=0)
        attempt['status'] = 'COMPLETE'
        log('All 15 metadata records verified and cached. The remaining analysis will run offline.')
    except BaseException:
        report['status'] = 'BLOCKED_CACHE_COMPLETION'
        attempt['status'] = 'FAILED_OR_INTERRUPTED'
        raise
    finally:
        attempt.update(client.metrics(), seconds=time.monotonic()-start)
        save(report_path, report)
    return report


def complete_offline(a, run, conf, b):
    """No HTTP client is created here, including when a saved response is absent."""
    root, records = cached_plan(a, run, conf, b)
    target = root/'targets.parquet'
    target_sha = sha(target)
    dc = c.key([conf, target_sha])
    out = run/'PRIVATE/download'
    require((out/'checkpoint.sqlite3').is_file(),
            'Complete the 15-game metadata cache step before offline reconciliation')
    sql = md.download.connect(out/'checkpoint.sqlite3', dc, target_sha)
    try:
        require(sql.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Metadata checkpoint damaged')
        verify_batch(sql, records, None)
        md.download.export_saved(sql, target, out/'finished', dc)
    finally:
        sql.close()
    save(run/'report/metadata_download.json', read(out/'finished/SUMMARY.json'))
    import metadata_batches
    result = metadata_batches.complete(a, run, conf, b, root,
                                       out/'finished/downloaded_metadata.parquet')
    # Keep the original audit and OFFLINE_HOLD evidence byte-for-byte unchanged.
    # This new report states whether their historical hold is now resolved.
    save(run/'report/METADATA_HOLD_RESOLUTION.json',
         dict(status='RESOLVED', configuration=conf, historical_hold='OFFLINE_HOLD.json',
              target_sha256=target_sha, cached_games=EXPECTED_TARGETS,
              new_unresolved_rows=0, original_audit_reused=True,
              original_quarantine_and_identity_checks_preserved=True,
              analytical_network=False, private_rows_exported=False))
    return result
