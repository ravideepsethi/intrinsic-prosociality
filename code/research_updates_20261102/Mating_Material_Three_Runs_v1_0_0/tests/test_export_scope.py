"""Scope, complete table integration, provenance and restart manifests."""
import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'code'))
from common_retained import *
from balance_retained import RECENT,PRIOR
from retained_export import export,cell_lineage
from retained_pipeline import STAGES,DEPENDENCIES,arguments

class ExportScopeTests(unittest.TestCase):
    def test_only_three_analysis_families_are_schedulable(self):
        self.assertEqual(STAGES,['preflight','balance_ladder','spaced_balance_frames','act_stakes','spaced_compliers','export'])
        self.assertEqual(DEPENDENCIES['export'],STAGES[1:-1])
        self.assertEqual(len(read(ROOT/'METHOD.json')['families']),3)
        for name in ('static_retained.py','matched_retained.py','matched_fit.py'):
            self.assertFalse((ROOT/'code'/name).exists())
        self.assertNotIn('strict_without_environment',STAGES)

    def test_excluded_values_are_absent_and_pending_stays_pending(self):
        for r in csv_rows(ROOT/'evidence/RECONCILIATION.csv'):
            if r['status']=='DROPPED_BY_AUTHOR':
                self.assertEqual(r['old_value'],'');self.assertEqual(r['new_value'],'')
        method=read(ROOT/'METHOD.json');self.assertFalse(method['whole_paper_complete'])
        self.assertEqual(method['spaced_authority']['row_set_sha256'],'ce3751fda15f20b2ebe1840716e908a8c4cb182fbe20825498103c19cd94189e')

    def test_export_has_every_requested_cell_and_verifiable_sources(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td);run=p/'run';close=p/'close';(run/'report').mkdir(parents=True);(close/'report').mkdir(parents=True)
            counts=dict(n=3000,recipients=400,opponents=450,account_clusters=700,date_clusters=25)
            save(run/'report/DESIGN_COUNTS.json',dict(spaced=counts,repeated=counts))
            old=[];joint=[]
            for spec in ('spaced_recent_balance','spaced_noenv_recent_balance','repeated_FE_recent_balance'):
                old += [dict(sample=spec,term='balance_'+k,coefficient=.001,standard_error=.001,p_value=.3,**counts) for k in RECENT]
                joint.append(dict(sample=spec,chi2=16.,df=7,p_value=.02,**counts))
            write_csv(close/'report/model_estimates.csv',old);write_csv(close/'report/balance_joint.csv',joint)
            for label,keys in [('entry_spaced_recent_balance',RECENT),('ordinary_spaced_recent_balance',RECENT),('spaced_nohistory_15traits',RECENT+PRIOR),('spaced_nohistory_15traits_noenv',RECENT+PRIOR)]:
                path=run/'PRIVATE/balance'/label/'result.json'
                jj=[dict(sample=label,test_set='recent_7',wald_chi2=16.,rank=7,p_value_asymptotic=.02,**counts)]
                if len(keys)==15:jj.append(dict(sample=label,test_set='all_15',wald_chi2=27.,rank=15,p_value_asymptotic=.03,**counts))
                save(path,dict(estimates=[dict(sample=label,term='balance_'+k,coefficient=.002,standard_error=.001,p_value=.04,**counts) for k in keys],joint_tests=jj))
                save(path.parent/'_DONE.json',dict(config_sha256='synthetic',files=[record(path,path.parent)]))
            estimates=[dict(outcome='y',term=k,coefficient=.2,standard_error=.05,ci95_low=.1,ci95_high=.3,p_value=.01,**counts) for k in ['band_0','band_1','band_2','band_3','giver_cost_per_5','recipient_benefit_per_5','well_ahead_minus_near_equal']]
            save(run/'report/ACT_SYSTEM.json',dict(estimates=estimates,first_stages=[dict(endogenous_column=j,conditional_F=80+j,**counts) for j in range(6)]))
            write_csv(run/'report/table_D6_complier_characteristics.csv',[dict(trait=str(j),coefficient=1.,standard_error=.1,all_exposures=1.1,draw_recipients=1.2,negative_weight_absolute_mass_over_signed_total=.02,**counts) for j in range(11)])
            write_csv(run/'report/table_D2_implied_bias.csv',[dict(outcome=k,coefficient=.001,standard_error=.0002,**counts) for k in ('y','received')])
            save(run/'report/DIAGNOSTIC_FRAME_COUNTS.json',[dict(frame='entry',n=3000,reference_count_in_note=17745415,reference_count_matches=False)])
            export(SimpleNamespace(closeout=close),run,'synthetic');dst=run/'report/RA_TABLES'
            f6=csv_rows(dst/'tables/table_F6.csv');self.assertEqual(len(f6),18)
            self.assertEqual([r['panel'] for r in f6].count('A'),7);self.assertEqual([r['panel'] for r in f6].count('B'),8)
            self.assertEqual(sum('column_6_coefficient' in r and r['column_6_coefficient']!='' for r in f6),7)
            for row in f6:
                for col in range(1,7):
                    prefix=f'column_{col}_'
                    if not row.get(prefix+'source_file'):continue
                    for key in ('coefficient','chi2','df','p_value','n','account_clusters','date_clusters'):
                        value=row.get(prefix+key)
                        if not value:continue
                        lineage=cell_lineage(row,prefix+key);source=csv_rows(dst/lineage['source_file'])[int(lineage['source_row'])-2]
                        self.assertEqual(str(source[key]),str(value))
            act=csv_rows(dst/'tables/table_D5_panelB.csv');self.assertEqual(len(act),8);self.assertEqual(float(act[-1]['conditional_F']),80.)
            recon=csv_rows(dst/'RECONCILIATION.csv');statuses={r['status'] for r in recon}
            self.assertNotIn('AUTHORIZED_PENDING_RUN',statuses);self.assertIn('PENDING_OUTSIDE_THREE_RUNS',statuses);self.assertIn('ARCHIVE_GAP',statuses)
            self.assertIn('UPDATED_DIAGNOSTIC_COUNT_REVIEW',statuses)
            self.assertFalse(read(dst/'METHOD.json')['whole_paper_complete'])
            self.assertEqual(read(dst/'methods/balance/METHOD.json')['status'],'COMPUTED')
            self.assertTrue((dst/'tables/table_F5.csv').is_file());self.assertTrue((dst/'tables/table_D8_environment.csv').is_file())
            for line in (dst/'checksums.txt').read_text().splitlines():
                digest,name=line.split('  ',1);self.assertEqual(sha(dst/name),digest)
            # A changed numerical result cannot be reused through its old receipt.
            corrupted=run/'PRIVATE/balance/entry_spaced_recent_balance/result.json';corrupted.write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                export(SimpleNamespace(closeout=close),run,'synthetic')

if __name__=='__main__':unittest.main()
