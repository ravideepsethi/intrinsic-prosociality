# C14A numerical-receipt serialization correction

The authenticated historical file
`c14a_monthly_chooser_fe_numerics.json.original_malformed` ends with the two
literal characters `\n` after its closing JSON brace. Its SHA-256 is
`a933f0b74949cd70ae35c94bca8a6e3f6d761031162d04c849f7acb627ac2066`,
which matches `report_file_hashes_original.tsv` exactly.

For public usability, `c14a_monthly_chooser_fe_numerics.json` removes those two
literal characters and terminates the file with an ordinary newline. No JSON
key or value changed. `report_file_hashes.tsv` authenticates that corrected
copy and all other Wave 0 report files. The original bytes and original
manifest remain beside it for auditability.
