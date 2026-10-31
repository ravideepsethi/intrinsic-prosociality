"""Authenticate the reviewed return, retain completed work, collect diagnostics.

The v1.0.1 run remains read-only. New outputs go into a v1.0.2 directory.
No failed statistical check is converted into a successful analysis.
"""
from engine import *
from bindings import public_copy
import zipfile

AUTHORITY = ROOT / 'authority/prior_batch'


def prior_root(project):
    key = read(AUTHORITY / 'LOCATION.json')['run_id']
    return Path(project) / 'derived/replication/mating_material_noniv_batch_v101_PRIVATE' / key[:16]


def authenticate_prior(project, auth):
    old = prior_root(project)
    require(old.is_dir(), 'The reviewed v1.0.1 run is missing: ' + str(old))
    require(sha(old/'report/REPORT_MANIFEST.json') == sha(AUTHORITY/'REPORT_MANIFEST.json'),
            'The previous batch report differs from the reviewed return')
    for r in read(AUTHORITY/'REPORT_MANIFEST.json'):
        rel = Path(r['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, 'Unsafe previous report path')
        verify(dict(r, path=str(old/'report'/rel)))
    old_auth = read(old/'PRIVATE/AUTH.json')
    for key in ('fingerprint', 'parent_run_id', 'manifest_sha256'):
        require(old_auth[key] == auth[key], 'The previous batch used different corrected inputs: ' + key)
    return old


def adopt_complete(old, run, auth):
    from batch import verified_done
    expected = read(AUTHORITY/'STATUS.json')['states']
    adopted = []
    for name, state in expected.items():
        if state['status'] not in ('COMPLETE','REUSED'):
            continue
        target = run/'PRIVATE/stages'/name
        if (target/'DONE.json').exists():
            verified_done(target/'DONE.json', auth['fingerprint'])
            continue
        source = old/'PRIVATE/stages'/name
        original = verified_done(source/'DONE.json', auth['fingerprint'])
        require(original is not None, 'The reviewed stage has no completion receipt: ' + name)
        # Cross-check both the completed private outputs and the reviewed public copy.
        for item in read(AUTHORITY/'REPORT_MANIFEST.json'):
            prefix = 'families/' + name + '/'
            if item['path'].startswith(prefix):
                verify(dict(item, path=str(source/'report'/item['path'][len(prefix):])))
        public_copy(source/'report', target/'report')
        provenance = target/'report/REUSED_FROM_V101.json'
        write(provenance, dict(prior_run_id=read(AUTHORITY/'LOCATION.json')['run_id'],
              prior_done_sha256=sha(source/'DONE.json'),
              parent_run_id=auth['parent_run_id'], models_refitted=0,
              original_status=original['result']['status']))
        records = original['files'] + [record(p) for p in sorted((target/'report').rglob('*')) if p.is_file()]
        write(target/'DONE.json', dict(status='COMPLETE', input_fingerprint=auth['fingerprint'],
              result=original['result'], files=records, adopted_from=str(source)))
        adopted.append(name)
        log('Retained and verified completed v1.0.1 family: ' + name)
    write(run/'report/REUSE.json', dict(prior_run_id=read(AUTHORITY/'LOCATION.json')['run_id'],
          adopted_this_launch=adopted, complete_families_in_prior=sum(s['status'] in ('COMPLETE','REUSED') for s in expected.values()),
          original_run_seconds=read(AUTHORITY/'STATUS.json')['seconds_this_launch'],
          original_outputs_modified=False))
    return adopted


def copy_patron_checkpoints(project, state, producer):
    """Copy only committed small fits; the original producer rechecks each key."""
    old = prior_root(project)/'PRIVATE/stages/patron/PRIVATE'
    copied = 0
    for category in ('rematch_fits', 'postcertification_fits'):
        for receipt_path in sorted((old/category).glob('*/CHECKPOINT.json')):
            directory = receipt_path.parent
            if '.partial' in directory.name:
                continue
            receipt = read(receipt_path)
            require(receipt.get('status')=='CHECKPOINT_COMPLETE', 'Uncommitted Patron checkpoint')
            producer.read_checkpoint(directory, receipt['config_sha256'])
            destination = Path(state)/category/directory.name
            if destination.exists():
                producer.read_checkpoint(destination, receipt['config_sha256'])
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name+'.copy_partial')
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir()
            for r in receipt['files']:
                require(Path(r['name']).name == r['name'], 'Unsafe Patron checkpoint filename')
                shutil.copy2(directory/r['name'], temporary/r['name'])
            shutil.copy2(receipt_path, temporary/'CHECKPOINT.json')
            producer.read_checkpoint(temporary, receipt['config_sha256'])
            os.replace(temporary, destination)
            copied += 1
    return copied


def collect_responsibility_zip(archive, out, auth, expected_package):
    """Copy authenticated aggregate evidence, including covariance arrays, on failure."""
    out = Path(out)
    with zipfile.ZipFile(archive) as z:
        require(z.testzip() is None, 'Responsibility diagnostic ZIP is damaged')
        require(len(z.namelist()) == len(set(z.namelist())), 'Duplicate diagnostic ZIP entries')
        require(z.read('SHA256SUMS.txt') == Path(expected_package).read_bytes(),
                'Responsibility diagnostic package differs from the preserved v1.0.1 source')
        manifest = json.loads(z.read('REPORT_MANIFEST.json'))
        require(len(manifest)==len({r['path'] for r in manifest}), 'Duplicate diagnostic manifest paths')
        entries = {r['path']:r for r in manifest}
        selected = sorted(n for n in z.namelist() if n.startswith('report/') and not n.endswith('/'))
        required = ['report/INPUT_LINEAGE.json','report/REFERENCE_REPRODUCTION.csv',
                    'report/reference_reproduction/model_covariances.npz',
                    'report/reference_reproduction/coefficient_order.json']
        require(all(n in selected for n in required), 'Missing responsibility reproduction diagnostics')
        for name in selected:
            rel = Path(name).relative_to('report')
            require(not rel.is_absolute() and '..' not in rel.parts and
                    not any('private' in p.lower() for p in rel.parts), 'Unsafe diagnostic report path')
            require(rel.suffix in ('.csv','.json','.txt','.npz','.png','.tex'), 'Unexpected diagnostic extension')
            payload = z.read(name);r=entries.get(name)
            require(r is not None and len(payload)==r['bytes'] and
                    hashlib.sha256(payload).hexdigest()==r['sha256'], 'Diagnostic checksum differs: '+name)
            if rel.suffix=='.csv':
                columns=next(csv.reader(payload.decode().splitlines()),[])
                require(not {'chooser','game_id','chooser_user_id','disconnected_user_id','username',
                    'user_id','username_norm','matched_kind_chooser_id'}.intersection(columns),
                    'Private identifier in diagnostic report')
        lineage=json.loads(z.read('report/INPUT_LINEAGE.json'))
        require(lineage['parent_run_id']==auth['parent_run_id'] and
                lineage['parent_manifest_sha256']==auth['manifest_sha256'], 'Wrong responsibility input parent')
        for name in selected:
            dest=out/'report/reference_diagnostics'/Path(name).relative_to('report')
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(z.read(name))
    comparisons=pd.read_csv(out/'report/reference_diagnostics/REFERENCE_REPRODUCTION.csv')
    failed=comparisons.loc[comparisons.passed.astype(str).str.lower()!='true'].copy()
    table(out/'report/REFERENCE_CHECKS_NEEDING_REVIEW',failed)
    result=dict(status='REFERENCE_REVIEW_REQUIRED',diagnostic_files=len(selected),
                failed_comparisons=len(failed),source_zip_sha256=sha(archive),models_refitted=0,
                tolerances_changed=False,
                explanation='Original check remains failed. Full aggregate reference estimates and covariance matrices are included for diagnosis.')
    write(out/'report/RESPONSIBILITY_REVIEW_STATUS.json',result)
    return result


def responsibility(a, auth, out):
    candidates=sorted((prior_root(a.project)/'PRIVATE/stages/responsibility/PRIVATE/native_return').glob('MATERIAL_RESPONSIBILITY_*_FAILED.zip'))
    require(len(candidates)==1, 'Expected the single responsibility failure ZIP from the reviewed batch')
    return collect_responsibility_zip(candidates[0],out,auth,
        ROOT/'components/Mating_Material_Responsibility_v1_0_2/SHA256SUMS.txt')
