"""Load the byte-frozen v1.0.0 scientific definition and checkpoint readers."""
from pathlib import Path
import sys, os, subprocess
FAST_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(FAST_ROOT/'original'))
from uniform_common import *
FAST_ROOT = Path(__file__).resolve().parent
EXECUTION_VERSION = '1.0.5'

def memory_budget():
    return float(os.environ.get('UNIFORM90_MEMORY_GIB', '11'))

def worker_limit():
    return int(os.environ.get('UNIFORM90_WORKERS', '4'))

def resources(requested_workers=None,requested_memory=None,total_gib=None,cores=None):
    if total_gib is None:
        if sys.platform=='darwin':
            total_gib=int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize'],text=True).strip())/2**30
        else:total_gib=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')/2**30
    cores=cores or os.cpu_count() or 1
    memory=float(requested_memory) if requested_memory is not None else min(.75*total_gib,total_gib-3.5)
    workers=min(int(requested_workers) if requested_workers is not None else cores,cores)
    require(workers>=1 and 6<=memory<=total_gib-2,'Resource settings must leave at least 2 GiB for the OS and provide at least 6 GiB for this pipeline')
    return dict(physical_memory_gib=total_gib,logical_cpu_cores=cores,memory_budget_gib=memory,workers=workers)

def ram_fits(n, p, kind):
    # Deliberately conservative peak reservations, including decoding, factor
    # construction, grouping codes, work arrays and Python/Arrow overhead.
    per_row = max(900, 8*p+400) if kind=='design' else 520+16*p
    estimate = 1.25 + n*per_row/2**30
    return estimate <= memory_budget()-1.5, estimate

def projection_threads(n,disk=False):
    threads=max(1,min(4,worker_limit(),int(os.environ.get('UNIFORM90_FE_THREADS','4'))))
    if disk:
        while threads>1 and disk_projection_reservation(n,threads)>memory_budget()-1.5:threads-=1
    return threads

def disk_projection_reservation(n,threads):
    return 2.5+n*(128+24*threads)/2**30
