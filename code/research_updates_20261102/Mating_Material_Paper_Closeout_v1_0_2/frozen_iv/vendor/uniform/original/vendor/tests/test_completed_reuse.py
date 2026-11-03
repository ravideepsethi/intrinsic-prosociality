import unittest,tempfile,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rebuild_common import *
import repair_completed as repair
import rebuild_candidates as candidates
import run_rebuild as runner


def fixture(root):
    parent=root/'old';run=root/'new'
    (parent/'PRIVATE').mkdir(parents=True);(parent/'report').mkdir()
    (run/'PRIVATE').mkdir(parents=True);(run/'report').mkdir()
    a=SimpleNamespace(project=root,r12_root=root/'r12',r9_root=None,local_plan=None,
                      reuse_run=root/'v100',reuse_chronology=parent)
    cfg={name:str(getattr(a,name)) if getattr(a,name) is not None else None
         for name in ('project','r12_root','r9_root','local_plan','reuse_run')}
    cfg.update(version='1.0.2',package_manifest_sha256=repair.CHRONOLOGY_MANIFEST,rule=dict(RULE,version='1.0.2'))
    oldconf=key(cfg);save(parent/'config.json',cfg)
    b={name:{'unchanged':name} for name in ('source','frame_root','frame_conf','comparison_root','comparison_conf',
           'old_paths','old_scores','metadata','quarantine','candidate_run','candidate_configuration')}
    b['primary']={name:name for name in ('primary','primary_scores','raw','all_scores','bound')}
    save(parent/'PRIVATE/BINDING.json',b)
    source=root/'input.txt';source.write_text('authenticated input')
    for name,filename in repair.OUTPUTS.items():
        def build(tmp,filename=filename):
            pq.write_table(pa.table(dict(row_id=[1,2],game_id=['abcdefgh','bcdefghi'])),tmp/filename)
            return dict(rows=2)
        stage(parent/'PRIVATE'/name,oldconf,build,[source])
    manifest=[]
    for name in repair.REPORTS:
        p=parent/'report'/name;save(p,dict(rows=2))
        manifest.append(dict(path=name,bytes=p.stat().st_size,sha256=sha(p)))
    save(parent/'report/REPORT_MANIFEST.json',manifest)
    return a,run,b,oldconf


class CompletedChronology(unittest.TestCase):
    def test_authenticated_reuse_never_calls_merge_and_preserves_parent(self):
        with tempfile.TemporaryDirectory() as td:
            a,run,b,oldconf=fixture(Path(td));before={p:sha(p) for p in a.reuse_chronology.rglob('*') if p.is_file()}
            with patch.object(repair,'CHRONOLOGY_CONF',oldconf):repair.authenticate_chronology(a,run,b)
            with patch('repair_chronology.run_chronology',side_effect=AssertionError('Chronology must not rerun')):
                candidates.chronology(a,run,'newconf',b)
                stamp=(run/'PRIVATE/locally_eligible/queries.parquet').stat().st_mtime_ns
                candidates.chronology(a,run,'newconf',b)
                self.assertEqual(stamp,(run/'PRIVATE/locally_eligible/queries.parquet').stat().st_mtime_ns)
            self.assertEqual(before,{p:sha(p) for p in before})
            self.assertEqual(load(run/'PRIVATE/chronology/_DONE.json')['config_sha256'],'newconf')
            self.assertEqual(load(run/'PRIVATE/chronology/_DONE.json')['imported_from_configuration'],oldconf)

    def test_missing_changed_output_dependency_binding_or_rules_rejected(self):
        for kind in ('missing','output','dependency','binding','rule'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
                root=Path(td);a,run,b,oldconf=fixture(root)
                if kind=='missing':(a.reuse_chronology/'PRIVATE/locally_eligible/_DONE.json').unlink()
                elif kind=='output':(a.reuse_chronology/'PRIVATE/chronology/features.parquet').write_bytes(b'bad')
                elif kind=='dependency':(root/'input.txt').write_text('tampered')
                elif kind=='binding':b['metadata']={'changed':True}
                else:
                    cfg=load(a.reuse_chronology/'config.json');cfg['rule']['entry']='changed'
                    save(a.reuse_chronology/'config.json',cfg)
                with patch.object(repair,'CHRONOLOGY_CONF',oldconf),self.assertRaises(RuntimeError):
                    repair.authenticate_chronology(a,run,b)

    def test_metadata_audit_has_own_stage_and_no_chronology_call(self):
        with patch.object(runner,'bind',return_value={}),patch('rebuild_metadata.plan') as plan,\
             patch.object(candidates,'chronology',side_effect=AssertionError('Audit must not call chronology')):
            a=SimpleNamespace(_stage='metadata_audit');runner.stage_execute(a,Path('run'),'conf');plan.assert_called_once()


if __name__=='__main__':unittest.main()
