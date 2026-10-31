"""R10 frozen design; inherited rating controls match the executed A1 code."""
from common import *

MONTHS=[f'{2023+(10+i)//12:04d}-{(10+i)%12+1:02d}' for i in range(24)]
SPEEDS=['ultrabullet','bullet','blitz','rapid','classical']
STAGES=['0_4','5_6','7_8','9_10','11_20','21_40','41_80','81_plus']
POSITIONS=['clearly_worse','modestly_worse','roughly_equal','better','clearly_better']
COLS=['column1','column2','column3','column4']

def design(d):
    """One union design. Model submatrices implement the four specified columns."""
    n=len(d); names=[]; arrays=[]; blocks={}
    def add(name,x):names.append(name);arrays.append(np.asarray(x,float))
    def block(key,fn):
        start=len(names);fn();blocks[key]=list(range(start,len(names)))
    def pos():
        for k in range(1,5):add('position_'+POSITIONS[k],d.position.to_numpy()==k)
    def stage():
        for k in range(1,8):add('stage_'+STAGES[k],d.stage.to_numpy()==k)
    def fe():
        for k in range(1,24):add('month_'+MONTHS[k],d.month_code.to_numpy()==k)
        for k in range(1,5):add('speed_'+SPEEDS[k],d.speed_code.to_numpy()==k)
    def control():
        for name in ['clock_c','clock_d']:
            x=d[name].to_numpy(float);ok=np.isfinite(x)&(x>=0)
            add('log1p_'+name,np.log1p(np.where(ok,x,0)));add('missing_'+name,~ok)
        x=d.gap.to_numpy(float);ok=np.isfinite(x);z=np.clip(np.where(ok,x,0),-600,600)/100
        add('gap100',z)
        for knot in [-3,-1,0,1,3]:add('gap_hinge_'+str(knot),np.maximum(z-knot,0))
        add('gap_low_tail',ok&(x< -600));add('gap_high_tail',ok&(x>600));add('gap_missing',~ok)
        for name in ['premium','rd_c','rd_d']:
            x=d[name].to_numpy(float);ok=np.isfinite(x)&(x>0);z=np.log(np.where(ok,x,1))
            add('log_'+name,z);add('log_'+name+'_sq',z*z);add('missing_'+name,~ok)
    def competition():
        for k in range(1,8):add('stage_'+STAGES[k]+':competitive',(d.stage.to_numpy()==k)&(d.position.to_numpy()>=2))
    def speed():
        for j in range(1,5):
            for k in range(1,8):add('stage_'+STAGES[k]+':'+SPEEDS[j],(d.stage.to_numpy()==k)&(d.speed_code.to_numpy()==j))
    for key,fn in [('position',pos),('stage',stage),('fe',fe),('control',control),('competitive',competition),('speed_interaction',speed)]:block(key,fn)
    base=blocks['position']+blocks['stage']+blocks['fe'];controlled=base+blocks['control']
    ix={'column1':base,'column2':controlled,'column3':controlled+blocks['competitive'],'column4':controlled+blocks['speed_interaction']}
    return np.column_stack(arrays),names,ix

def moments_design(d):
    """Empirical moments whose cluster uncertainty enters rates, weights and ratios."""
    names=[];a=[];y=100*d.y.to_numpy(float)
    def add(name,v):names.append(name);a.append(np.asarray(v,float))
    add('mean_y',y)
    for k in range(1,5):add('share_position_'+POSITIONS[k],d.position.to_numpy()==k)
    for k in range(1,8):add('share_stage_'+STAGES[k],d.stage.to_numpy()==k)
    add('share_competitive',d.position.to_numpy()>=2)
    for k in range(1,5):add('share_speed_'+SPEEDS[k],d.speed_code.to_numpy()==k)
    for group,mask in [('competitive',d.position.to_numpy()>=2),('noncompetitive',d.position.to_numpy()<2)]+[(s,d.speed_code.to_numpy()==k) for k,s in enumerate(SPEEDS)]:
        base=mask&(d.stage.to_numpy()==0)
        add('baseline_n_'+group,base);add('baseline_y_'+group,y*base)
    return np.column_stack(a),names

def dummy():
    return pd.DataFrame(dict(chooser=[1],y=[0],board=[0],ply=[20],position=[2],stage=[4],gap=[0.],clock_c=[10.],clock_d=[10.],premium=[6.],rd_c=[60.],rd_d=[60.],month_code=[0],speed_code=[1]))

def specification():
    return dict(sample='41,534,331 certified pool/nonadjacent opportunities, November 2023 through October 2025',author_accounts='retained, as explicitly requested in R10',outcome='100 * grant',fixed_effects=['chooser','speed','month'],
      position_reference='clearly_worse',stage_reference='0_4',rating_gap='disconnected_elo - chooser_elo; clipped at +/-600; knots -300,-100,0,100,300; lower/upper-tail and missing indicators',
      rating_logs='natural log of positive premium and each RD, their squares, and missing indicators; invalid/nonpositive values use log(1)=0 plus indicator, matching prior code',
      clocks='log1p(nonnegative seconds); missing/negative/nonfinite values use 0 plus missing indicator',
      covariance='chooser-cluster sandwich, G/(G-1), no (N-1)/(N-K) multiplier; G includes singleton choosers',
      p_values='two-sided asymptotic normal Wald; 95% normal Wald intervals',
      panel_A='7-test Holm family separately within each column',
      panel_B='13-test Holm family separately within each column; columns 3/4 use opportunity-share-weighted stage profiles, including uncertainty of the weights',
      panel_C='signed stage contrasts and signed change / raw region-specific 0-4 grant rate; joint delta-method covariance includes denominator uncertainty',
      panel_D='five separate speed profiles; fast comparator is opportunity-weighted ultrabullet/bullet combination; weights and their uncertainty use the full analysis sample',
      adjusted_rates='column 2: mean_y + (counterfactual indicator - observed indicator share) beta; opportunity-weighted; cluster uncertainty includes empirical composition',
      all_games='rated standard live games in the same 24 months, all match sources and termination reasons; no opportunity or author restriction',
      interpretation='conditional descriptive associations; speed comparisons do not identify investment or motives')
