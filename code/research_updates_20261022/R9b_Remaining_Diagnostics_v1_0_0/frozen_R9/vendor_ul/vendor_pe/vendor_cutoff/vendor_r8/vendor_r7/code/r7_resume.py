"""Authenticated read-only reuse of the reviewed v1.0.0 ENV extension."""
from r7_common import *
import shutil

EXPECTED_ROWS={'F50':7371688,'O50':4764089}
GATE_CONF='30547781f2c4184591916f2df432aa4e763c8e6982579e237a7105327a32d515'
GATE_PACKAGE='f272748a6c44d55009cd4397e5fcf80b059cf748f0b4a8a9b7f43eb16b5f279c'
# Reviewed production report, independently verified against its ZIP/manifest.
GATE_FILES={
    'checks.json':'c129890204bafcdc44e1027bad61a2a15e91545336397a39dd81051e41d80de5',
    'original_panel_A.json':'ef789eab516978e6d948c4af2158864e8d1594c1f4902963ce5b000bf9b4dfe4',
    'original_primary_balance.json':'6fac6caace2cbc5a00a30ca8f514315720e0ad6a3b705454e77670b8f9ab7128'}
PREVIOUS_CONF='dae86f8a1785ad8b93e40572338c0a363845033cc56054fc954ef9f9ddc2600b'
PREVIOUS_PACKAGE='40608c953af8263039d629637f6f12e26f6d4df3b98577123ee4a33010a6b76d'


def verify_completed(root, conf):
    receipt=io.complete(root,conf)
    if not receipt:raise RuntimeError('Reuse requires a completed stage: '+str(root))
    records=io.load(root/'dependencies_PRIVATE.json')
    for record in records:
        if io.sig(record['path'])!=record['signature']:
            raise RuntimeError('Reuse dependency changed: '+record['path'])
    return receipt


def bind(previous, binding):
    root=Path(previous).expanduser().resolve()
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=PREVIOUS_CONF or config.get('version')!='1.0.0' or config.get('package_sha256')!=PREVIOUS_PACKAGE:
        raise RuntimeError('Reuse requires the reviewed R7 v1.0.0 configuration dae86f8a1785')
    if config.get('spec_sha256')!=io.sha(ROOT/'R7_SPEC.md'):
        raise RuntimeError('R7 specification changed; ENV reuse is not authorized by this migration')
    old_binding=io.load(root/'INPUTS_PRIVATE.json')
    if old_binding!=binding:raise RuntimeError('Previous R7 source binding differs from the current authenticated inputs')
    receipt=verify_completed(root/'reproduction',PREVIOUS_CONF)
    if receipt.get('status')!='REPRODUCTION_GATE_PASSED':raise RuntimeError('Previous reproduction gate did not pass')
    paths={'S0_original':Path(binding['paths']['original']),'S0':Path(binding['paths']['receipt'])}
    for sample,n in EXPECTED_ROWS.items():
        folder=root/'prepared'/sample
        verify_completed(folder,PREVIOUS_CONF)
        paths[sample]=folder/'model.parquet'
        if pq.ParquetFile(paths[sample]).metadata.num_rows!=n:raise RuntimeError('Reused ENV row count differs: '+sample)
    return paths,dict(root=str(root),config_sha256=PREVIOUS_CONF,
        reused='completed F50/O50 environment tables; all 120 chronology tasks preserved',
        reproduction='current numerical engine rechecked in new run; original receipts unchanged',
        inputs={name:dict(path=str(path),sha256=io.sha(path)) for name,path in paths.items()})


def bind_reproduction(previous,binding):
    root=Path(previous).expanduser().resolve()
    config=io.load(root/'config.json')
    if io.cfgsha(config)!=GATE_CONF or config.get('version')!='1.0.2' or config.get('package_sha256')!=GATE_PACKAGE:
        raise RuntimeError('Reproduction reuse requires the reviewed R7 v1.0.2 configuration 30547781f2c4')
    if config.get('spec_sha256')!=io.sha(ROOT/'R7_SPEC.md'):
        raise RuntimeError('Specification changed since the reviewed reproduction gate')
    if io.load(root/'INPUTS_PRIVATE.json')!=binding:
        raise RuntimeError('Reproduction source binding differs from the current authenticated inputs')
    receipt=verify_completed(root/'reproduction',GATE_CONF)
    if receipt.get('status')!='REPRODUCTION_GATE_PASSED':raise RuntimeError('Previous reproduction gate did not pass')
    for name,digest in GATE_FILES.items():io.checked(root/'reproduction'/name,digest)
    checks=io.load(root/'reproduction/checks.json')
    if len(checks)!=9 or not all(r.get('passed') is True for r in checks):
        raise RuntimeError('Previous reproduction checks incomplete')
    return dict(root=str(root),config_sha256=GATE_CONF,version='1.0.2',
                status='REPRODUCTION_GATE_PASSED',checks=len(checks),files=dict(GATE_FILES),
                note='Reused verified Mac production gate; v1.0.3 changes input attachment/validation, not the estimators tested by this gate')


def reuse_reproduction(reuse,binding,root,conf):
    previous=Path(reuse['root'])
    source=previous/'reproduction'
    # bind_reproduction already checks the current authenticated source binding
    # and every original dependency signature. Retain its hash-bearing receipt
    # instead of rereading all multi-million-row inputs merely to copy the gate.
    inputs=[previous/'config.json',previous/'INPUTS_PRIVATE.json',source/'_DONE.json',
            source/'dependencies_PRIVATE.json']+[source/name for name in GATE_FILES]
    def build(tmp):
        bind_reproduction(previous,binding)
        for name in GATE_FILES:shutil.copyfile(source/name,tmp/name)
        # Portable aggregate provenance excludes machine-specific source paths.
        io.js(tmp/'reuse.json',{k:v for k,v in reuse.items() if k!='root'})
        return dict(status='REPRODUCTION_GATE_PASSED',checks=9,original_rows=2682330,
                    diagnostic_rows=2682329,reused_from_config=GATE_CONF)
    return stable_stage(root,conf,build,inputs)
