"""Regression tests for the observed invalid-key blocker and private exports."""
import json, tempfile, zipfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
import duckdb
import audit

def main():
    assert audit.key_summary('abcdefgh')['standard_eight']
    assert not audit.key_summary('abcdefgh1234')['standard_eight']
    assert audit.key_summary(' abcdefgh ')['standard_eight_after_strip']
    assert audit.key_summary('https://lichess.org/abcdefgh')['url_shaped']
    assert audit.key_summary(None)=={'kind':'null'}
    assert audit.key_summary('abc\x00defg')['contains_control']
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);private=root/'run/PRIVATE';private.mkdir(parents=True)
        rows=[dict(game_id='secret88',utc_ms=1686000000000,archive_ordinal=10,white_id=1,black_id=2,
            white_elo=1500,black_elo=1600,result_code=2),
            dict(game_id='broken-key-private',utc_ms=0,archive_ordinal=11,white_id=1,black_id=3,
            white_elo=1500,black_elo=1700,result_code=0),
            dict(game_id='nullcase',utc_ms=None,archive_ordinal=12,white_id=8,black_id=9,
            white_elo=1200,black_elo=1300,result_code=1)]
        table=pa.Table.from_pylist(rows);source=root/'source.parquet';pq.write_table(table,source)
        bad=root/'bad.parquet';pq.write_table(pa.Table.from_pylist(rows[1:]).select(['game_id','utc_ms','white_id','black_id']),bad)
        affected=root/'affected.parquet';pq.write_table(pa.table({'chooser':[1]}),affected)
        h=audit.sha(source);c=duckdb.connect()
        report,target,before=audit.inspect_source(c,source,bad,affected,private)
        assert report['invalid_rows']==2 and report['target_time_kind']=='zero'
        assert report['target_key']['length']==18 and not report['target_key']['standard_eight']
        assert report['neighbor_rows']==3 and report['neighbor_positive_time_rows']==1
        assert report['cached_bad_rows_match_source']
        numeric=root/'numeric.parquet'
        pq.write_table(pa.Table.from_pylist([dict(archive_ordinal=11,white_id=1,black_id=3,
            game_id='secret89',utc_ts='2023-06-03 12:00:00',white_elo=1500,black_elo=1700,result='0-1')]),numeric)
        up=audit.numeric_comparison(c,[numeric],private)
        assert up['comparisons'][0]['same_players'] and up['comparisons'][0]['utc_in_June_2023']
        assert not up['comparisons'][0]['same_game_key']
        assert audit.sha(source)==h and audit.snap(source)==before
        audit.js(root/'run/report/KEY_AND_TIME.json',report)
        audit.js(root/'run/report/LINEAGE.json',up)
        audit.export(root/'run',root)
        z=next(root.glob('KAC_TIMESTAMP_DIAGNOSTIC_RESULT_*.zip'))
        with zipfile.ZipFile(z) as archive:
            assert all(name.startswith('report/') for name in archive.namelist())
            text='\n'.join(archive.read(n).decode() for n in archive.namelist())
            for secret in ['broken-key-private','secret88','secret89','nullcase']:
                assert secret not in text
        c.close()
        # A stale cache must not be treated as an exact reproduction of the source.
        pq.write_table(pa.Table.from_pylist(rows[1:2]).select(['game_id','utc_ms','white_id','black_id']),bad)
        c=duckdb.connect()
        try:audit.inspect_source(c,source,bad,affected,private)
        except RuntimeError as e:assert str(e)=='CACHED_BAD_ROWS_DIFFER_FROM_SOURCE'
        else:raise AssertionError('Stale cache accepted')
        c.close()
    print('DIAGNOSTIC_TEST_OK: invalid key; cached-row multiset; null and zero distinction; upstream mismatch retained; source preservation; private-row export exclusion.',flush=True)

if __name__=='__main__':main()
