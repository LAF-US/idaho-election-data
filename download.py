#!/usr/bin/env python3
"""Download the canvass site's search exports, as the site serves them.

The site's search pages (Contests, Ballot Questions, Voter Statistics) each offer a CSV of their
results at two breakdowns (show_granularity_dt_id 3 = county, 7 = precinct). The site only offers
an export when a search has fewer than 1,000 results, so this asks for one year at a time, for
every even year in the site's year list (1990 through 2024). Before each year's export it reads
that year's search page and skips the export, as a failure, if the page says the search is over
the limit.

Each file goes in a folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR
"""
import hashlib, os, re, sys, urllib.parse, urllib.request

SITE = 'https://canvass.sos.idaho.gov'
TABS = ['contests', 'ballot_questions', 'voter_stats']
BREAKDOWNS = [3, 7]
FIRST, LAST = 1990, 2024
OVER_LIMIT = b'narrow your search'  # the site's text when a search has 1,000 results or more


def search_url(tab, year):
    return f'{SITE}/eng/{tab}/search/year_from:{year}/year_to:{year}'


def export_url(tab, year, breakdown):
    return f'{search_url(tab, year)}/show_granularity_dt_id:{breakdown}/.csv'


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'canvass-download'})
    with urllib.request.urlopen(req, timeout=900) as r:
        return r.headers, r.read()


def filename(url, headers):
    """The folder that mirrors the address, and the name the site gives the file."""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', headers.get('Content-Disposition', ''))
    path = urllib.parse.urlsplit(url).path.strip('/')
    if m:
        return path, os.path.basename(urllib.parse.unquote(m.group(1)))
    folder, _, last = path.rpartition('/')
    return folder, last or 'index'


def save(out, url, headers, body):
    folder, name = filename(url, headers)
    d = os.path.join(out, folder)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), 'wb') as f:
        f.write(body)
    first_line = body.split(b'\n', 1)[0][:200].decode('utf-8', 'replace')
    lines = body.count(b'\n')
    print(f'saved {os.path.join(folder, name)}: {len(body):,} bytes, {lines:,} lines, '
          f'sha256 {hashlib.sha256(body).hexdigest()[:12]}, first line: {first_line}', flush=True)


def get(out, url):
    try:
        headers, body = fetch(url)
    except Exception as e:
        print(f'FAILED {url}: {e}', flush=True)
        return None
    print(f'got {url} ({headers.get_content_type()})', flush=True)
    return headers, body


def main(out):
    failed = 0
    for tab in TABS:
        for year in range(FIRST, LAST + 1, 2):
            page = get(out, search_url(tab, year))
            if not page:
                failed += 1
                continue
            if OVER_LIMIT in page[1]:
                print(f'OVER THE LIMIT {search_url(tab, year)}: the site offers no export; skipped', flush=True)
                failed += 1
                continue
            for breakdown in BREAKDOWNS:
                url = export_url(tab, year, breakdown)
                got = get(out, url)
                if got:
                    save(out, url, *got)
                else:
                    failed += 1
    print(f'Done, {failed} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
