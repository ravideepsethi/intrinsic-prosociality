"""Joint-covariance contrasts, Holm families, and standardized rates."""
from common import *
from design import COLS,POSITIONS,STAGES,SPEEDS,specification
from scipy.special import ndtr
from scipy.stats import chi2

class Scalar:
    def __init__(self,value,gradient):self.v=float(value);self.g=np.asarray(gradient,float)
    def cast(self,x):return x if isinstance(x,Scalar) else Scalar(x,np.zeros_like(self.g))
    def __add__(self,x):x=self.cast(x);return Scalar(self.v+x.v,self.g+x.g)
    __radd__=__add__
    def __neg__(self):return Scalar(-self.v,-self.g)
    def __sub__(self,x):return self+-self.cast(x)
    def __rsub__(self,x):return self.cast(x)+-self
    def __mul__(self,x):x=self.cast(x);return Scalar(self.v*x.v,self.g*x.v+x.g*self.v)
    __rmul__=__mul__
    def __truediv__(self,x):
        x=self.cast(x)
        if abs(x.v)<1e-15:raise ZeroDivisionError('Zero denominator in requested contrast')
        return Scalar(self.v/x.v,(self.g*x.v-x.g*self.v)/(x.v*x.v))

class Model:
    def __init__(self,col,fit,cov):
        self.col=col;self.f=fit['fits'][col];self.k=len(self.f['names']);self.cov=cov
        self.names=self.f['names']+fit['moment_names'];values=np.r_[self.f['beta'],fit['mean_m']]
        eye=np.eye(len(values));self.vars={n:Scalar(values[i],eye[i]) for i,n in enumerate(self.names)}
        self.zero=Scalar(0,np.zeros(len(values)))
    def b(self,name):return self.vars[name]
    def pos(self,k):return self.b('position_'+POSITIONS[k]) if k else self.zero
    def stage(self,k,group=None):
        if k==0:return self.zero
        s='stage_'+STAGES[k];r=self.b(s)
        if self.col=='column3':
            w=self.b('share_competitive') if group is None else (1 if group=='competitive' else 0)
            r+=w*self.b(s+':competitive')
        if self.col=='column4':
            if group is None:
                for speed in SPEEDS[1:]:r+=self.b('share_speed_'+speed)*self.b(s+':'+speed)
            elif group!='ultrabullet':r+=self.b(s+':'+group)
        return r
    def rate(self,kind,k):
        r=self.b('mean_y')+(self.pos(k) if kind=='position' else self.stage(k))
        labels=POSITIONS if kind=='position' else STAGES
        for j in range(1,len(labels)):
            r-=self.b('share_'+kind+'_'+labels[j])*(self.pos(j) if kind=='position' else self.stage(j))
        return r
    def baseline(self,group):return self.b('baseline_y_'+group)/self.b('baseline_n_'+group)
    def fast(self,k):
        bullet=self.b('share_speed_bullet');ultra=1-sum(self.b('share_speed_'+s) for s in SPEEDS[1:])
        return (ultra*self.stage(k,'ultrabullet')+bullet*self.stage(k,'bullet'))/(ultra+bullet)
    def estimable(self,grad):
        z=grad[:self.k]/self.f['scale'];null=self.f['null']
        return np.linalg.norm(null.T@z)<=1e-7*max(np.linalg.norm(z),1e-10)
    def row(self,panel,name,value,group='',family='',unit='percentage_points'):
        row=dict(column=self.col,panel=panel,group=group,contrast=name,unit=unit,holm_family=family)
        if not self.estimable(value.g):return dict(row,status='NOT_ESTIMABLE',estimate=None,se=None,p_value=None,ci_low=None,ci_high=None)
        var=float(value.g@self.cov@value.g)
        require(var>=-1e-10,'Negative contrast variance')
        se=np.sqrt(max(var,0));p=2*ndtr(-abs(value.v/se)) if se>1e-14 else (1. if abs(value.v)<1e-12 else 0.)
        return dict(row,status='ESTIMATED',estimate=value.v,se=float(se),p_value=float(p),ci_low=float(value.v-1.959963984540054*se),ci_high=float(value.v+1.959963984540054*se))

def holm(rows):
    families={}
    for i,r in enumerate(rows):
        if r['holm_family']:families.setdefault(r['holm_family'],[]).append(i)
    for indices in families.values():
        ordered=sorted(indices,key=lambda i:rows[i]['p_value'] if rows[i]['p_value'] is not None else 1.)
        previous=0.
        for rank,i in enumerate(ordered):
            p=rows[i]['p_value'] if rows[i]['p_value'] is not None else 1.
            previous=max(previous,min(1.,p*(len(indices)-rank)));rows[i]['p_holm']=previous
            rows[i]['holm_family_size']=len(indices)
    return rows

def joint(model,values,name):
    if not all(model.estimable(v.g) for v in values):return dict(column=model.col,test=name,status='NOT_ESTIMABLE')
    v=np.array([x.v for x in values]);J=np.stack([x.g for x in values]);V=J@model.cov@J.T
    vals,vec=np.linalg.eigh((V+V.T)/2);tol=max(1e-12,vals.max()*1e-9);good=vals>tol
    if not good.any():return dict(column=model.col,test=name,status='NO_VARIANCE')
    stat=float(np.sum((vec[:,good].T@v)**2/vals[good]));df=int(good.sum())
    return dict(column=model.col,test=name,status='ESTIMATED',wald_chi2=stat,df=df,p_value=float(chi2.sf(stat,df)))

def make_rows(fit,covs):
    rows=[];coef=[];profiles=[];rates=[];joints=[];models={}
    for col in COLS:
        m=models[col]=Model(col,fit,covs[col])
        for name in m.f['names']:coef.append(m.row('coefficients',name,m.b(name)))
        for k in [4,3,2,1]:rows.append(m.row('A',POSITIONS[k]+' minus clearly_worse',m.pos(k),family=col+'_A_7'))
        for high,low in [(4,3),(3,2),(2,1)]:rows.append(m.row('A',POSITIONS[high]+' minus '+POSITIONS[low],m.pos(high)-m.pos(low),family=col+'_A_7'))
        for k in range(1,8):rows.append(m.row('B',STAGES[k]+' minus 0_4',m.stage(k),group='full_sample_standardized',family=col+'_B_13'))
        for k in range(2,8):rows.append(m.row('B',STAGES[k]+' minus '+STAGES[k-1],m.stage(k)-m.stage(k-1),group='full_sample_standardized',family=col+'_B_13'))
    m=models['column3']
    rebounds={}
    for region in ['competitive','noncompetitive']:
        for k in range(8):profiles.append(m.row('stage_profile',STAGES[k]+' minus 0_4',m.stage(k,region),group=region))
        decline=m.stage(6,region);rebounds[region]=m.stage(7,region)-m.stage(6,region)
        rows.append(m.row('C','81_plus minus 41_80',rebounds[region],group=region))
        rows.append(m.row('C','41_80 minus 0_4',decline,group=region))
        try:
            base=m.baseline(region)
            rows.append(m.row('C','raw 0_4 grant rate',base,group=region,unit='percent'))
            rows.append(m.row('C','signed change / raw 0_4 rate',decline/base,group=region,unit='ratio'))
            rows.append(m.row('C','decline as percent of raw 0_4 rate',-100*decline/base,group=region,unit='percent_of_baseline'))
        except ZeroDivisionError:rows.append(dict(column=m.col,panel='C',group=region,contrast='ratio to raw 0_4 rate',unit='ratio',holm_family='',status='ZERO_BASELINE',estimate=None,se=None,p_value=None,ci_low=None,ci_high=None))
    rows.append(m.row('C','competitive minus noncompetitive: late rebound',rebounds['competitive']-rebounds['noncompetitive']))
    m=models['column4']
    for speed in SPEEDS:
        for k in range(8):profiles.append(m.row('stage_profile',STAGES[k]+' minus 0_4',m.stage(k,speed),group=speed))
        rows.append(m.row('D','81_plus minus 41_80',m.stage(7,speed)-m.stage(6,speed),group=speed))
        rows.append(m.row('D','41_80 minus 0_4',m.stage(6,speed),group=speed))
    for fast,slow in [('ultrabullet_bullet','blitz'),('blitz','rapid'),('rapid','classical')]:
        def effect(k,s):return m.fast(k) if s=='ultrabullet_bullet' else m.stage(k,s)
        group=slow+' minus '+fast
        for k in range(1,8):profiles.append(m.row('between_speed_stage_profile',STAGES[k]+' minus 0_4',effect(k,slow)-effect(k,fast),group=group))
        rows.append(m.row('D','between-speed difference: 41_80 minus 0_4',effect(6,slow)-effect(6,fast),group=group))
        rows.append(m.row('D','between-speed difference: 81_plus minus 41_80',(effect(7,slow)-effect(6,slow))-(effect(7,fast)-effect(6,fast)),group=group))
    joints.append(joint(m,[m.stage(k,s)-m.stage(k,'ultrabullet') for s in SPEEDS[1:] for k in range(1,8)],'all_seven_stage_profiles_equal_across_five_speeds'))
    m=models['column2']
    for kind,labels in [('position',POSITIONS),('stage',STAGES)]:
        for k,label in enumerate(labels):rates.append(m.row('adjusted_rates',label,m.rate(kind,k),group=kind,unit='percent'))
    return holm(rows),coef,profiles,rates,joints

def write_report(run,fit,meats):
    require(fit['g']>1,'At least two chooser clusters are required');factor=fit['g']/(fit['g']-1)
    covs={k:factor*meats[k] for k in COLS}
    rows,coef,profiles,rates,joints=make_rows(fit,covs)
    for filename,r in [('contrasts',rows),('coefficients',coef),('stage_profiles',profiles),('adjusted_rates_column2',rates),('joint_speed_test',joints)]:table(run/'report'/filename,r)
    diagnostics=[]
    for col in COLS:
        f=fit['fits'][col]
        names=f['names']+fit['moment_names'];npz(run/'report'/('covariance_'+col+'.npz'),covariance=covs[col],names=np.array(names,dtype='U'),beta=f['beta'],moment_means=fit['mean_m'])
        diagnostics.append(dict(column=col,opportunities=fit['n'],choosers=fit['g'],opportunities_in_choosers_with_at_least_two=fit['within_n'],choosers_with_at_least_two=fit['within_g'],opportunities_in_choosers_with_position_variation=fit['position_vary_n'],opportunities_in_choosers_with_stage_variation=fit['stage_vary_n'],mean_outcome_percent=fit['mean_y'],rank=f['rank'],columns=len(f['names']),cluster_correction=factor,normal_equation_error=f['normal_equation_error']))
    table(run/'report/model_summary',diagnostics);dump(run/'report/SPECIFICATION.json',specification())
    # Main paper table: Panel A positions; Panel B stage coefficients for additive columns.
    lines=['# R10: two questions, four columns','',f'Analysis sample: {fit["n"]:,} opportunities; {fit["g"]:,} chooser accounts. Outcome mean: {fit["mean_y"]:.6f}%.',
      f'Opportunities belonging to choosers with at least two observations: {fit["within_n"]:,}. Singleton observations remain in sample descriptions and standardized rates; their within-transformed regressors are zero.','',
      'Entries are percentage-point coefficients (chooser-clustered SE). Columns 3 and 4 below use opportunity-weighted stage profiles. Group-specific profiles are in stage_profiles.csv.','',
      '| Contrast | (1) Additive | (2) Controls | (3) Competitive interaction | (4) Speed interaction |','|---|---:|---:|---:|---:|']
    for panel in ['A','B']:
        wanted=[r['contrast'] for r in rows if r['column']=='column1' and r['panel']==panel and (' minus clearly_worse' in r['contrast'] if panel=='A' else ' minus 0_4' in r['contrast'])]
        for contrast in wanted:
            cells=[]
            for col in COLS:
                r=next(x for x in rows if x['column']==col and x['panel']==panel and x['contrast']==contrast)
                cells.append(f'{r["estimate"]:+.4f} ({r["se"]:.4f})' if r['status']=='ESTIMATED' else r['status'])
            lines.append('| '+contrast+' | '+' | '.join(cells)+' |')
    lines += ['', '## Interpretation and conventions','',
      '- Panel A and B have separate Holm families of 7 and 13 within each column. Unestimable hypotheses count as p=1 in their family.',
      '- Column 3 estimates stage changes within competitive and noncompetitive regions. Ratios use the raw 0-4 grant rate in the corresponding region; numerator-denominator covariance is included.',
      '- Column 3 position coefficients relative to clearly worse describe the 0-4 reference stage; cross-region position differences also depend on the stage interactions at later stages.',
      '- Column 4 retains all five speeds. The combined ultrabullet/bullet comparison weights their profiles by their opportunity shares in the full sample; estimated-weight uncertainty is included.',
      '- Adjusted rates standardize every opportunity to the indicated position or stage, retaining all other observed features and chooser effects. Their SEs include empirical-composition uncertainty.',
      '- The requested count of rows in choosers with at least two opportunities is not proof that every regressor varies within every such chooser. Separate position/stage variation counts are supplied.',
      '- These are conditional descriptive associations. Differences across speeds can be consistent with the proposed investment measures, but do not isolate a causal investment mechanism.',
      '- All-game medians are a separate descriptive calculation. Its completion and source coverage are recorded in ALL_GAMES_STATUS.json; no opportunity-only median is substituted.','']
    (run/'report/README_RESULTS.md').write_text('\n'.join(lines))
    # Ready-to-paste LaTeX with fixed effects and correctly labelled heterogeneous profiles.
    tex=['% Generated by R10; outcome and SE units: percentage points.',r'\begin{tabular}{lrrrr}',r'\toprule',r' & (1) & (2) & (3) & (4) \\',r'\midrule']
    for name in [r['contrast'] for r in rows if r['column']=='column1' and r['panel'] in ['A','B'] and (r['contrast'].endswith(' minus clearly_worse') or r['contrast'].endswith(' minus 0_4'))]:
        cells=[]
        for col in COLS:
            r=next(x for x in rows if x['column']==col and x['contrast']==name and x['panel'] in ['A','B'])
            cells.append(f'{r["estimate"]:.3f} ({r["se"]:.3f})' if r['status']=='ESTIMATED' else '--')
        tex.append(name.replace('_',r'\_')+' & '+' & '.join(cells)+r' \\')
    tex += [r'\midrule',r'Chooser, speed, month FE & Yes & Yes & Yes & Yes \\',r'Clock and rating controls & No & Yes & Yes & Yes \\',r'\bottomrule',r'\end{tabular}',
      '% Columns 3/4 stage rows are sample-share-standardized averages; report region/speed profiles separately.']
    (run/'report/main_table.tex').write_text('\n'.join(tex)+'\n')
    return covs
