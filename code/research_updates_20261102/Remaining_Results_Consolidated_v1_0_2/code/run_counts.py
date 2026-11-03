"""Authenticate the completed IV inputs, then run the repaired count-only reader."""
import argparse,sys,traceback
from pathlib import Path
from result_common import *
import read_remaining_counts as counts

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    a.report.mkdir(parents=True,exist_ok=True);block_network()
    try:
        parent=a.project/counts.IV_REL
        config=load(parent/'config.json')
        require(key(config)==load(ROOT/'authority/PARENTS.json')['iv_config_sha256'],'Completed IV configuration differs')
        require(load(parent/'report/STATUS.json')['status']=='BATCH_COMPLETE','IV parent is incomplete')
        files=[parent/'PRIVATE/model_inputs/legacy_spaced/source.parquet',parent/'PRIVATE/model_inputs/legacy_spaced/scores.parquet']
        fm=parent/'PRIVATE/FRAMES90.json';scores=Path(load(fm)['scores'])
        if not scores.is_absolute():scores=parent/scores
        files.append(scores)
        with heartbeat('Authenticating summary-count inputs'):bound=[bind_iv_file(f,a.project) for f in files]
        save(a.report/'INPUT_LINEAGE.json',dict(iv_files=bound,frames_manifest_sha256=sha(fm)))
        sys.argv=['read_remaining_counts','--project-root',str(a.project),'--output-dir',str(a.report)]
        rc=counts.main();guard(bound)
        save(a.report/'STATUS.json',dict(status='COMPLETE' if rc==0 else 'PARTIAL',return_code=rc))
        return rc
    except Exception as e:
        save(a.report/'STATUS.json',dict(status='FAILED',error=type(e).__name__+': '+str(e)))
        (a.report/'ERROR.txt').write_text(traceback.format_exc());traceback.print_exc();return 1
if __name__=='__main__':raise SystemExit(main())
