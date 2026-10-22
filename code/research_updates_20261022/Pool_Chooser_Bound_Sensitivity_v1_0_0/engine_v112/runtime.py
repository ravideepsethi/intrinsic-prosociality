"""Read-only shared arrays, bounded process scheduling and measured ETAs."""
import bootstrap_path
import atexit, json, multiprocessing, os, re, subprocess, time
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import numpy as np
from io_utils import binding, digest, json_read, json_write, log, require

_POOL=None
_POOL_KEY=None


def ensure_mapped(design):
    """Parent alone creates/verifies the numeric cache, once per invocation.

    Original authenticated NPZ files remain untouched. Uncompressed NPY arrays
    let spawned Mac workers share the OS page cache instead of unzipping and
    allocating a private copy in each process. These files never leave PRIVATE.
    """
    design=Path(design);root=design/'MAPPED';ready=root/'READY.json'
    source={name:digest(design/(name+'.npz')) for name in ['development','evaluation']}
    identity=binding(source)
    if ready.exists():
        meta=json_read(ready);require(meta['source_identity']==identity,'Mapped source changed')
        for name,items in meta['arrays'].items():
            for key,record in items.items():
                require(re.fullmatch(r'\w+',key) is not None,'Invalid array name')
                path=root/name/(key+'.npy')
                require(path.is_file() and digest(path)==record['sha256'],'Mapped cache checksum failed: '+str(path))
        return meta
    root.mkdir(exist_ok=True);meta=dict(source_identity=identity,arrays={},total_bytes=0)
    for name in source:
        folder=root/name;folder.mkdir(exist_ok=True);meta['arrays'][name]={}
        with np.load(design/(name+'.npz'),allow_pickle=False) as archive:
            for key in archive.files:
                require(re.fullmatch(r'\w+',key) is not None,'Invalid array name')
                value=archive[key];require(not value.dtype.hasobject,'Object arrays cannot be shared safely')
                path=folder/(key+'.npy');part=path.with_suffix('.partial')
                with part.open('wb') as f:np.save(f,value,allow_pickle=False)
                os.replace(part,path)
                meta['arrays'][name][key]=dict(shape=list(value.shape),dtype=value.dtype.str,
                    bytes=value.nbytes,sha256=digest(path))
                meta['total_bytes']+=value.nbytes
    json_write(ready,meta)
    log(f'Numeric cache ready: {meta["total_bytes"]/1024**2:.1f} MiB, shared read-only between workers')
    return meta


def load_mapped(design):
    root=Path(design)/'MAPPED';meta=json_read(root/'READY.json');out={}
    for name,items in meta['arrays'].items():
        out[name]={}
        for key,record in items.items():
            require(re.fullmatch(r'\w+',key) is not None,'Invalid array name')
            value=np.load(root/name/(key+'.npy'),mmap_mode='r',allow_pickle=False)
            require(list(value.shape)==record['shape'] and value.dtype.str==record['dtype'],'Mapped array schema changed')
            out[name][key]=value
    return out


def memory_info():
    """Available memory is a conservative scheduling hint, not an allocation guarantee."""
    total=available=None
    try:
        if os.uname().sysname=='Darwin':
            total=int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize'],text=True).strip())
            text=subprocess.check_output(['/usr/bin/vm_stat'],text=True)
            size=int(re.search(r'page size of (\d+) bytes',text).group(1))
            counts=dict((k,int(v)) for k,v in re.findall(r'([^\n:]+):\s+(\d+)\.',text))
            available=size*sum(counts.get(k,0) for k in ['Pages free','Pages inactive','Pages speculative'])
        else:
            text=Path('/proc/meminfo').read_text()
            total=int(re.search(r'MemTotal:\s+(\d+)',text).group(1))*1024
            available=int(re.search(r'MemAvailable:\s+(\d+)',text).group(1))*1024
            # Honor a container's memory limit when this code is tested there.
            p=Path('/sys/fs/cgroup/memory.max');q=Path('/sys/fs/cgroup/memory.current')
            if p.exists() and p.read_text().strip().isdigit():
                limit=int(p.read_text());used=int(q.read_text()) if q.exists() else 0
                total=min(total,limit);available=min(available,max(0,limit-used))
    except (OSError,ValueError,AttributeError,subprocess.SubprocessError):pass
    return total,available


def choose_workers(requested,mapped,max_support=6,perception=False,switching=False):
    cpu=max(1,os.cpu_count() or 1);cap=min(10,cpu)
    if requested!='auto':cap=min(cap,int(requested))
    n=max(items['y']['shape'][0] for items in mapped['arrays'].values())
    # Predict/filter and simulation still allocate temporaries. Allow a larger
    # allowance for five-bin perception and two-state forward/backward arrays.
    factor=100 if perception else (55 if switching else 18)
    per_worker=max(384*1024**2,200*1024**2+n*max_support*8*factor+mapped['total_bytes']*.35)
    total,available=memory_info()
    if total is None or available is None:memory_cap=4
    else:
        reserve=min(2*1024**3,total*.15)
        budget=max(0,min(total*.65,available-reserve)-mapped['total_bytes'])
        memory_cap=max(1,int(budget//per_worker))
    workers=max(1,min(cap,memory_cap))
    plan=dict(requested=requested,workers=workers,cpu_count=cpu,cap=10,
      total_memory_bytes=total,available_memory_bytes=available,
      estimated_private_bytes_per_worker=int(per_worker),shared_array_bytes=mapped['total_bytes'],
      numerical_threads_per_worker=1,process_start_method='spawn',
      note='Conservative capacity estimate; close competing heavy jobs for maximum throughput. Not a measured optimal worker count.')
    log(f'Worker plan: {workers} processes; 1 numerical thread each; estimated private RAM {per_worker/1024**3:.2f} GiB/worker')
    return plan


def close_pool():
    global _POOL,_POOL_KEY
    if _POOL is not None:_POOL.shutdown(wait=True,cancel_futures=True)
    _POOL=None;_POOL_KEY=None


atexit.register(close_pool)


def get_pool(design,workers,initializer):
    global _POOL,_POOL_KEY
    key=(str(Path(design).resolve()),workers)
    if _POOL_KEY!=key:
        close_pool()
        _POOL=ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn'),
              initializer=initializer,initargs=(key[0],))
        _POOL_KEY=key
    return _POOL


def run_timed(worker,task):
    begin=time.monotonic();result=worker(task)
    return result,time.monotonic()-begin


def duration(seconds):
    if seconds>=3600:return f'{seconds/3600:.1f} h'
    if seconds>=60:return f'{seconds/60:.1f} min'
    return f'{seconds:.0f} s'


def execute(tasks,worker,design,workers,label,initializer):
    """Bound the queue; retain workers across dependent model batches.

    Cached tasks are validated synchronously and excluded from the ETA rate.
    Results retain their original order, independent of worker completion order.
    """
    initializer(design);results=[None]*len(tasks);pending=[];cached=0
    for j,task in enumerate(tasks):
        path=task[5] if worker.__name__=='fit_one' else task[-1]
        if Path(path).exists():results[j]=worker(task);cached+=1
        else:pending.append((j,task))
    log(f'{label}: {cached}/{len(tasks)} cached; {len(pending)} new tasks; {workers} workers')
    if not pending:return results
    started=time.monotonic();elapsed=[];completed=0
    if worker.__name__ in ['bootstrap_one','recovery_one']:
        first=pending[0][1]
        fits,options=(first[2],first[3]) if worker.__name__=='bootstrap_one' else (first[4],first[5])
        # A deliberately broad starting estimate. Warm-start timings need not
        # describe independent starts; actual completed replications replace it.
        rough=sum(max(1.,r.get('elapsed_seconds',60.)) for r in fits.values())*(options['starts']+1)
        rough*=len(pending)/min(workers,len(pending))
        log(f'{label}: provisional ETA {duration(rough*.7)}–{duration(rough*2.)}; based on fitted-model timings, pending completed-replication calibration')
    def progress():
        left=len(pending)-completed
        if elapsed:
            # Allow for running tasks and a partially occupied final wave.
            eta=max(0.,sum(elapsed)/len(elapsed)*left/min(workers,max(1,left)))
            text='ETA about '+duration(eta)+' (updated from completed tasks)'
        else:text='ETA awaiting the first completed task; elapsed '+duration(time.monotonic()-started)
        log(f'{label}: {cached+completed}/{len(tasks)} complete; {text}')
    if workers==1:
        for j,task in pending:
            results[j],seconds=run_timed(worker,task);elapsed.append(seconds);completed+=1;progress()
    else:
        pool=get_pool(design,workers,initializer);queue=iter(pending);active={}
        def submit():
            item=next(queue,None)
            if item is None:return False
            j,task=item;active[pool.submit(run_timed,worker,task)]=j;return True
        for _ in range(min(len(pending),workers*2)):submit()
        while active:
            done,_=wait(active,timeout=30,return_when=FIRST_COMPLETED)
            if not done:progress();continue
            for future in done:
                j=active.pop(future);results[j],seconds=future.result()
                elapsed.append(seconds);completed+=1;submit()
            progress()
    log(f'{label}: finished in {duration(time.monotonic()-started)}')
    return results
