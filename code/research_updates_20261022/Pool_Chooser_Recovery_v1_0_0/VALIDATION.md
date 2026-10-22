# Validation of v1.0.0

Checked on 23 September 2026 using authenticated synthetic source runs and the bundled numerical engine. The real account arrays are on the user's Mac; production recovery has not been run in this workspace.

- End-to-end execution: two spawned workers, two replications per generator, six datasets, and all 24 selected model fits successful. All feasible-start objective checks pass. Each generating model's selected fit improves on its true feasible generating vector without using that vector as a start.
- A separate multitype fixture fits all four model classes with unequal support sizes, including a three-component generator. The label-matching diagnostics and all six score comparisons complete successfully.
- All six dataset fingerprints reproduce exactly from independent development/evaluation RNG streams. Simulated probability vectors equal the persistent account type's emission probability at every opportunity. Reported grant totals match the simulated arrays. The original outcome arrays remain unchanged.
- Changing a simulated future outcome leaves all forecasts through that opportunity unchanged. Known-model KL diagnostics are nonnegative to numerical tolerance.
- All 15 nonempty Parquet/CSV table pairs agree in the smoke report, allowing for CSV null parsing.
- All 48 tested generic starting vectors for production-sized mixtures are feasible and produce finite state effects, including the near-additive starting regions.
- A known-result aggregation exercise verifies winner frequencies, pairwise means and standard deviations, empirical-margin exceedances, retention of capped successful fits, failure denominators, withholding of percentiles below 100, and Wilson limits. Zero out of 100 gives an upper 95% Wilson limit of approximately 0.0369935.
- Restart after removal of one dataset-level completion checkpoint reuses its completed model checkpoints and reconstructs its report. Changing to one worker preserves all 379 snapshotted source/checkpoint files' bytes and modification times. No model optimization is repeated in that restart.

These checks validate simulation mechanics, reporting, and restart behavior. They do not prove global optimization, structural identification, real-world validity of the model, or nominal confidence-interval coverage. The 100-per-generator production recovery is the scientific diagnostic still to be run.
