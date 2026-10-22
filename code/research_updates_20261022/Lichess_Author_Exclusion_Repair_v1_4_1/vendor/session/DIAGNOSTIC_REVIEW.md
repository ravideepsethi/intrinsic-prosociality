# Timestamp diagnostic review

The uploaded ZIP SHA-256 is `54765b1b5ef1373f5739c954742e65cc7c9ce7111a427db7649431832a51e198`, matching its sidecar. Every report member matches the exported manifest's size and hash.

The June 2023 bullet source has 34,704,245 rows, 35 row groups, and the same footer signature as the historical manifest. The diagnostic's full-file hash is `5d76bdafcae9ec8e08d9eb1718491880cc0cb5a8a0fc19cf53d01cd180c61c50`. The historical manifest already recorded a minimum time of zero; this is not evidence of a newly damaged file.

There are 322 invalid-time rows: 321 null timestamps with null game IDs, and one zero timestamp with an empty-string game ID. The latter is the single record involving an analysis chooser. It has nonmissing remaining fields, distinct players, positive ratings, and a supported result code. Those fields do not prove a valid game or recover its time.

The cached invalid rows agree with the source. Only the target appears within three archive ordinals on either side; no valid neighboring timestamp was available there. The producer's declared upstream June bullet numeric partition is missing at the checked location. This does not establish that no other copy or raw source exists anywhere.

The API recovery must not be retried: there is no valid game key to send. No repair, model rerun, account exclusion or API request occurred in the diagnostic.

The next package therefore declares two count sensitivities, rather than inventing a game key or timestamp, silently excluding the chooser, or treating the existing strict verification gate as passed. It does not require another user-run diagnostic before estimating those sensitivities.
