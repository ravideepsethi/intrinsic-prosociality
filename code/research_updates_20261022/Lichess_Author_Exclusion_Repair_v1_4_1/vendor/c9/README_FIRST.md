# Pool-main C9 fresh randomization v1.0.0

Run the recovered original C9 producer on the certified new main sample.
Read `C9_POOL_MAIN_REBINDING.md` for the exact scope and remaining caveats.

Save the ZIP and its sidecar to `~/Desktop/Lichess_Desktop`, then paste the
whole block in `RUN_COMMAND.txt` into Terminal. Expect **45-120 minutes** on
the usual ten-worker setup, with uncertainty mainly from all-game session
construction and external-drive throughput. Allow 80 GiB free on XT_Pro.

The package needs the completed Wave 2B1 inputs, executed B2 script, and B2
reference checkpoints. It finds the existing Python environment automatically
and installs nothing. The self-tests run first, followed by authentication,
session construction, fresh C9 draws, exact B2 reproduction and collection.

The output is `POOL_MAIN_C9_FRESH_RESULTS_<UTC>_<configuration>.zip` and its
`.sha256` sidecar on the Desktop. Upload both. The same command resumes after
interruption. Do not launch a second concurrent C9 run.

To change resource limits before launching, use `POOL_MAIN_C9_WORKERS` (1-10)
and `POOL_MAIN_C9_MEMORY` (default `12GB`). `POOL_MAIN_PYTHON` can explicitly
select the compatible interpreter already used for Wave 2B1. No API requests
or profile reads occur.

This is the original 30-minute-session C9 primary plus its two secondary
contrasts. Ply, 15/60-minute session sensitivities and Holm closure remain open.
