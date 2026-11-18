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

Then it checks every number from 1 up to the highest number listed that has no saved folder in any
tab, because the site's own count (12,556 contests on its home page) is higher than what its search
pages list (12,530). For each such number it reads that number's page in each tab and saves any
download the page links; it prints what the site answered for numbers with nothing to save.

A contest whose download folder already exists in OUTDIR is skipped, so a later run picks up where
an earlier one stopped. The run stops starting new contests after MINUTES minutes.

Each file goes in a folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR [MINUTES]
"""
import concurrent.futures, hashlib, html, os, re, sys, time, urllib.error, urllib.parse, urllib.request

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


def get(url, tries=3):
    """The page, or None. A 5xx answer from the site is tried again after a pause."""
    for attempt in range(tries):
        try:
            return fetch(url)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        except Exception as e:
            if attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        time.sleep(15 * (attempt + 1))


def answer(url):
    """What the site gives for a page: ('ok', headers, body), ('http NNN', None, None) or ('failed', ...)."""
    for attempt in range(3):
        try:
            h, b = fetch(url)
            return 'ok', h, b
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                return f'http {e.code}', None, None
        except Exception as e:
            if attempt == 2:
                return f'failed ({e})', None, None
        time.sleep(15 * (attempt + 1))


def title(body):
    m = re.search(rb'<title>(.*?)</title>', body or b'', re.S)
    return html.unescape(m.group(1).decode('utf-8', 'replace')).strip() if m else ''


def saved(out, n):
    return any(os.path.isdir(os.path.join(out, 'eng', tab, 'download', str(n))) for tab in TABS)


def check_number(out, n):
    """Read number n's page in each tab; save what it links. Returns a line saying what happened."""
    seen = []
    for tab in TABS:
        state, h, body = answer(f'{SITE}/eng/{tab}/view/{n}')
        links = download_links(tab, body) if state == 'ok' else []
        if links:
            got = [(u, get(u)) for u in links]
            for u, g in got:
                if g:
                    save(out, u, *g)
            if all(g for _, g in got):
                return f'number {n}: {tab}, {title(body)}'
            return f'FAILED number {n}: {tab}, a download did not come down'
        seen.append(f'{tab} {state}' + (f' "{title(body)[:90]}"' if state == 'ok' else ''))
    return f'number {n}: nothing to save ({"; ".join(seen)})'


def sweep(out, last, stop_at, workers=4):
    todo = [n for n in range(1, last + 1) if not saved(out, n)]
    print(f'checking {len(todo)} numbers from 1 to {last} that have no saved folder', flush=True)
    found = failed = 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        futures = {}
        it = iter(todo)
        def submit():
            for n in it:
                if time.time() > stop_at:
                    return False
                futures[pool.submit(check_number, out, n)] = n
                return True
            return False
        for _ in range(workers * 2):
            submit()
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            for f in done:
                futures.pop(f)
                line = f.result()
                print(line, flush=True)
                if line.startswith('FAILED') or ' http 5' in line or 'failed (' in line:
                    failed += 1
                elif 'nothing to save' not in line:
                    found += 1
                submit()
    left = sum(1 for n in todo if not saved(out, n))
    print(f'number check: {found} contests found and saved, {failed} numbers the site did not answer', flush=True)
    if time.time() > stop_at:
        print('STOPPED at the time limit before checking every number. Run again to continue.', flush=True)
        return failed + 1
    return failed


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
    state, _, _ = answer(f'{SITE}/eng/contests/view/2')
    if state != 'ok':
        print(f'The site did not serve a known contest page ({SITE}/eng/contests/view/2: {state}). '
              f'Nothing downloaded; run again when the site is back.', flush=True)
        return 1
    stop_at = time.time() + minutes * 60
    failed = 0
    highest = 0
    for tab in TABS:
        numbers, f = list_contests(tab)
        failed += f
        highest = max([highest, *numbers])
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
    failed += sweep(out, highest, stop_at)
    print(f'Done, {failed} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) == 3 else 100))
