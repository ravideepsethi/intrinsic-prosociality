"""Bind the completed 75% analysis; carry forward its exact reviewed exclusions.

The larger checkpoint is independently read. No new metadata exclusions are
silently accepted. The frozen frame and factual histories remain intact.
"""
from phase100_common import *
import copy

POLICY = 'phase100_preserve_exact_certified75_three_record_quarantine_v1'


def bind_previous(a, local, phase):
    authority = io.load(RELEASE/'evidence/parent75_authority.json')
    root = a.project_root/authority['root_relative']
    conf = authority['config_sha256']
    config = io.load(root/'config.json')
    if io.cfgsha(config) != conf or config['code_sha256'] != authority['code_sha256']:
        raise RuntimeError('Completed 75% producer/configuration changed')
    io.checked(root/'report/summary.json', authority['summary_sha256'])
    io.checked(root/'report/REPORT_MANIFEST.json', authority['manifest_sha256'])
    summary = io.load(root/'report/summary.json')
    if summary['status'] != authority['status']:
        raise RuntimeError('Expected the completed, reviewed 75% analysis')
    if config['local_receipts'] != local['input_receipts']:
        raise RuntimeError('75% and 100% local-source receipts differ')
    if config['phase']['config_sha256'] != phase['config_sha256'] or config['phase']['root'] != phase['root']:
        raise RuntimeError('75% and 100% download frames differ')
    env_common.checked_stage_files(root/'quarantine', conf,
        ['summary.json', 'quarantined_records_PRIVATE.parquet',
         'april_merged_PRIVATE.parquet', 'january_merged_PRIVATE.parquet', 'june_merged_PRIVATE.parquet'])
    return dict(root=str(root), conf=conf, summary_sha256=authority['summary_sha256'])


def audit_quarantine(a, up, phase, coverage, root, conf, memory):
    bound = bind_previous(a, up, phase)
    previous = Path(bound['root']); oldq = previous/'quarantine'
    unresolved = [coverage/m/'unresolved_PRIVATE.parquet' for m in ex.MONTHS]
    pools = [coverage/m/'pool.parquet' for m in ex.MONTHS]
    memberships = [coverage/m/'membership_PRIVATE.parquet' for m in ex.MONTHS]
    oldfiles = []
    for m in ex.MONTHS:
        folder = previous/'coverage'/m
        env_common.checked_stage_files(folder, bound['conf'], ['pool.parquet', 'membership_PRIVATE.parquet'])
        oldfiles += [folder/'pool.parquet', folder/'membership_PRIVATE.parquet']

    def build(tmp):
        c = io.conn(tmp/'spill', memory, 1)
        try:
            rows = []
            for month, path in zip(ex.MONTHS, unresolved):
                for gid, disposition in c.execute('SELECT game_id,disposition FROM '+io.parq([path])).fetchall():
                    rows.append(dict(month=month, game_id=gid, disposition=disposition))
            actual = sorted((r['month'], r['game_id'], r['disposition']) for r in rows)
            expected = sorted((r['month'], r['game_id'], r['disposition']) for r in io.read(oldq/'quarantined_records_PRIVATE.parquet').to_pylist())
            diagnostic = dict(current_unresolved=len(actual), previous_unresolved=len(expected),
                counts_by_month=[dict(month=m, rows=sum(r['month']==m for r in rows)) for m in sorted(set(r['month'] for r in rows))],
                identities_match=(actual == expected), new_exclusions_applied=False)
            # This aggregate persists even when an unexpected record stops analysis.
            io.js(coverage.parent/'quarantine_diagnostic.json', diagnostic)
            if actual != expected:
                raise RuntimeError('100% unresolved identities differ from the certified 75% quarantine. Coverage and quarantine_diagnostic.json were saved; no new row exclusions applied.')
            for month in ex.MONTHS:
                current = coverage/month; old = previous/'coverage'/month
                c.execute('CREATE OR REPLACE VIEW membership AS SELECT * FROM '+io.parq([current/'membership_PRIVATE.parquet']))
                where="retrieval_rank<from_hex('"+threshold(75).hex()+"')"
                before = tmp/(month+'_prior_members.parquet')
                io.copy(c, 'SELECT * FROM membership WHERE '+where, before)
                from phase100_inputs import compare_samples
                compare_samples(c, before, old/'membership_PRIVATE.parquet', month+' prior frame')
                io.copy(c, 'SELECT p.* FROM '+io.parq([current/'pool.parquet'])+' p JOIN membership USING(game_id) WHERE '+where, tmp/(month+'_prior_pool.parquet'))
                compare_samples(c, tmp/(month+'_prior_pool.parquet'), old/'pool.parquet', month+' prior pool metadata')
                before.unlink(); (tmp/(month+'_prior_pool.parquet')).unlink()
            # Verify that the exact reviewed merged metadata for each flagged ID
            # has not changed. Published snapshots are immutable, not repaired here.
            from cached_inputs import metadata_for_month
            for label, month in [('april','2024-04'), ('january','2025-01'), ('june','2025-06')]:
                old = oldq/(label+'_merged_PRIVATE.parquet')
                gid = io.read(old)['game_id'][0].as_py()
                path = tmp/(label+'_merged_PRIVATE.parquet')
                io.copy(c, 'SELECT * FROM '+io.parq(metadata_for_month(phase['metadata'],month))+' WHERE game_id='+io.lit(gid), path)
                compare_samples(c, path, old, label+' flagged metadata')
            if rows:
                ids=','.join(io.lit(r['game_id']) for r in rows)
                if c.execute('SELECT count(*) FROM '+io.parq(pools)+' WHERE game_id IN ('+ids+')').fetchone()[0]:
                    raise RuntimeError('Quarantined game entered the retained pool')
            io.table(tmp/'quarantined_records_PRIVATE.parquet',io.read(oldq/'quarantined_records_PRIVATE.parquet'))
            info = copy.deepcopy(io.load(oldq/'summary.json'))
            info.update(policy=POLICY, phase_percent=100, prior_analysis_config_sha256=bound['conf'],
                counts_by_cohort=dict(new_phase75=3,increment_75_100=0,new_phase100=3,old_author_clean=0,pooled=3),
                scope='The exact three previously reviewed exclusions; zero additional exclusions in the 75–100% band.',
                amendment_scope='No new available-case amendment.', certified75_pool_and_membership_reproduced=True)
            io.js(tmp/'summary.json', info)
            return info
        finally:
            finish_connection(c, tmp/'spill')
    deps = unresolved+pools+memberships+oldfiles+[oldq/'_DONE.json',oldq/'quarantined_records_PRIVATE.parquet',oldq/'summary.json',Path(phase['metadata'])]
    result = stable_stage(root,conf,build,deps)
    io.log('100% metadata audit passed: exact prior three exclusions; no new exclusions; prior pool reproduced.')
    return result
