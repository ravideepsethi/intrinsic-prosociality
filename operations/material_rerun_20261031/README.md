# Offline publication checks and package preparation

Read [the checkpoint guide](../../docs/material_rerun_20261031/README.md) for
scope, current entry points, runtime guidance, and remaining analyses.

`verify_release.py` checks only the October 31 publication and root README.
It requires Python 3.10+ and Bash, uses no network, and does not execute the
published statistical code. Expected runtime: 10–60 seconds.

`prepare_package.py` authenticates an original local ZIP and restores all of
its members into a new directory outside the repository. The whole archive,
member inventory, original member hashes, and exact public template
transformations must agree. Expected runtime: under one minute on a local SSD.
It refuses existing output directories, symlinks in archives, and traversal.
It never launches the restored package.

The original archive is required because public snapshots omit private
configuration and input certificates. Do not hand-fill `.in` files and treat
them as the authenticated execution packages.
