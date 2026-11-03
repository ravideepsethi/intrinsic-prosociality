"""Restore F50 follow-up from the authenticated, already assembled Phase-050 cache.

The entry projection deliberately omits later-choice outcomes. The wide feature
cache retains their complete-window nulls. Never rebuild, fill or select on Y.
"""
from r7_common import *
from r7_inputs import completed_file
import preliminary_core as core

IDENTITY = ['game_id','recipient_id','opponent_id','archive_start_ms','anchor_ms','complete90']


def attach(entry, ordinary, features, root, conf, memory):
    def build(tmp):
        for path,columns in [(entry,['row_id']+IDENTITY),
                             (ordinary,['row_id']+IDENTITY+['y','reached']),
                             (features,['row_id']+IDENTITY+['y','reached','entry_eligible','previous_frame','author_game'])]:
            env_common.checked_columns(path,columns)
        if {'y','reached'} & set(pq.ParquetFile(entry).schema_arrow.names):
            raise RuntimeError('F50 entry projection unexpectedly already contains follow-up outcomes')
        c=io.conn(tmp/'spill',min(memory-1,4),1)
        try:
            for name,path in [('e',entry),('o',ordinary),('f',features)]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+io.parq([path]))
            # Materialize only the narrow F50 projection. The wide cache may be
            # much larger; it never becomes an in-memory Arrow/NumPy table.
            keys=','.join('f.'+k for k in ['row_id']+IDENTITY+['y','reached'])
            c.execute('CREATE TEMP TABLE y AS SELECT '+keys+',f.entry_eligible,f.previous_frame,f.author_game FROM f SEMI JOIN e USING(row_id)')
            n=pq.ParquetFile(entry).metadata.num_rows
            for name in ('e','y'):
                if c.execute('SELECT count(*),count(DISTINCT row_id) FROM '+name).fetchone()!=(n,n):
                    raise RuntimeError('F50 outcome attachment missing or duplicate row IDs: '+name)
            if c.execute('SELECT count(*) FROM y WHERE entry_eligible IS DISTINCT FROM true OR previous_frame IS DISTINCT FROM false OR author_game IS DISTINCT FROM false').fetchone()[0]:
                raise RuntimeError('F50 outcome source has wrong eligibility, cohort or author treatment')
            mismatch=' OR '.join('a.'+k+' IS DISTINCT FROM b.'+k for k in IDENTITY)
            if c.execute('SELECT count(*) FROM e a JOIN y b USING(row_id) WHERE '+mismatch).fetchone()[0]:
                raise RuntimeError('F50 outcome attachment identity mismatch')
            if c.execute(f'SELECT count(*) FROM y WHERE anchor_ms IS NULL OR complete90 IS DISTINCT FROM (anchor_ms+{90*DAY}<{core.PANEL_END})').fetchone()[0]:
                raise RuntimeError('F50 complete-window flag differs from the frozen anchor/cutoff rule')
            invalid='''(complete90 AND (y IS NULL OR reached IS NULL OR y NOT IN (0,1)
                OR reached NOT IN (0,1) OR y>reached))
                OR (NOT complete90 AND (y IS NOT NULL OR reached IS NOT NULL))'''
            if c.execute('SELECT count(*) FROM y WHERE '+invalid).fetchone()[0]:
                raise RuntimeError('F50 follow-up violates binary/complete-window missingness contract')
            # Independently reconcile the ordinary frame's frozen outcomes on
            # exactly its rows, including both outcome flags and all identities.
            no=pq.ParquetFile(ordinary).metadata.num_rows
            if c.execute('SELECT count(*),count(DISTINCT a.row_id) FROM o a JOIN y b USING(row_id)').fetchone()!=(no,no):
                raise RuntimeError('Ordinary outcome bridge missing or duplicate rows')
            if c.execute('SELECT count(*) FROM o a JOIN y b USING(row_id) WHERE '+mismatch+
                         ' OR a.y IS DISTINCT FROM b.y OR a.reached IS DISTINCT FROM b.reached').fetchone()[0]:
                raise RuntimeError('Ordinary frozen outcomes differ from the F50 outcome source')
            written=io.copy(c,'SELECT e.*,y.y,y.reached FROM e JOIN y USING(row_id) ORDER BY e.row_id',tmp/'model.parquet')
            if written!=n:raise RuntimeError('Outcome attachment changed the frozen F50 denominator')
            known,positive,reached=c.execute('SELECT count(*) FILTER(WHERE complete90),count(*) FILTER(WHERE y=1),count(*) FILTER(WHERE reached=1) FROM y').fetchone()
            info=dict(sample='F50',rows=n,complete90_rows=known,incomplete90_rows=n-known,
                      y_ones=positive,reached_ones=reached,ordinary_bridge_rows=no,
                      ordinary_outcomes_identical=True,rows_removed=0,outcomes_imputed=0,
                      source='authenticated Phase-050 assembled/features.parquet',
                      incomplete_window_policy='retain nulls; full-row Y analyses explicitly unsupported if any selected row lacks complete follow-up')
            io.js(tmp/'summary.json',info)
            return info
        finally:finish_connection(c,tmp/'spill')
    stage,info=stable_stage(root,conf,build,[entry,ordinary,features])
    return stage/'model.parquet',info


def prepare(paths,binding,root,conf,memory):
    features=completed_file(binding['phase50']['root'],'assembled/features.parquet',binding['phase50']['conf'])
    path,info=attach(paths['F50'],paths['O50'],features,root,conf,memory)
    return dict(paths,F50=path),info
