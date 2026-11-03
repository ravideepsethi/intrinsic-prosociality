import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import receipt_companions as r
import receipt_numerics
import repair_censored as repair
from result_common import csv_save, save, sha, DAY


def json_bytes(value):
    return (json.dumps(value,sort_keys=True,indent=2)+'\n').encode()


def make_archive(path, files):
    manifest=[dict(path=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
              for name,data in files.items()]
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items():z.writestr(name,data)
        z.writestr('RETURN_MANIFEST.json',json_bytes(manifest))


class CensorRepairTests(unittest.TestCase):
    def test_full_targeted_repair_nullable_parquet_preserves_other_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);project=root/'project';rng=np.random.default_rng(20261102);n=900
            parents=r.load(r.ROOT/'authority/PARENTS.json');rid=parents['receipt_run_id']
            parent=project/'derived/replication/mating_material_receipt_v100_PRIVATE'/rid[:16]
            source=parent/'PRIVATE/recipient/recipient_private.parquet';source.parent.mkdir(parents=True)
            D=rng.integers(2,size=n).astype(bool)
            y=(rng.random(n)<(.10+.1*D)).astype(float)
            anchor=1704067200000+rng.integers(15,size=n)*3600000+1000
            delta=rng.integers(1,20,size=n,dtype=np.int64)*3600000
            nxt=[]
            for j in range(n):
                phase=j%6
                nxt.append(None if phase in (0,5) else
                           int(anchor[j]+delta[j]+(-10 if phase==1 else 10 if phase==2 else 0))
                           if phase in (1,2,3) else int(anchor[j]+91*DAY))
            values=dict(cohort_row_id=np.arange(n),recipient_user_id=np.arange(n)+1000,
                exposure_chooser_user_id=rng.integers(100,size=n),received_mercy=D,
                exposure_claimed_win=~D,arm_eligible=np.ones(n,bool),exposure_no_mating_draw=np.zeros(n,bool),
                exposure_chooser_loss=np.zeros(n,bool),first_ever_pair=np.ones(n,bool),
                a1_90d_followup_eligible=np.ones(n,bool),exposure_cell_code=np.zeros(n,np.int64),
                exposure_month_code=np.zeros(n,np.int64),reached_fair_chooser_within_90d=np.ones(n,bool),
                first_subsequent_kind_draw=y,first_subsequent_delta_ms=delta,
                recipient_next_disconnection_utc_ms=pa.array(nxt,type=pa.int64()),exposure_anchor_utc_ms=anchor)
            values.update({name:rng.normal(size=n) for name in r.core.EXPOSURE_CONTROLS})
            pq.write_table(pa.table(values),source)
            d,support=r.load_receipt(source)
            def fit_subset(ix,name):
                X,names=r.core.model_controls(d,ix,state_conditioned=False)
                result=receipt_numerics.fit(y[ix],D[ix],X,names,support['weights'][ix],
                    [d['exposure_cell_code'][ix],d['exposure_month_code'][ix]],
                    d['exposure_chooser_user_id'][ix],ix,r.common,r.core)
                result.update(specification=name,fixed_effects=['exposure cell','exposure month'])
                return result
            reference=fit_subset(np.arange(n),'reference_conditional_validation')
            old=fit_subset(np.flatnonzero(np.isin(np.arange(n)%6,[2,3,4])),repair.MODEL)
            model=parent/'report/models/conditional.json';save(model,reference)
            sample=dict(all_fresh_exposures=n,common_support=n,common_support_complete90=n,complete90_reached=n)
            result=parent/'report/RESULTS.json';save(result,{'summary':{'sample':sample}})
            sources=[dict(path=str(p),bytes=p.stat().st_size,sha256=sha(p)) for p in (source,model)]
            receipts=[dict(v,path=str(Path(v['path']).relative_to(parent))) for v in sources]
            save(parent/'_SUCCESS.json',dict(status='RECEIPT_COMPLETE_MORE_FAMILIES_PENDING',run_id=rid,files=receipts))
            parents=dict(parents,receipt_result_sha256=sha(result));real_load=r.load
            def patched_load(path):
                if Path(path)==r.ROOT/'authority/PARENTS.json':return parents
                if Path(path)==r.ROOT/'authority/receipt_RESULTS.json':return {'summary':{'sample':sample}}
                return real_load(path)
            names=['conditional_exposure_and_later_choice_hours',repair.MODEL,
                   'engagement_log1p_games_30d','engagement_any_game_10m',
                   'engagement_any_game_30m','engagement_any_game_60m']
            models=[old if name==repair.MODEL else dict(reference,specification=name) for name in names]
            table=root/'table.csv'
            csv_save(table,[{k:v for k,v in model.items() if not isinstance(v,(list,dict))} for model in models])
            previous={
                'STATUS.json':json_bytes(dict(status='ALL_REQUESTED_RESULT_JOBS_COMPLETE')),
                'JOB_STATUS.json':json_bytes([]),
                'SELF_TEST.log':b'Previous synthetic checks\n',
                'counts/COUNT_RESULTS.csv':b'name,value\nfixture,123\n',
                'rating_validation/aggregate/report/RATING_VALIDATION.csv':b'arm,value\ndraw,0.993\n',
                'receipt_companions/STATUS.json':json_bytes(dict(status='COMPLETE',models_reported=6)),
                'receipt_companions/CONDITIONAL_COUNTS.json':json_bytes(dict(complete90=n,conditional=n,censored=450)),
                'receipt_companions/INPUT_LINEAGE.json':json_bytes(dict(parent_run_id=rid,sources=sources)),
                'receipt_companions/RECEIPT_COMPANIONS.csv':table.read_bytes(),
                'receipt_companions/run.log':b'Original run\n',
            }
            for m in models:previous['receipt_companions/'+m['specification']+'.json']=json_bytes(m)
            archive=root/'previous.zip';make_archive(archive,previous)
            decoded=repair.read_previous(archive,sha(archive));self.assertEqual(previous,decoded)
            original_sha=sha(source)
            with patch.object(r,'load',patched_load),patch.object(r,'SUPPORT_N',n),\
                 patch.object(r,'COMPLETE90_N',n),patch.object(r,'CONDITIONAL_N',n),\
                 patch.object(receipt_numerics,'fit',wraps=receipt_numerics.fit) as mocked_fit:
                corrected,audit=repair.recompute(project,previous)
                self.assertEqual(mocked_fit.call_count,2)
                again,audit_again=repair.recompute(project,previous)
                self.assertEqual(mocked_fit.call_count,2)
                self.assertEqual(corrected,again)
            self.assertEqual(sha(source),original_sha)
            self.assertEqual(audit['legacy_rows'],450)
            self.assertEqual(audit['corrected_rows'],750)
            self.assertEqual(audit['restored_rows'],300)
            self.assertEqual(audit['negative_one_sentinels'],300)
            self.assertEqual(audit['choice_ties_next'],150)
            self.assertEqual(audit['removed_rows'],0)
            self.assertEqual(corrected['rows'],750)
            expected=fit_subset(np.flatnonzero(np.arange(n)%6!=1),repair.MODEL)
            self.assertAlmostEqual(corrected['estimate'],expected['estimate'],places=12)
            self.assertAlmostEqual(corrected['se'],expected['se'],places=12)
            out=root/'report'
            jobs=repair.merge_report(previous,out,corrected,audit)
            self.assertEqual(len(jobs),3)
            with (out/'receipt_companions/RECEIPT_COMPANIONS.csv').open() as handle:
                updated=list(csv.DictReader(handle))
            original=list(csv.DictReader(io.StringIO(table.read_text())))
            for before,after in zip(original,updated):
                if before['specification']==repair.MODEL:self.assertEqual(int(after['rows']),750)
                else:self.assertEqual(before,after)
            for name,data in previous.items():
                if name.startswith(('counts/','rating_validation/')) or Path(name).stem in set(names)-{repair.MODEL}:
                    self.assertEqual((out/name).read_bytes(),data)
            self.assertFalse(real_load(out/'repair/SUPERSEDED_INVALID_CENSOR_ESTIMATE.json')['valid_for_reporting'])
            self.assertEqual(real_load(out/'receipt_companions/CONDITIONAL_COUNTS.json')['censored'],750)
            with self.assertRaisesRegex(RuntimeError,'checksum'):
                repair.read_previous(archive,'0'*64)
            with zipfile.ZipFile(archive,'a') as z:z.writestr('unlisted.txt','changed')
            with self.assertRaisesRegex(RuntimeError,'Unlisted'):
                repair.read_previous(archive,sha(archive))


if __name__=='__main__':unittest.main()
