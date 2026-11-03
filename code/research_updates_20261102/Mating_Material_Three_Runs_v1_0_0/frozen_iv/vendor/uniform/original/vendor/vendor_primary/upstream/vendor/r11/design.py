"""R11: literal uncentered R10 gap basis, separately within both regions."""
from common import *

MONTHS=[f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)]
SPEEDS=['ultrabullet','bullet','blitz','rapid','classical']
STAGES=['0_4','5_6','7_8','9_10','11_20','21_40','41_80','81_plus']
POSITIONS=['clearly_worse','modestly_worse','roughly_equal','better','clearly_better']
REGIONS=['noncompetitive','competitive']
COLS=['column1','column2','column3']
KNOTS=[-3,-1,0,1,3]
GAP_NAMES=['gap100']+['gap_hinge_'+str(k) for k in KNOTS]+['gap_low_tail','gap_high_tail','gap_missing']

def gap_basis(raw):
    x=np.asarray(raw,float);ok=np.isfinite(x);g=np.clip(np.where(ok,x,0),-600,600)/100
    return np.column_stack([g]+[np.maximum(g-k,0) for k in KNOTS]+[ok&(x< -600),ok&(x>600),~ok])

def design(d):
    n=len(d);names=[];arrays=[];blocks={};competitive=d.position.to_numpy()>=2
    def add(name,x):names.append(name);arrays.append(np.asarray(x,float))
    def block(key,fn):
        start=len(names);fn();blocks[key]=list(range(start,len(names)))
    def pos():
        for k in range(1,5):add('position_'+POSITIONS[k],d.position.to_numpy()==k)
    def stage():
        for region,mask in [('noncompetitive',~competitive),('competitive',competitive)]:
            for k in range(1,8):add('stage_'+STAGES[k]+':'+region,(d.stage.to_numpy()==k)&mask)
    def fe():
        for k in range(1,24):add('month_'+MONTHS[k],d.month_code.to_numpy()==k)
        # Bullet is observed in the certified sample. Ultrabullet's zero column is explicit.
        for k in [0,2,3,4]:add('speed_'+SPEEDS[k],d.speed_code.to_numpy()==k)
    H=gap_basis(d.gap)
    def regional_gap():
        for region,mask in [('noncompetitive',~competitive),('competitive',competitive)]:
            for j,name in enumerate(GAP_NAMES):add(name+':'+region,H[:,j]*mask)
    def pooled_gap():
        for j,name in enumerate(GAP_NAMES):add(name,H[:,j])
    def control():
        for name in ['clock_c','clock_d']:
            x=d[name].to_numpy(float);ok=np.isfinite(x)&(x>=0)
            add('log1p_'+name,np.log1p(np.where(ok,x,0)));add('missing_'+name,~ok)
        for name in ['premium','rd_c','rd_d']:
            x=d[name].to_numpy(float);ok=np.isfinite(x)&(x>0);z=np.log(np.where(ok,x,1))
            add('log_'+name,z);add('log_'+name+'_sq',z*z);add('missing_'+name,~ok)
    for key,fn in [('position',pos),('stage',stage),('fe',fe),('regional_gap',regional_gap),('pooled_gap',pooled_gap),('control',control)]:block(key,fn)
    base=blocks['position']+blocks['stage']+blocks['fe']
    ix={'column1':base+blocks['regional_gap']+blocks['control'],
        'column2':base+blocks['regional_gap'],
        'column3':base+blocks['pooled_gap']+blocks['control']}
    return np.column_stack(arrays),names,ix

def moments_design(d):
    """Moments for coherent counterfactuals, weights and baseline-rate denominators."""
    names=[];a=[];y=100*d.y.to_numpy(float);competitive=d.position.to_numpy()>=2;H=gap_basis(d.gap)
    def add(name,v):names.append(name);a.append(np.asarray(v,float))
    add('mean_y',y)
    for k in range(1,5):add('share_position_'+POSITIONS[k],d.position.to_numpy()==k)
    for k in range(1,8):add('share_stage_'+STAGES[k],d.stage.to_numpy()==k)
    add('share_competitive',competitive)
    for j,name in enumerate(GAP_NAMES):add('mean_'+name,H[:,j])
    for region,mask in [('noncompetitive',~competitive),('competitive',competitive)]:
        for k in range(1,8):add('share_stage_'+STAGES[k]+':'+region,(d.stage.to_numpy()==k)&mask)
        for j,name in enumerate(GAP_NAMES):add('mean_'+name+':'+region,H[:,j]*mask)
        base=mask&(d.stage.to_numpy()==0)
        add('baseline_n_'+region,base);add('baseline_y_'+region,y*base)
    return np.column_stack(a),names

def dummy():
    return pd.DataFrame(dict(chooser=[1],y=[0],board=[0],ply=[20],position=[2],stage=[4],gap=[0.],clock_c=[10.],clock_d=[10.],premium=[6.],rd_c=[60.],rd_d=[60.],month_code=[0],speed_code=[1]))

def specification():
    return dict(sample='41,534,331 certified pool/nonadjacent opportunities; November 2023 through October 2025',author_accounts='retained by explicit R11 instruction',outcome='100 * grant',
      fixed_effects=['chooser','speed (bullet reference)','month (2023-11 reference)'],position_reference='clearly_worse (evaluation <= -300)',competitive='evaluation >= -100; no redundant C main effect',
      columns={'column1':'Table 2: region-specific stage and gap, with x_g','column2':'same region-specific stage and gap, without all x_g controls and their missing indicators','column3':'region-specific stage, pooled gap, with x_g; same model space as R10 column 3'},
      stage='seven indicators multiplied separately by C and (1-C); 0-4 reference in each region',
      rating_gap='r = disconnected_elo - chooser_elo; g = clip(r,-600,600)/100; b(r) = [g, max(g+3,0), max(g+1,0), max(g,0), max(g-1,0), max(g-3,0), 1(r<-600), 1(r>600), 1(r missing)]',
      gap_missing='nonfinite r is evaluated at r=0 plus its missing indicator, inherited from R10; every term is region-interacted in columns 1/2',
      h='h_R(r) = dot(b(r), gamma_R), R in {competitive,noncompetitive}; hinges are NOT centered at zero',
      position_interpretation='Panel A reports literal beta coefficients. At stage 0-4 and r=0, add h_C(0)-h_L(0) to each competitive-bin beta for comparison to clearly_worse; zero-gap translations are supplied separately.',
      slopes='six derivatives per 100 rating points INSIDE the clipping range: (-600,-300),(-300,-100),(-100,0),(0,100),(100,300),(300,600). Outside +/-600 derivatives are zero; tail indicators permit level jumps. Derivatives at knots are undefined.',
      gap_support='six mutually exclusive raw-r segments: r<-300; -300<=r<-100; -100<=r<0; 0<=r<100; 100<=r<300; r>=300. Tails r<-600 and r>600 are overlapping subsets, not additional disjoint segments. Missing r is reported separately.',
      rating_logs='natural log of positive premium and each RD, their squares, and missing indicators; invalid/nonpositive inputs use log(1)=0 plus indicator',
      clocks='log1p(nonnegative seconds); invalid values use 0 plus missing indicator',
      covariance='chooser cluster G/(G-1), including singleton choosers in G; no (N-1)/(N-K) multiplier',
      inference='two-sided asymptotic normal Wald p values, pointwise 95% normal Wald CIs; joint delta-method covariance for empirical weights and ratios',
      multiplicity='Per column: Panel A family 7; Panel B pooled profile family 13 (7 baseline and 6 adjacent contrasts); Panel C five gap contrasts per region, two families of 5. Regional stage profiles, rebound differences, ratios, cross-region gap differences, slopes, adjusted rates and zero-gap translations are unadjusted and explicitly marked.',
      adjusted_rates='column1: average counterfactual predictions using mean_y + mean(X_cf-X)*beta. Setting position also sets C and updates BOTH stage and gap interactions. Setting stage holds observed positions/C/gaps fixed. No clipping of LPM predictions. Empirical composition uncertainty included.',
      all_games='all local available complete monthly rated standard live PGN archives in the target window; all match sources/endings, author accounts retained; successful months explicitly listed. No opportunity-only replacement.',
      quantiles='exact histogram quantiles, linear interpolation with zero-based index (N-1)*p, p=.25,.5,.75 (Hyndman-Fan type 7)',
      interpretation='conditional descriptive associations; not identification of motives or causal effects')
