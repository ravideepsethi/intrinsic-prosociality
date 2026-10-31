# Consistent local adjusted data and fitted payoff lines

## Price and specification

The horizontal variable is the chooser's actual rating payoff from drawing:

\[
r_i = r_{G,i} = K_i(1/2-E_i) = \kappa_i(1-2E_i).
\]

Negative values mean a rating loss from drawing relative to the pre-game
reference; positive values mean a gain. The axis is expressed in rating
points. It is neither a rating-gap axis nor a residualized price coordinate.

The local sample is the existing v1.1.0 sample with \(|r_i|<1\), chooser-oriented
board evaluation at least −100 cp, its established complete-case rules, and
at least two observations in each chooser-by-speed-pool fixed-effect cell.
The exact production counts are 11,036,021 observations, 1,290,329 choosers,
1,483,874 fixed-effect cells, and 276,094 kind draws.

Let \(y_i\) equal 100 for a kind draw and zero otherwise. The frozen local model
is

\[
y_i=\alpha_{c(i),p(i)}+g(r_i)'\beta+z_i'\gamma+u_i,
\qquad
g(r)=(r1\{r<0\},r1\{r>0\},1\{r>0\},1\{r=0\})'.
\]

It permits separate loss/gain slopes, a right-minus-left level term, and a
separate exact-zero level. The regressors \(z_i\) are exactly those from
v1.1.0: continuous piecewise-linear splines in displayed rating gap and
expected-score imbalance, a spline in log forgone-win premium, game-stage
bands, log rating deviations and their squares, board evaluation terms,
chooser rating and its square, clock terms and missing indicators, month,
and tournament status. Both relative-strength splines have no knot at zero.
The bundled `reference_price_model_v110.py` is byte-identical to the executed
v1.1.0 script. Its model functions are imported; its former plotting routine
is never called by the corrected runner.

## The corrected dots and lines

The v1.1.0 local display mixed broad-sample bin coefficients with lines from a
separately fitted local model. Using the same list of control variables did
not make those separately estimated adjustments interchangeable.

Version 1.1.1 computes the fitted residual from the local model, including its
fixed effects. Define \(\bar g=N^{-1}\sum_i g(r_i)\) and \(\bar y=N^{-1}\sum_i y_i\)
on that same local estimation sample. The adjusted observation is

\[
a_i=\bar y+\hat u_i+(g(r_i)-\bar g)'\hat\beta.
\]

This subtracts the locally estimated fixed effects and nuisance-control
component, then applies a common level normalization. The frequency-weighted
mean of the plotted adjusted observations equals the local sample mean.

There are four 0.25-point bins per side and one exact-zero category. Each
nonzero point is \((\overline r_b,\overline a_b)\), so the horizontal position is
the actual mean draw payoff in its bin. The line is

\[
m(r)=\bar y+(g(r)-\bar g)'\hat\beta.
\]

Every nonzero bin stays on one side of zero. Because the payoff component is
linear within each side,

\[
\overline a_b-m(\overline r_b)=\overline{\hat u}_b.
\]

This is the exact same-model dot/line identity. Binned residual departures
remain visible; the code does not smooth the dots or force each dot onto the
line. At exact zero, the fitted zero indicator makes the aggregate residual
zero up to numerical precision, so the adjusted zero point and fitted level
coincide. It is drawn once. The loss/gain lines end at their one-sided limits
and are not connected to that diamond.

These are binned partial residuals, conditional on the specified local
payoff/control model. The fitted model contributes to their construction.
They do not provide independent nonparametric evidence for its shape, and
this display correction is not a new causal identification strategy.

## Uncertainty for the adjusted points

Bars are pointwise 95% chooser-clustered CR1 intervals. They account for
estimation of the nuisance coefficients and fixed effects. Taking the
standard deviation of adjusted rows and dividing by the square root of the
bin count would not do this.

Here is the implemented linear-functional calculation. Write the full
non-FE design as \(X=[G,Z]\), its coefficient vector as \(\theta\), and let
\(M_F\) remove fixed-effect cell means. Denote \(X^w=M_FX\) and
\(B=(X^{w\prime}X^w)^{-1}\), evaluated on the retained independent columns.
For a bin containing \(n_b\) observations, define

\[
c_b'=\bigl[(\bar g_b-\bar g)',0'\bigr]-\bar X_b^{w\prime}.
\]

The adjusted-bin estimate relative to the display mean is
\(\overline a_b-\bar y=\bar y_b^w+c_b'\hat\theta\). For chooser cluster \(q\),
define the score \(s_q=\sum_{i\in q}X_i^w\hat u_i\). Its estimated influence
on the normalized bin level is

\[
\psi_{bq}=\frac{1}{n_b}\sum_{i\in q\cap b}\hat u_i+c_b'B s_q.
\]

Each fixed-effect cell is nested in one chooser cluster, and residuals sum
to zero within each cell. Consequently the within-FE projection of the bin
weights yields the same cluster residual sum in the first term. The full
bin covariance is

\[
\widehat V_{bb'}=\frac{Q}{Q-1}\frac{N-1}{N-J-p}
\sum_q\psi_{bq}\psi_{b'q},
\]

where \(Q\) counts choosers, \(J\) counts fixed-effect cells, and \(p\) counts
retained non-FE columns. This is the same finite-sample correction as the
frozen coefficient covariance. All intervals treat the observed design and
the sample-mean display normalization as fixed. They are not confidence
intervals for an unconditionally estimated population baseline probability.

The exported curve covariance uses
\((g(r)-\bar g)'\widehat V_\beta(g(r)-\bar g)\). The figure displays bin intervals
and fitted lines; pointwise curve intervals are available in the aggregate
fit table. At exact zero, the bin and curve standard errors coincide; the
runner verifies this identity.

The independent self-test fits an explicit full set of fixed-effect dummies,
constructs adjusted points directly as outcome minus fitted FE and nuisance
terms, and calculates the cluster sandwich from that full regression.
It checks the points and complete bin covariance against the streaming
implementation. This also tests cells nested in chooser clusters and record
batches that split clusters.

## The broad companion panel

The 41 broad-bin estimates from \(|r_G|<5\) are reused byte for byte from the
authenticated source output. Their original joint-bin model and centered
covariance remain the source of Panel A. The connecting tail segments are
removed. Panel B is a separately adjusted local model, not a zoom of those
broad dots. Each panel is normalized to its own estimation-sample mean;
differences in their absolute vertical levels are not a treatment effect.

The standalone local figure avoids combining these two normalizations on one
fitted display and is provided as the paper-facing local figure.

## Scope of the correction

This release corrects the plotting construction. It does not resolve the
scientific question of which relative-strength counterfactual is appropriate.
Neither an improved visual alignment nor the v1.1.0 local slope difference
alone settles the manuscript's conclusions from other specifications. An
earlier description that the controls had removed the U-shaped pattern and
therefore established a new paper conclusion was too strong.
