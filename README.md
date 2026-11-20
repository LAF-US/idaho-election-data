# idaho-election-data

Idaho Secretary of State election results, saved as the state's sites serve them.

## Election-night results (results.voteidaho.gov)

`results.voteidaho.gov/` holds the files the election-night results site serves, in folders that mirror the site's addresses:

- `results/public/api/jurisdictions/id`: the site's list of elections. Each election's `publicElectionId` (`nov2026`, `may2026`, `dec2025`, `nov2025`) is the name used in the addresses below.
- `results/public/api/elections/id/<election>`: the election's status, including `asOf` (when the count was last updated), `isOfficialResults`, and the reports it publishes.
- `cdn/results/id/export-<election>.json`: the site's Media Export, linked from its Reports page. It holds every contest's statewide totals (`results`) and, for each of the 44 counties, every contest on that county's ballot with each candidate's precinct results (`localResults`).
- `cdn/results/<jurisdictionId>/<report>`: the PDF and Excel reports the election lists.

The status and export files keep their addresses and are replaced whenever the site serves something different, so this branch's history holds every version the site served. Report files get a new name for each version, so each is saved once.

`download_results.py` downloads the files. Each file is downloaded on its own under a temporary name and renamed once complete, so a download that stops partway never replaces a saved file, and one that fails doesn't stop the rest; the next run tries it again. The GitHub Actions workflow runs it and commits whatever changed.
