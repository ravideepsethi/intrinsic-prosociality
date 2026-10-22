#!/usr/bin/env python3
import argparse, json, re, shutil, time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime

import duckdb
import pyarrow.parquet as pq

MONTH_RE = re.compile(r"month=([0-9]{4}-[0-9]{2})")
SPEED_RE = re.compile(r"speed=([^/]+)")

def q(s):
    return "'" + str(s).replace("'", "''") + "'"

def find_parts(numeric_root):
    base = Path(numeric_root) / "events_numeric"
    parts = []
    for d in sorted(base.glob("month=*/speed=*")):
        m = MONTH_RE.search(str(d))
        s = SPEED_RE.search(str(d))
        if m and s and list(d.glob("*.parquet")):
            parts.append((m.group(1), s.group(1), d))
    return parts

def count_rows(path):
    total = 0
    files = list(Path(path).rglob("*.parquet"))
    for p in files:
        total += pq.ParquetFile(p).metadata.num_rows
    return total, len(files)

def run_one(month, speed, in_dir, out_root, memory_gb):
    t0 = time.time()
    out_root = Path(out_root)
    final_dir = out_root / "events_replay_sorted_time" / f"speed={speed}" / f"month={month}"
    done = final_dir / "_SUCCESS.json"
    final_file = final_dir / "part-00000.parquet"

    tmp_dir = out_root / "tmp" / f"speed={speed}" / f"month={month}"
    tmp_file = tmp_dir / "part-00000.tmp.parquet"

    log = out_root / "logs" / f"sort_time_{speed}_{month}.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    if done.exists():
        rows, files = count_rows(final_dir)
        return {"month": month, "speed": speed, "status": "SKIP", "rows": rows, "files": files, "inversions": 0, "elapsed_sec": 0}

    if final_dir.exists():
        shutil.rmtree(final_dir)
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    final_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    duck_tmp = out_root / "duckdb_tmp" / f"{speed}_{month}"
    duck_tmp.mkdir(parents=True, exist_ok=True)

    glob = str(Path(in_dir) / "*.parquet")

    sql = f"""
    COPY (
      WITH base AS (
        SELECT
          archive_ordinal,
          utc_ts,
          try_strptime(utc_ts, '%Y-%m-%d %H:%M:%S') AS ts,
          game_id,
          white_id,
          black_id,
          white_elo,
          black_elo,
          white_rating_diff,
          black_rating_diff,
          result
        FROM read_parquet({q(glob)})
        WHERE
          result IN ('1-0','0-1','1/2-1/2')
          AND white_id IS NOT NULL
          AND black_id IS NOT NULL
          AND white_elo IS NOT NULL
          AND black_elo IS NOT NULL
          AND utc_ts IS NOT NULL
      )
      SELECT
        CAST(archive_ordinal AS BIGINT) AS archive_ordinal,
        CAST(epoch_ms(ts) AS BIGINT) AS utc_ms,
        game_id,
        CAST(white_id AS BIGINT) AS white_id,
        CAST(black_id AS BIGINT) AS black_id,
        CAST(white_elo AS INTEGER) AS white_elo,
        CAST(black_elo AS INTEGER) AS black_elo,
        CAST(white_rating_diff AS INTEGER) AS white_rating_diff,
        CAST(black_rating_diff AS INTEGER) AS black_rating_diff,
        CAST(
          CASE result
            WHEN '1-0' THEN 2
            WHEN '1/2-1/2' THEN 1
            WHEN '0-1' THEN 0
            ELSE NULL
          END AS TINYINT
        ) AS result_code
      FROM base
      WHERE ts IS NOT NULL
      ORDER BY archive_ordinal
    )
    TO {q(str(tmp_file))}
    (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000);
    """

    log.write_text(sql)

    con = duckdb.connect()
    con.execute("SET threads=1")
    con.execute(f"SET memory_limit='{memory_gb}GB'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory={q(str(duck_tmp))}")
    con.execute(sql)
    con.close()

    tmp_file.replace(final_file)
    shutil.rmtree(tmp_dir)

    rows, files = count_rows(final_dir)

    inv = 0
    prev = None
    pf = pq.ParquetFile(final_file)
    for batch in pf.iter_batches(columns=["archive_ordinal"], batch_size=1_000_000):
        arr = batch.column(0).to_numpy(zero_copy_only=False)
        if len(arr) == 0:
            continue
        if prev is not None and arr[0] < prev:
            inv += 1
        if len(arr) > 1:
            inv += int((arr[1:] < arr[:-1]).sum())
        prev = int(arr[-1])

    rec = {
        "month": month,
        "speed": speed,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "rows": int(rows),
        "files": int(files),
        "inversions": int(inv),
        "elapsed_sec": round(time.time() - t0, 2),
    }
    done.write_text(json.dumps(rec, indent=2))

    return {"month": month, "speed": speed, "status": "OK" if inv == 0 else "BAD_SORT", **rec}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--numeric-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--memory-gb-per-worker", type=int, default=3)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(exist_ok=True)

    parts = find_parts(args.numeric_root)

    command = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "numeric_root": args.numeric_root,
        "out": str(out),
        "workers": args.workers,
        "memory_gb_per_worker": args.memory_gb_per_worker,
        "n_partitions": len(parts),
        "adds": "utc_ms from utc_ts for time-aware RD inflation",
    }
    (out / "command.json").write_text(json.dumps(command, indent=2))
    print(json.dumps(command, indent=2), flush=True)

    results, failed = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_one, m, s, str(d), str(out), args.memory_gb_per_worker): (m, s) for m, s, d in parts}
        for fut in as_completed(futs):
            try:
                rec = fut.result()
            except Exception as e:
                m, s = futs[fut]
                rec = {"month": m, "speed": s, "status": "FAIL", "error": repr(e)}
            results.append(rec)
            if rec["status"] not in {"OK", "SKIP"}:
                failed.append(rec)
            print(f"{rec['status']} {rec['month']} {rec['speed']} rows={rec.get('rows')} inv={rec.get('inversions')} elapsed={rec.get('elapsed_sec')}s", flush=True)
            with (out / "progress_results.jsonl").open("a") as f:
                f.write(json.dumps(rec) + "\n")

    results = sorted(results, key=lambda r: (r["speed"], r["month"]))
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "n_partitions": len(results),
        "n_failed_or_bad": len(failed),
        "bad": failed[:50],
        "total_rows": int(sum(r.get("rows") or 0 for r in results if r.get("status") in {"OK", "SKIP"})),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\nSUMMARY")
    print(json.dumps(summary, indent=2), flush=True)

    if failed:
        raise SystemExit(f"Failed/bad partitions: {len(failed)}")

if __name__ == "__main__":
    main()
