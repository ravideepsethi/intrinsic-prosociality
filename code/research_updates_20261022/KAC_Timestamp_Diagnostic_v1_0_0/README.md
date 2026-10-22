# Targeted chronology diagnostic v1.0.0

The v1.0.2 recovery result completed all ten matched-receipt models and all three IV specifications. The history branch stopped with `RECOVERY_INVALID_GAME_KEY`. This diagnostic determines the stored key's format and checks available producer records before any repair is proposed.

Run `RUN_DIAGNOSTIC.command --threads 3` using the Terminal command supplied with this ZIP. It reuses an existing Python environment. Expected runtime: approximately 2–10 minutes on the existing external drive; up to 20 minutes if the upstream numeric partition is slow. This is an estimate, not a measured benchmark for this new diagnostic. A progress message appears every 30 seconds during the data reads.

The diagnostic:

- Uses the existing v1.0.2 cached bad-row and affected-chooser Parquets.
- Checks those bad rows against only the June 2023 bullet source, projecting columns through DuckDB.
- Separately identifies null timestamps, zero timestamps, malformed keys, whitespace and URL-shaped keys. It does not guess a normalized key.
- Recomputes the historical footer signature and hashes the 666 MB source file. The historical manifest already recorded a minimum timestamp of zero; a zero is not by itself evidence of recent damage.
- Reads the producer's command, success receipt and SQL log when present, then checks the same archive ordinal in the producer-declared June bullet numeric partition. If the upstream source is absent or unsuitable, it records that fact.
- Writes raw identifiers and any neighboring source rows only under a new `PRIVATE` directory on the external drive. The upload ZIP contains aggregate diagnostics and key formats, with no game/account identifiers.
- Applies no repair, imputes no timestamps, excludes no accounts, makes no API requests and reruns no models. No raw PGN decompression or whole-history scan is performed.

The known v1.0.2 and original companion run locks must be available. The diagnostic then uses at most three DuckDB threads and a 2 GB memory limit. Numerical and Arrow thread pools are limited to one. Existing data and result files are read only.

Upload the printed `KAC_TIMESTAMP_DIAGNOSTIC_RESULT_....zip` and its `.zip.sha256`. A `DIAGNOSTIC_COMPLETE_REPAIR_NOT_APPLIED` status means the inspection finished; it does not mean the repetition analysis has run.

The accompanying `RESULTS_REVIEW.md` summarizes the verified statistical results and remaining manuscript tasks. Author-account exclusion remains a separate unresolved sample amendment.
