"""Exercise real parquet/SQL bridges, including empty outcome shards."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from common_retained import *
from frames_retained import act_features

class FrameJoinTests(unittest.TestCase):
 def test_act_bridge_both_colors_exact_order_and_identity_failure(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);src=root/'source.parquet';panel=root/'panel.parquet'
   pq.write_table(pa.table(dict(row_id=[0,3],game_id=[10,11],recipient_id=[1,2],opponent_id=[7,8],received=[True,False])),src)
   data=dict(game_id=[11,10],disconnected_user_id=[2,1],chooser_user_id=[8,7],kind_draw=[False,True],chooser_color=['white','black'],disconnected_color=['black','white'],engine_eval_cp_disconnected=[300.,0.],ply_count=[50,20],chooser_win_premium_v2=[5.,6.],chooser_draw_payoff_v2=[-1.,2.],chooser_win_payoff_v2=[4.,8.],white_win_premium_v2=[5.,8.],black_win_premium_v2=[7.,6.],white_draw_ratingdiff_v2=[-1.,2.],black_draw_ratingdiff_v2=[3.,2.],white_win_ratingdiff_v2=[4.,10.],black_win_ratingdiff_v2=[10.,8.],chooser_pre_rd_v2=[40.,50.],disconnected_pre_rd_v2=[45.,55.],chooser_clock_last_obs_s=[30.,40.],disconnected_clock_last_obs_s=[50.,60.])
   pq.write_table(pa.table(data),panel);auth=dict(paths=dict(spaced=str(src)),panels=[dict(path=str(panel))]);run=root/'run';run.mkdir()
   out=act_features(SimpleNamespace(),run,'synthetic',auth)
   np.testing.assert_array_equal(col(out,'row_id'),[0,3]);np.testing.assert_array_equal(col(out,'recipient_benefit'),[8,7])
   data['chooser_user_id'][0]=99;pq.write_table(pa.table(data),panel);bad=root/'bad';bad.mkdir()
   with self.assertRaisesRegex(RuntimeError,'identity/arm'):act_features(SimpleNamespace(),bad,'synthetic_bad',auth)
if __name__=='__main__':unittest.main()
