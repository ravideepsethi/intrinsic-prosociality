"""Original arena/pool model, filtered in both account roles before eligibility."""
from remaining_common import *

def run_stage(args,auth,out):
    vendor=ROOT/'vendor/arena';sys.path.insert(0,str(vendor))
    import common as ac,analysis as an
    candidates=[]
    for success in (args.project/'output/arena_replication_v102').glob('*/_SUCCESS.json'):
        if read(success).get('status')=='ARENA_REPLICATION_WAVE1_COMPLETE':candidates.append(success)
    success=unique_path(candidates,'Completed arena replication');old=success.parent
    b=read(old/'private/BUILD.json');contract=b['contract']
    require(read(success)['input_contract']==contract,'Arena success/build differ')
    stage=read(old/'private/stages/suppression.json')
    require(stage['contract']==contract,'Arena model/build differ')
    for r in stage['files']:
        p=old/'public'/r['path'];require(p.stat().st_size==r['bytes'] and sha(p)==r['sha256'],'Arena aggregate changed')
    require(len(b['panel_paths'])==len(b['narrow_paths'])==24,'Incomplete arena month inventory')
    narrow=[];flows=[]
    c=db(out/'PRIVATE/spill',args.memory_gb-2,args.workers)
    try:
        for broad,small in zip(b['panel_paths'],b['narrow_paths']):
            broad,small=Path(broad),Path(small)
            require(broad.parent==small.parent and ac.verify_complete(broad.parent,contract),'Unsealed arena input')
            # Arena games need a separate exclusion set: the 42-game main-pool
            # set is not a complete account filter outside the main sample.
            pair=names_pair(broad)
            c.execute('CREATE OR REPLACE TEMP TABLE arena_author_games AS SELECT DISTINCT game_id FROM '+scan(broad)+' s WHERE '+author_sql(pair))
            before=pq.ParquetFile(small).metadata.num_rows
            target=out/'PRIVATE/panels'/(broad.parent.name+'.parquet')
            query='SELECT s.* FROM '+scan(small)+' s'
            if args.variant=='excluded':query+=' ANTI JOIN arena_author_games USING(game_id)'
            after=copy(c,query,target);narrow.append(str(target))
            flows.append(dict(month=broad.parent.name,before=before,after=after,removed=before-after))
    finally:c.close()
    new=dict(b,narrow_paths=narrow,contract=digest([contract,auth['fingerprint'],sha(__file__)]))
    write(out/'private/BUILD.json',new)
    # Only the combined competitive/worse comparison is retained in the current
    # manuscript. Its dual-format eligibility is recomputed after exclusion.
    con,_=an.open_data(out,f'{args.memory_gb-2}GB',args.workers)
    try:
        frame=an.load_frame(con,'eval>=-100 OR eval<=-300')
        frame['arena_fair']=frame.arena*frame.fair
        result=an.model_save(out/'report','arena_by_board_merit',frame,['arena','arena_fair'],an.CONTROLS,an.FULL_FE,new['contract'],'Original current-manuscript arena interaction model')
        require(result['status']=='ESTIMATED','Arena model failed')
        contrasts={name:an.linear_contrast(result,weights) for name,weights in [('competitive',{'arena':1,'arena_fair':1}),('clearly_worse',{'arena':1}),('difference_between_board_regions',{'arena_fair':1})]}
        table(out/'report/coefficients',result['coefficients'])
        table(out/'report/contrasts',[dict(contrast=name,**r) for name,r in contrasts.items()])
        table(out/'report/sample_rates',[dict(source=name,**r) for name,r in result['sample_rates'].items() if isinstance(r,dict)])
        if args.variant=='included':
            expected=read(old/'public/suppression/arena_by_board_merit.json')
            require(result['n']==expected['n'] and result['clusters']==expected['clusters'],'Arena sample does not reproduce')
            for got,ref in zip(result['coefficients'],expected['coefficients']):
                require(got['term']==ref['term'],'Arena coefficient ordering differs')
                for col in ('estimate_pp','se_pp'):
                    if col in got:require(np.isclose(got[col],ref[col],rtol=2e-7,atol=2e-8),'Arena baseline coefficient does not reproduce: '+col)
    finally:con.close()
    table(out/'report/exclusion_flow',flows)
    return dict(status='ARENA_GRADIENT_REFITTED',models=1,both_roles_filtered=True,dual_format_eligibility_rebuilt=True)
