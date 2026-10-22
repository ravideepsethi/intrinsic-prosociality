"""Read score and bound flags from the SAME UCI message, never merged info.

Search ends at the same requested node limit. Its evaluation is the last
unbounded UCI score available before bestmove. A final bound is never used as
a point estimate. Search-total nodes and selected-score nodes remain separate.
"""
import threading
import chess
import chess.engine

CONTRACT = 'KAC_A2_LAST_UNBOUNDED_AT_FIXED_BUDGET_V1'


class ScoreStream:
    def __init__(self):
        self.last = None
        self.last_exact = None
        self.messages = []
        self.max_nodes = 0
        self.merged = {}

    def post(self, info):
        if info.get('multipv', 1) != 1:
            raise RuntimeError('Unexpected MultiPV stream')
        self.max_nodes = max(self.max_nodes, int(info.get('nodes', 0)))
        self.merged.update(info)  # Diagnostic reproduction of the old behavior.
        if 'score' not in info:
            return
        score = info['score'].pov(chess.WHITE)
        self.last = dict(cp=score.score(), mate=score.mate(),
                         lowerbound=bool(info.get('lowerbound', False)),
                         upperbound=bool(info.get('upperbound', False)),
                         nodes=int(info.get('nodes', 0)), depth=info.get('depth'))
        self.messages.append(self.last.copy())
        if not self.last['lowerbound'] and not self.last['upperbound']:
            self.last_exact = self.last.copy()

    def finish(self):
        last = self.last
        selected = self.last_exact
        bounded = bool(last and (last['lowerbound'] or last['upperbound']))
        merged_bound = bool(self.merged.get('lowerbound') or self.merged.get('upperbound'))
        status = ('NO_SCORE' if last is None else 'NO_EXACT_SCORE' if selected is None else
                  'SHORT' if self.max_nodes < 100000 else 'SCORED')
        return dict(cp_white=selected['cp'] if selected else None,
                    mate_white=selected['mate'] if selected else None,
                    nodes=self.max_nodes, score_nodes=selected['nodes'] if selected else 0,
                    depth=selected['depth'] if selected else None, status=status,
                    final_depth=last['depth'] if last else None,
                    selected_unbounded=selected is not None,
                    used_prior_exact=bool(selected and bounded),
                    final_cp_white=last['cp'] if last else None,
                    final_mate_white=last['mate'] if last else None,
                    final_lowerbound=bool(last and last['lowerbound']),
                    final_upperbound=bool(last and last['upperbound']),
                    score_messages=len(self.messages),
                    bounded_messages=sum(m['lowerbound'] or m['upperbound'] for m in self.messages),
                    merged_bound=merged_bound,
                    stale_bound=bool(last and merged_bound and not bounded))


def collect(engine, fen, timeout=180):
    board = chess.Board(fen)
    if board.is_game_over():
        result = ScoreStream().finish()
        result.update(status='TERMINAL', bestmove=None, complete=True)
        return result, []
    stream = ScoreStream()
    # SimpleAnalysisResult iteration does not itself impose a search deadline.
    timer = threading.Timer(timeout, engine.close)
    timer.daemon = True
    timer.start()
    try:
        with engine.analysis(board, chess.engine.Limit(nodes=100000), game=object(),
                             info=chess.engine.INFO_ALL) as analysis:
            for message in analysis:
                stream.post(message)
            best = analysis.wait()
        if best.move is None or best.move not in board.legal_moves:
            raise RuntimeError('No legal bestmove at completed nonterminal search')
        result = stream.finish()
        result.update(bestmove=best.move.uci(), complete=True)
        return result, stream.messages
    finally:
        timer.cancel()
