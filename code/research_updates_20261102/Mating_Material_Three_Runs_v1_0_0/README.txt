Three Authorized Analyses — revised November 1 RA note

This replaces Mating_Material_Retained_Analyses_v1_0_0 for the revised scope.
Run only RUN_THREE.command. Expected first run: 2–4 hours provisionally;
external-drive I/O may extend this. Startup tests: about 1–2 minutes.
The command prints Toronto start and finish estimates, with EDT/EST labels.
Needs 80 GiB free. Uses at most 10 workers and 11 GiB; heavy stages are sequential.

New computation is limited to:
1. The balance ladder, spaced diagnostic frames and implied-bias projection.
2. Receipt effects by position with the two stake interactions.
3. Spaced-design complier characteristics.

The exact delivered 3,103,311 exposure rows are reused and their hash, recipient
count and draw-receipt count are checked. The primary sample is not rebuilt.
The four dropped analysis families have no stage or CLI option in this runner.
The strict-material without-ENV row is an archive gap, not an extra scheduled fit.
Other companion models/counts outside the three runs are explicitly pending if
not found in the supplied CSV/JSON archives. No archived value is substituted.

Put the ZIP in ~/Desktop/Lichess_Desktop, extract it there and run:
bash "$HOME/Desktop/Lichess_Desktop/Mating_Material_Three_Runs_v1_0_0/RUN_THREE.command"

It reuses the completed material/IV/closeout inputs on XT_Pro. New checkpoints
are isolated under derived/replication/mating_material_three_runs_v100_PRIVATE.
The command resumes its own verified completed stages. It does not delete the
previous broader run or reuse any of its now-excluded results. Production analysis
is offline; pinned dependency installation may use the network once.

Return MATERIAL_THREE_RUNS_<configuration>_RETURN.zip from Lichess_Desktop.
A return archive is written after each stage. Failures preserve checkpoints and
allow independent requested stages to proceed. Export requires all three families.
The return includes table CSVs, raw new numerical outputs, METHOD files, source
links, checksums and per-cell reconciliation. Private row-level data stay local.

The unchanged full IV return archive has already been supplied separately;
its SHA256 is included under evidence/. This package contains no manuscript
rewrite. Paper completion still requires review, resolving explicitly pending
items and figure mapping, and manuscript/PDF integration.
