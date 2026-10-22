"""Continue the authenticated v1.0.0 journals without changing their bindings."""
from pathlib import Path
import sys

CONTROLLER_PACKAGE = Path(__file__).resolve().parents[1]
LEGACY_PACKAGE = CONTROLLER_PACKAGE / 'vendor/phased_v100'
sys.path.insert(0, str(LEGACY_PACKAGE / 'code'))
from phase_common import *
import phase_common as pc
import run_phases as legacy

VERSION = '1.0.0'
CHECKPOINTS = (25, 50, 75, 100)
LEGACY_PACKAGE_SHA = '4d59b0269dbf02963f6494485bd54e842bc245db4c54255aafa04f4a62de772f'
LIMIT75 = ((1 << 256) * 75 // 100).to_bytes(32, 'big')


def verify_release():
    for line in (CONTROLLER_PACKAGE / 'PACKAGE_MANIFEST.sha256').read_text().splitlines():
        digest, name = line.split('  ', 1)
        io.checked(io.child(CONTROLLER_PACKAGE, name), digest)
    io.checked(LEGACY_PACKAGE / 'PACKAGE_MANIFEST.sha256', LEGACY_PACKAGE_SHA)
    pc.verify_release()


def load_existing(a, up):
    pointer_path = a.phase_pointer or a.desktop / 'RUN2_PHASED_LATEST_PRIVATE.json'
    if not pointer_path.is_file():
        raise RuntimeError('Completed phased download pointer not found: ' + str(pointer_path))
    pointer = io.load(pointer_path)
    root = Path(pointer['root']).resolve()
    if root.parent != (a.project_root / pc.PHASE_REL).resolve():
        raise RuntimeError('The phased run is outside the expected mounted project directory')
    definition = io.load(root / 'config.json')
    conf = io.cfgsha(definition)
    expected = dict(version=pc.PHASE_VERSION, package_sha256=LEGACY_PACKAGE_SHA,
        upstream_run=pc.UPSTREAM_RUN, upstream_plan=pc.UPSTREAM_PLAN,
        input_receipts=up['input_receipts'], phases=list(pc.PHASES),
        phase_rule='inherited rank < floor(2^256 * percent/100)',
        extra_sqlite=definition.get('extra_sqlite', []))
    if definition != expected or root.name != conf[:12] or pointer['config_sha256'] != conf:
        raise RuntimeError('The saved phase definition differs from the authenticated v1.0.0 plan')
    state = io.load(root / 'STATE_PRIVATE.json')
    plan = Path(state['plan']).resolve()
    if plan != root / 'plan' or io.complete(plan, conf) is None:
        raise RuntimeError('The original fixed phase plan is missing or mismatched')
    if state['summary'] != io.load(plan / 'summary.json'):
        raise RuntimeError('Saved phase state differs from its authenticated plan summary')
    if state['summary']['frame_rows'] != pc.FRAME_ROWS:
        raise RuntimeError('The full fixed denominator changed')
    # These are the only metadata locations written by the original producer.
    if Path(state['metadata']).resolve() not in {
        Path(up['metadata']).resolve(), root / 'merged_sqlite/metadata.parquet'}:
        raise RuntimeError('Unrecognized inherited metadata snapshot')
    if Path(state['metadata']).resolve() == root / 'merged_sqlite/metadata.parquet':
        if io.complete(root / 'merged_sqlite', conf) is None:
            raise RuntimeError('The inherited SQLite metadata export is incomplete')
    bands = {}
    for p in pc.PHASES:
        target = plan / f'targets_{p}.parquet'
        digest = io.sha(target)
        binding = io.cfgsha([conf, p, digest])
        total, done = legacy.progress(root / 'download' / str(p), target, binding)
        row = next(r for r in state['summary']['phases'] if r['through_percent'] == p)
        if total != row['incremental_targets']:
            raise RuntimeError('An inherited band has the wrong target count')
        finished = root / 'download' / str(p) / 'finished'
        if (finished / '_DONE.json').exists():
            receipt = io.complete(finished, binding)
            if receipt['requested'] != total or done != total:
                raise RuntimeError('Finished export and saved request journal disagree')
        bands[p] = dict(target=target, sha256=digest, conf=binding, total=total, done=done)
    if not (root / 'download/10/finished/_DONE.json').is_file():
        raise RuntimeError('Finish the existing 10% download before using this continuation')
    return root, conf, state, bands


def selection(percent):
    if percent == 75:
        return "NOT f.previous_frame AND f.retrieval_rank<from_hex('" + LIMIT75.hex() + "')"
    return pc.selection_sql(percent)
