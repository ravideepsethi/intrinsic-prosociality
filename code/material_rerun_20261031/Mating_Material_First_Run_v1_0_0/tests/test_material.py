import random
import unittest
import numpy as np
import pyarrow as pa
from fixtures import FIXTURES, row, make_rows
from mmrerun.material import lacks_mating_material, classify, fen_state


class MaterialTests(unittest.TestCase):
    def test_nine_handoff_cases_and_promoted_bishops_both_colors(self):
        for name,fen,drop in FIXTURES:
            with self.subTest(name=name):
                self.assertEqual(lacks_mating_material(fen,"white"),drop)
                black=fen.split()[0].swapcase()+" w - - 0 1"
                self.assertEqual(lacks_mating_material(black,"black"),drop)

    def test_vector_equals_scalar(self):
        data=make_rows()
        for name,fen,drop in FIXTURES:
            black=fen.split()[0].swapcase()+" w - - 0 1"
            data.append(row(name,black,drop,len(data),color="black"))
        batch=pa.RecordBatch.from_pylist(data)
        white=np.array([r["chooser_color"]=="white" for r in data])
        old,cases,checked=classify(batch,white)
        self.assertEqual((cases!=0).tolist(),[lacks_mating_material(r["fen_after_last_move"],r["chooser_color"]) for r in data])
        self.assertEqual(old.tolist(),[r["chooser_has_mating_material"] for r in data])
        self.assertGreater(checked,0)

    def test_knight_and_bishop_opponent_exceptions(self):
        for piece in "rnbp":
            fen=piece+"5k1/8/8/8/8/8/8/4K1N1 b - - 0 1"
            self.assertFalse(lacks_mating_material(fen,"white"))
        for piece in "rq":
            fen=piece+"5k1/8/8/8/8/8/8/4KB2 b - - 0 1"
            self.assertTrue(lacks_mating_material(fen,"white"))
        self.assertFalse(lacks_mating_material("n5k1/8/8/8/8/8/8/4KB2 b - - 0 1","white"))

    def test_bad_turn_missing_king_invalid_width_rejected(self):
        for fen in ["6k1/8/8/8/8/8/8/4K3 w - - 0 1", "8/8/8/8/8/8/8/4K3 b - - 0 1",
                    "6k2/8/8/8/8/8/8/4K3 b - - 0 1", "6k1/8/8/8/8/8/8/13K3 b - - 0 1"]:
            with self.assertRaises(RuntimeError):lacks_mating_material(fen,"white")

    def test_cached_count_mismatch_rejected(self):
        data=make_rows()
        data[3]["disconnected_rooks"]=0
        with self.assertRaisesRegex(RuntimeError,"piece counts disagree"):
            classify(pa.RecordBatch.from_pylist(data),np.ones(len(data),bool))

    def test_null_count_and_missing_column_rejected(self):
        for mutation in ("null","missing"):
            data=make_rows()
            if mutation=="null":data[0]["chooser_pawns"]=None
            else:
                for r in data:r.pop("chooser_pawns")
            with self.assertRaises(RuntimeError):
                classify(pa.RecordBatch.from_pylist(data),np.ones(len(data),bool))

    def test_randomized_scalar_vector_parity(self):
        rng=random.Random(20261027)
        data=[]
        for index in range(1000):
            board=[""]*64
            board[6]="k";board[60]="K"
            squares=[x for x in range(64) if x not in (6,60)]
            rng.shuffle(squares)
            for char,square in zip(rng.choices("PNBRQpnbrq",k=rng.randrange(0,20)),squares):board[square]=char
            rows=[]
            for rank in range(8):
                text="";empty=0
                for char in board[rank*8:(rank+1)*8]:
                    if char:
                        if empty:text+=str(empty);empty=0
                        text+=char
                    else:empty+=1
                if empty:text+=str(empty)
                rows.append(text)
            fen="/".join(rows)+" b - - 0 1"
            own,other,_=fen_state(fen,True)
            if own.sum()>15 or other.sum()>15:continue
            data.append(row("random",fen,lacks_mating_material(fen,"white"),index))
        _,cases,_=classify(pa.RecordBatch.from_pylist(data),np.ones(len(data),bool),verify_all_fens=True)
        self.assertEqual((cases!=0).tolist(),[lacks_mating_material(r["fen_after_last_move"],"white") for r in data])


if __name__=="__main__":unittest.main()
