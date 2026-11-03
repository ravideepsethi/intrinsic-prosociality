from __future__ import annotations
from collections import Counter
from pathlib import Path
import os
import time
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from .inputs import NEEDED, OPTIONAL_CHECKS, AUTHORS
from .material import classify, column
from .io import require, signature, record, save, load, verify, digest


def values(batch, name):
    return np.asarray(column(batch, name).to_numpy(zero_copy_only=False))


def booleans(batch, name):
    a = column(batch, name)
    require(pa.types.is_boolean(a.type), "Expected Boolean column: " + name)
    return np.asarray(a.to_numpy(zero_copy_only=False), dtype=bool)


def outcome_and_roles(batch, month, already_excluded):
    n = batch.num_rows
    names = batch.schema.names
    color = values(batch, "chooser_color")
    require(np.isin(color, ["white", "black"]).all(), "Invalid chooser color")
    white = color == "white"
    require(np.array_equal(values(batch, "disconnected_color"), np.where(white, "black", "white")),
            "Chooser/disconnected colors disagree")
    require((values(batch, "api_status") == "timeout").all(), "A non-timeout row entered the decision universe")
    require((values(batch, "month") == month).all(), "Month partition/value disagreement")
    result = values(batch, "pgn_result")
    require(np.isin(result, ["1-0", "0-1", "1/2-1/2"]).all(), "Missing or invalid recorded result")
    draw = result == "1/2-1/2"
    win = ((result == "1-0") & white) | ((result == "0-1") & ~white)
    loss = ~(draw | win)
    for name, expected in [("timeout_draw", draw), ("timeout_chooser_win", win), ("timeout_chooser_loss", loss), ("api_is_draw", draw)]:
        if name in names:
            require(np.array_equal(booleans(batch, name), expected), "Outcome flag disagrees with PGN: " + name)
    if "api_winner" in names:
        winners = batch.column(names.index("api_winner"))
        expected = np.where(win, color, np.where(loss, np.where(white, "black", "white"), ""))
        actual = pc.fill_null(winners, "")
        require(pc.all(pc.equal(actual, pa.array(expected))).as_py(),
                "API winner disagrees with PGN/roles")
    for name in ("api_rated", "pgn_api_result_consistent"):
        if name in names:
            require(booleans(batch, name).all(), "Source consistency failure: " + name)
    if "api_variant" in names:
        require((values(batch, "api_variant") == "standard").all(), "Non-standard input")
    clean = np.ones(n, bool)
    normalized = []
    for name in ("chooser_username_norm", "disconnected_username_norm"):
        s = pc.utf8_lower(pc.utf8_trim_whitespace(column(batch, name)))
        require(pc.all(pc.greater(pc.utf8_length(s), 0)).as_py(), "Missing participant identity")
        clean &= ~pc.is_in(s, value_set=pa.array(AUTHORS)).to_numpy(zero_copy_only=False)
        normalized.append(s)
    if already_excluded:
        require(clean.all(), "Author account remains in the certified excluded main sample")
    return white, draw, win, loss, clean, normalized


def process_audit(job):
    item, config = job
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    root = Path(config["run"]) / "PRIVATE/audit" / item["family"] / item["month"]
    root.mkdir(parents=True, exist_ok=True)
    key = digest([config["id"], item["family"], item["month"], item["sha256"], "audit_v1"])
    done = root / "DONE.json"
    require(signature(item["path"]) == item["signature"], "Input changed before audit")
    if done.exists():
        r = load(done)
        require(r["key"] == key, "Audit cache identity mismatch")
        for f in r["files"]:
            verify(f)
        return dict(r, reused=True)
    pf = pq.ParquetFile(item["path"])
    columns = NEEDED + [x for x in OPTIONAL_CHECKS if x in pf.schema_arrow.names]
    path = root / "decisions.parquet"
    temp = path.with_suffix(".partial.parquet")
    exceptions = root / "exceptions_PRIVATE.parquet"
    extemp = exceptions.with_suffix(".partial.parquet")
    writer = exwriter = None
    counts = Counter()
    cross = Counter()
    reasons = Counter()
    started = time.monotonic()
    offset = 0
    try:
        for batch in pf.iter_batches(columns=columns, batch_size=config["batch_rows"], use_threads=False):
            white, draw, win, loss, clean, normalized = outcome_and_roles(batch, item["month"], item["already_author_excluded"])
            old_material, cases, inspected = classify(batch, white, config["verify_all_fens"])
            old_grant = booleans(batch, "outcome_kind_draw")
            if "kind_draw" in batch.schema.names:
                require(np.array_equal(booleans(batch,"kind_draw"), old_grant), "Old kind_draw alias disagrees")
            require(np.array_equal(old_material, booleans(batch, "chooser_has_mating_material")), "Stored historical material screen disagrees with piece counts")
            require(np.array_equal(old_grant, draw & old_material), "Stored old grant disagrees with recorded draw and old screen")
            cp = values(batch, "engine_eval_cp_disconnected").astype(float)
            require(np.isfinite(cp).all(), "Nonfinite engine evaluation")
            state = np.select([cp <= -300, cp < -100, cp <= 100, cp < 300], [0, 1, 2, 3], default=4).astype(np.uint8)
            passes = cases == 0
            keep = clean & passes
            new_grant = keep & draw
            bad_win = clean & win & ~passes
            loss_rows = clean & loss
            outside = clean & ~passes & (cp < -100)
            same_bishop_pairs = clean & old_material & ~passes
            added = clean & passes & draw & ~old_grant
            removed = clean & old_grant & ~passes
            kappa = values(batch, "chooser_win_premium_v2").astype(float)
            require(np.isfinite(kappa).all() and (kappa > 0).all(), "Missing/nonpositive original win premium")
            ply = values(batch, "ply_count")
            require(np.isfinite(ply).all() and ((ply >= 0) & (ply == np.trunc(ply))).all(), "Invalid ply count")
            counts.update(dict(input_rows=batch.num_rows, author_rows=int((~clean).sum()),
                old_opportunities=int(clean.sum()), old_grants=int((clean & old_grant).sum()),
                new_opportunities=int(keep.sum()), new_grants=int(new_grant.sum()),
                dropped=int((clean & ~passes).sum()), reclassified_draws=int(added.sum()),
                removed_old_grants=int(removed.sum()), zero_win_conflicts=int(bad_win.sum()),
                chooser_loss_rows=int(loss_rows.sum()), source_chooser_loss_rows=int(loss.sum()),
                retained_chooser_loss_rows=int((keep & loss).sum()),
                dropped_outside_competitive=int(outside.sum()),
                old_pass_new_fail=int(same_bishop_pairs.sum()), fens_fully_parsed=inspected))
            # Fixed-size aggregate bins; never loop over the complete row set in Python.
            for out_code, out_mask in [(0, draw), (1, win), (2, loss)]:
                mask = clean & out_mask
                code = old_material.astype(np.int16) * 2 + passes.astype(np.int16)
                for value, number in enumerate(np.bincount(code[mask], minlength=4)):
                    if number:
                        cross[(out_code, value // 2, value % 2)] += int(number)
                take = mask & ~passes
                code = cases.astype(np.int16) * 5 + state
                for value, number in enumerate(np.bincount(code[take], minlength=20)):
                    if number:
                        reasons[(value // 5, out_code, value % 5)] += int(number)
            table = pa.table(dict(source_row=np.arange(offset, offset+batch.num_rows, dtype=np.int64),
                game_id=column(batch, "game_id"), month=column(batch,"month"), chooser=normalized[0], opponent=normalized[1],
                author_clean=clean, old_material=old_material, case=cases, keep=keep,
                old_grant=old_grant, grant=new_grant, recorded_draw=draw, recorded_chooser_win=win,
                recorded_chooser_loss=loss,
                state=state, eval_cp=cp, ply=ply, speed=column(batch, "api_speed"),
                rating=column(batch, "chooser_elo"), kappa=kappa))
            if writer is None:
                writer = pq.ParquetWriter(temp, table.schema, compression="zstd", compression_level=3)
            writer.write_table(table, row_group_size=config["batch_rows"])
            exmask = bad_win | loss_rows | outside | same_bishop_pairs
            if exmask.any():
                ex = pa.Table.from_batches([batch]).filter(pa.array(exmask))
                ex = ex.append_column("mmr_case", pa.array(cases[exmask]))
                ex = ex.append_column("mmr_zero_win_conflict", pa.array(bad_win[exmask]))
                ex = ex.append_column("mmr_recorded_chooser_loss", pa.array(loss[exmask]))
                ex = ex.append_column("mmr_dropped_outside_competitive", pa.array(outside[exmask]))
                if exwriter is None:
                    exwriter = pq.ParquetWriter(extemp, ex.schema, compression="zstd")
                exwriter.write_table(ex)
            offset += batch.num_rows
            save(root / "progress.json", dict(rows=offset, total=item["rows"], seconds=time.monotonic()-started))
    finally:
        if writer:
            writer.close()
        if exwriter:
            exwriter.close()
    require(offset == item["rows"], "Audit source row count differs")
    require(signature(item["path"]) == item["signature"], "Input changed during audit")
    require(writer is not None, "Empty monthly input is unsupported")
    os.replace(temp, path)
    files = [record(path)]
    if exwriter:
        os.replace(extemp, exceptions)
        files.append(record(exceptions))
    r = dict(key=key, family=item["family"], month=item["month"], counts=dict(counts),
        crosstab=[dict(outcome=o, old_pass=old, new_pass=new, rows=n) for (o, old, new), n in sorted(cross.items())],
        dropped_cases=[dict(case=case, outcome=o, state=s, rows=n) for (case, o, s), n in sorted(reasons.items())],
        files=files, source_sha256=item["sha256"], seconds=time.monotonic()-started, reused=False)
    save(done, r)
    return r


class MaskCursor:
    """Pair input batches with saved decisions even when row-group boundaries differ."""
    def __init__(self, path, batch_rows):
        self.reader = iter(pq.ParquetFile(path).iter_batches(
            columns=["source_row", "game_id", "keep", "grant"], batch_size=batch_rows, use_threads=False))
        self.current = None

    def take(self, n):
        pieces = []
        remaining = n
        while remaining:
            if self.current is None or self.current.num_rows == 0:
                self.current = next(self.reader, None)
            require(self.current is not None, "Decision mask ended before its source")
            count = min(remaining, self.current.num_rows)
            pieces.append(self.current.slice(0, count))
            self.current = self.current.slice(count)
            remaining -= count
        return pa.Table.from_batches(pieces).combine_chunks()

    def exhausted(self):
        return (self.current is None or self.current.num_rows == 0) and next(self.reader, None) is None


def build_panel(job):
    item, config, audit = job
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    root = Path(config["run"]) / "PRIVATE/panels" / item["family"] / ("month=" + item["month"])
    root.mkdir(parents=True, exist_ok=True)
    mask = audit["files"][0]
    key = digest([config["id"], item["sha256"], mask["sha256"], "full_width_v1"])
    done = root / "DONE.json"
    require(signature(item["path"]) == item["signature"], "Source changed before panel build")
    if done.exists():
        r = load(done)
        require(r["key"] == key, "Panel cache identity mismatch")
        verify(r["file"])
        return dict(r, reused=True)
    require(audit["counts"]["zero_win_conflicts"] == 0,
            "Cannot build a panel after a contradictory result")
    verify(mask)
    cursor = MaskCursor(mask["path"], config["batch_rows"])
    source = pq.ParquetFile(item["path"])
    path = root / "analysis_panel.parquet"
    tmp = path.with_suffix(".partial.parquet")
    writer = None
    offset = rows = grants = 0
    try:
        for batch in source.iter_batches(batch_size=config["batch_rows"], use_threads=False):
            decision = cursor.take(batch.num_rows)
            require(pc.all(pc.equal(decision["source_row"], pa.array(np.arange(offset, offset+batch.num_rows)))).as_py(),
                    "Saved decisions shifted relative to source rows")
            require(pc.all(pc.equal(decision["game_id"], column(batch, "game_id"))).as_py(),
                    "Saved decisions do not match source game IDs")
            offset += batch.num_rows
            data = pa.Table.from_batches([batch]).filter(decision["keep"])
            grant = pc.filter(decision["grant"], decision["keep"])
            data = data.set_column(data.schema.get_field_index("outcome_kind_draw"),
                                   pa.field("outcome_kind_draw", pa.bool_()), grant)
            if "kind_draw" in data.column_names:
                data = data.set_column(data.schema.get_field_index("kind_draw"),pa.field("kind_draw",pa.bool_()),grant)
            data = data.set_column(data.schema.get_field_index("chooser_has_mating_material"),
                                   pa.field("chooser_has_mating_material", pa.bool_()), pa.array(np.ones(data.num_rows, bool)))
            if "timeout_draw_no_mating_material" in data.column_names:
                data = data.set_column(data.schema.get_field_index("timeout_draw_no_mating_material"),
                    pa.field("timeout_draw_no_mating_material", pa.bool_()), pa.array(np.zeros(data.num_rows, bool)))
            # No rating, chronology, board, clock, or speed column is altered.
            metadata = dict(data.schema.metadata or {})
            metadata.update({b"mmr_contract": b"MATING_MATERIAL_FIRST_RUN_V1", b"mmr_run_id": config["id"].encode(),
                             b"mmr_source_sha256": item["sha256"].encode()})
            data = data.replace_schema_metadata(metadata)
            if writer is None:
                writer = pq.ParquetWriter(tmp, data.schema, compression="zstd", compression_level=3)
            writer.write_table(data, row_group_size=config["batch_rows"])
            rows += data.num_rows
            grants += pc.sum(grant).as_py() or 0
        require(cursor.exhausted(), "Saved decisions have trailing rows")
    finally:
        if writer:
            writer.close()
    require(rows == audit["counts"]["new_opportunities"] and grants == audit["counts"]["new_grants"],
            "Built panel does not reproduce audited counts")
    require(signature(item["path"]) == item["signature"], "Source changed during panel build")
    os.replace(tmp, path)
    r = dict(key=key, family=item["family"], month=item["month"], rows=rows, grants=grants,
             file=record(path), source_sha256=item["sha256"], decision_sha256=mask["sha256"], reused=False)
    save(done, r)
    return r
