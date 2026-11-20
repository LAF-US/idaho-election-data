#!/usr/bin/env python3
"""Download the Idaho election-night results site's files, as the site serves them.

results.voteidaho.gov lists its elections in one JSON file:
  /results/public/api/jurisdictions/id                   the site's elections (publicElectionId, date, name)
For each election it serves:
  /results/public/api/elections/id/<ELECTION>            the election's status: asOf, isOfficialResults,
                                                         and the reports it publishes
  /cdn/results/id/export-<ELECTION>.json                 the site's "Media Export": every contest's
                                                         statewide totals and, for each of the 44
                                                         counties, every contest on its ballot with
                                                         precinct results
  /cdn/results/<jurisdictionId>/<blobName>               each report the election's status lists in
                                                         publicReportCategories (PDF and Excel), as linked
                                                         from the site's Reports page

Each file goes in a folder that mirrors its address on the site (results.voteidaho.gov/...). The
JSON files keep their addresses, and a file is replaced only when the site serves something different,
so the repo's history keeps every version the site served. Report files carry a new name for each
version, so each is downloaded once and never replaced.

Each file is downloaded on its own and written under a temporary name, then renamed once complete,
so a download that stops partway never replaces a saved file. A file that fails doesn't stop the
others; the next run tries it again.

  python3 download_results.py OUTDIR
"""
import hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request

SITE = 'https://results.voteidaho.gov'
ELECTIONS = SITE + '/results/public/api/jurisdictions/id'
STATUS = SITE + '/results/public/api/elections/id/{election}'
EXPORT = SITE + '/cdn/results/id/export-{election}.json'


def fetch(url, tries=3):
    """The body, or None after printing why. A 5xx answer or a dropped connection is tried again."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'idaho-election-data'})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
                if r.status != 200 or not body:
                    print(f'FAILED {url}: HTTP {r.status}, {len(body)} bytes', flush=True)
                    return None
                return body
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        except Exception as e:
            if attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        time.sleep(15 * (attempt + 1))


def path_for(out, url):
    p = urllib.parse.urlsplit(url)
    return os.path.join(out, p.netloc, urllib.parse.unquote(p.path).strip('/'))


def save(out, url, body):
    """Write body to the file that mirrors url, unless that file already holds exactly this. True if written."""
    path = path_for(out, url)
    if os.path.isfile(path) and open(path, 'rb').read() == body:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.part', 'wb') as f:
        f.write(body)
    os.replace(path + '.part', path)
    print(f'saved {os.path.relpath(path, out)}: {len(body):,} bytes, '
          f'sha256 {hashlib.sha256(body).hexdigest()[:12]}', flush=True)
    return True


def get_json(out, url):
    """Download url, save it, and return it parsed; None if it couldn't be downloaded or read."""
    body = fetch(url)
    if body is None:
        return None
    try:
        j = json.loads(body)
    except ValueError:
        print(f'FAILED {url}: not JSON ({body[:60]!r})', flush=True)
        return None
    save(out, url, body)
    return j


def reports(status):
    """The address of every report file the election's status lists."""
    folder = status.get('jurisdictionId')
    for cat in status.get('publicReportCategories') or []:
        for rep in cat.get('reports') or []:
            for f in [rep] + (rep.get('versions') or []):
                if folder and f.get('blobName'):
                    yield f'{SITE}/cdn/results/{folder}/{urllib.parse.quote(f["blobName"])}'


def main(out):
    failed = 0
    site = get_json(out, ELECTIONS)
    if site is None:
        print('The site did not serve its list of elections. Nothing downloaded; run again later.', flush=True)
        return 1
    elections = [e['publicElectionId'] for e in site.get('elections') or [] if e.get('publicElectionId')]
    print(f'{len(elections)} elections listed: {", ".join(elections)}', flush=True)
    for election in elections:
        status = get_json(out, STATUS.format(election=election))
        if status is None:
            failed += 1
        export = fetch(EXPORT.format(election=election))
        if export is None:
            failed += 1
        else:
            save(out, EXPORT.format(election=election), export)
        for url in reports(status or {}):
            if os.path.isfile(path_for(out, url)):
                continue
            body = fetch(url)
            if body is None:
                failed += 1
            else:
                save(out, url, body)
    print(f'Done, {failed} failed.', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
