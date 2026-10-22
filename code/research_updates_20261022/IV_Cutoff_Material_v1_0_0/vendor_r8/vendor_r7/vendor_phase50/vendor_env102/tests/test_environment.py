import sys,tempfile,unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'code'))
from env_common import *
import env_rates as rates
import env_models as models
import env_prepare as prepare
import env_report as reporting
import run_environment as runner
sys.path.insert(0,str(ENTRY/'tests'))
from test_entry import data


def model_data(n=6000):
    d=data(n);rng=np.random.default_rng(722)
    d=selected(d,oldmodels.support_mask(d));n=len(d['row_id'])
    d['opponent_disconnect_main']=d['active_timeout']&~d['recipient_disconnect_main']&(rng.random(n)<.6)
    d['timeout_role_unclassified']=d['active_timeout']&~(d['recipient_disconnect_main']|d['opponent_disconnect_main'])
    status=np.asarray(['mate','resign','outoftime'])[np.arange(n)%3].astype(object);status[d['active_timeout']]='timeout';d['status']=status
    d['matched_main']=d['recipient_disconnect_main']|d['opponent_disconnect_main']
    d['games']=rng.integers(2,150,n);d['own']=rng.binomial(d['games'],.03);d['chooser']=rng.binomial(d['games']-d['own'],.08)
    d['opponent_observed_disconnect_rate']=d['own']/d['games'];d['opponent_observed_chooser_rate']=d['chooser']/d['games'];d['log_opponent_games90']=np.log1p(d['games'])
    d['environment_supported']=np.ones(n,bool)
    d['received']=rng.random(n)<np.clip(.2+1.2*d['comp_adjusted_7d'],.02,.8)
    return d


class ModelTests(unittest.TestCase):
    def test_independent_fixed_XC_bridge_and_role_identity(self):
        d=model_data();got=models.compute(d,'entry','new',edges=[-.1,-.02,0,.02,.135,.2])
        old=oldmodels.estimate(d,'new','competitive_supported')
        for r in got['estimates']:
            if r['outcome'] in ENTRY_COLUMNS:
                target=next(v for v in old['estimates'] if v['instrument']==r['instrument'] and v['control_level']=='XC' and v['outcome']==r['outcome'])
                for k in ('coefficient','standard_error'):
                    if k in target:self.assertAlmostEqual(r[k],target[k],10)
        for name in ('recipient_disconnect_main','opponent_disconnect_main','analysis_entry_90'):
            total=sum(r['adjusted_slope_contribution_pp_per_fixed_SD'] for r in got['bins'] if r['outcome']==name)
            fit=next(r for r in got['estimates'] if r['outcome']==name and r['instrument']=='competitive')
            self.assertAlmostEqual(total,fit['coefficient_pp'],10)
        d['opponent_disconnect_main'][np.flatnonzero(d['recipient_disconnect_main'])[0]]=True
        with self.assertRaisesRegex(RuntimeError,'Both focal'):models.compute(d,'entry','bad')

    def test_zero_score_variation_is_reported_without_fabricated_interval(self):
        d=model_data();d['adjusted_7d'][:]=0;d['comp_adjusted_7d'][:]=0
        for name in ENTRY_COLUMNS+['opponent_disconnect_main','timeout_role_unclassified']:d[name][:]=False
        d['status'][:]='mate'
        r=models.compute(d,'entry','zero',edges=[-.1,-.02,0,.02,.135,.2])
        self.assertTrue(all(not x['supported'] for x in r['estimates']))
        self.assertEqual(r['bins'][0]['reason'],'NO_RESIDUAL_SCORE_VARIATION_FOR_BIN_DECOMPOSITION')

    def test_common_rows_control_ladder_and_independent_FWL_IV(self):
        d=model_data();r=models.compute(d,'iv','iv',True)
        self.assertEqual(len({v['row_set_sha256'] for v in r['estimates']}),1)
        self.assertEqual({v['control_level'] for v in r['estimates']},{'XC','XC_volume','XC_volume_own','XC_volume_chooser','XC_both_rates'})
        xs,names,_,_,groups,_=stats.controls(d,True)
        extra=[d['comp_expected_7d'],np.log1p(d['comp_n_7d']),np.log1p(d['comp_counterparts_7d'])]+[d[k] for k in ENV_NAMES]
        xs += [(v-v.mean())/max(float(v.std()),1e-12) for v in extra]
        residual,_=num.partial_out(np.column_stack(xs+[d['comp_adjusted_7d'],d['received'],d['y']]),groups,len(xs))
        z,D,Y=residual.T;want=float(z@Y)/float(z@D)
        fit=next(v for v in r['estimates'] if v['estimator']=='2SLS' and v['instrument']=='competitive' and v['control_level']=='XC_both_rates')
        self.assertAlmostEqual(want,fit['iv_coefficient'],9)
        self.assertIn('AR95_intervals_pp',fit)
        self.assertEqual({v['trait'] for v in r['balance']},set(RECENT))
        self.assertFalse(set(ENV_NAMES)&{v['trait'] for v in r['balance']})

    def test_unavailable_status_not_zero_and_environment_exclusions_explicit(self):
        d=model_data();d['status'][::2]=None;d['previous_frame'][::2]=True
        got=models.compute(d,'entry','mixed')
        self.assertFalse(any(r['outcome']=='ending_outoftime' for r in got['estimates']))
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);d['environment_supported'][::10]=False;io.table(p/'d.parquet',pa.table(d))
            job=dict(input=str(p/'d.parquet'),kind='entry',cohort='new',environment=True,conf='test',output=str(p/'fit'))
            models.model_job(job);out=io.load(p/'fit/result.json')
            self.assertEqual(out['accounting'][0]['common_model_rows'],int(d['environment_supported'].sum()))
            self.assertEqual(len({r['n'] for r in out['estimates']}),1)


class RateTests(unittest.TestCase):
    def test_exact_window_role_pair_author_end_boundary_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);cut=int(STARTS[6])-7*DAY;lo=cut-90*DAY;authors_ids=[999991,999992]
            q=pa.table(dict(recipient_id=[20,21,30],opponent_id=[10,10,30],month_code=[6,6,6]))
            io.table(p/'q.parquet',q);req,ri=rates.requests([p/'q.parquet'],p/'requests','test',.5)
            # Pair 10/20 will be removed only for the first query. Strict cutoff and end-time checks.
            games=[('a',lo,10,20),('b',lo+1,10,21),('c',cut-1,10,22),('d',cut,10,23),
                   ('e',lo-1,10,24),('f',lo+2,10,999991),('g',lo+3,10,25)]
            chron=pa.table(dict(game_id=[v[0] for v in games],utc_ms=[v[1] for v in games],white_id=[v[2] for v in games],black_id=[v[3] for v in games]))
            io.table(p/'chron.parquet',chron)
            main=pa.table(dict(game_id=['a','b','c','f','g'],utc_ms=[lo,lo+1,cut-1,lo+2,lo+3],api_last_move_at_ms=[lo+10,lo+11,cut,lo+12,lo+13],
                disconnected_user_id=[10,21,10,999991,25],chooser_user_id=[20,10,22,10,10]))
            io.table(p/'main.parquet',main)
            pj=dict(path=str(p/'main.parquet'),sha256=io.sha(p/'main.parquet'),bytes=(p/'main.parquet').stat().st_size,
                authors=authors_ids,memory=.5,conf='test',output=str(p/'panel'))
            pr=rates.panel_job(pj)
            info=[dict(path=str(p/'panel/events.parquet'),minimum=pr['minimum'],maximum=pr['maximum'])]
            record=dict(path=str(p/'chron.parquet'),signature=io.sig(p/'chron.parquet'),rows=len(games),file_index=0)
            jobs,plan=rates.chronology_jobs([record],ri['windows'],info,req,p/'parts','test',.5)
            for j in jobs:j['authors']=authors_ids;rates.chronology_job(j)
            rr,_=rates.combine(req,[j['output'] for j in jobs],[r['path'] for r in info],p/'rates','test',1,1)
            out=arrays(io.read(rr/'rates.parquet'))
            self.assertEqual(out['games'].tolist(),[3,3,0]);self.assertEqual(out['own'].tolist(),[0,1,0]);self.assertEqual(out['chooser'].tolist(),[2,1,0])
            self.assertEqual(out['environment_supported'].tolist(),[True,True,False])
            self.assertTrue(np.isnan(out[RATE_NAMES[0]][2]))
            sha=io.sha(rr/'rates.parquet');rates.chronology_job(jobs[0]);rates.combine(req,[j['output'] for j in jobs],[r['path'] for r in info],p/'rates','test',1,1)
            self.assertEqual(sha,io.sha(rr/'rates.parquet'))
            # A changed canonical file cannot quietly reuse counts.
            with (p/'chron.parquet').open('ab') as f:f.write(b'change')
            with self.assertRaisesRegex(RuntimeError,'changed'):rates.chronology_jobs([record],ri['windows'],info,req,p/'new','test',.5)

    def test_numerator_missing_from_game_universe_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);cut=int(STARTS[6])-7*DAY
            io.table(p/'q.parquet',pa.table(dict(recipient_id=[20],opponent_id=[10],month_code=[6])))
            req,_=rates.requests([p/'q.parquet'],p/'requests','x',.5)
            part=p/'part';part.mkdir()
            io.table(part/'person.parquet',pa.table(dict(person=[10],month_code=[6],games=[1],own=[0],chooser=[0])))
            io.table(part/'pair.parquet',pa.table(dict(person=[10],partner=[20],month_code=[6],games=[0],own=[0],chooser=[0])))
            io.table(p/'events.parquet',pa.table(dict(game_id=['missing'],start_ms=[cut-10],end_ms=[cut-1],i=[10],j=[21])))
            with self.assertRaisesRegex(RuntimeError,'not completely matched'):rates.combine(req,[part],[str(p/'events.parquet')],p/'rates','x',1,1)

    def test_time_pruning_and_incomplete_windows(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.table(p/'q.parquet',pa.table(dict(recipient_id=[20],opponent_id=[10],month_code=[0])))
            req,r=rates.requests([p/'q.parquet'],p/'requests','x',.5)
            self.assertFalse(r['windows'][0]['complete'])
            with self.assertRaisesRegex(RuntimeError,'No complete'):rates.chronology_jobs([],r['windows'],[],req,p/'out','x',.5)


class OperationalTests(unittest.TestCase):
    def test_missing_input_and_modified_entry_config_fail_early(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);io.js(p/'config.json',dict(changed=True))
            with self.assertRaisesRegex(RuntimeError,'reviewed completed entry'):bind(p,p)
            io.table(p/'bad.parquet',pa.table({'x':[1]}))
            with self.assertRaisesRegex(RuntimeError,'lacks required'):rates.requests([p/'bad.parquet'],p/'q','x',.5)

    def test_union_schema_report_keeps_later_fields(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);oldreport.write_rows(p,'test',[dict(a=1),dict(a=2,iv_coefficient_pp=.9)])
            t=io.read(p/'test.parquet');self.assertEqual(t['iv_coefficient_pp'][1].as_py(),.9)

if __name__=='__main__':unittest.main()
