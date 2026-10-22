"""Stream frozen sample construction through bounded Parquet batches.

Same feature checks and row-level rules as phase_features.combine. The global
exposure stream is indexed once; no sample-dependent histories or spacing.
"""
from phase100_common import *
from phase_features import verify_original_features, all_known
import collections

BATCH_ROWS=131072

class RiskIndex:
    def __init__(self, events):
        ei=np.asarray(events['recipient_id'],np.int64)
        et=np.asarray(events['anchor_ms'],np.int64)
        es=np.asarray(events['archive_start_ms'],np.int64)
        if np.any(et<es):raise ValueError('Selected anchor precedes start')
        order=np.lexsort((et,ei));self.ei,self.et=ei[order],et[order]
        self.keys=audit.moments(self.ei,self.et)
        # Apply the same second stable ordering as prospective_risk.
        es=es[order];order=np.lexsort((es,self.ei))
        self.si,self.ss,self.st=self.ei[order],es[order],self.et[order]
        self.startkeys=audit.moments(self.si,self.ss)

    def query(self,d):
        i=np.asarray(d['recipient_id'],np.int64);start=np.asarray(d['archive_start_ms'],np.int64)
        n=len(i);qkeys=audit.moments(i,start);at=np.searchsorted(self.keys,qkeys,side='left');ix=at-1
        previous=np.full(n,-1,np.int64);tie=np.zeros(n,bool)
        if len(self.keys):
            good=(ix>=0)&(self.ei[np.clip(ix,0,len(self.ei)-1)]==i)
            previous[good]=self.et[ix[good]]
            tie=(at<len(self.keys))&(self.keys[np.minimum(at,len(self.keys)-1)]==qkeys)
        ix=np.searchsorted(self.startkeys,qkeys,side='left')-1;pending=np.zeros(n,bool)
        if len(self.si):
            safe=np.clip(ix,0,len(self.si)-1)
            pending=(ix>=0)&(self.si[safe]==i)&(self.st[safe]>=start)
        return dict(at_risk=(previous<0)|(start>previous+90*DAY),previous_selected_anchor=previous,
            anchor_tie=tie,earlier_started_not_yet_anchored=pending)


def process_batch(t,saved,risk_index,author_ids,new_cohort,write):
        d=arrays(t);old=d['previous_frame'].astype(bool)
        ix=num.lookup(saved['row_id'],d['row_id'][old])
        if np.any(ix<0):raise RuntimeError('Unknown original row ID during assembly')
        saved={k:v[ix] for k,v in saved.items()}
        pos=verify_original_features(d,saved)
        if np.any(d['matched_main'] & ~d['eligible_main']):raise RuntimeError('Main panel and recomputed adjacency disagree')
        risk=risk_index.query(d)
        if not np.array_equal(risk['at_risk'][old],saved['at_risk_90'][pos]):raise RuntimeError('Full-stream cooldown does not reproduce original comparison')
        d['at_risk_90']=risk['at_risk'];d['history_complete']=d['history_window_complete']
        d['complete90']=d['anchor_ms']+90*DAY<core.PANEL_END
        # Original rows use their authenticated frozen classification; new rows
        # use the explicit metadata classification saved during preparation.
        all_known(d,['ordinary_narrow']+ENTRY_COLUMNS)
        new=~d['previous_frame'].astype(bool)
        if not np.array_equal(d['ordinary_narrow'][new],np.isin(d['status'][new],list(core.NARROW))):
            raise RuntimeError('New ordinary-ending classification disagrees with metadata')
        all_known(d,['eligible_main','first_observed_pair','pre_games_30d']+COUNT_COLUMNS)
        design.validate_history(d,True)
        involved=authors.author_mask(d['recipient_id'],d['opponent_id'],author_ids)
        entry_keep,flow=design.entry_mask(d,90)
        entry_keep &= ~involved
        keep=entry_keep & d['ordinary_narrow'] & d['complete90']
        if np.any(d['y']&~d['reached']):raise RuntimeError('Kindness without reaching a choice')
        reached=d['reached'].astype(bool)
        if np.any(reached&((d['outcome_t']>d['anchor_ms']+90*DAY)|(d['outcome_t']<=d['anchor_ms'])|
            (d['outcome_start']<=d['anchor_ms'])|(d['outcome_opponent']==d['opponent_id'])|(d['outcome_gid']==d['game_id']))):
            raise RuntimeError('Invalid follow-up timing or opponent')
        # Preserve the joined Parquet schema and null bitmaps. Rebuilding the
        # table from NumPy arrays makes all-null legacy strings infer as null,
        # and nullable integer histories infer as floats in mixed/new batches.
        # These types must not depend on which rows happen to be in a batch.
        selected=t
        for name in ('at_risk_90','history_complete','complete90'):
            column=pa.array(d[name],type=pa.bool_())
            at=selected.schema.get_field_index(name)
            selected=(selected.set_column(at,name,column) if at>=0 else
                selected.append_column(name,column))
        # Save every assembled query with disposition; no incomplete window becomes a zero.
        feature_table=selected
        for name,values in [('analysis_eligible',keep),('entry_eligible',entry_keep),('author_game',involved)]:
            feature_table=feature_table.append_column(name,pa.array(values,type=pa.bool_()))
        # Observed flags are distinct from the complete-window outcome, even in
        # synthetic/diagnostic queries that include incomplete windows.
        for name in ('y','reached'):
            feature_table=feature_table.append_column('observed_'+name,selected[name])
            feature_table=feature_table.set_column(feature_table.schema.get_field_index(name),name,
                pa.array(d[name],mask=~d['complete90']))
        write('features',feature_table)
        selected=selected.select([k for k in selected.column_names if not k.startswith('original_')])
        for family,fmask in [('ordinary',keep),('entry',entry_keep)]:
            for label,cohort in [(new_cohort,~old),('old_author_clean',old),('pooled',np.ones(len(old),bool))]:
                mask=fmask & cohort
                sample=selected.filter(pa.array(mask,type=pa.bool_()))
                # Entry equations never use later-choice outcomes. Do not store incomplete outcomes as zeros.
                if family=='entry':
                    sample=sample.drop([k for k in ('y','reached','outcome_gid','outcome_t','outcome_start','outcome_opponent') if k in sample.column_names])
                name=family+'_'+label
                write(name,sample)
        flows=[]
        for label,mask in [(new_cohort,~old),('old_original',old)]:
            subset={k:v[mask] for k,v in d.items()};sm,sf=design.entry_mask(subset,90)
            flows += [dict(sample=label,**r) for r in sf]
            flows.append(dict(sample=label,step='entry_after_author_exclusion',rows=int((entry_keep&mask).sum())))
            flows.append(dict(sample=label,step='ordinary_complete90_after_author_exclusion',rows=int((keep&mask).sum())))
        return flows,int(old.sum()),int(involved.sum()),int(risk['earlier_started_not_yet_anchored'].sum())


def combine(queries,baseline,scorepaths,outcomepaths,chronpath,stream,author_ids,root,conf,memory,entrypath,new_cohort='new_phase100'):
    def build(tmp):
        c=io.conn(tmp/'spill',memory,1)
        try:
            for name,paths in [('q',[queries]),('scores',scorepaths),('o',outcomepaths),('x',[chronpath]),('e',[entrypath])]:
                c.execute('CREATE VIEW '+name+' AS SELECT * FROM '+io.parq(paths))
            query="""SELECT q.* EXCLUDE(pre_games_30d,eligible_main,first_observed_pair),
                CASE WHEN q.previous_frame THEN q.pre_games_30d ELSE x.pre_games_30d END AS pre_games_30d,
                CASE WHEN q.previous_frame THEN q.eligible_main ELSE x.eligible_main END AS eligible_main,
                CASE WHEN q.previous_frame THEN q.first_observed_pair ELSE x.first_observed_pair END AS first_observed_pair,
                scores.* EXCLUDE(row_id),o.* EXCLUDE(row_id),e.* EXCLUDE(row_id)
                FROM q JOIN scores USING(row_id) JOIN o USING(row_id) JOIN e USING(row_id) LEFT JOIN x USING(row_id)"""
            count=pq.ParquetFile(queries).metadata.num_rows;assert_rows(c,query,count,'Final feature join')
            b=io.parq([baseline])
            if c.execute('SELECT count(*) FROM (SELECT row_id FROM q WHERE previous_frame) q FULL JOIN '+b+' b USING(row_id) WHERE q.row_id IS NULL OR b.row_id IS NULL').fetchone()[0]:
                raise RuntimeError('Original assembly row set changed')
            io.copy(c,query+' ORDER BY q.row_id',tmp/'joined.parquet')
        finally:finish_connection(c,tmp/'spill')
        saved=arrays(io.read(baseline));risk=RiskIndex(arrays(io.read(stream,['recipient_id','anchor_ms','archive_start_ms'])))
        writers={};flow=collections.Counter();old_count=authors_count=pending_count=processed=0
        def write(name,table):
            if name not in writers:writers[name]=pq.ParquetWriter(tmp/(name+'.parquet'),table.schema,compression='zstd')
            if not table.schema.equals(writers[name].schema,check_metadata=False):
                raise RuntimeError('Typed assembly schema changed between batches: '+name)
            writers[name].write_table(table,row_group_size=BATCH_ROWS)
        try:
            for batch in pq.ParquetFile(tmp/'joined.parquet').iter_batches(batch_size=BATCH_ROWS,use_threads=False):
                rows,oc,ac,pc=process_batch(pa.Table.from_batches([batch]),saved,risk,author_ids,new_cohort,write)
                for row in rows:flow[(row['sample'],row['step'])]+=row['rows']
                old_count+=oc;authors_count+=ac;pending_count+=pc;processed+=len(batch)
            if processed!=count or old_count!=len(saved['row_id']):raise RuntimeError('Streamed assembly row accounting changed')
        finally:
            for writer in writers.values():writer.close()
        del saved,risk
        (tmp/'joined.parquet').unlink()
        groups={}
        for family in ('ordinary','entry'):
            for label in (new_cohort,'old_author_clean','pooled'):
                name=family+'_'+label;path=tmp/(name+'.parquet')
                cols=[k for k in ('row_id','recipient_id','received','y','reached','complete90','outcome_gid') if k in pq.ParquetFile(path).schema_arrow.names]
                groups[name]=stats.describe(arrays(io.read(path,cols)))
        flows=[dict(sample=sample,step=step,rows=n) for (sample,step),n in flow.items()]
        io.js(tmp/'flow.json',flows)
        return dict(sample_accounting=groups,original_features_reproduced=old_count,author_targets_excluded=authors_count,
            full_original_exposure_stream_preserved=True,earlier_started_unanchored=pending_count,
            assembly_batch_rows=BATCH_ROWS,assembly_method='bounded_Parquet_batches_same_frozen_rules',
            assembly_schema_policy='preserve_joined_Arrow_types_and_nulls_v1')
    return stable_stage(root,conf,build,[queries,baseline,chronpath,stream,entrypath]+scorepaths+outcomepaths)
