# Version 1.0.1: explicit UTC during validation

The v1.0.0 production run stopped before building the arena sample or estimating
any model. All 153 input-file hash/schema checks completed, then the original
source-mask validator rejected 138,986 rows under its combined flag/identity/month
check. The uploaded failure report passed its checksum, ZIP CRC and 3-entry
manifest checks. Its aggregate error does not identify which condition failed.

The arena wrapper omitted `SET TimeZone='UTC'`. The original pool builder sets
UTC explicitly before calling the same validator. That validator compares the
stored month with `strftime(to_timestamp(focal_start_ms/1000.0),'%Y-%m')`, whose
result depends on the DuckDB session timezone. Valid UTC month-boundary games
therefore fail when the session inherits a North American or other non-UTC zone.
The development environment was UTC, which hid the omission in v1.0.0's tests.

Version 1.0.1 restores the original builder's timezone setting on every shared
database connection. It calls the original, byte-identical validator with all
its checks intact. The sample rule, source files, outcomes and estimators are
unchanged. No row is discarded to get past validation.

Before validating, the runner writes `validation/source_month_timezone.json`
with the inherited and active timezone and month mismatches under both. This
will determine whether timezone conversion explains all 138,986 flagged rows
on the production machine; that exact count cannot be confirmed from the
v1.0.0 report alone. If validation still fails, the report also includes counts
for each of the original flag/identity/month failure conditions.

Three added tests exercise the complete original source-mask validator:

- Correct UTC rows fail under Toronto, Denver and Paris timezones and pass
  when UTC is restored, with no data edits.
- The corrected connection factory passes the same rows when its inherited
  defaults are Toronto, Denver, Paris, Kolkata and UTC. Dates straddle month
  boundaries in winter and summer.
- Genuine identity and month errors remain fatal, with diagnostic counts.

The v1.0.1 run uses a separate `output/arena_replication_v101/` directory and
`ARENA_REPLICATION_RESULTS_v101_*.zip` report names. The failed v1.0.0 run is
preserved. No completed analysis work needs to be recovered from that run.
Rerunning the v1.0.1 command resumes its own checkpoints normally.
