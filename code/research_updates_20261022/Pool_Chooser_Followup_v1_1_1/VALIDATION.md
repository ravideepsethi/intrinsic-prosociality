# Software validation

These are software checks on synthetic observations, not new empirical findings.

The unchanged benchmark's 22 numerical and pipeline tests pass. The follow-up's 14 tests pass, including analytic gradients for all eight state-model variants, weighted account likelihoods, brute-force enumeration of a short latent-state path, equality of sequential and joint likelihoods, exact static and independent-state embeddings, gate/willingness nesting in the relaxed model, absence of future-outcome leakage, fixed-factor restrictions, extreme utilities, reproducible simulation and rejection of altered/unsafe manifest entries. New regression checks verify equality of penalized objectives at the desert-to-both embedding and correct dependency/support matching for cross-starts.

A complete synthetic parent run with 160 development and 160 evaluation accounts and 36 opportunities per account was imported. The follow-up reproduced its archived scores, completed the boundary audit, repaired all ten original fits, estimated the four new static restrictions with inherited original complexity choices, and estimated all nine matched static/state models. New grid searches used J=1, ridge=.001, two starts and maxiter=800; inherited static fits include J=2. This checks the pipeline rather than production-grid statistical performance. All 108 supplied full-year starts across repair, challenge and switching passed the feasible-objective comparison.

Using Python's `spawn` multiprocessing mode, as used on macOS, repair, challenge and switching each completed two bootstrap draws, plus a third repair draw to check incremental continuation. Recovery uses one replication per scenario: seven scenarios for repair and challenge, five for switching. All these refit/recovery fits met the gradient and feasible-start criteria. Small synthetic fits did hit numerical bounds; those flags remained visible, and no percentile interval was emitted below 100 paired draws.

Resuming repair, bootstrap and recovery preserves all cached fit/draw files byte-for-byte and their modification times. SELECTED_FITS.json is deterministically rewritten with identical bytes. Raising the bootstrap budget from two to three adds exactly one draw cache. The parent producer files remain unchanged.

The optional perception adapter is also checked on the synthetic parent, including its matching/subsetting, original exact bin likelihood, bootstrap, recovery and counterfactual decomposition.

The released archive is unpacked and its internal checksums and numerical tests are checked from the unpacked directory. Shell launchers are parsed with Bash. No production refit, expanded search or switching estimate has been computed in this environment; the XT_Pro drive is needed for those runs. Production-scale resource use and model discrimination must be assessed from the user's run.
