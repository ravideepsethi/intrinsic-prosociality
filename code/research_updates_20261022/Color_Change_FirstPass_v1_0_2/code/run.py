#!/usr/bin/env python3
"""First pass only. Expected runtime 2-6 hours; see README for assumptions."""
from __future__ import annotations
import argparse, fcntl, platform, shutil, traceback, zipfile
from common import *
from panel import normalize_all
from replay import replay_all
from analysis import dose_all,summarize,visibility_status
from grace import grace_all
from checkpoints import preflight_all

PLAN={
 "version":DATA_CONTRACT_VERSION,"scope":"Institutional reconstruction and first-pass descriptive diagnostics. Behavioral/IV specifications remain gated.",
 "color_cutoff_utc":CUTOFF,"transition_bracket":["2025-11-18T07:15:00Z",CUTOFF],
 "advantage_elo":ADVANTAGE,"announcement_utc":"2025-12-22T22:35:00Z","further_information_date":"2026-01-07",
 "grace_issue_date":"2026-01-30","grace_production_cutoff":None,
 "replay_start_checkpoint":"2025-10","replay_months":list(POST_MONTHS),
 "normalization_window":["2023-09","2026-04"],
 "primary_matched_reconstruction_baseline":"All rated games November 1 to November 18 07:15 UTC, within outcome, speed, color, RD bin, and opponent-minus-own gap bin.",
 "reconstruction_decision":"Review post-month cell errors and signed errors against matched pre cells; no automatic pooled MAE certification. The transition bracket is separate.",
 "integer_visibility":"Blocked: the authenticated producer stores no fractional rating state; rounding diagnostics do not establish exact visibility.",
 "dose_definition":"d_G=draw_new-draw_old; d_C=win_new-win_old; delta_kappa=d_C-d_G at the same anchored pregame state.",
 "established_diagnostic_cohort":"At least 100 same-speed rated updates by October 31 2023. Fixed conservative cohort; not the final A2 cohort specification.",
 "descriptive_sample":"All source timeout opportunities, excluding self-player records. The completed pool/non-immediate-rematch sidecar is not re-created or applied here; these weekly series are not the manuscript A2 sample.",
 "returning_support":"RD>=200, fixed established cohort, >=90 days since previous same-speed rated update. Account age alone is not used.",
 "grace_denominator":"Targeted >=5-second time-forfeit candidate frame. Not all disconnections and not platform-wide timeout share.",
 "power_gate":{
   "status":"PENDING_VALIDATED_DOSE_CENSORING_AND_RESIDUALIZED_SUPPORT",
   "awareness_scenarios":[.05,.10,.20,.50,1.0],
   "established_go":"Detect the exact predicted statistic at <=20% awareness under frozen pre-period dependence-aware inference.",
   "targeted_go":"Detect at <=50% awareness in a predeclared established stratum with support.",
   "no_go":"Report institutional validation and precision bound if the MDE cannot address plausible responses.",
   "inference":"Pre-period weekly/blocked-placebo noise; effective time support, not opportunity-count-only SEs. Two-way chooser/week inference is secondary.",
   "planning_effect_pp_single_color":[.03535,.04713],
   "planning_effect_pp_white_minus_black":[.07069,.09426],
   "warning":"The symmetric color x period x band statistic can cancel linear relocation; derive its own F. These planning effects are not MDEs."
 },
 "later_A3":"Include d_G main effect and Post*d_G; individual and week effects, color, pre-rule K and E, board, stage, clocks, tenure. Diagnose residualized support; two-way clustering alone does not solve serial dependence or confounding.",
 "later_A4":"Freeze symmetric g in [-30,30] profiles and two sign-flip bands. No predeclared null; displayed vs underlying thresholds are distinct predictions.",
 "later_A5":"Split Nov18-Dec22 announcement, announcement-Jan7, Jan7-censor; public code or feedback can generate awareness before announcement.",
 "later_A6_A8":"Decompose raw/adjusted sign reversals by controls. Clearly-losing comparison is a specificity test.",
 "IV":{
   "exposures":"Require full 90-day follow-up before the observed censor timestamp; new completed cohorts principally Aug-Oct2025.",
   "histories":"Strictly prior opponent decisions; compare five/ten on the same eligible sample and report sample selection separately.",
   "incident_control":"Hourly platform-wide timeout share leave-one-out, same controls in first stage, RF and 2SLS; top percentile sensitivity frozen without receipt outcomes.",
   "color_control":"Recipient color x post at the later outcome choice; no post-Nov18 exposure enters if censoring is late January.",
   "exclusion_sensitivity":"(RF-delta)/FS in consistent instrument-SD units; reported 0.020 pp/SD is a historical benchmark, not a result of this run.",
   "estimation_status":"Not run before shared censoring and incident dependencies are resolved."
 }
}

def plot_weekly(report):
    """Small dependency-free SVG of descriptive rates; no inferential band."""
    df=pd.read_parquet(report/"weekly_color_grant_descriptive.parquet")
    df=df[(df.board_state=="competitive")&df.established_at_2023_10]
    if df.empty:return
    z=df.groupby(["week","color"])[["opportunities","grants"]].sum()
    z["pct"]=100*z.grants/z.opportunities
    y=z.pct.unstack().dropna()
    if not {"white","black"}<=set(y):return
    y["difference_pp"]=y.white-y.black
    y.reset_index().to_csv(report/"weekly_fixed_cohort_difference.csv",index=False)
    # Pandas 3 may return microsecond-resolution dates. Convert explicitly to
    # epoch seconds rather than assuming the integer representation is ns.
    dates=pd.to_datetime(y.index,utc=True);xs=np.array([t.timestamp() for t in dates])
    vals=y.difference_pp.to_numpy(); lo=min(-.1,float(vals.min())*1.2);hi=max(.1,float(vals.max())*1.2)
    def X(v):return 65+840*(v-xs.min())/max(1,xs.max()-xs.min())
    def Y(v):return 335-260*(v-lo)/(hi-lo)
    pieces=['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="420" viewBox="0 0 960 420"><rect width="960" height="420" fill="white"/>',
      '<text x="65" y="28" font-family="sans-serif" font-size="18">Competitive positions: weekly White minus Black grant rate</text>',
      '<text x="65" y="51" font-family="sans-serif" font-size="12">All-source fixed established cohort; descriptive percentage points; reconstruction review pending</text>']
    for v in np.linspace(lo,hi,5):
        pieces.append(f'<line x1="65" y1="{Y(v):.2f}" x2="905" y2="{Y(v):.2f}" stroke="#dddddd"/><text x="8" y="{Y(v)+4:.2f}" font-family="sans-serif" font-size="11">{v:.2f}</text>')
    points=" ".join(f"{X(t):.2f},{Y(v):.2f}" for t,v in zip(xs,vals))
    pieces.append(f'<polyline fill="none" stroke="#1f4e79" stroke-width="1.7" points="{points}"/>')
    for date,label,height in ((CUTOFF,"Nov 18 convention",90),("2025-12-22T22:35:00Z","Dec 22 announcement",110)):
        p=pd.Timestamp(date).timestamp()
        if xs.min()<=p<=xs.max():pieces.append(f'<line x1="{X(p):.2f}" x2="{X(p):.2f}" y1="70" y2="335" stroke="#b24a36" stroke-dasharray="4,4"/><text x="{X(p)-165:.2f}" y="{height}" font-family="sans-serif" font-size="11">{label}</text>')
    for t in pd.date_range(dates.min(),dates.max(),freq="6MS"):
        pieces.append(f'<text x="{X(t.timestamp())-20:.2f}" y="359" font-family="sans-serif" font-size="11">{t:%Y-%m}</text>')
    pieces.append('<text x="65" y="398" font-family="sans-serif" font-size="11">Cohort: at least 100 same-speed rated updates by October 2023. No causal or awareness interpretation.</text></svg>')
    (report/"weekly_fixed_cohort_difference.svg").write_text("\n".join(pieces))

def write_report(report,work,normal,doses,grace):
    n=sum(x["rows"] for x in doses);nv=sum(x["valid_state_rows"] for x in doses)
    gaps=[x["month"] for x in doses if x["valid_state_rows"]<x["rows"]]
    status={"computation":"FIRST_PASS_COMPUTATION_COMPLETE","reconstruction_validation":"REVIEW_REQUIRED",
      "power_decision":"NOT_YET_ELIGIBLE","behavioral_estimates_run":False,"iv_estimates_run":False,
      "opportunities":n,"authenticated_state_opportunities":nv,"months_with_incomplete_rating_states":gaps,
      "exact_visibility":"NOT_IDENTIFIED","grace_censoring":"NOT_YET_FROZEN",
      "large_parquet_root":str(work),"source_normalization":normal,"dose_receipts":doses}
    write_json(report/"SUMMARY.json",status)
    (report/"READ_ME_FIRST.md").write_text(f"""# November 2025 color change: first-pass results

Computation completed. **Reconstruction still requires review; behavioral and IV estimates have not run.**

Normalized {n:,} non-self-player opportunities across September 2023-April 2026. {nv:,} have authenticated pregame rating states in this package. Incomplete rating-state coverage: {', '.join(gaps) or 'none'}.

## Review in this order

1. `matched_reconstruction.csv`: post months versus the November 1-18 07:15 UTC baseline in the same outcome/speed/color/RD/gap cells. Includes signed errors and old-versus-new MAE. `reconstruction_cells.csv` adds tail shares and the excluded transition bracket. A small pooled MAE does not validate every cell.
2. `grace_and_iv_dependencies.json` and available `grace_daily_targeted.csv`: mechanically defined candidate-frame rates by speed and material. January 30 is not assumed to be deployment. The >=5-second API frame cannot identify all disconnections or the platform-wide timeout denominator. Missing input branches are recorded explicitly. No censoring date is selected automatically.
3. `dose_distribution.csv` and `premium_near_equality.csv`: fixed-state d_G, d_C, delta_kappa and ratio distributions. These are exact for the anchored certified formula, conditional on the reconstructed hidden state. They do not reveal fractional production rating phase.
4. `visibility_status.json`: exact display visibility and cumulative informative feedback remain unavailable. Floor/nearest-integer reconstruction counts are diagnostic conventions only.
5. `weekly_fixed_cohort_difference.svg` and weekly CSV/Parquet: descriptive series for a conservative cohort with >=100 same-speed rated updates before November 2023, across all source timeout opportunities. The existing pool/non-immediate-rematch sidecar is not joined here. This is not the final A2 sample or specification and has no opportunity-count-based confidence interval.

No GO decision, continuous DiD, threshold DDD, or IV estimate is released by this run. The frozen plan records their prerequisites and the power decision. No fixed statistical pass threshold was invented from the previously quoted 0.34-0.46 pooled MAE.

## Data definitions

Gap g is opponent minus chooser displayed rating. White c=+1; Black c=-1. The shift is 11.782457 Elo inside the expected-score logit, from November 18 07:22 UTC by convention. The 07:15-07:22 bracket is kept separate. d_G and d_C compare both formulas at one pregame state; delta_kappa=d_C-d_G.

RD-bin codes: 0=[45,45.01), 1=[45.01,60), 2=[60,100), 3=[100,200), 4=[200,infinity). Gap-bin boundaries: -200,-50,-30,-11.782457,0,11.782457,30,50,200. Right-hand bins include the boundary. Ratio denominators <=1e-9 are separately counted. Quantiles in CSV are arrays written as text; Parquet is the primary machine-readable output.

The long-inactivity stratum uses RD>=200, >=90 days since a previous same-speed update and the fixed established cohort, which supplies established history more than a year earlier. Prior-games bins are experience measures; they are not account ages. Raw/adjusted behavioral decompositions are not run here.

The complete 32-month API/engine coverage does not imply complete certified rating-state coverage. This run resumes only November 2025-January 2026 from October 2025, the policy window needed for the first gate. It does not replay 2013 onward, redo Stockfish, recover identities, or change the certified panel.

Large reusable ZSTD Parquets and monthly restart checkpoints: `{work}`. The upload ZIP contains aggregate reports, configuration, source receipts and logs; it excludes game-level and account-level Parquets.
""")
    return status

def bundle(report,desktop):
    archive=Path(desktop)/(report.name+".zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(report.rglob("*")):
            if p.is_file():z.write(p,report.name+"/"+str(p.relative_to(report)))
    Path(str(archive)+".sha256").write_text(sha(archive)+"  "+archive.name+"\n")
    log(f"Review ZIP: {archive}")
    return archive

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--project-root",type=Path,default=Path("/Volumes/XT_Pro/lichess_kindness"))
    p.add_argument("--desktop",type=Path,default=Path.home()/"Desktop/Lichess_Desktop")
    p.add_argument("--workers",type=int,default=10);p.add_argument("--no-jit",action="store_true")
    args=p.parse_args()
    if not 1<=args.workers<=10:p.error("workers must be between 1 and 10")
    if not args.project_root.is_dir():p.error("project drive is not mounted")
    args.desktop.mkdir(parents=True,exist_ok=True)
    work=args.project_root/"derived/replication_36m/color_change_firstpass_v100"
    work.mkdir(parents=True,exist_ok=True)
    lock=open(work/"run.lock","a+")
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit("This first-pass job is already running; no duplicate run was started.")
    stamp_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report=args.project_root/"output"/"color_change_firstpass_v100"/("COLOR_FIRSTPASS_RESULT_"+stamp_id)
    report.mkdir(parents=True,exist_ok=True)
    t0=time.monotonic()
    freeze=work/"FROZEN_PLAN.json"
    if freeze.exists() and read_json(freeze)!=PLAN:raise RuntimeError("Existing first-pass plan differs; do not mix versions in this output root")
    write_json(freeze,PLAN);write_json(report/"FROZEN_PLAN.json",PLAN)
    write_json(report/"ENVIRONMENT.json",{"python":sys.version,"platform":platform.platform(),"duckdb":duckdb.__version__,"numpy":np.__version__,"pandas":pd.__version__,"pyarrow":pa.__version__,"workers":args.workers,"replay_processes":min(5,args.workers),"expected_initial_runtime":"2-6 hours; 30-120 minutes if Numba is already installed and I/O is fast; neither estimate is a measured benchmark for this extension","resumed_runtime":"5-30 minutes when all expensive replay and normalization outputs are reusable"})
    write_json(report/"visibility_status.json",visibility_status())
    write_json(report/"IMPLEMENTATION.json",{"package_version":VERSION,"data_contract_version":DATA_CONTRACT_VERSION,"repair":"Checkpoint inventory hashes identify Parquet data, not metadata JSON. Historical timestamp repair retained. Existing normalized partitions and the frozen plan remain compatible."})
    log("First pass: expected 2-6 hours initially; throughput ETA will appear during replay.")
    log(f"{args.workers} workers for independent month jobs; up to 5 independent speed replay processes.")
    log(f"Persistent restart root: {work}")
    try:
        if shutil.disk_usage(work).free<35*1024**3:raise RuntimeError("Need at least 35 GiB free for narrow Parquets, checkpoints and SQL spill.")
        producer=args.project_root/"replication_package/code/06_build_glicko2_cost_layer.py"
        audited=load_stage06(producer)
        prerequisites=preflight_all(args.project_root,work,args.workers,audited.REQUIRED_REPLAY_COLUMNS)
        write_json(report/"replay_preflight.json",prerequisites)
        from engine import configure
        _,backend=configure(audited,not args.no_jit)
        log(f"Replay mathematical parity preflight passed; backend={backend}")
        normal=normalize_all(args.project_root,work,args.workers,768)
        write_json(report/"normalized_sources.json",normal)
        log("Resuming three policy-window months; certified main-panel replay is reused.")
        replay=replay_all(args.project_root,work,args.workers,not args.no_jit)
        write_json(report/"replay_receipts.json",replay)
        # Preserve the first gate in the small review bundle even if a later
        # payoff/denominator stage stops. These are aggregate cells, not users.
        for rec in replay:
            dest=report/"replay_diagnostic_cells"/(rec["contract"]["speed"]+"_"+rec["contract"]["month"]+".parquet")
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(rec["outputs"]["diagnostics"]["path"],dest)
        doses=dose_all(args.project_root,work,args.workers,768)
        summarize(work,report,args.workers)
        grace=grace_all(args.project_root,work,report,args.workers)
        plot_weekly(report)
        status=write_report(report,work,normal,doses,grace)
        status["elapsed_seconds"]=round(time.monotonic()-t0,1)
        write_json(report/"_COMPUTATION_COMPLETE.json",status)
        bundle(report,args.desktop)
        log("FIRST_PASS_COMPUTATION_COMPLETE — reconstruction/grace/visibility review remains; no causal estimates released.")
        return 0
    except Exception as exc:
        write_json(report/"FAILURE.json",{"error":str(exc),"traceback":traceback.format_exc(),"elapsed_seconds":round(time.monotonic()-t0,1),"restart_root":str(work)})
        for name in ("source_catalog.json","normalization_status.json","replay_preflight.json","replay_status.json"):
            if (work/name).is_file():shutil.copy2(work/name,report/name)
        for p0 in sorted((work/"base").glob("month=*/opportunities.json")):
            target=report/"completed_normalization"/(p0.parent.name+".json")
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p0,target)
        for p0 in sorted((work/"timestamp_resolution").glob("*.json")):
            target=report/"timestamp_resolution"/p0.name
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p0,target)
        for p0 in sorted((work/"checkpoint_authentication").glob("*.json")):
            target=report/"checkpoint_authentication"/p0.name
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p0,target)
        for p0 in sorted((work/"replay").glob("speed=*/month=*/_SUCCESS.json")):
            target=report/"completed_replay"/(p0.parent.parent.name+"_"+p0.parent.name+".json")
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p0,target)
        bundle(report,args.desktop)
        log(f"STOPPED: {exc}. Completed months remain reusable. Upload the review ZIP.")
        return 2
    finally:
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()

if __name__=="__main__":raise SystemExit(main())
