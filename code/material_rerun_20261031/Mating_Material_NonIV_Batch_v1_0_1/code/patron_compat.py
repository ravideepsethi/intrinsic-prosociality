"""Arrow streaming adapter for the pinned DuckDB 1.3.2 environment.

The SQL, batch size, model algebra, and covariance calculations are unchanged.
The archived producer used a method introduced after the pinned environment.
"""

def record_batches(database, query, rows_per_batch=200_000):
    reader = database.execute(query).fetch_record_batch(rows_per_batch=rows_per_batch)
    try:
        yield from reader
    finally:
        reader.close()


def install(engine):
    engine.record_batches = record_batches
