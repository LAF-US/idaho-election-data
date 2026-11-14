#!/usr/bin/env python3
"""Download the canvass site's search exports, as the site serves them.

The site's search pages (Contests, Ballot Questions, Voter Statistics) each offer a CSV of their
results, and the address takes a year range. This asks for 1990 through 2024 (the site's whole
year list) at both breakdowns the pages link to (show_granularity_dt_id 3 and 7). If one export
comes back too big for GitHub (over 95 MB), it asks for that export one year at a time instead.

Each file goes in a folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR
"""
import hashlib, os, re, sys, urllib.parse, urllib.request

SITE = 'https://canvass.sos.idaho.gov'
TABS = ['contests', 'ballot_questions', 'voter_stats']
BREAKDOWNS = [3, 7]
FIRST, LAST = 1990, 2024
TOO_BIG = 95_000_000  # GitHub refuses files over 100 MB


def export_url(tab, breakdown, first, last):
    return f'{SITE}/eng/{tab}/search/year_from:{first}/year_to:{last}/show_granularity_dt_id:{breakdown}/.csv'


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
        for breakdown in BREAKDOWNS:
            url = export_url(tab, breakdown, FIRST, LAST)
            got = get(out, url)
            if got and len(got[1]) <= TOO_BIG:
                save(out, url, *got)
                continue
            if got:
                print(f'{url} is {len(got[1]):,} bytes, too big for GitHub; asking one year at a time', flush=True)
            for year in range(FIRST, LAST + 1, 2):
                url = export_url(tab, breakdown, year, year)
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
