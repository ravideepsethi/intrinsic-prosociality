"""Small artificial opportunities; never a substitute for a production run."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'code'))
from common import *
from predictions import START, STOP


def data():
    rng = np.random.default_rng(821)
    days = pd.date_range('2023-11-01', '2025-10-31', freq='D', tz='UTC')
    # Both colors every day; heterogeneous baselines, slopes and stakes.
    n = len(days) * 6
    chooser = np.arange(n) % 73
    rd = rng.uniform(45, 100, n)
    rd[::3] = 45
    opp_rd = rng.uniform(45, 105, n)
    gap = rng.choice([-300., -100., -5., 0., 5., 100., 300.], n)
    t = np.repeat(days.astype('int64') // 1000000, 6) + (np.arange(n) % 6) * 10000
    d = pd.DataFrame(dict(game_id=['synthetic_' + str(i) for i in range(n)],
        chooser=['chooser_' + str(i) for i in chooser], t=t,
        month=pd.to_datetime(t, unit='ms', utc=True).strftime('%Y-%m'),
        color=np.where(np.arange(n) % 2 == 0, 'white', 'black'), speed='blitz',
        ply=rng.integers(11, 100, n), cp=rng.uniform(-99, 99, n),
        clock=rng.uniform(5, 150, n), opp_clock=rng.uniform(5, 150, n),
        history_days=rng.uniform(366, 1000, n), prior_starts=rng.integers(100, 2000, n),
        inactivity_days=rng.uniform(0, 4, n), opp_prior_starts=rng.integers(50, 2000, n),
        rating=1500., opp_rating=1500. + gap, rd=rd, opp_rd=opp_rd, g=gap,
        y=(rng.random(n) < (.02 + .08 * (chooser % 7 == 0))).astype(int),
        state='equal', regular=True))
    _, k, rg, rc = payoff(d.rating, d.opp_rating, d.rd, d.opp_rd)
    _, ko, _, _ = payoff(d.opp_rating, d.rating, d.opp_rd, d.rd)
    d['ki'], d['kj'], d['rg'], d['rc'] = k / 2, ko / 2, rg, rc
    return d


def cache(base):
    source = Path(base) / 'source'
    work = Path(base) / 'work'
    reference = read(ROOT / 'authority/reference.json')
    write(source / 'RUN_IDENTITY.json', dict(package_sha256=reference['mechanism_package_sha256']))
    d = data()
    inputs = []
    for month in MONTHS:
        p = source / 'analysis' / (month + '.parquet')
        frame(d[d.month.eq(month)], p)
        inputs.append(dict(month=month, sha256=sha(p), size=p.stat().st_size))
    reference['inputs'] = inputs
    reference['expected'] = dict(n=len(d), grants=int(d.y.sum()), accounts=d.chooser.nunique())
    return source, work, reference, d
