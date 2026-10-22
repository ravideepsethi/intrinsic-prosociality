Lichess Social Contact v1.0.0 -- October 5, 2026

QUESTION
After a pool encounter, do the two players have more subsequent contact when
the connected player granted a draw rather than claimed a win? Include rated
and casual games, all speeds and variants, and separate known non-pool games.
Repeated contact is a behavioral measure, not proof of a formal friendship
or of a motive the giver anticipated when acting.

RUN
Save the ZIP in ~/Desktop/Lichess_Desktop and use the supplied checksum-
verifying Terminal block. RUN_SOCIAL_CONTACT.command selects an existing
Python with NumPy, PyArrow and DuckDB, checks offline fixtures, logs to the
Desktop folder, and uses caffeinate. It installs nothing and needs no token.

RUNTIME
Default: at most 20,000 matched sets = 40,000 pair-history requests.
Planning estimate: 12-36 hours plus local preparation, UNBENCHMARKED against
the live API for this program. The one-second request spacing alone is
11.1 hours at the maximum roster. Latency, throttling and fewer eligible
matches can change this substantially. The program prints the actual target
count, then measured ETAs to the next milestone and completion. All 25/50/
75/100% milestones continue automatically. It makes one request at a time.
HTTP 429 waits at least 60 seconds. There is no paid API service.

Allow about 4-8 GiB RAM and 10 GiB additional disk as unmeasured planning
allowances. The 4096 MB DuckDB setting is not a total process memory cap.
Four local DuckDB threads are used; increasing workers does not parallelize
network requests. Raw API responses and normalized pair records are cached
per request; preparation and batch outcome files are Parquet checkpoints.
Rerunning the command reuses successful requests. A stopped transport run
does not erase earlier work. --retry-unavailable retries previously recorded
unavailable histories; successful histories remain cached.

REUSE
Requires the completed Lichess Reputation v1.0.0 run whose public report was
LICHESS_REPUTATION_REPORT_1d4e350c2249_20261005T224542Z.zip, SHA-256
0353ae6bc074c2ac21c8954a197f830a265bac3c409c80857786e4ea48865439.
It checks the scientific parent reports and completed private checkpoints,
then reuses their focal features and 9.54 million matched chronology rows.
There is no new scan of the 7.2 billion historical source rows, Stockfish
evaluation, rating replay, or cohort reconstruction. Original files remain
read-only. A projected read of main-panel account names resolves the roster.
New files live in derived/replication/social_contact_v100_PRIVATE.

DESIGN
Eligibility: first recorded rated meeting, no tied first starts, and complete
180-day follow-up in the parent's existing one-in-five unordered-pair sample.
Both author accounts remain excluded from focal data.
Match within chooser, calendar quarter, speed and five evaluation bands.
Select one grant and one claim in each eligible cell using fixed hashes,
then take up to 20,000 cells by a separate fixed hash. No future contact is
used in selection. This estimates a comparison in the overlap population,
not an average for all granters or all opportunities. Attrition is reported.

For each selected pair, public game export is filtered by opponent and date.
No rated, speed, variant, or maximum-game filter is supplied. The returned
records are filtered locally to 90 days before and 180 days after the focal
event. Completed casual and rated games are retained across all variants;
aborted/not-started games and imported/relay records are excluded.
The focal game and all known rated games in the query window must reappear
with the right accounts, times and rated flag. Failed verification is missing
history, not a zero. Casual completeness cannot be independently certified.

OUTCOMES
Any later game; rated; casual; known non-pool; rated non-pool; casual non-pool;
source=friend; source=pool; lobby; organized competition. Follow-up windows
are 7/30/90/180 days. The 90-day table also separates contacts after the first
hour and after the first week. Counts, distinct UTC dates, and contact spread
over at least a week are reported, including repeated known non-pool play.

Source=friend is a game-source label, not evidence that one player followed
the other. Non-pool includes tournament and lobby games, so it does not by
itself identify deliberate opponent choice. Pool labels are not treated as
proof of accidental matching or as proof that a rematch did not occur.

FORMAL FRIENDSHIP
This package has no dated follow-edge history for these pairs. It makes no
follow/unfollow calls and does not label repeated play as confirmed friendship.
Dated directed link additions/removals and pre-event relationship states
would be needed to estimate formal friendship formation. The report keeps
that outcome explicitly NOT_OBSERVED.

RETURN
LICHESS_SOCIAL_CONTACT_REPORT_*.zip and its .sha256 from the Desktop folder.
If it stops, also return the Desktop .log. Reports contain aggregate outcomes,
not account names or private row-level histories. LOCAL_RATED_CONTACTS.csv
is calculated before the network pass for the selected matched population.
contact_rates_and_missing_bounds.csv reports bounds for the full selected
roster. matched_estimates.csv gives raw and adjusted within-chooser matched
comparisons; balance.csv reports remaining measured differences.

OVERRIDES
  SOCIAL_CONTACT_PYTHON=/absolute/path/python /bin/bash RUN_SOCIAL_CONTACT.command
  SOCIAL_CONTACT_PROJECT_ROOT=/path/to/lichess_kindness /bin/bash RUN_SOCIAL_CONTACT.command
  /bin/bash RUN_SOCIAL_CONTACT.command --max-sets 20000 --workers 4 --memory-mb 4096

Offline fixtures passed; live API and private Mac data are checked at runtime.
See METHODS.txt for inference, selection, and missing-data interpretation.
