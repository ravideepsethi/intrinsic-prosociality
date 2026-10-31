"""An interrupted stage never becomes a valid checkpoint."""
from util import *
import shutil,uuid

def stage(parent,name,key,build):
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True);target=parent/name
    if target.exists():
        require((target/'CHECKPOINT.json').is_file(),'Unsealed checkpoint: '+str(target))
        receipt=read(target/'CHECKPOINT.json');require(receipt['key']==key,'Checkpoint inputs changed: '+name)
        for item in receipt['files']:verify(item,target)
        log(name+': verified checkpoint');return target,receipt['summary']
    temporary=parent/(name+'.partial_'+uuid.uuid4().hex);temporary.mkdir()
    try:
        summary=build(temporary)
        files=[record(f,temporary) for f in sorted(temporary.rglob('*')) if f.is_file()]
        save(temporary/'CHECKPOINT.json',dict(key=key,files=files,summary=summary))
        os.replace(temporary,target);return target,summary
    except BaseException:
        shutil.rmtree(temporary,ignore_errors=True);raise

def copy_query(connection,query,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    connection.execute('COPY ('+query+') TO '+sqlstr(path)+' (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880)')
