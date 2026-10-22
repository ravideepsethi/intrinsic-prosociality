from fw_common import *
from fw_b import fit_model

def run(a,run,parts,key):
    report=run/'D/report';report.mkdir(parents=True,exist_ok=True)
    b=load(run/'B/report/STATUS.json')
    if not b['D_trigger']:
        status=dict(status='NOT_TRIGGERED',reason='BOTH position-response interval excludes zero in primary B model.')
    else:
        spec=dict(name='D_provisional_RD110',reg='normalized',provisional=True,full=True)
        rows,info=fit_model(parts,run/'D/provisional',digest([key,'D_RD110']),spec,a)
        table(report,'tabD2_provisional',[dict(r,group_label=['RD_at_most_110','RD_above_110'][r['group']] if isinstance(r.get('group'),int) else r.get('group')) for r in rows])
        status=dict(status='PARTIAL_CASUAL_HISTORY_UNAVAILABLE',provisional=info,
            reason='Standard Lichess monthly PGN archives contain rated games. Casual share cannot be inferred from absence in those archives.',
            required_casual_input='A complete standard-game chronology containing rated and casual games, both players, and timestamps before each opportunity; >=20 games in the prior 90 days ending the day before.',
            source='https://database.lichess.org/',source_checked_utc='2026-10-12',
            caveat='RD > 110 is a proxy, not an observed game-time display flag. Provisional status also reflects account age and rating uncertainty. Regressor is rG/premium.')
    save(report/'STATUS.json',status);return status
