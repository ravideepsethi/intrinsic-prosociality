"""Optional synthetic memory check; never invoked by the production launcher.

Usage: python validation/benchmark_chronology.py /absolute/result.json
Creates only temporary synthetic Parquets, then removes them.
"""
import sys, tempfile, time, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'code'))
from bootstrap import *
import bounded_comparisons as bc
import duckdb


def main():
    n=5_000_000; memory=.384; width=200_000
    with tempfile.TemporaryDirectory(prefix='material_chronology_benchmark_') as directory:
        root=Path(directory); q=root/'q.parquet'; oq=root/'oq.parquet'; ox=root/'ox.parquet'
        db=connect(root/'generate',1.)
        try:
            extra=','.join(f'(i*{k+11}%10000003)::BIGINT payload_{k}' for k in range(8))
            copy(db, f"SELECT i::BIGINT row_id,lpad(i::VARCHAR,8,'0') game_id,i%100003 recipient_id,"
                 f"i%900001+100004 opponent_id,i+1700000000000 archive_start_ms,{extra} FROM range({n+1}) t(i)",q)
            copy(db,'SELECT * FROM '+c.parq([q])+f' WHERE row_id<{n}',oq)
            extra=','.join(f'(i*{k+3}%999983)::BIGINT fact_{k}' for k in range(12))
            copy(db,f'SELECT i::BIGINT row_id,i%3<>0 eligible_main,i%4<>0 first_observed_pair,{extra} FROM range({n}) t(i)',ox)
        finally:db.close()
        original={};started=time.monotonic();db=connect(root/'original',memory)
        try:
            for name,path in [('q',q),('oq',oq),('ox',ox)]:view(db,name,path)
            copy(db,'SELECT q.row_id,ox.* EXCLUDE(row_id) FROM q JOIN oq USING(row_id) JOIN ox USING(row_id) ORDER BY row_id',root/'original_hits.parquet')
            original['status']='COMPLETE'
        except duckdb.OutOfMemoryException as error:
            original.update(status='OUT_OF_MEMORY',error=str(error).splitlines()[0])
        finally:
            db.close();original['seconds']=time.monotonic()-started
        # Production installs this process-local digest cache. It still hashes
        # every input once; otherwise a microbenchmark repeats that disk read.
        from fast_digest_cache import install
        install(c.frozen.r.io)
        started=time.monotonic();out,meta=bc.reuse_plan(root/'bounded',c.key('benchmark102'),q,oq,ox,width,memory)
        reuse_seconds=time.monotonic()-started
        require(meta['reused']==n and meta['missing']==1,'Synthetic reuse count changed')
        fresh=root/'fresh.parquet'
        db=connect(root/'freshgen',memory)
        try:
            extra=','.join(f'({n}*{k+3}%999983)::BIGINT fact_{k}' for k in range(12))
            copy(db,f'SELECT {n}::BIGINT row_id,{n}%3<>0 eligible_main,{n}%4<>0 first_observed_pair,{extra}',fresh)
        finally:db.close()
        started=time.monotonic();final,_=bc.eligible_queries(root/'bounded',c.key('benchmark102'),q,[out/'hits.parquet',fresh],width,memory)
        eligible_seconds=time.monotonic()-started
        db=connect(root/'verify',memory)
        try:
            view(db,'x',out/'hits.parquet');view(db,'f',final/'queries.parquet')
            require(db.execute(f'SELECT count(*) FROM x WHERE row_id<0 OR row_id>={n} OR '+
                ' OR '.join(f'fact_{k}<>(row_id*{k+3}%999983)' for k in range(12))).fetchone()[0]==0,
                'Synthetic factual values changed')
            require(db.execute('SELECT count(*) FROM f WHERE row_id%3=0 OR row_id%4=0').fetchone()[0]==0,
                'Synthetic eligibility changed')
            expected=db.execute(f'SELECT count(*) FROM range({n+1}) t(i) WHERE i%3<>0 AND i%4<>0').fetchone()[0]
            require(rows(final/'queries.parquet')==expected,'Synthetic eligible count changed')
        finally:db.close()
        result=dict(synthetic_rows=n+1,duckdb_memory_gb=memory,maximum_ids_per_chunk=width,
                    original_join=original,bounded_reuse_seconds=reuse_seconds,
                    bounded_eligibility_seconds=eligible_seconds,checks='PASS',
                    production_benchmark=False,retained_rows=expected)
        Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':main()
