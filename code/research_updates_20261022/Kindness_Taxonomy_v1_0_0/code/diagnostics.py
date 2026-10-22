from common import *
import datetime as dt

def rate_table(c,path,groups,where='TRUE',source='panel'):
    export(c,path,f'''WITH a AS (SELECT {groups},chooser,count(*)::DOUBLE n,sum(y)::DOUBLE g
      FROM {source} WHERE {where} GROUP BY ALL), t AS(SELECT {groups},sum(n) n,sum(g) g,count(*) accounts,
       sum(g*g) gg,sum(g*n) gn,sum(n*n) nn FROM a GROUP BY ALL)
      SELECT {groups},n opportunities,g grants,accounts,100*g/n rate_pct,
       CASE WHEN accounts>1 AND gg-2*(g/n)*gn+pow(g/n,2)*nn>=-1e-10
         THEN 100*sqrt(greatest(0,gg-2*(g/n)*gn+pow(g/n,2)*nn)*accounts/(accounts-1))/n END cluster_se_pp
      FROM t ORDER BY ALL''')

def correlations(n,g,weights=None):
    p=g/n;w=np.ones(len(p)) if weights is None else np.asarray(weights,float);w=w/w.sum()
    m=w@p;a=p-m;v=np.sum(w[:,None]*a*a,axis=0)
    if v.min()<=0:return None
    return float(np.sum(w*a[:,0]*a[:,1])/np.sqrt(v.prod()))

def persistence(c,folder,cfg):
    out=[]
    for region,condition in [('lost','state=0'),('competitive','state>=2')]:
        c.execute(f'''CREATE OR REPLACE TEMP TABLE pers AS SELECT chooser,
          count(*) FILTER(WHERE year=1)::DOUBLE n1,count(*) FILTER(WHERE year=2)::DOUBLE n2,
          coalesce(sum(y) FILTER(WHERE year=1),0)::DOUBLE g1,coalesce(sum(y) FILTER(WHERE year=2),0)::DOUBLE g2
          FROM panel WHERE {condition} GROUP BY chooser''')
        for minimum in (1,5,20):
            d=arrays(c.execute(f'SELECT * FROM pers WHERE n1>={minimum} AND n2>={minimum} AND n1+n2>=4 ORDER BY chooser').to_arrow_table())
            if len(d['chooser'])<3:
                out.append(dict(region=region,minimum_each_year=minimum,status='INSUFFICIENT_ACCOUNTS'));continue
            n=np.column_stack([d['n1'],d['n2']]);g=np.column_stack([d['g1'],d['g2']]);w=n.prod(axis=1)/n.sum(axis=1)
            raw=correlations(n,g);weighted=correlations(n,g,w);rng=np.random.default_rng(cfg['seed']+minimum+(region=='lost')*100)
            draws=[]
            for b in range(cfg['bootstrap_reps']):
                ix=rng.integers(0,len(n),len(n));v=correlations(n[ix],g[ix])
                if v is not None:draws.append(v)
            lo,hi=np.quantile(draws,[.025,.975]) if draws else (None,None)
            out.append(dict(region=region,minimum_each_year=minimum,minimum_total=4,accounts=len(n),opportunities_y1=n[:,0].sum(),opportunities_y2=n[:,1].sum(),
              grants_y1=g[:,0].sum(),grants_y2=g[:,1].sum(),raw_correlation=raw,harmonic_weighted_correlation=weighted,
              bootstrap_low=lo,bootstrap_high=hi,valid_bootstraps=len(draws),bootstrap_requested=cfg['bootstrap_reps'],
              status='ESTIMATED' if raw is not None else 'ZERO_VARIANCE',interpretation='Rare-event sampling noise attenuates raw correlations; no automatic apathy/noise classification'))
    csvwrite(folder/'E1_persistence.csv',out)

def early(c,folder,cfg):
    persistence(c,folder,cfg)
    c.execute('''CREATE OR REPLACE TEMP VIEW clocks AS SELECT *,CASE WHEN clock IS NULL OR NOT isfinite(clock) OR clock<0 THEN 'missing'
      WHEN clock<10 THEN '00_under10' WHEN clock<30 THEN '01_10to29' WHEN clock<60 THEN '02_30to59'
      WHEN clock<120 THEN '03_60to119' ELSE '04_120plus' END clock_bin FROM panel''')
    rate_table(c,folder/'E2_lost_speed_clock.csv','year,speed,clock_bin','state=0','clocks')
    c.execute('''CREATE OR REPLACE TEMP VIEW e3 AS SELECT p.* FROM panel p SEMI JOIN
      (SELECT chooser FROM panel WHERE year=1 AND state=0 GROUP BY chooser HAVING sum(y)>=2) a USING(chooser)''')
    rate_table(c,folder/'E3_year1_selected_profiles.csv','year,state',source='e3')
    rate_table(c,folder/'G1_year_state.csv','year,state')
    rate_table(c,folder/'G1_year_speed_state.csv','year,speed,state')
    rate_table(c,folder/'G1_year_stage_state.csv','year,stage,state')
    export(c,folder/'G1_year_totals.csv','''SELECT year,count(*) opportunities,sum(y) grants,100*avg(y) grant_pct,
      count(DISTINCT chooser) choosers,count(DISTINCT CASE WHEN y=1 THEN chooser END) ever_granters,
      count(*) FILTER(WHERE state>=2) competitive_opportunities,sum(y) FILTER(WHERE state>=2) competitive_grants,
      count(*) FILTER(WHERE state=0) lost_opportunities,sum(y) FILTER(WHERE state=0) lost_grants FROM panel GROUP BY year''')
    write(folder/'interpretation.json',dict(E1='Persistence is behavioral repeatability. A low raw correlation with rare outcomes does not establish noise.',
      E2='Speed and clock concentration does not observe misclicks. Missing clocks have their own denominator.',
      E3='Account selection uses year-1 lost grants only; year-2 shapes are the validation result. Selection does not force a flat profile.',
      G1='Descriptive main-panel headlines only. Existing structural/Patron/receipt headlines have distinct estimands and are not silently replaced.'))

def ratio_contrast(data,coeff):
    """Joint account-cluster delta covariance for contrasts of cell ratios."""
    if not len(data):return dict(status='NO_SUPPORT')
    ids=np.array([r[0] for r in data],dtype=np.int64);cell=np.array([r[1] for r in data],int)
    n=np.array([r[2] for r in data],float);y=np.array([r[3] for r in data],float)
    nn=np.bincount(cell,weights=n,minlength=len(coeff));yy=np.bincount(cell,weights=y,minlength=len(coeff))
    if (nn==0).any():return dict(status='EMPTY_COMPARISON_CELL')
    rates=yy/nn;w=np.asarray(coeff);score=w[cell]*(y-rates[cell]*n)/nn[cell]
    _,a=np.unique(ids,return_inverse=True);s=np.bincount(a,weights=score);G=len(s)
    se=np.sqrt((s@s)*G/(G-1)) if G>1 else np.nan
    return dict(status='ESTIMATED',accounts=G,cell_n=nn.tolist(),**interval(100*(w@rates),100*se))

def rule_change(c,folder,cfg):
    # The observed event time is a repository merge proxy, not a certified deployment.
    cutoff=int(dt.datetime.fromisoformat(cfg['rule_proxy_date']).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    c.execute(f'''CREATE OR REPLACE TEMP VIEW rule_rows AS SELECT *,floor((start_ms-{cutoff})/{7*DAY}.)::INT AS "week",
       CASE WHEN speed IN('bullet','ultrabullet') THEN 'bullet' ELSE speed END speed_group
       FROM panel WHERE start_ms>={cutoff-56*DAY} AND start_ms<{cutoff+56*DAY}''')
    rate_table(c,folder/'G2_weekly_state_rates.csv','week,speed_group,state',source='rule_rows')
    export(c,folder/'G2_composition.csv','''SELECT week,speed_group,state,count(*) opportunities,
      avg(ply) mean_ply,avg(rating) mean_rating,avg(rival_rating-rating) mean_rating_gap,
      avg(cost) mean_cost,avg(clock) mean_clock,avg(rival_clock) mean_rival_clock,
      count(clock) clock_observed FROM rule_rows GROUP BY ALL ORDER BY ALL''')
    c.execute('''CREATE OR REPLACE TEMP TABLE rw AS SELECT chooser,state,speed_group,week,count(*)::DOUBLE n,sum(y)::DOUBLE y
      FROM rule_rows GROUP BY ALL''')
    contrasts=[]
    for s in range(5):
        for speed in ('blitz','rapid','classical'):
            for week in range(-8,8):
                if week==-1:continue
                query=f'''SELECT chooser,((speed_group={q(speed)})::INT*2+(week={week})::INT) cell,n,y FROM rw
                  WHERE state={s} AND speed_group IN('bullet',{q(speed)}) AND week IN(-1,{week})'''
                rr=ratio_contrast(c.execute(query).fetchall(),[1,-1,-1,1])
                contrasts.append(dict(state=s,speed=speed,week=week,reference_week=-1,comparison='relative to bullet',**rr))
    csvwrite(folder/'G2_relative_event_study.csv',contrasts)
    did=[]
    for shift in cfg['rule_date_sensitivity_days']:
        t=cutoff+shift*DAY
        for s in range(5):
            for speed in ('blitz','rapid','classical'):
                query=f'''SELECT chooser,((CASE WHEN speed IN('bullet','ultrabullet') THEN 'bullet' ELSE speed END={q(speed)})::INT*2+
                   (start_ms>={t})::INT) cell,count(*)::DOUBLE n,sum(y)::DOUBLE y FROM panel
                   WHERE state={s} AND speed IN('bullet','ultrabullet',{q(speed)}) AND start_ms>={t-56*DAY} AND start_ms<{t+56*DAY}
                   GROUP BY ALL'''
                did.append(dict(state=s,speed=speed,cutoff_shift_days=shift,**ratio_contrast(c.execute(query).fetchall(),[1,-1,-1,1])))
    csvwrite(folder/'E4_relative_pre_post.csv',did)
    write(folder/'rule_evidence.json',dict(merge_utc=cfg['rule_merge_utc'],live_deployment_verified=False,
      before_s=dict(bullet=40,blitz=40,rapid=80,classical=120),after_s=dict(bullet=30,blitz=60,rapid=120,classical=300),
      files_changed=['modules/round/src/main/RoundSocket.scala'],button_layout_change_in_PR=False,
      interpretation='All speed categories changed. Bullet is a relative comparator, not untreated. Merge-date proxy, selection and composition prevent an automatic causal interpretation.'))
