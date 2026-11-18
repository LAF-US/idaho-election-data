#!/usr/bin/env python3
"""Download every contest's own file from the canvass site, as the site serves it.

The site stores each race, ballot question and voter-statistics table as one numbered contest.
Each contest has its own page (/eng/TAB/view/N), and that page links the contest's own CSV
(/eng/TAB/download/N/show_granularity_dt_id:G/.csv) at the finest breakdown the contest has.

This reads each tab's search page one year at a time (every even year from 1990 through 2024) and
collects the contest numbers the page lists. A search page lists at most 1,000 contests; when a
year is over that limit, it reads that year one county at a time instead, with the site's own
county filter (filter_by_division_id), using the county numbers from the page's county list.
Then, for each contest number, it reads the contest's page and saves every download the page links.

A contest whose download folder already exists in OUTDIR is skipped, so a later run picks up where
an earlier one stopped. The run stops starting new contests after MINUTES minutes.

Each file goes in a folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR [MINUTES]
"""
import hashlib, os, re, sys, time, urllib.parse, urllib.request

SITE = 'https://canvass.sos.idaho.gov'
TABS = ['contests', 'ballot_questions', 'voter_stats']
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


def county_ids(page):
    """The site's number for each county, read from the county list on a search page."""
    found = {}
    for value, name in re.findall(rb'<option[^>]*value="(\d+)"[^>]*>\s*([^<]+?)\s*</option>', page):
        name = name.decode('utf-8', 'replace')
        if name in COUNTIES and name not in found:
            found[name] = value.decode()
    return found


def contest_numbers(tab, page):
    """The contest numbers a search page lists, from its links to each contest's page."""
    return {int(n) for n in re.findall(rf'/{tab}/view/(\d+)'.encode(), page)}


def download_links(tab, page):
    """The downloads a contest's page links."""
    return sorted({SITE + m.decode() for m in
                   re.findall(rf'/eng/{tab}/download/\d+/show_granularity_dt_id:\d+/\.csv'.encode(), page)})


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'canvass-download'})
    with urllib.request.urlopen(req, timeout=300) as r:
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
    print(f'saved {os.path.join(folder, name)}: {len(body):,} bytes, '
          f'sha256 {hashlib.sha256(body).hexdigest()[:12]}', flush=True)


def get(url):
    try:
        return fetch(url)
    except Exception as e:
        print(f'FAILED {url}: {e}', flush=True)
        return None


def list_contests(tab):
    """Every contest number the tab's search pages list. Returns (numbers, failures)."""
    numbers, failed = set(), 0
    for year in range(FIRST, LAST + 1, 2):
        search = search_url(tab, year)
        page = get(search)
        if not page:
            failed += 1
            continue
        if OVER_LIMIT not in page[1]:
            found = contest_numbers(tab, page[1])
            print(f'{tab} {year}: {len(found)} contests', flush=True)
            numbers |= found
            continue
        counties = county_ids(page[1])
        print(f'OVER THE LIMIT {search}: reading one county at a time '
              f'({len(counties)} of {len(COUNTIES)} counties found in the page)', flush=True)
        failed += len(COUNTIES) - len(counties)
        year_numbers = set()
        for name, county in counties.items():
            search = search_url(tab, year, county)
            page = get(search)
            if not page:
                failed += 1
            elif OVER_LIMIT in page[1]:
                print(f'OVER THE LIMIT {search} ({name}): skipped', flush=True)
                failed += 1
            else:
                year_numbers |= contest_numbers(tab, page[1])
        print(f'{tab} {year}: {len(year_numbers)} contests, read by county', flush=True)
        numbers |= year_numbers
    return numbers, failed


def main(out, minutes):
    stop_at = time.time() + minutes * 60
    failed = 0
    for tab in TABS:
        numbers, f = list_contests(tab)
        failed += f
        todo = [n for n in sorted(numbers)
                if not os.path.isdir(os.path.join(out, 'eng', tab, 'download', str(n)))]
        print(f'{tab}: {len(numbers)} contests listed, {len(numbers) - len(todo)} already saved, '
              f'{len(todo)} to download', flush=True)
        for i, n in enumerate(todo):
            if time.time() > stop_at:
                print(f'STOPPED at the {minutes}-minute limit: {len(todo) - i} {tab} contests left. '
                      f'Run again to continue.', flush=True)
                print(f'Done, {failed} failed.')
                return 1
            page = get(f'{SITE}/eng/{tab}/view/{n}')
            if not page:
                failed += 1
                continue
            links = download_links(tab, page[1])
            if not links:
                print(f'NO DOWNLOAD LINK on {SITE}/eng/{tab}/view/{n}', flush=True)
                failed += 1
            for url in links:
                got = get(url)
                if got:
                    save(out, url, *got)
                else:
                    failed += 1
    print(f'Done, {failed} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) == 3 else 100))
