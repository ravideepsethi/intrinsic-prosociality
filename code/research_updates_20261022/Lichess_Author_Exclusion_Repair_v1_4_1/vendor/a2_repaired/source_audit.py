"""Bounded file-name/footer inventory. Never reads game rows or invokes recovery."""
from common import *
import re
PATTERN=re.compile(r'hourly_rated_games|history|chronology|title|arena|tournament|rating.*peak|personal.*best|retiming',re.I)
def audit(project):
    found=[];visited=0;truncated=False
    roots=[project/'derived/replication',project/'output']
    for root in roots:
        if not root.is_dir():continue
        for base,dirs,files in os.walk(root):
            visited+=1
            dirs[:]=[n for n in sorted(dirs) if not n.startswith('.') and n not in
                     {'api_payloads','game_responses','engine','replay','spill','node_modules','site-packages','panel','buckets','parts'}]
            if len(Path(base).relative_to(root).parts)>=6:dirs[:]=[]
            per_directory=0
            for name in sorted(files):
                if not name.endswith('.parquet') or not PATTERN.search(str(Path(base).relative_to(root)/name)):continue
                p=Path(base)/name;r=dict(path=str(p),bytes=p.stat().st_size)
                try:
                    pf=pq.ParquetFile(p);r.update(rows=pf.metadata.num_rows,columns=pf.schema_arrow.names)
                except Exception as e:r['error_type']=type(e).__name__
                found.append(r);per_directory+=1
                if per_directory>=3:break
                if len(found)>=200:truncated=True;break
            if len(found)>=200 or visited>=5000:truncated=True;break
        if truncated:break
    # Three representative footers from the explicitly named all-game authority.
    chrono=project/'derived/glicko2_replay/rating_events_replay_sorted_v2_time/events_replay_sorted_time'
    known=[]
    for month in ['2023-10','2025-10','2025-11']:
        paths=sorted(chrono.glob('speed=*/month='+month+'/part-*.parquet'))[:3] if chrono.is_dir() else []
        for p in paths:
            pf=pq.ParquetFile(p);known.append(dict(path=str(p),bytes=p.stat().st_size,rows=pf.metadata.num_rows,columns=pf.schema_arrow.names))
    manifest=project/'output/dynamic_prosociality_a3_chronology_gate_v100/20260821T234626Z/chronology_input_manifest.tsv'
    return dict(status='METADATA_INVENTORY_ONLY',visited_directories=visited,truncated=truncated,candidates=found,
                named_chronology_footers=known,named_manifest_exists=manifest.is_file(),
                named_manifest_sha256=sha(manifest) if manifest.is_file() else None,
                chronology_warning='Result-code semantics and membership coverage must be reconciled to the corrected producer before reuse. No 7.76-billion-row scan was started.',
                next_gates={
                  'A3':'Need historical scoring rules, tournament IDs, complete tournament player sequence, scored draw streak and actual tournament end; no inferred arena price.',
                  'B1':'No title columns in certified panel. Need game-time PGN titles; current API titles are a different measurement.',
                  'A4':'Align timeout numerator and rated-game denominator to the same time convention and source coverage.',
                  'A5_A8_B3':'Build one shared completed-game/session/prefix-history producer after source schemas and lineage are verified.'})
