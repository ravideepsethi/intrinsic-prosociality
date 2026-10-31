"""Run the recovered, unchanged structural estimators on authenticated arena rows.

Source files are unchanged. Explicit adapters bind their panel paths and expected
row counts to the new arena build; no original all-source coefficient is used as
an arena validation target. Original authority checks remain in the input build.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import sys
import pandas as pd

from common import *

def invoke(module, argv):
    old=sys.argv
    try:
        sys.argv=[module.__file__,*map(str,argv)]
        return module.main()
    finally:
        sys.argv=old

def export_aggregates(source,dest,exclude_parts=()):
    source=Path(source);dest=Path(dest)
    for p in source.rglob('*'):
        rel=p.relative_to(source)
        if not p.is_file() or any(x in rel.parts for x in ('private_cache','receipts','_work',*exclude_parts)):
            continue
        if p.suffix not in ('.csv','.parquet','.pdf','.png'):
            continue
        if p.suffix in ('.csv','.parquet'):
            if p.suffix=='.csv': columns=pd.read_csv(p,nrows=0).columns
            else:
                import pyarrow.parquet as pq
                columns=pq.ParquetFile(p).schema_arrow.names
            forbidden={'chooser','chooser_id','chooser_user_id','username','username_norm','game_id','opponent','recipient'}
            require(not (forbidden & set(columns)), 'Private identifier in proposed public table: '+str(rel))
        target=dest/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(p,target)

def krd(run,memory,threads):
    run=Path(run);build=read_json(run/'private/BUILD.json')
    out=run/'private/legacy/krd'
    module=load_source('source/wave1/structural/rating_gap_krd_decomposition.py','arena_krd_source')
    module.ROOT=run;module.PANEL=run/'private/months'
    module.EXPECTED_ROWS=build['totals']['arena_nonadjacent'][0]
    if not (out/'settings.json').exists():
        # Preserve any failed attempt; K/RD producer itself is not resumable.
        if out.exists():
            out.rename(out.with_name('krd.incomplete.'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())))
        invoke(module,['--out-root',out,'--threads',threads,'--memory-limit',memory])
    saved=read_json(out/'settings.json')
    require(saved['authority']['rows']==build['totals']['arena_nonadjacent'][0], 'Wrong K/RD sample')
    con=database(':memory:',threads,memory,run/'private/work/krd')
    cache=out/'private_cache/rating_gap_krd_derived_private.parquet'
    n,error=con.execute(f'SELECT count(*),max(abs(draw_payoff-predicted_draw_payoff)) FROM {parquet(cache)}').fetchone()
    require(n==build['totals']['arena_nonadjacent'][0] and error<=1e-8,
            'K/RD cache lost rows or failed the mechanical payoff identity')
    con.close()
    renderer=load_source('source/wave1/structural/render_rating_gap_krd.py','arena_krd_renderer')
    invoke(renderer,['--out-root',out])
    export_aggregates(out,run/'public/rating_gap_krd')
    json_write(run/'public/rating_gap_krd/ARENA_LINEAGE.json',{'input_contract':build['contract'],
      'rows':n,'source_sha256':sha(module.__file__),'mechanical_identity_max_error':error,
      'interpretation':'Arena-only rating mechanics; tournament points and streak value are not included.'})

def nonparametric(run,memory,threads,workers):
    run=Path(run);build=read_json(run/'private/BUILD.json');out=run/'private/legacy/nonparametric'
    module=load_source('source/wave1/structural/rating_gap_nonparametric_closure_parallel.py',
                       'rating_gap_nonparametric_closure_parallel')
    module.ROOT=run;module.SOURCE_ROOT=run/'private/legacy/krd'
    module.SOURCE_SETTINGS=module.SOURCE_ROOT/'settings.json'
    module.SOURCE_CACHE=module.SOURCE_ROOT/'private_cache/rating_gap_krd_derived_private.parquet'
    module.EXPECTED_ROWS=build['totals']['arena_nonadjacent'][0]
    # Worker task inputs carry the new cache paths; they do not infer the source
    # panel from the unchanged module-level original-panel defaults.
    model_workers=min(workers,max(1,int((ram_gb()-6)//3)),10)
    invoke(module,['--out-root',out,'--prep-threads',threads,'--prep-memory-limit',memory,
                   '--model-workers',model_workers,'--worker-threads',1,'--worker-memory-limit','2GB'])
    renderer=load_source('source/wave1/structural/render_rating_gap_nonparametric_closure.py','arena_nonparam_renderer')
    invoke(renderer,['--out-root',out])
    export_aggregates(out,run/'public/rating_gap_nonparametric')
    json_write(run/'public/rating_gap_nonparametric/ARENA_LINEAGE.json',{'input_contract':build['contract'],
      'rows':build['totals']['arena_nonadjacent'][0],'source_sha256':sha(module.__file__),
      'source_settings_sha256':sha(module.SOURCE_SETTINGS),
      'scope':'Same gap/K20/K50/stable-account/year/common-support specifications as pool Wave 1, re-estimated on arena.'})

def controlled(run,memory,threads):
    run=Path(run);build=read_json(run/'private/BUILD.json')
    out=run/'private/legacy/controlled';cache=run/'private/controlled_cache'
    engine=load_source('source/wave1/controlled/reference_price_model_v110.py','reference_price_model_v110')
    args=['--panel',run/'private/months','--out',out,'--private',cache,
          '--threads',threads,'--memory',memory,'--batch-rows',32768]
    if out.exists() or cache.exists():args+=['--resume']
    if not (out/'receipts/completion_receipt.json').exists():invoke(engine,args)
    renderer=load_source('source/wave1/controlled/controlled_reference_price_figure.py','arena_controlled_renderer')
    receipt=read_json(out/'receipts/completion_receipt.json')
    def arena_source_validation(source,allow_synthetic):
        hashes=renderer.verify_manifest(source)
        required=['receipts/completion_receipt.json','tables/controlled_reference_price_bins.csv',
                  'tables/controlled_local_h1_coefficients.csv','tables/source_month_inventory.csv',
                  'tables/source_identity_checks.csv']
        require(set(required)<=set(hashes),'Controlled payoff result is missing manifest-covered outputs')
        require(receipt['status']=='CONTROLLED_REFERENCE_PRICE_FIGURE_COMPLETE' and receipt['version']=='1.1.0',
                'Wrong controlled-payoff engine result')
        require(not receipt.get('synthetic_smoke_test'),'Synthetic input cannot become an arena result')
        require(receipt['code_sha256']==sha(engine.__file__),'Controlled payoff engine hash changed')
        require(Path(receipt['panel']).resolve()==(run/'private/months').resolve(),'Wrong payoff panel')
        inventory=pd.read_csv(source/'tables/source_month_inventory.csv')
        identity=pd.read_csv(source/'tables/source_identity_checks.csv').iloc[0]
        expected=build['totals']['arena_nonadjacent']
        require(len(inventory)==24 and int(inventory.n.sum())==expected[0] and int(inventory.kind.sum())==expected[1],
                'Controlled payoff source margins differ from arena')
        require(int(identity['n'])==int(identity['distinct_games'])==expected[0],'Controlled payoff game IDs changed')
        return receipt,hashes
    renderer.validate_source=arena_source_validation
    fig=run/'private/legacy/controlled_figure'
    scratch=run/'private/work/controlled_renderer'
    # Completion includes the renderer manifest, written after its receipt.
    figure_complete=(fig/'OUTPUT_MANIFEST.sha256').is_file()
    if not figure_complete:
        suffix='.incomplete.'+str(time.time_ns())
        for item in (fig,scratch,Path(str(fig)+'.zip'),Path(str(fig)+'.zip.sha256')):
            if item.exists():item.rename(item.with_name(item.name+suffix))
    else:
        renderer.verify_manifest(fig)
        fixed=read_json(fig/'receipts/completion_receipt.json')
        require(fixed['status']=='CONTROLLED_REFERENCE_PRICE_FIX_COMPLETE'
                and not fixed['synthetic_validation'],'Wrong arena figure completion')
        require(fixed['source_manifest_sha256']==sha(out/'OUTPUT_MANIFEST.sha256'),
                'Existing arena figure belongs to a different source')
    if not fig.exists():
        invoke(renderer,['--source-run',out,'--source-private',cache,'--out',fig,
                         '--scratch',scratch,'--threads',threads,
                         '--memory',memory,'--batch-rows',32768])
    # Publish only the corrected figure; the model engine's older local display
    # mixes adjustment samples and remains private for provenance.
    export_aggregates(out,run/'public/controlled_payoff/model',exclude_parts=('figures',))
    export_aggregates(fig,run/'public/controlled_payoff/figure')
    json_write(run/'public/controlled_payoff/ARENA_LINEAGE.json',{'input_contract':build['contract'],
      'rows':build['totals']['arena_nonadjacent'][0],'engine_sha256':sha(engine.__file__),
      'renderer_sha256':sha(renderer.__file__),'old_full_panel_numeric_bridge_requested':False,
      'interpretation':'Conditional rating-payoff diagnostic; it does not measure the full cost of an arena draw.'})
