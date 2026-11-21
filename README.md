# idaho-election-data

Idaho Secretary of State election results, saved as the state's sites serve them.

## Election-night results (results.voteidaho.gov)

`results.voteidaho.gov/` holds the files the election-night results site serves, in folders that mirror the site's addresses:

- `results/public/api/jurisdictions/id`: the site's list of elections. Each election's `publicElectionId` (`nov2026`, `may2026`, `dec2025`, `nov2025`) is the name used in the addresses below.
- `results/public/api/elections/id/<election>`: the election's status, including `asOf` (when the count was last updated), `isOfficialResults`, and the reports it publishes.
- `cdn/results/id/export-<election>.json`: the site's Media Export, linked from its Reports page. It holds every contest's statewide totals (`results`) and, for each county the export includes, every contest on that county's ballot with each candidate's precinct results (`localResults`).
- `cdn/results/<jurisdictionId>/<report>`: the PDF and Excel reports the election lists.

The status and export files keep their addresses and are replaced whenever a run gets something different, so this branch's history holds every version a run got. A version the site served only between two runs isn't kept. Report files get a new name for each version, so each is saved once.

`download_results.py` downloads the files. Each file is downloaded on its own under a temporary name and renamed once complete, so a download that stops partway never replaces a saved file, and one that fails doesn't stop the rest; the next run tries it again. The GitHub Actions workflow runs it and commits whatever changed.

## Schedule

The workflow wakes every hour and runs `download_results.py --scheduled`, which pulls only what is due, from the current time and its tracking files (`results_daily.txt`, `results_official.txt`, `results_monthly.txt`). In the first 24 hours after poll close, that hourly run keeps going and pulls about every 5 minutes for 55 minutes after it starts; a slow run or a late start shifts those times. At any other time nothing runs every 5 minutes.

- **Election nights:** election days come from Idaho Code 34-106(1), the third Tuesday in May and the Tuesday following the first Monday in November. From poll close (9 PM Mountain, America/Boise time) that election is pulled every 5 minutes for the first 24 hours, then every hour until 72 hours after poll close.
- **Until official:** after that, once a day, from the 15:00 UTC run (if that run is late or fails, the next run that day tries again; `results_daily.txt` keeps the day), until its status says `isOfficialResults` and a run has pulled all its files after that (that run writes the election to `results_official.txt`), or 45 days after poll close.
- **Monthly:** from 15:00 UTC on the 1st, every election the site lists. The run that finishes it without a failure writes the month to `results_monthly.txt`; until one does, each hourly run tries again.
- **By hand:** Actions > Download election-night results > Run workflow pulls every election the site lists.

GitHub runs scheduled workflows only from the default branch, so the schedule starts once this is on `main`.
