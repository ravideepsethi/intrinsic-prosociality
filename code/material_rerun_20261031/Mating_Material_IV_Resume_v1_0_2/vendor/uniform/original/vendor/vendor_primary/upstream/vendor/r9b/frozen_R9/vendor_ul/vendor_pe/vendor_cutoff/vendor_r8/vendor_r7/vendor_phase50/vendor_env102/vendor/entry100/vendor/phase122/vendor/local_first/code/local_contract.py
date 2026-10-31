"""Run 2 retrieval amendment; the fixed comparison frame is never resampled."""
from common import *
import shutil, time, contextlib
sys.path.insert(0, str(ROOT/'comparison_original'))
import expansion_common as ex
import download_expansion as dl
import preliminary_core as core

VERSION='1.0.1'
PREP_CONF='628dfb8f80a89dd04d287b40326c408ae13c20e4bd4eabb7bec71b03b697d37f'
FRAME_ROWS=61158951
ORIGINAL_TARGETS=57087753
RATE=29.05
SHARDS=16
OUT_REL='derived/replication/run2_local_first_v101_PRIVATE'

def prep_root(project): return project/ex.OUT_REL/PREP_CONF[:12]
def old_download(desktop): return desktop/('CHOOSER_COMPARISON_EXPANSION_DOWNLOAD_'+PREP_CONF[:12]+'_PRIVATE')
def fingerprint_files(paths):
    return [dict(path=str(p),signature=io.sig(p)) for p in paths]
def finish_connection(c, path):
    c.close();shutil.rmtree(path,ignore_errors=True)
def threads_one():
    pa.set_cpu_count(1);pa.set_io_thread_count(1)
def stable_stage(root,conf,producer,inputs=()):
    """Completed source bytes are immutable during a stage, including resumed stages."""
    before=fingerprint_files(inputs)
    result=io.stage(root,conf,producer)
    if fingerprint_files(inputs)!=before:raise RuntimeError('Input changed while producing or verifying a stage')
    return result
def verify_saved_stage(root):
    receipt=io.load(Path(root)/'_DONE.json')
    return io.complete(root,receipt['config_sha256'])
def qident(name): return '"'+name.replace('"','""')+'"'
def metadata_empty(path):io.table(path,pa.Table.from_pylist([],schema=ex.metadata_schema()))

@contextlib.contextmanager
def old_download_lock(desktop):
    root=old_download(desktop)
    if root.is_dir():
        with dl.exclusive(root/'RUN.lock','The original Run 2 downloader is active. Pause that terminal with Ctrl-C, then rerun this command; its committed responses will be reused.'):
            yield root
    else:yield root

def make_index(c, query, path, count=None):
    """Eight-byte case-sensitive IDs in a shared read-only mmap; no per-worker set copies."""
    if count is None:count=c.execute('SELECT count(*) FROM ('+query+')').fetchone()[0]
    arr=np.lib.format.open_memmap(path,mode='w+',dtype='S8',shape=(count,))
    pos=0
    for batch in c.execute(query).to_arrow_reader(batch_size=131072):
        values=batch.column(0).to_pylist()
        if any(not isinstance(g,str) or core.GID.fullmatch(g) is None for g in values):raise RuntimeError('Invalid exact game ID')
        arr[pos:pos+len(values)]=np.asarray(values,dtype='S8');pos+=len(values)
    if pos!=count:raise RuntimeError('ID index row count differs')
    arr.flush();del arr

def index_mask(index, values):
    a=np.asarray(values,dtype='S8')
    if not len(index):return np.zeros(len(a),bool)
    pos=np.searchsorted(index,a);safe=np.minimum(pos,len(index)-1)
    return (pos<len(index))&(index[safe]==a)
