"""Conservation checks and a small, materialized focal-feature join."""
from util import *

FEATURES=['prior_same_speed','tie_n','prev_t','prev_gid','prev_result','prev_tie']+[
    str(n)+str(g) for g in (15,30,60) for n in ('pos','cens')]


class Checks:
    def __init__(self,c,run,month,out):
        self.c=c;self.run=Path(run);self.month=month;self.out=Path(out)
        self.report=dict(month=month,stages=[],status='IN_PROGRESS',
            rule='Same exact chooser/game/time/speed identity; no rows repaired, synthesized, or dropped.')
        self.expected=None;self.focal=month in MONTHS
        if self.focal:
            c.execute('CREATE TEMP TABLE focal_index AS SELECT game_id,chooser,t,ordinal,speed_code FROM '+
                scan(self.run/'PRIVATE/focal'/month/'rows.parquet'))
            self.n=c.execute('SELECT count(*) FROM focal_index').fetchone()[0]
            require(c.execute('SELECT count(DISTINCT game_id) FROM focal_index').fetchone()[0]==self.n,
                'Duplicate focal game in month')
            missing=c.execute('SELECT count(*) FROM focal_index f ANTI JOIN needed n USING(chooser)').fetchone()[0]
            self.report['focal_rows']=self.n;self.report['focal_choosers_missing_from_needed']=missing
            self.write();require(missing==0,'Focal chooser missing from needed set; see history_integrity report')

    def write(self):js(self.run/'report/history_integrity'/f'{self.month}.json',self.report)

    def raw(self):
        c=self.c
        count=c.execute('SELECT count(*) FROM raw').fetchone()[0]
        expected=c.execute('''SELECT
            (SELECT count(*) FROM raw r SEMI JOIN needed n ON r.white_id=n.chooser)+
            (SELECT count(*) FROM raw r SEMI JOIN needed n ON r.black_id=n.chooser)''').fetchone()[0]
        self.report.update(filtered_raw_games=count,expected_player_events=expected)
        if self.focal:
            c.execute('''CREATE TEMP TABLE raw_focal_candidates AS SELECT r.* FROM raw r
                SEMI JOIN focal_index f ON r.game_id=f.game_id''')
            c.execute('''CREATE TEMP TABLE raw_focal_matches AS SELECT f.game_id,f.chooser,r.t,r.speed_code
                FROM focal_index f JOIN raw_focal_candidates r ON f.game_id=r.game_id
                AND f.chooser IN(r.white_id,r.black_id)''')
            self._identity('raw_focal_matches','filtered_raw')
            c.execute('DROP TABLE raw_focal_matches');c.execute('DROP TABLE raw_focal_candidates')
        self.write()

    def stage(self,name):
        # These two checksums are diagnostics of accidental identity changes, not
        # a cryptographic substitute for source and output hashes.
        row=self.c.execute(f'''SELECT count(*),bit_xor(hash(chooser,game_id,t,ordinal,speed_code)),
            sum(hash(game_id,chooser,ordinal,t,speed_code)::HUGEINT) FROM {name}''').fetchone()
        got=[int(x or 0) for x in row]
        self.report['stages'].append(dict(stage=name,rows=got[0],xor_identity_checksum=str(got[1]),sum_identity_checksum=str(got[2])))
        if self.expected is None:
            require(got[0]==self.report['expected_player_events'],'Player-event count mismatch')
            self.expected=got
        self.write()
        if got!=self.expected:
            self.report['status']='BLOCKED_STAGE_IDENTITY_CONSERVATION';self.write()
            raise RuntimeError('History identity changed at '+name+'; see history_integrity report')

    def _identity(self,table,label):
        c=self.c
        row=c.execute(f'''SELECT count(*),count(*) FILTER(WHERE a.game_id IS NULL),
            count(*) FILTER(WHERE f.t IS DISTINCT FROM a.t OR f.speed_code IS DISTINCT FROM a.speed_code)
            FROM focal_index f LEFT JOIN {table} a USING(chooser,game_id)''').fetchone()
        checks=[int(x) for x in row]
        self.report[label+'_identity_check']=checks;self.write()
        if tuple(row)!=(self.n,0,0):
            copy(c,f'''SELECT f.* FROM focal_index f LEFT JOIN {table} a USING(chooser,game_id)
                WHERE a.game_id IS NULL OR f.t IS DISTINCT FROM a.t OR f.speed_code IS DISTINCT FROM a.speed_code''',
                self.out/'PRIVATE_GATE'/f'{label}_bad_keys.parquet')
            self.report['status']='BLOCKED_FOCAL_IDENTITY';self.write()
            raise RuntimeError('Focal identity failed at '+label+'; see history_integrity report')

    def features(self):
        if not self.focal:return
        c=self.c
        # First reduce the large relation to focal game keys, then materialize the
        # chooser-side features. The validation join now uses two small tables.
        c.execute('''CREATE TEMP TABLE focal_candidates AS SELECT a.* FROM annotated a
            SEMI JOIN focal_index f ON a.game_id=f.game_id''')
        c.execute('''CREATE TEMP TABLE focal_features AS SELECT a.game_id,a.chooser,a.t,a.speed_code,'''+
            ','.join('a.'+x for x in FEATURES)+''' FROM focal_candidates a
            JOIN focal_index f ON a.game_id=f.game_id AND a.chooser=f.chooser''')
        c.execute('DROP TABLE focal_candidates')
        self._identity('focal_features','annotated_compact')

    def written(self,path):
        c=self.c
        # Audit the actual Parquet round trip, including all original focal columns.
        columns=pq.ParquetFile(self.run/'PRIVATE/focal'/self.month/'rows.parquet').schema_arrow.names
        select=','.join('"'+x.replace('"','""')+'"' for x in columns)
        one='SELECT '+select+' FROM focal'
        two='SELECT '+select+' FROM '+scan(path)
        difference=c.execute('SELECT count(*) FROM (('+one+' EXCEPT ALL '+two+') UNION ALL ('+
            two+' EXCEPT ALL '+one+'))').fetchone()[0]
        self.report['written_original_focal_multiset_differences']=difference;self.write()
        require(difference==0,'Written focal Parquet differs from frozen focal sample')

    def finish(self):
        self.report['status']='PASS';self.write()
