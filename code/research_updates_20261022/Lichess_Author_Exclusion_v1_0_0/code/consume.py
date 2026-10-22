"""Explicit opt-in interface for subsequent author-excluded analysis packages.

This does not redirect or silently patch earlier certified programs.
"""
from pathlib import Path
from exclusion import POLICY,policy_sha
from io_tools import read,verify_record,authenticate

WORK='derived/replication/author_exclusion_v100_PRIVATE'

def ready(project):
    work=Path(project)/WORK
    result=read(work/'AUTHOR_EXCLUDED_MAIN_READY_PRIVATE.json')
    if result.get('contract')!='AUTHOR_EXCLUDED_MAIN_24M_V1' or result.get('policy_sha256')!=policy_sha() or result.get('policy')!=POLICY:
        raise RuntimeError('Author-exclusion policy or dataset contract differs')
    return result

def main_files(project):
    """Authenticate and return the 24 monthly main-sample input paths."""
    m=ready(project);records=m['datasets']['main_24m']
    expected=[f'{y}-{month:02d}' for y in (2023,2024,2025) for month in range(1,13) if '2023-11'<=f'{y}-{month:02d}'<='2025-10']
    if sorted(r['month'] for r in records)!=expected:raise RuntimeError('Author-excluded main months differ')
    work=Path(project)/WORK
    for r in records:authenticate(r['path'],r['sha256'],work,r['rows'])
    return [r['path'] for r in sorted(records,key=lambda r:r['month'])]

def excluded_games(project,*,family,months):
    """Return an authenticated game-index path only for covered source months.

    The index covers opportunities audited from specified roots, not all games
    on Lichess. Direct username/ID filters remain necessary for other sources.
    """
    m=ready(project)
    covered={r['month'] for r in m['audited_inputs'] if r['family']==family}
    if not months or not set(months)<=covered:raise RuntimeError('Requested analysis months are not covered by the author audit')
    verify_record(m['excluded_games'])
    return m['excluded_games']['path']
