"""scalachess InsufficientMatingMaterial.apply(board, chooser), 2023/2025.

The side-specific test is NOT the global dead-position / insufficient-material
test offered by many chess libraries. In particular, two knights pass here.
No outcome, rating, or engine evaluation enters the predicate.
"""
from __future__ import annotations
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
from .io import require

ROLES = ("pawns", "knights", "bishops", "rooks", "queens")
PIECES = "PNBRQ"
COUNT_COLUMNS = [s + "_" + r for s in ("chooser", "disconnected") for r in ROLES]
CASE_NAMES = {0: "passes", 1: "bare_king", 2: "one_knight_vs_king_queens", 3: "same_color_bishops_no_opponent_pawn_knight"}
RULE = {
    "name": "SCALACHESS_CHOOSER_MATING_MATERIAL_2023_2025_V1",
    "source_commits": ["3050826", "e8133fa"],
    "drop": ["chooser king only", "chooser king + exactly one knight; opponent only king/queens",
             "chooser king + bishops only; all board bishops on one square color; opponent no pawn/knight"],
    "recorded_position": "final FEN, disconnected side to move",
    "retained_grant": "recorded draw",
    "retained_claim": "recorded chooser win",
}


def fen_state(fen, chooser_white):
    """Independent scalar parser, used for sparse boundary rows and tests."""
    require(isinstance(fen, str), "Missing final FEN")
    fields = fen.split()
    require(len(fields) == 6 and fields[1] in ("w", "b"), "Invalid final FEN fields")
    require(fields[1] == ("b" if chooser_white else "w"), "FEN turn disagrees with disconnected role")
    rows = fields[0].split("/")
    require(len(rows) == 8, "Invalid FEN ranks")
    counts = {x: 0 for x in "PNBRQKpnbrqk"}
    colors = set()
    for rank, row in enumerate(rows):
        file = 0
        previous_digit = False
        for char in row:
            if char in "12345678":
                require(not previous_digit, "Adjacent FEN digits")
                file += int(char)
                previous_digit = True
            else:
                require(char in counts and file < 8, "Invalid FEN piece/width")
                counts[char] += 1
                if char in "Bb":
                    colors.add((rank + file) % 2)
                file += 1
                previous_digit = False
        require(file == 8, "Invalid FEN rank width")
    require(counts["K"] == counts["k"] == 1, "Final FEN must contain one king of each color")
    own = np.array([counts[x if chooser_white else x.lower()] for x in PIECES], dtype=np.int16)
    other = np.array([counts[x.lower() if chooser_white else x] for x in PIECES], dtype=np.int16)
    return own, other, len(colors) == 2


def lacks_mating_material(fen, chooser_color):
    """The public scalar predicate: True means DROP this decision."""
    require(chooser_color in ("white", "black"), "Unknown chooser color")
    own, other, both_colors = fen_state(fen, chooser_color == "white")
    p, n, b, r, q = own
    op, on, ob, ore, oq = other
    if own.sum() == 0:
        return True
    if n == 1 and p + b + r + q == 0 and op + on + ob + ore == 0:
        return True
    return bool(b > 0 and p + n + r + q == 0 and op + on == 0 and not both_colors)


def column(batch, name):
    idx = batch.schema.get_field_index(name)
    require(idx >= 0, "Missing column: " + name)
    col = batch.column(idx)
    require(col.null_count == 0, "Null values in " + name)
    return col


def classify(batch, chooser_white, verify_all_fens=False):
    """Vectorized exact rule, with sparse FEN parsing at every material boundary.

    Cached counts come from the authenticated producer, which counted them from
    this same FEN. We reparse EVERY bare-king, knight-only, bishop-only row, plus
    a deterministic 1/4096 sample of the others. This checks every possible
    disagreement with the old rule, including opposite-color bishops.
    --verify-all-fens is a slower independent validation option.
    """
    counts = []
    for name in COUNT_COLUMNS:
        values = np.asarray(column(batch, name).to_numpy(zero_copy_only=False))
        require(np.isfinite(values).all() and ((values >= 0) & (values <= 16) &
                (values == np.trunc(values))).all(), "Invalid piece counts in " + name)
        counts.append(values.astype(np.int16, copy=False))
    p, n, b, r, q, op, on, ob, ore, oq = counts
    require(((p + n + b + r + q) <= 15).all() and ((op + on + ob + ore + oq) <= 15).all(),
            "More than 15 non-king pieces on one side")
    old = (p > 0) | (r > 0) | (q > 0) | (b >= 2) | ((b > 0) & (n > 0)) | (n >= 2)
    king = (p + n + b + r + q) == 0
    knight_only = (n == 1) & ((p + b + r + q) == 0)
    knight_bad = knight_only & ((op + on + ob + ore) == 0)
    bishop_only = (b > 0) & ((p + n + r + q) == 0)
    bishop_bad = bishop_only & ((op + on) == 0)
    fens = column(batch, "fen_after_last_move")
    # Arrow performs the inexpensive role check on ALL rows; the full parser is sparse.
    turn = pc.list_element(pc.split_pattern(fens, pattern=" ", max_splits=2), 1)
    expected = pa.array(np.where(chooser_white, "b", "w"))
    require(pc.all(pc.equal(turn, expected)).as_py(), "Final FEN turn disagrees with chooser role")
    check = king | knight_only | bishop_only
    if verify_all_fens:
        check[:] = True
    else:
        # Position-based stride has fixed cost; does not affect the rule or output.
        check[::4096] = True
    idx = np.flatnonzero(check)
    inspected = pc.take(fens, pa.array(idx)).to_pylist()
    for i, fen in zip(idx, inspected):
        own, other, both = fen_state(fen, bool(chooser_white[i]))
        require(np.array_equal(own, [x[i] for x in counts[:5]]) and
                np.array_equal(other, [x[i] for x in counts[5:]]), "FEN/cached piece counts disagree")
        if bishop_bad[i] and both:
            bishop_bad[i] = False
    cases = np.zeros(len(chooser_white), dtype=np.uint8)
    cases[king] = 1
    cases[knight_bad] = 2
    cases[bishop_bad] = 3
    return old, cases, len(idx)
