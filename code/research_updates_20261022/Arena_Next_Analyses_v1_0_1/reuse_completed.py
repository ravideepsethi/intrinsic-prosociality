"""Import the user's verified aggregate results without rerunning five stages.

Each imported result retains its original receipt and contract. The new receipt
certifies the import and its files, not execution of the old analysis under new
code. No original run files or private caches are modified.
"""
from __future__ import annotations
import hashlib
import json
import tempfile
import zipfile
from next_common import *


def checked_report(path, authority):
    require(sha(path)==authority['parent_report_sha256'],'Completed v100 report checksum changed')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        require(len(names)==len(set(names)),'Duplicate entries in completed report')
        blobs={name:z.read(name) for name in names}
    require(hashlib.sha256(blobs['MANIFEST.json']).hexdigest()==authority['parent_manifest_sha256'],
            'Completed report manifest changed')
    entries=json.loads(blobs['MANIFEST.json'])['files']
    require(set(blobs)=={'MANIFEST.json'}|{r['path'] for r in entries},'Unmanifested completed report files')
    for r in entries:
        name=Path(r['path'])
        require(not name.is_absolute() and '..' not in name.parts,'Invalid completed report path')
        b=blobs[r['path']]
        require(len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256'],
                'Completed report member checksum changed: '+r['path'])
    return blobs


def import_completed(root,contract,sample):
    authority=read(ROOT/'authority/V100_REUSE_AUTHORITY.json')
    for r in authority['unchanged_analysis_sources']:
        require(sha(safe_child(ROOT,r['path']))==r['sha256'],'Cannot reuse a completed stage after its analysis source changed')
    common=(ROOT/'next_common.py').read_bytes().replace(
        ("VERSION = '"+VERSION+"'").encode(),b"VERSION = '1.0.0'")
    require(hashlib.sha256(common).hexdigest()==authority['parent_common_sha256'],
            'Cannot reuse completed stages after shared functions changed')
    blobs=checked_report(ROOT/'authority/V100_COMPLETED_RESULTS.zip',authority)
    require(json.loads(blobs['INPUT_QA.json'])==sample['authority'],'Completed results refer to different arena inputs')
    status=json.loads(blobs['RUN_STATUS.json']);records=[]
    for stage in authority['stages']:
        original=json.loads(blobs[stage+'/_DONE.json'])
        require(original['contract']==authority['parent_contract'] and original['summary']['status']=='COMPLETE',
                'Prior stage is not complete under the authorized parent contract')
        require(status['stages'][stage]==original['summary'],'Prior run and stage summaries differ')
        prefix=stage+'/'
        require({n[len(prefix):] for n in blobs if n.startswith(prefix)}==
                {'_DONE.json'}|{x['path'] for x in original['files']},'Prior stage file inventory differs')
        provenance={'stage':stage,'method':'verified aggregate import; analysis not rerun',
          'original_version':'1.0.0','original_contract':authority['parent_contract'],
          'original_run':authority['parent_run'],'original_report_sha256':authority['parent_report_sha256'],
          'original_completion_receipt_sha256':hashlib.sha256(blobs[prefix+'_DONE.json']).hexdigest(),
          'analysis_sources_unchanged':True,'private_caches_imported':False}
        dest=Path(root)/'public'/stage
        old=stage_complete(dest,contract)
        if old:
            require(read(dest/'INHERITED_FROM_V100.json')==provenance,'Imported stage provenance differs')
        else:
            require(not dest.exists(),'Unrecognized incomplete import directory: '+str(dest))
            with tempfile.TemporaryDirectory(prefix='import_'+stage+'_',dir=Path(root)/'private') as temp:
                folder=Path(temp)/stage;folder.mkdir()
                for r in original['files']:
                    b=blobs[prefix+r['path']]
                    require(len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256'],
                            'Original stage receipt does not authenticate its result')
                    target=safe_child(folder,r['path']);target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b)
                (folder/'_V100_DONE.json').write_bytes(blobs[prefix+'_DONE.json'])
                js(folder/'INHERITED_FROM_V100.json',provenance)
                summary=dict(original['summary'],reused_from_version='1.0.0',analysis_rerun=False,
                             original_contract=authority['parent_contract'])
                finish_stage(folder,contract,summary)
                os.replace(folder,dest)
            log('Imported verified completed v100 results: '+stage)
        records.append(provenance)
    js(Path(root)/'public/REUSED_RESULTS.json',{'stages':records,'input_qa_equal':True,
       'original_report_sha256':authority['parent_report_sha256'],'original_run_files_modified':False})
    return records
