from util import *
from checkpoints import stage
from panel import projections,partition,descriptions
from equal_weights import analyze
from estimation import fit_models
from reporting import write_reports
import shutil

def execute(auth,run,key,workers,memory,shards,counts,reference=None):
    timing={};t=time.monotonic()
    paths=projections(auth,run,key,workers,memory);timing['project']=time.monotonic()-t
    t=time.monotonic()
    def describe(out):
        summary=descriptions(paths,out,workers,memory,counts)
        summary['equal_weights']=analyze(out/'chooser_counts_PRIVATE.parquet',out/'report')
        return summary
    desc,summary=stage(run/'PRIVATE','descriptives',digest([key,'descriptives']),describe)
    for p in sorted((desc/'report').iterdir()):shutil.copy2(p,run/'report'/p.name)
    timing['descriptives_and_equal_weights']=time.monotonic()-t;t=time.monotonic()
    with heartbeat('Partitioning complete chooser histories'):
        by=partition(paths,run,key,shards,workers,memory,counts['opportunities'])
    timing['partition']=time.monotonic()-t;t=time.monotonic()
    fits=fit_models(by,run,key,workers,memory,shards,counts)
    timing['regressions']=time.monotonic()-t;t=time.monotonic()
    summary['regression_results']=write_reports(fits,run/'report',reference)
    timing['reporting']=time.monotonic()-t
    return summary,timing
