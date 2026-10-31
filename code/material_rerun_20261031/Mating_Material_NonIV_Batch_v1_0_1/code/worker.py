#!/usr/bin/env python3
"""A fresh interpreter per family prevents historical module-name collisions."""
from engine import *
import argparse,traceback
import sources

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--batch-root',type=Path,required=True)
    p.add_argument('--project',type=Path,required=True);p.add_argument('--workers',type=int,required=True);p.add_argument('--memory-gb',type=float,required=True)
    a=p.parse_args(argv);a.variant='excluded'
    auth=read(a.batch_root/'PRIVATE/AUTH.json');out=a.batch_root/'PRIVATE/stages'/a.stage
    (out/'report').mkdir(parents=True,exist_ok=True);(out/'PRIVATE').mkdir(exist_ok=True)
    started=time.monotonic()
    try:
        sources.guard(auth)
        if a.stage in ('reputation','stakes','countdown'):
            import cached_families as f
        elif a.stage in ('krd','nonparametric'):
            import gap as f
        else:import families as f
        with heartbeat('Running '+a.stage):result=getattr(f,a.stage)(a,auth,out)
        sources.guard(auth)
        result=dict(result,elapsed_seconds=time.monotonic()-started,input_fingerprint=auth['fingerprint'])
        write(out/'report/STAGE_RESULT.json',result)
        files=[]
        # All permanent outputs are hashed. Spill, interrupted work and native
        # return ZIPs are excluded; private analytical Parquets are included.
        for path in sorted(out.rglob('*')):
            rel=path.relative_to(out)
            if not path.is_file() or path.name in ('DONE.json','ERROR_PRIVATE.txt'):continue
            if any(x.startswith(('spill','tmp','interrupted_')) or x=='native_return' for x in rel.parts):continue
            if '.partial' in path.name:continue
            if path.suffix in ('.json','.parquet','.csv','.npz','.npy','.pdf','.png','.txt','.tex'):
                files.append(record(path))
        require(files,'Family produced no outputs')
        write(out/'DONE.json',dict(status='COMPLETE',result=result,input_fingerprint=auth['fingerprint'],files=files))
        return 0
    except BaseException as exc:
        (out/'PRIVATE/ERROR_PRIVATE.txt').write_text(traceback.format_exc())
        write(out/'report/STAGE_ERROR.json',dict(stage=a.stage,error_type=type(exc).__name__,message=str(exc),
              elapsed_seconds=time.monotonic()-started,status='FAILED_REVIEW_REQUIRED'))
        log(a.stage+' failed: '+str(exc));return 2

if __name__=='__main__':sys.exit(main())
