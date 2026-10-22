"""Explicit author exclusion shared by the audit and downstream consumers."""
from pathlib import Path
import hashlib,json
import pyarrow as pa
import pyarrow.parquet as pq

PACKAGE=Path(__file__).resolve().parents[1]
POLICY=json.loads((PACKAGE/'AUTHOR_EXCLUSION.json').read_text())
AUTHORS=tuple(POLICY['excluded_usernames'])
NAME_PAIRS=(('chooser_username_norm','disconnected_username_norm'),
            ('chooser_username','disconnected_username'),
            ('candidate_chooser','likely_disconnected_player'),
            ('chooser','opponent'),('username','recipient_name'),
            ('api_white_username_norm','api_black_username_norm'),
            ('api_white_username','api_black_username'),('white_username_pgn','black_username_pgn'))

def lit(x):return "'"+str(x).replace("'","''")+"'"
def ident(x):return '"'+str(x).replace('"','""')+'"'
def normalized(column,alias='s'):
    return 'lower(trim(CAST('+ident(alias)+'.'+ident(column)+' AS VARCHAR)))'
def is_name_type(t):
    if pa.types.is_dictionary(t):t=t.value_type
    return pa.types.is_string(t) or pa.types.is_large_string(t)
def username_pair(path):
    schema=pq.ParquetFile(path).schema_arrow
    types={f.name:f.type for f in schema}
    for pair in NAME_PAIRS:
        if all(n in types and is_name_type(types[n]) for n in pair):return pair
    raise RuntimeError('Both player username fields are required: '+Path(path).name)
def name_hits(pair,alias='s'):
    names=','.join(lit(x) for x in AUTHORS)
    return [f'coalesce({normalized(n,alias)} IN ({names}),FALSE)' for n in pair]
def names_keep_sql(pair,alias='s'):
    a,b=name_hits(pair,alias);return f'NOT ({a} OR {b})'
def exact_keep_sql(*,name_columns=(),numeric_columns=(),author_ids=None,alias='s'):
    """Account or game filter. The caller must supply every relevant player role.

    Numeric-only callers require BOTH usernames resolved in the canonical
    namespace. A missing mapping can never silently become an empty exclusion.
    Game-ID-only consumers should anti-join the audited excluded-game index.
    """
    terms=[];names=','.join(lit(x) for x in AUTHORS)
    for n in name_columns:terms.append(f'coalesce({normalized(n,alias)} IN ({names}),FALSE)')
    if numeric_columns:
        if author_ids is None or set(author_ids)!=set(AUTHORS):
            raise RuntimeError('Numeric filtering requires both verified author ID mappings')
        ids=[int(author_ids[n]) for n in AUTHORS]
        if len(set(ids))!=2 or any(x<0 for x in ids):raise RuntimeError('Conflicting author ID mapping')
        for n in numeric_columns:terms.append(f'coalesce({ident(alias)}.{ident(n)} IN ({",".join(map(str,ids))}),FALSE)')
    if not terms:raise RuntimeError('No identity fields supplied')
    return 'NOT ('+' OR '.join(terms)+')'
def policy_sha():return hashlib.sha256((PACKAGE/'AUTHOR_EXCLUSION.json').read_bytes()).hexdigest()
