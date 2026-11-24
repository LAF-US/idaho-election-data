# idaho-election-data

Idaho Secretary of State election results, saved as the state's sites serve them.

## Official canvass results (canvass.sos.idaho.gov)

- `canvass.sos.idaho.gov/` holds every file as downloaded: each contest's own file (`eng/{contests,ballot_questions,voter_stats}/download/{number}/...`) and the search exports (`eng/*/search/...`), which an earlier version of `download.py` saved. `canvass.sos.idaho.gov/numbers_with_nothing_to_save.txt` lists the contest numbers the site answered with nothing to download in every tab, so the next run doesn't check them again.
- `results.sqlite` holds every number from the contest files in one database. Query the `results` view: one row per contest file, place and candidate, with the file's path so any number can be checked against its source. `totals` holds each file's own Totals row.
- `CHECK.txt` lists every place where a contest file's rows don't add up to that file's own Totals row or county row.
- `download.py` downloads each contest's own file (not the search exports); `build_db.py` builds `results.sqlite` and `CHECK.txt` from them. The Download canvass site workflow runs both.

Example:

```sql
SELECT county, place, candidate, votes FROM results
WHERE number = 20485 AND breakdown = 'precinct' AND place LIKE '%Arco 1%';
```

## Election-night results (results.voteidaho.gov)

`results.voteidaho.gov/` holds the files the election-night results site serves, in folders that mirror the site's addresses:

- `results/public/api/jurisdictions/id`: the site's list of elections. Each election's `publicElectionId` (`nov2026`, `may2026`, `dec2025`, `nov2025`) is the name used in the addresses below.
- `results/public/api/elections/id/<election>`: the election's status, including `asOf` (when the count was last updated), `isOfficialResults`, and the reports it publishes.
- `cdn/results/id/export-<election>.json`: the site's Media Export, linked from its Reports page. It holds every contest's statewide totals (`results`) and, for each county the export includes, every contest on that county's ballot with each candidate's precinct results (`localResults`).
- `cdn/results/<jurisdictionId>/<report>`: the PDF and Excel reports the election lists.

The status and export files keep their addresses and are replaced whenever a run gets something different, so this branch's history holds every version a run got. A version the site served only between two runs isn't kept. Report files get a new name for each version, so each is saved once.

`download_results.py` downloads the files. Each file is downloaded on its own under a temporary name and renamed once complete, so a download that stops partway never replaces a saved file, and one that fails doesn't stop the rest; the next run tries it again. The Download election-night results workflow runs it and commits whatever changed.

## Schedule

That workflow wakes every hour and runs `download_results.py --scheduled`, which pulls only what is due, from the current time and its tracking files (`results_daily.txt`, `results_official.txt`). In the first 24 hours after poll close, that hourly run keeps going and pulls about every 5 minutes for 55 minutes after it starts; a slow run or a late start shifts those times. At any other time nothing runs every 5 minutes.

- **Election nights:** election days come from Idaho Code 34-106(1), the third Tuesday in May and the Tuesday following the first Monday in November, and from the date of every election the site lists, which adds special and runoff elections. Each hourly run saves the site's list first, so an election counts from the first run after the site lists it. From poll close (9 PM Mountain, America/Boise time) that election is pulled every 5 minutes for the first 24 hours, then every hour until 72 hours after poll close.
- **Until official:** after that, once a day, from the 15:00 UTC run (if that run is late or fails, the next run that day tries again; `results_daily.txt` keeps the day), until its status says `isOfficialResults` and a run has pulled all its files after that (that run writes the election to `results_official.txt`), or 45 days after poll close.
- **By hand:** Actions > Download election-night results > Run workflow pulls every election the site lists.

GitHub runs scheduled workflows only from the default branch, so the schedule runs from `main`. Every run saves the files it downloads to the `results` branch, not `main`.
