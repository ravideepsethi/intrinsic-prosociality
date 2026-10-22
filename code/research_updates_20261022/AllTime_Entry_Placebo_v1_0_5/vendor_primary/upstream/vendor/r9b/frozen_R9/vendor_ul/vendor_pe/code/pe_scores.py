"""Score F50 once; bridge the frozen O50 subset with exact identity checks."""
from pe_common import *
from iv_history import prepare_queries, score_job, combine

IDENTITY = ('game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','month_code','complete90')

def subset_scores(entry, ordinary, scores, root, conf, memory):
    def build(tmp):
        c = u.conn(tmp/'spill', memory, 1)
        try:
            for name, path in [('e',entry), ('o',ordinary), ('s',scores)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+u.parq([path]))
            n = pq.ParquetFile(ordinary).metadata.num_rows
            for name in ('e','o','s'):
                total, unique = c.execute(f'SELECT count(*),count(DISTINCT row_id) FROM {name}').fetchone()
                u.require(total == unique, 'Duplicate row IDs in '+name)
            u.require(c.execute('SELECT count(*) FROM o JOIN e USING(row_id) JOIN s USING(row_id)').fetchone()[0] == n,
                      'O50 is not an exact supported subset of F50')
            cols = IDENTITY + ('n_7d','counterparts_7d','expected_7d','adjusted_7d','y','reached')
            terms = ' OR '.join('o.'+k+' IS DISTINCT FROM e.'+k for k in cols)
            u.require(c.execute('SELECT count(*) FROM o JOIN e USING(row_id) WHERE '+terms).fetchone()[0] == 0,
                      'O50/F50 identity, history, or frozen outcome mismatch')
            r.io.copy(c, 'SELECT s.* FROM s SEMI JOIN o USING(row_id) ORDER BY row_id', tmp/'scores.parquet')
            info = dict(rows=n, verified_subset=True, frozen_outcomes_identical=True, donor_scans_repeated_for_O50=0)
            r.io.js(tmp/'summary.json', info)
            return info
        finally: r.finish_connection(c, tmp/'spill')
    folder, info = r.stable_stage(root, conf, build, [entry,ordinary,scores])
    return folder/'scores.parquet', info
