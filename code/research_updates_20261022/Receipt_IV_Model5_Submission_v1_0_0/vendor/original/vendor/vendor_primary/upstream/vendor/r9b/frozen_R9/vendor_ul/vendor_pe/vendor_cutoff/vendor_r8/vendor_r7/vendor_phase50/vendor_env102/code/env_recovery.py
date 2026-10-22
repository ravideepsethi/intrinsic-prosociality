"""Adopt only unchanged prepared Parquets from the exact previous release.

No old model is adopted: models are refitted with the corrected missing-status
validation. The old run and its receipts stay untouched. Source/reference and
future-choice caches are reused by the unchanged downstream producers.
"""
from env_common import *


def previous_config(binding,release=None):
    a=io.load(PACKAGE/'evidence/recovery_authority.json')
    if release is not None:a=dict(a,**release)
    return dict(version=a['previous_version'],package_sha256=a['previous_package_manifest_sha256'],binding=binding,design=a['design'])


def adopt_prepared(project,binding,newroot,conf):
    dest=newroot/'prepared_entry'
    if dest.exists():return dict(status='NEW_RELEASE_CHECKPOINT_ALREADY_PRESENT',adopted=False)
    authority=io.load(PACKAGE/'evidence/recovery_authority.json')
    for release in authority.get('additional_previous_releases',[])+[None]:
        expected=previous_config(binding,release);oldconf=io.cfgsha(expected)
        oldroot=project/OUTPUT_REL/oldconf[:12];source=oldroot/'prepared_entry'
        if (source/'_DONE.json').is_file():break
    else:return dict(status='NO_COMPLETED_COMPATIBLE_PREPARATION',adopted=False)
    actual=io.load(oldroot/'config.json')
    if actual!=expected or io.cfgsha(actual)!=oldconf:raise RuntimeError('Previous environment configuration changed')
    receipt=io.complete(source,oldconf)
    required={'bins.json'}|{c+'.parquet' for c in COHORTS}
    if {r['path'] for r in receipt['files']}!=required:raise RuntimeError('Previous preparation has an unexpected file set')
    def build(tmp):
        for r in receipt['files']:
            src=io.child(source,r['path']);target=io.child(tmp,r['path'])
            try:os.link(src,target)
            except OSError:shutil.copyfile(src,target)
        return dict(role_authority=receipt.get('role_authority'),adopted_preparation=True,
            source_config_sha256=oldconf,source_receipt_sha256=io.sha(source/'_DONE.json'))
    stable_stage(dest,conf,build,[source/r['path'] for r in receipt['files']])
    io.log('Reused all five completed v'+expected['version']+' prepared Parquets; refitting models with checked fixed-effect calculations.')
    return dict(status='PREPARED_PARQUETS_REUSED',adopted=True,source_config_sha256=oldconf,files=len(required),old_models_reused=0)
