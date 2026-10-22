# Validation

The inherited five numerical tests passed on 2026-09-17: bin boundaries including exact zero and tiny signed values; coefficients and chooser-clustered covariance against full dummy OLS; raw covariance and central contrasts; complete-chooser streaming/shards; zero audit and prior JSON-array reading.

Three RD-specific tests also passed: inclusive <=75 applied to both players with no K or outcome filter; reading the correct prior RD75 counts; and filtered coefficients and cluster covariance against dense dummy OLS after recomputing singleton removal.

A two-worker synthetic integration passed for both samples and the combined report. It verified restricted sample counts, separate checkpoints, identical resumed curves, preservation of the full-sample curve, and generation of all eight paired PNG/PDF figures. Synthetic outputs are test fixtures, not research results.

The production panel is on the user's XT_Pro drive and was not re-estimated in this environment. Runtime gates will verify the input hashes, exact prior RD75 sample counts, old central-bin partition, and unchanged gap estimates. A success marker is written only after those gates and figure/report generation complete.
