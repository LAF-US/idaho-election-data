#!/usr/bin/env python3
"""Download the canvass site's search exports, as the site serves them.

The site's search pages (Contests, Ballot Questions, Voter Statistics) each offer a CSV of their
results at two breakdowns (show_granularity_dt_id 3 = county, 7 = precinct). The site only offers
an export when a search has fewer than 1,000 results, so this asks for one year at a time, for
every even year in the site's year list (1990 through 2024). Before each year's export it reads
that year's search page. If the page says the search is over the limit, it asks for that year one
county at a time instead, with the site's own county filter (filter_by_division_id), using the
county numbers from the page's county list. A county search that is still over the limit is
skipped, as a failure.

Each file goes in a folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR
"""
import hashlib, os, re, sys, urllib.parse, urllib.request

SITE = 'https://canvass.sos.idaho.gov'
TABS = ['contests', 'ballot_questions', 'voter_stats']
BREAKDOWNS = [3, 7]
FIRST, LAST = 1990, 2024
OVER_LIMIT = b'narrow your search'  # the site's text when a search has 1,000 results or more


COUNTIES = ['Ada', 'Adams', 'Bannock', 'Bear Lake', 'Benewah', 'Bingham', 'Blaine', 'Boise',
            'Bonner', 'Bonneville', 'Boundary', 'Butte', 'Camas', 'Canyon', 'Caribou', 'Cassia',
            'Clark', 'Clearwater', 'Custer', 'Elmore', 'Franklin', 'Fremont', 'Gem', 'Gooding',
            'Idaho', 'Jefferson', 'Jerome', 'Kootenai', 'Latah', 'Lemhi', 'Lewis', 'Lincoln',
            'Madison', 'Minidoka', 'Nez Perce', 'Oneida', 'Owyhee', 'Payette', 'Power', 'Shoshone',
            'Teton', 'Twin Falls', 'Valley', 'Washington']


def search_url(tab, year, county=None):
    url = f'{SITE}/eng/{tab}/search/year_from:{year}/year_to:{year}'
    return f'{url}/filter_by_division_id:{county}' if county else url


def export_url(search, breakdown):
    return f'{search}/show_granularity_dt_id:{breakdown}/.csv'


def county_ids(page):
    """The site's number for each county, read from the county list on a search page."""
    found = {}
    for value, name in re.findall(rb'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', page):
        name = name.decode('utf-8', 'replace')
        if name in COUNTIES and name not in found:
            found[name] = value.decode()
    return found


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


def exports(out, search):
    """Save a search's exports. Returns the number of failures."""
    failed = 0
    for breakdown in BREAKDOWNS:
        url = export_url(search, breakdown)
        got = get(out, url)
        if got:
            save(out, url, *got)
        else:
            failed += 1
    return failed


def main(out):
    failed = 0
    for tab in TABS:
        for year in range(FIRST, LAST + 1, 2):
            search = search_url(tab, year)
            page = get(out, search)
            if not page:
                failed += 1
                continue
            if OVER_LIMIT not in page[1]:
                failed += exports(out, search)
                continue
            counties = county_ids(page[1])
            print(f'OVER THE LIMIT {search}: asking one county at a time '
                  f'({len(counties)} of {len(COUNTIES)} counties found in the page)', flush=True)
            failed += len(COUNTIES) - len(counties)
            for name, county in counties.items():
                search = search_url(tab, year, county)
                page = get(out, search)
                if not page:
                    failed += 1
                elif OVER_LIMIT in page[1]:
                    print(f'OVER THE LIMIT {search} ({name}): skipped', flush=True)
                    failed += 1
                else:
                    failed += exports(out, search)
    print(f'Done, {failed} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
