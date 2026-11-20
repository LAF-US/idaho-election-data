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

With --scheduled, it pulls only what your schedule calls for at this hour (the workflow runs it every
hour), from the date alone:
  - Election days come from Idaho Code 34-106(1): the third Tuesday in May and the Tuesday following
    the first Monday in November, every year.
  - From poll close on election day (9 PM Mountain, America/Boise time) for 72 hours: that election,
    every hour. For the first 24 hours, --every-5-minutes (the workflow runs it every 5 minutes) also
    pulls it, and pulls nothing at any other time.
  - After that: that election once a day (the 15:00 UTC run), until its saved status says
    isOfficialResults, or 45 days after poll close, whichever comes first.
  - Every month, from the 15:00 UTC run on the 1st: every election the site lists. The run that pulls
    all of it without a failure writes the month to OUTDIR/results_monthly.txt; until one does, each
    hourly run tries again, so a late or dropped run on the 1st doesn't skip the month.
Without --scheduled, it pulls every election the site lists.

  python3 download_results.py OUTDIR [--scheduled | --every-5-minutes]
"""
import calendar, datetime as dt, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request, zoneinfo

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


HOURLY_DAYS, DAILY_HOUR, MAX_DAYS, FIVE_MINUTE_HOURS = 3, 15, 45, 24
BOISE, POLLS_CLOSE = zoneinfo.ZoneInfo('America/Boise'), 21   # 9 PM Mountain
MONTHLY = 'results_monthly.txt'
MON = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def election_days(year):
    """Idaho Code 34-106(1): the third Tuesday in May; the Tuesday following the first Monday in November."""
    def nth(month, weekday, n):
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    return [nth(5, calendar.TUESDAY, 3), nth(11, calendar.MONDAY, 1) + dt.timedelta(days=1)]


def is_official(out, election):
    path = path_for(out, STATUS.format(election=election))
    try:
        return bool(json.load(open(path)).get('isOfficialResults'))
    except (OSError, ValueError):
        return False


def monthly_due(out, now):
    if now.day == 1 and now.hour < DAILY_HOUR:
        return False
    try:
        done = open(os.path.join(out, MONTHLY)).read().strip()
    except OSError:
        done = ''
    return done != f'{now:%Y-%m}'


def window(out, now):
    """The elections in an election-day window at this hour: hourly for 72 hours from poll close, then
    the 15:00 UTC run each day until the saved status says official, or 45 days after poll close."""
    found = []
    for day in election_days(now.year - 1) + election_days(now.year):
        election = f'{MON[day.month - 1]}{day.year}'
        start = dt.datetime(day.year, day.month, day.day, POLLS_CLOSE, tzinfo=BOISE).astimezone(dt.timezone.utc)
        age = now - start
        if dt.timedelta(0) <= age < dt.timedelta(days=HOURLY_DAYS):
            found.append(election)
        elif dt.timedelta(days=HOURLY_DAYS) <= age < dt.timedelta(days=MAX_DAYS) and now.hour == DAILY_HOUR \
                and not is_official(out, election):
            found.append(election)
    return found


def first_day(now):
    """The elections within 24 hours of poll close, which the 5-minute run pulls."""
    found = []
    for day in election_days(now.year - 1) + election_days(now.year):
        start = dt.datetime(day.year, day.month, day.day, POLLS_CLOSE, tzinfo=BOISE).astimezone(dt.timezone.utc)
        if dt.timedelta(0) <= now - start < dt.timedelta(hours=FIVE_MINUTE_HOURS):
            found.append(f'{MON[day.month - 1]}{day.year}')
    return found


def main(out, scheduled=False, now=None, every_5=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if every_5:
        scheduled = True
    monthly = scheduled and not every_5 and monthly_due(out, now)
    wanted = (first_day(now) if every_5 else window(out, now)) if scheduled else []
    if scheduled and not monthly and not wanted:
        print(f'Nothing due at {now:%Y-%m-%d %H:%M} UTC.', flush=True)
        return 0
    failed = 0
    site = get_json(out, ELECTIONS)
    if site is None:
        print('The site did not serve its list of elections. Nothing downloaded; run again later.', flush=True)
        return 1
    elections = [e['publicElectionId'] for e in site.get('elections') or [] if e.get('publicElectionId')]
    print(f'{len(elections)} elections listed: {", ".join(elections)}', flush=True)
    if scheduled and not monthly:
        missing = [e for e in wanted if e not in elections]
        if missing:
            print(f'In its election window but not listed by the site: {", ".join(missing)}', flush=True)
        elections = [e for e in elections if e in wanted]
        print(f'Due this hour: {", ".join(elections) or "none the site lists"}', flush=True)
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
    if monthly and not failed:
        with open(os.path.join(out, MONTHLY), 'w') as f:
            f.write(f'{now:%Y-%m}\n')
        print(f'Monthly pull for {now:%Y-%m} done.', flush=True)
    print(f'Done, {failed} failed.', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    flags = {'--scheduled', '--every-5-minutes'}
    args = [a for a in sys.argv[1:] if a not in flags]
    if len(args) != 1 or len(flags & set(sys.argv[1:])) > 1:
        sys.exit(__doc__)
    sys.exit(main(args[0], scheduled='--scheduled' in sys.argv[1:], every_5='--every-5-minutes' in sys.argv[1:]))
