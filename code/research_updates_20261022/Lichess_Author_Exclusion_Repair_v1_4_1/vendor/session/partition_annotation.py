"""Bounded Arrow/NumPy session annotation with exact original-column checks."""
from util import *
import pyarrow.compute as pc

GAPS=(15,30,60)

def array(table,name,fill=0):
    return pc.fill_null(table[name],fill).to_numpy(zero_copy_only=False)

def equal_columns(left,right,columns):
    require(left.num_rows==right.num_rows,'Partition row count changed')
    for name in columns:
        a,b=left[name],right[name]
        require(a.type==b.type,'Partition type changed: '+name)
        same=pc.or_(pc.fill_null(pc.equal(a,b),False),pc.and_(pc.is_null(a),pc.is_null(b)))
        if pa.types.is_floating(a.type):
            same=pc.or_(same,pc.and_(pc.fill_null(pc.is_nan(a),False),pc.fill_null(pc.is_nan(b),False)))
        require(bool(pc.all(same).as_py()) if left.num_rows else True,'Partition values changed: '+name)

def annotate(table):
    require(table.num_rows>0,'Empty session partition')
    columns=table.column_names
    require(all('pos'+str(g) not in columns for g in GAPS),'Already annotated input')
    order=pc.sort_indices(table,sort_keys=[('chooser','ascending'),('t','ascending'),
        ('ordinal','ascending'),('game_id','ascending')])
    original=table.take(order)
    n=original.num_rows;index=np.arange(n,dtype=np.int64)
    chooser=array(original,'chooser');times=array(original,'t')
    first=np.r_[True,chooser[1:]!=chooser[:-1]]
    ends=np.r_[first[1:],True]
    first_at=np.maximum.accumulate(np.where(first,index,0))
    prior=array(original,'prev_t');prior_null=pc.is_null(original['prev_t']).to_numpy()
    require(np.all(~prior_null[1:][~first[1:]]) and
        np.array_equal(prior[1:][~first[1:]],times[:-1][~first[1:]]),'Predecessor times disagree with account order')
    require(np.all(prior_null|(prior<=times)),'History predecessor is in the future')
    result=original;session_ends=None
    for gap in GAPS:
        sid=array(original,'sid'+str(gap))
        breaks=(prior_null|(times-prior>=gap*60000)).astype(np.int64)
        cumulative=np.cumsum(breaks)
        expected_sid=cumulative-(cumulative[first_at]-breaks[first_at])
        require(np.array_equal(sid,expected_sid),'Session IDs disagree with direct gap calculation')
        group_start=first.copy();group_start[1:]|=sid[1:]!=sid[:-1]
        group_at=np.maximum.accumulate(np.where(group_start,index,0))
        carry=array(original,'carry'+str(gap))
        carry_censored=array(original,'carry_cens'+str(gap),True)
        require(np.array_equal(carry,carry[first_at]) and
            np.array_equal(carry_censored,carry_censored[first_at]),'Carry varies within chooser')
        positions=index-group_at+1+np.where(sid==0,carry,0)
        censored=(sid==0)&carry_censored
        require(np.all(positions>=1),'Nonpositive session position')
        result=result.append_column('pos'+str(gap),pa.array(positions,type=pa.int64()))
        result=result.append_column('cens'+str(gap),pa.array(censored,type=pa.bool_()))
        if gap==30:
            carry_start=array(original,'carry_start30')
            has_carry_start=~pc.is_null(original['carry_start30']).to_numpy()
            start=np.where((sid==0)&has_carry_start,carry_start,times[group_at])
            require(np.all(start<=times),'Session starts after its own game')
            result=result.append_column('start30',pa.array(start,type=pa.int64()))
            session_ends=np.r_[group_start[1:],True]
    equal_columns(original,result,columns)
    # Each chooser belongs to one partition; last rows give exact monthly carry.
    last=result.filter(pa.array(ends))
    before=['chooser','t','game_id','result','rating_diff','tie_n','pos15','pos30','pos60',
        'cens15','cens30','cens60','start30']
    after=['chooser','last_t','last_gid','last_result','last_diff','last_tie','pos15','pos30','pos60',
        'cens15','cens30','cens60','start30']
    latest=last.select(before).rename_columns(after)
    summary=result.filter(pa.array(session_ends)).select(['chooser','start30','pos30','cens30','t'])
    summary=summary.rename_columns(['chooser','start30','observed_session_length','left_censored','last_t'])
    return original,result,latest,summary

def write_arrow(table,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.partial_'+uuid.uuid4().hex)
    pq.write_table(table,temp,compression='zstd',row_group_size=131072)
    os.replace(temp,path)

def worker(task):
    paths,destination,key,bucket,buckets,columns=task;out=Path(destination)
    if cached(out,key):return str(out)
    table=pa.concat_tables([pq.ParquetFile(p).read(columns=columns,use_threads=False) for p in paths])
    require(np.all(array(table,'chooser')%buckets==bucket),'Account crossed its designated partition')
    original,annotated,latest,summary=annotate(table)
    write_arrow(annotated,out/'annotated.parquet')
    roundtrip=pq.ParquetFile(out/'annotated.parquet').read(use_threads=False)
    equal_columns(annotated,roundtrip,annotated.column_names)
    equal_columns(original,roundtrip,columns)
    write_arrow(latest,out/'latest.parquet');write_arrow(summary,out/'sessions30.parquet')
    # Preserve the much smaller summaries independently too.
    equal_columns(latest,pq.ParquetFile(out/'latest.parquet').read(),latest.column_names)
    equal_columns(summary,pq.ParquetFile(out/'sessions30.parquet').read(),summary.column_names)
    js(out/'CHECKS.json',dict(rows=original.num_rows,choosers=latest.num_rows,sessions30=summary.num_rows,
        original_columns_equal=True,written_columns_equal=True,gap_session_ids_equal=True,
        method='Arrow stable account/time/ordinal/game ordering; NumPy group positions'))
    commit(out,key,rows=original.num_rows,bucket=bucket)
    return str(out)
