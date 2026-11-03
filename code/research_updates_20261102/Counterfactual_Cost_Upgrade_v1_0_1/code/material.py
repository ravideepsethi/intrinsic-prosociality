"""Source-based material rule, separate from the project's historical screen.

Implements scalachess InsufficientMatingMaterial.apply(board, color) at the
bundled 2023 and 2025 snapshots. The usual cases use cached piece counts.
Only bishop-only cases needing square colors parse the cached final FEN.
No observed result or rating change enters this classification.
"""
from __future__ import annotations

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc

from engine import require

ROLES = ("pawns", "knights", "bishops", "rooks", "queens")
MATERIAL_COLUMNS = ["fen_after_last_move"] + [
    side + "_" + role for side in ("chooser", "disconnected") for role in ROLES]


def bishop_colors(fen, chooser_white, own_bishops, other_bishops):
    """Whether all bishops on the board occupy both square colors."""
    require(isinstance(fen, str), "Missing FEN for bishop-color material check")
    fields = fen.split()
    require(len(fields) >= 2, "Invalid FEN for bishop-color material check")
    require(fields[1] == ("b" if chooser_white else "w"), "FEN turn/chooser disagreement")
    ranks = fields[0].split("/")
    require(len(ranks) == 8, "Invalid FEN board ranks")
    colors = set(); white_b = black_b = 0
    kings = {"K": 0, "k": 0}
    for rank_index, row in enumerate(ranks):
        file_index = 0
        for char in row:
            if char in "12345678":
                file_index += int(char)
            else:
                require(char in "prnbqkPRNBQK" and file_index < 8, "Invalid FEN piece")
                if char in "Bb":
                    colors.add((rank_index + file_index) % 2)
                    white_b += char == "B"; black_b += char == "b"
                if char in kings:
                    kings[char] += 1
                file_index += 1
        require(file_index == 8, "Invalid FEN board width")
    require(kings == {"K": 1, "k": 1}, "Invalid king counts in FEN")
    actual = (white_b, black_b) if chooser_white else (black_b, white_b)
    require(actual == (own_bishops, other_bishops), "FEN/cached bishop-count mismatch")
    return len(colors) == 2


def classify_material(batch, chooser_white):
    counts = {}
    for side in ("chooser", "disconnected"):
        for role in ROLES:
            col = batch.column(batch.schema.get_field_index(side + "_" + role))
            require(col.null_count == 0, "Missing cached piece count")
            x = np.asarray(col.to_numpy(zero_copy_only=False), dtype=float)
            require(np.isfinite(x).all() and ((x >= 0) & (x <= 16) & (x == np.trunc(x))).all(),
                    "Invalid cached piece count")
            counts[side + "_" + role] = x.astype(np.int16)
    p, n, b, r, q = (counts["chooser_" + role] for role in ROLES)
    op, on, ob, ore, oq = (counts["disconnected_" + role] for role in ROLES)
    historical = (p > 0) | (r > 0) | (q > 0) | (b >= 2) | ((b > 0) & (n > 0)) | (n >= 2)
    only_king = (p + n + b + r + q) == 0
    knight_insufficient = ((n == 1) & ((p + b + r + q) == 0) &
                           ((op + on + ob + ore) == 0))  # Opponent may have queens.
    bishop_only = (b > 0) & ((p + n + r + q) == 0)
    bishop_insufficient = bishop_only & ((op + on) == 0)
    # Opposite-color bishops on EITHER side supply the remaining exception.
    inspect = np.flatnonzero(bishop_insufficient & ((b + ob) >= 2))
    if len(inspect):
        column = batch.column(batch.schema.get_field_index("fen_after_last_move"))
        fens = pc.take(column, pa.array(inspect)).to_pylist()
        for i, fen in zip(inspect, fens):
            bishop_insufficient[i] = not bishop_colors(fen, bool(chooser_white[i]), int(b[i]), int(ob[i]))
    platform = ~(only_king | knight_insufficient | bishop_insufficient)
    return historical, platform, len(inspect)
