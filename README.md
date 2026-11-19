# idaho-election-data

Idaho Secretary of State canvass results (https://canvass.sos.idaho.gov), saved as the site presents them.

- `canvass.sos.idaho.gov/` holds every file as downloaded: each contest's own file (`eng/{contests,ballot_questions,voter_stats}/download/{number}/...`) and the search exports (`eng/*/search/...`).
- `results.sqlite` holds every number from the contest files in one database. Query the `results` view: one row per contest file, place and candidate, with the file's path so any number can be checked against its source. `totals` holds each file's own Totals row.
- `CHECK.txt` lists every place where a contest file's rows don't add up to that file's own Totals row or county row.
- `download.py` downloads the files; `build_db.py` builds `results.sqlite` and `CHECK.txt` from them. The GitHub Actions workflow runs both.

Example:

```sql
SELECT county, place, candidate, votes FROM results
WHERE number = 20485 AND breakdown = 'precinct' AND place LIKE '%Arco 1%';
```
