"""Production adapters and launcher orchestration on a miniature source tree."""
import sys,tempfile,unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from test_core import fixture
from common import *
import run,prepare

def source_panel(d):
    white=d.color.eq('white')
    return pd.DataFrame(dict(game_id=d.game_id,chooser_user_id=d.chooser,disconnected_user_id=d.opponent,
       api_created_at_ms=d.t,api_speed=d.speed,chooser_color=d.color,disconnected_color=np.where(white,'black','white'),
       outcome_kind_draw=d.y,engine_eval_cp_disconnected=d.cp,ply_count=d.ply,chooser_elo=d.rating,
       disconnected_elo=d.opp_rating,chooser_pre_rd_v2=d.rd,disconnected_pre_rd_v2=d.opp_rd,
       chooser_draw_payoff_v2=d.rg,chooser_win_payoff_v2=d.rc,chooser_win_premium_v2=d.ki,
       white_win_premium_v2=np.where(white,d.ki,d.kj),black_win_premium_v2=np.where(white,d.kj,d.ki),
       chooser_clock_last_obs_s=d.clock,disconnected_clock_last_obs_s=d.opp_clock))

class Runner(unittest.TestCase):
    def test_support_command_and_resume_preserve_cached_months(self):
        with tempfile.TemporaryDirectory() as tmp:
            project=Path(tmp);d=fixture(10);d=d[d.month=='2023-11'].copy();d['speed']='blitz'
            p=project/'panel.parquet';frame(source_panel(d),p)
            record=dict(month='2023-11',rows=len(d),sha256=sha(p),size_bytes=p.stat().st_size)
            def ts(x):return int(pd.Timestamp(x,tz='UTC').timestamp()*1000)
            times={'2022-01':[ts('2022-01-01')+j*1000 for j in range(100)],
                   '2023-10':[ts('2023-10-24'),ts('2023-10-31')],
                   '2023-11':[ts('2023-11-07'),ts('2023-11-14')]}
            history=[]
            for month,tt in times.items():
                rr=[]
                for _,r in d.iterrows():
                    for j,t in enumerate(tt):rr.append(dict(game_id=f'h{month}_{r.chooser}_{j}',white_id=int(r.chooser),black_id=int(r.opponent),utc_ms=t))
                    if month=='2023-11':rr.append(dict(game_id=r.game_id,white_id=int(r.chooser),black_id=int(r.opponent),utc_ms=int(r.t)))
                hp=project/(month+'.parquet');frame(pd.DataFrame(rr),hp)
                history.append(dict(speed='blitz',month=month,path=str(hp),rows=len(rr),size=hp.stat().st_size))
            argv=['run.py','--project-root',str(project),'--desktop',str(project/'desktop'),'--phase','support','--workers','2']
            with patch.object(sys,'argv',argv),patch.object(run,'verify',return_value='SYNTHETIC_ONLY'),patch.object(run,'sources',return_value=[(p,record)]),patch.object(run,'catalog',return_value=history),patch.object(run,'MONTHS',('2023-11',)),patch.object(run,'SPEEDS',('blitz',)),patch.object(prepare,'SPEEDS',('blitz',)):
                run.main()
                cache=project/'derived/replication/mechanism_separation_v100_PRIVATE'
                hp=cache/'history_features/blitz_2023-11.parquet';before=hp.stat().st_mtime_ns
                run.main();self.assertEqual(before,hp.stat().st_mtime_ns)
            a=pd.read_parquet(cache/'analysis/2023-11.parquet')
            self.assertTrue(a.regular.all());self.assertTrue((a.prior_starts==104).all())
            reports=list((project/'desktop').glob('MECHANISM_RESULT_*.zip'));self.assertEqual(len(reports),2)
            with __import__('zipfile').ZipFile(reports[0]) as z:
                self.assertTrue(any(n.endswith('input_checksums.parquet') for n in z.namelist()))
                self.assertFalse(any('history_features/' in n for n in z.namelist()))

if __name__=='__main__':unittest.main()
