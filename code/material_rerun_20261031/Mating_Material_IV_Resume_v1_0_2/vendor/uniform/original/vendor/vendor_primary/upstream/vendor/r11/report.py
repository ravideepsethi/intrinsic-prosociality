"""Joint-covariance contrasts, Holm families, and standardized rates."""
from common import *
from design import COLS,POSITIONS,STAGES,REGIONS,GAP_NAMES,KNOTS,gap_basis,specification
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

GAP_CONTRASTS=[(100,-100),(0,-100),(100,0),(300,0),(-300,0)]
SLOPE_LABELS=['-600_to_-300','-300_to_-100','-100_to_0','0_to_100','100_to_300','300_to_600']

class Model:
    def __init__(self,col,fit,cov):
        self.col=col;self.f=fit['fits'][col];self.k=len(self.f['names']);self.cov=cov
        self.names=self.f['names']+fit['moment_names'];values=np.r_[self.f['beta'],fit['mean_m']]
        eye=np.eye(len(values));self.vars={n:Scalar(values[i],eye[i]) for i,n in enumerate(self.names)}
        self.zero=Scalar(0,np.zeros(len(values)))
    def b(self,name):return self.vars[name]
    def pos(self,k):return self.b('position_'+POSITIONS[k]) if k else self.zero
    def stage(self,k,region=None):
        if k==0:return self.zero
        if region is not None:return self.b('stage_'+STAGES[k]+':'+region)
        w=self.b('share_competitive')
        return w*self.stage(k,'competitive')+(1-w)*self.stage(k,'noncompetitive')
    def gap_coef(self,name,region):return self.b(name if self.col=='column3' else name+':'+region)
    def h(self,r,region):return sum((v*self.gap_coef(name,region) for name,v in zip(GAP_NAMES,gap_basis([r])[0])),self.zero)
    def slope(self,k,region):return self.gap_coef('gap100',region)+sum((self.gap_coef('gap_hinge_'+str(t),region) for t in KNOTS[:k]),self.zero)
    def zero_gap_position(self,k):return self.pos(k)+(self.h(0,'competitive')-self.h(0,'noncompetitive') if k>=2 else self.zero)
    def rate(self,kind,k):
        r=self.b('mean_y')
        if kind=='position':
            r+=self.pos(k)-sum((self.b('share_position_'+POSITIONS[j])*self.pos(j) for j in range(1,5)),self.zero)
            target='competitive' if k>=2 else 'noncompetitive'
            for j in range(1,8):r+=self.b('share_stage_'+STAGES[j])*self.stage(j,target)
            for region in REGIONS:
                for j in range(1,8):r-=self.b('share_stage_'+STAGES[j]+':'+region)*self.stage(j,region)
            if self.col!='column3':
                for name in GAP_NAMES:
                    r+=self.b('mean_'+name)*self.gap_coef(name,target)
                    for region in REGIONS:r-=self.b('mean_'+name+':'+region)*self.gap_coef(name,region)
        elif kind=='stage':
            r+=self.stage(k)
            for region in REGIONS:
                for j in range(1,8):r-=self.b('share_stage_'+STAGES[j]+':'+region)*self.stage(j,region)
        else:raise ValueError(kind)
        return r
    def baseline(self,region):return self.b('baseline_y_'+region)/self.b('baseline_n_'+region)
    def estimable(self,grad):
        z=grad[:self.k]/self.f['scale'];return np.linalg.norm(self.f['null'].T@z)<=1e-7*max(np.linalg.norm(z),1e-10)
    def row(self,panel,name,value,group='',family='',unit='percentage_points'):
        row=dict(column=self.col,panel=panel,group=group,contrast=name,unit=unit,holm_family=family,adjustment='Holm' if family else 'none; unadjusted',ci_type='pointwise 95% normal Wald')
        if not self.estimable(value.g):return dict(row,status='NOT_ESTIMABLE',estimate=None,se=None,p_value=None,ci_low=None,ci_high=None)
        var=float(value.g@self.cov@value.g);require(var>=-1e-10,'Negative contrast variance')
        se=np.sqrt(max(var,0));p=2*ndtr(-abs(value.v/se)) if se>1e-14 else (1. if abs(value.v)<1e-12 else 0.)
        return dict(row,status='ESTIMATED',estimate=value.v,se=float(se),p_value=float(p),ci_low=float(value.v-1.959963984540054*se),ci_high=float(value.v+1.959963984540054*se))

def gap_label(hi,lo):return f'h({hi:+d}) minus h({lo:+d})'

def make_rows(fit,covs):
    rows=[];coef=[];profiles=[];rates=[];translations=[];weights=[]
    for col in COLS:
        m=Model(col,fit,covs[col])
        for name in m.f['names']:coef.append(m.row('coefficients',name,m.b(name)))
        for k in [4,3,2,1]:rows.append(m.row('A',POSITIONS[k]+' minus clearly_worse: raw beta',m.pos(k),family=col+'_A_7'))
        for high,low in [(4,3),(3,2),(2,1)]:rows.append(m.row('A',POSITIONS[high]+' minus '+POSITIONS[low]+': raw beta',m.pos(high)-m.pos(low),family=col+'_A_7'))
        for k in range(1,8):rows.append(m.row('B_pooled',STAGES[k]+' minus 0_4',m.stage(k),group='opportunity_weighted',family=col+'_B_13'))
        for k in range(2,8):rows.append(m.row('B_pooled',STAGES[k]+' minus '+STAGES[k-1],m.stage(k)-m.stage(k-1),group='opportunity_weighted',family=col+'_B_13'))
        rebounds={}
        for region in REGIONS:
            for k in range(1,8):
                row=m.row('B_region',STAGES[k]+' minus 0_4',m.stage(k,region),group=region)
                rows.append(row);profiles.append(row)
            rebounds[region]=m.stage(7,region)-m.stage(6,region)
            rows.append(m.row('B_rebound','81_plus minus 41_80',rebounds[region],group=region))
            try:
                base=m.baseline(region);decline=m.stage(6,region)
                rows.append(m.row('B_baseline','raw 0_4 grant rate',base,group=region,unit='percent'))
                rows.append(m.row('B_ratio','signed 41_80 minus 0_4 / raw 0_4 rate',decline/base,group=region,unit='ratio'))
                rows.append(m.row('B_ratio','decline as percent of raw 0_4 rate',-100*decline/base,group=region,unit='percent_of_baseline'))
            except ZeroDivisionError:
                rows.append(dict(column=col,panel='B_ratio',group=region,contrast='ratio to raw 0_4 rate',unit='ratio',holm_family='',adjustment='none; unadjusted',status='ZERO_BASELINE',estimate=None,se=None,p_value=None,ci_low=None,ci_high=None))
            for hi,lo in GAP_CONTRASTS:
                value=m.h(hi,region)-m.h(lo,region)
                rows.append(m.row('C_gap',gap_label(hi,lo),value,group=region,family=col+'_C_'+region+'_5'))
                # Exact integer weights allow every gap contrast to be checked by hand.
                for name,w in zip(GAP_NAMES,gap_basis([hi])[0]-gap_basis([lo])[0]):
                    if w:weights.append(dict(column=col,region=region,contrast=gap_label(hi,lo),coefficient=name if col=='column3' else name+':'+region,weight=float(w)))
            for k,label in enumerate(SLOPE_LABELS):rows.append(m.row('C_slope',label,m.slope(k,region),group=region,unit='percentage_points_per_100_rating_points'))
        rows.append(m.row('B_rebound','competitive minus noncompetitive: 81_plus minus 41_80',rebounds['competitive']-rebounds['noncompetitive']))
        for hi,lo in GAP_CONTRASTS:
            rows.append(m.row('C_difference',gap_label(hi,lo),(m.h(hi,'competitive')-m.h(lo,'competitive'))-(m.h(hi,'noncompetitive')-m.h(lo,'noncompetitive')),group='competitive minus noncompetitive'))
        for k in [4,3,2,1]:translations.append(m.row('position_at_zero_gap',POSITIONS[k]+' minus clearly_worse at stage 0_4, gap 0',m.zero_gap_position(k)))
        for high,low in [(4,3),(3,2),(2,1)]:translations.append(m.row('position_at_zero_gap',POSITIONS[high]+' minus '+POSITIONS[low]+' at stage 0_4, gap 0',m.zero_gap_position(high)-m.zero_gap_position(low)))
        if col=='column1':
            for kind,labels in [('position',POSITIONS),('stage',STAGES)]:
                for k,label in enumerate(labels):rates.append(m.row('adjusted_rates',label,m.rate(kind,k),group=kind,unit='percent'))
    return holm(rows),coef,profiles,rates,translations,weights

def write_report(run,fit,meats):
    require(fit['g']>1,'At least two chooser clusters required');factor=fit['g']/(fit['g']-1);covs={c:factor*meats[c] for c in COLS}
    rows,coef,profiles,rates,translations,weights=make_rows(fit,covs)
    for name,data in [('contrasts',rows),('coefficients',coef),('stage_profiles',profiles),('adjusted_rates_column1',rates),('position_at_zero_gap',translations),('gap_contrast_weights',weights)]:table(run/'report'/name,data)
    diagnostics=[]
    for col in COLS:
        f=fit['fits'][col]
        npz(run/'report'/('covariance_'+col+'.npz'),covariance=covs[col],names=np.array(f['names']+fit['moment_names'],dtype='U'),beta=f['beta'],beta_names=np.array(f['names'],dtype='U'),moment_means=fit['mean_m'],moment_names=np.array(fit['moment_names'],dtype='U'),scale=f['scale'],null=f['null'],cluster_correction=np.array(factor))
        diagnostics.append(dict(column=col,opportunities=fit['n'],choosers=fit['g'],opportunities_in_choosers_with_at_least_two=fit['within_n'],choosers_with_at_least_two=fit['within_g'],opportunities_in_choosers_with_position_variation=fit['position_vary_n'],opportunities_in_choosers_with_stage_variation=fit['stage_vary_n'],mean_outcome_percent=fit['mean_y'],rank=f['rank'],columns=len(f['names']),cluster_correction=factor,normal_equation_error=f['normal_equation_error']))
    table(run/'report/model_summary',diagnostics);dump(run/'report/SPECIFICATION.json',specification())
    def fmt(r):return f'{r["estimate"]:+.4f} ({r["se"]:.4f})' if r['status']=='ESTIMATED' else r['status']
    selected=[r for r in rows if r['column']=='column1' and ((r['panel']=='A' and 'minus clearly_worse' in r['contrast']) or r['panel']=='B_region' or (r['panel']=='C_gap' and r['contrast']==gap_label(100,-100)))]
    lines=['# R11 main regression','',f'{fit["n"]:,} opportunities; {fit["g"]:,} choosers; mean outcome {fit["mean_y"]:.6f}%.',
      f'{fit["within_n"]:,} opportunities belong to choosers with at least two observations. Author accounts retained.','',
      'Column 1 is Table 2. Column 2 omits all x_g controls. Column 3 pools the gap but retains region-specific stages. Entries below are percentage points (chooser-clustered SE).','',
      '| Term | Region | (1) Table 2 | (2) Without x_g | (3) Pooled gap |','|---|---|---:|---:|---:|']
    tex=[r'\begin{tabular}{llrrr}',r'\toprule',r'Term & Region & (1) Table 2 & (2) Without $x_g$ & (3) Pooled gap \\',r'\midrule']
    for r in selected:
        cells=[fmt(next(x for x in rows if x['column']==col and x['panel']==r['panel'] and x['group']==r['group'] and x['contrast']==r['contrast'])) for col in COLS]
        lines.append('| '+r['contrast']+' | '+r['group']+' | '+' | '.join(cells)+' |')
        tex.append(r['contrast'].replace('_',r'\_')+' & '+r['group'].replace('_',r'\_')+' & '+' & '.join(cells)+r' \\')
    tex += [r'\bottomrule',r'\end{tabular}', '% Raw position beta coefficients use the literal uncentered hinge basis.', '% Zero-gap, stage-0-4 position effects are in position_at_zero_gap.csv.', '% Missing-indicator and absent-speed columns can be rank deficient; all reported contrasts pass estimability checks.']
    lines += ['', '## Parameterization and interpretation','',
      'g = clip(r,-600,600)/100. h_R(r) = gamma_g,R*g + gamma_-3,R*max(g+3,0) + gamma_-1,R*max(g+1,0) + gamma_0,R*max(g,0) + gamma_1,R*max(g-1,0) + gamma_3,R*max(g-3,0) + gamma_low,R*1(r<-600) + gamma_high,R*1(r>600). A region-specific missing-gap indicator is also included.',
      'For example h_R(+100)-h_R(-100) = 2*gamma_g,R + 2*gamma_-3,R + 2*gamma_-1,R + gamma_0,R. All contrast weights are in gap_contrast_weights.csv.',
      'h_R(0)=3*gamma_-3,R+gamma_-1,R. Thus raw cross-region position betas are parameterization coefficients, not by themselves contrasts at gap zero. position_at_zero_gap.csv supplies the latter at stage 0-4. Within-region adjacent position differences do not require this translation.',
      'The six slope rows apply inside [-600,600]. Outside that range the function is flat, with a level jump at each strict tail indicator. Knots have left/right slopes rather than a single derivative.',
      'Position standardization changes the position bin and C together, updating both the stage and gap interactions for every opportunity. Stage standardization retains each opportunity\'s position, C, gap, controls and chooser effect. These are LPM standardized rates; they are not clipped to [0,100].',
      'Every column has a 7-test Panel A Holm family, a 13-test opportunity-weighted pooled stage family, and two 5-test gap families. Other requested tests are unadjusted and marked as such. Confidence intervals are pointwise, not simultaneous. Pooled-gap column 3 has cross-region gap differences constrained to zero by construction.',
      'The covariance NPZ contains beta, beta_names, full joint covariance, names, moment_means, moment_names and an estimability null space. The first len(beta) rows/columns of covariance are the coefficient covariance. Remaining rows carry empirical-composition uncertainty.',
      'Baseline ratios divide the adjusted stage change by the region\'s RAW 0-4 rate. They are descriptive normalizations, not percentage changes between two adjusted rates.',
      'R11 retains the explicitly requested original sample. Six missing-control columns and the absent ultrabullet category may be unestimable; unestimable focal contrasts are reported explicitly, never replaced with a zero.',
      'All-game percentile coverage is a separate calculation: inspect ALL_GAMES_STATUS.json and all_games_month_coverage.csv. Available-month summaries are game-weighted pooled quantiles, not averages of monthly quantiles. No opportunity-only summary substitutes for all games.','']
    (run/'report/README_RESULTS.md').write_text('\n'.join(lines));(run/'report/appendix_comparison.tex').write_text('\n'.join(tex)+'\n')
    table(run/'report/table2_all_contrasts',[r for r in rows if r['column']=='column1'])
    main=[r'\begin{tabular}{llrrr}',r'\toprule',r'Term & Region & Estimate (SE) & $p$ & Holm $p$ \\',r'\midrule']
    for panel,title in [('A','Position coefficients (raw hinge parameterization)'),('B_region','Stage by region, relative to 0--4'),('C_gap','Rating-gap contrasts by region')]:
        main.append(r'\multicolumn{5}{l}{'+title+r'} \\')
        for r in rows:
            if r['column']!='column1' or r['panel']!=panel or (panel=='A' and 'minus clearly_worse' not in r['contrast']):continue
            def ptext(p):return '--' if p is None or pd.isna(p) else (r'$<0.001$' if p<.001 else f'{p:.3f}')
            main.append(r['contrast'].replace('_',r'\_')+' & '+r['group']+' & '+fmt(r)+' & '+ptext(r['p_value'])+' & '+ptext(r.get('p_holm'))+r' \\')
    main += [r'\bottomrule',r'\end{tabular}', '% Column 1 only. All requested contrasts and inference: table2_all_contrasts.csv.', '% Regional stage p-values are unadjusted; the specified 13-test Holm family is on the pooled profile.', '% Cross-region position effects at gap zero require the translation in position_at_zero_gap.csv.']
    (run/'report/main_table.tex').write_text('\n'.join(main)+'\n')
    return covs

