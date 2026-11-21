#!/usr/bin/env python3
"""Download the Idaho election-night results site's files, as the site serves them.

results.voteidaho.gov lists its elections in one JSON file:
  /results/public/api/jurisdictions/id                   the site's elections (publicElectionId, date, name)
For each election it serves:
  /results/public/api/elections/id/<ELECTION>            the election's status: asOf, isOfficialResults,
                                                         and the reports it publishes
  /cdn/results/id/export-<ELECTION>.json                 the site's "Media Export": every contest's
                                                         statewide totals and, for each county in
                                                         the export, every contest on its ballot
                                                         with precinct results
  /cdn/results/<jurisdictionId>/<blobName>               each report the election's status lists in
                                                         publicReportCategories (PDF and Excel), as linked
                                                         from the site's Reports page

Each file goes in a folder that mirrors its address on the site (results.voteidaho.gov/...). The
JSON files keep their addresses, and a file is replaced only when the site serves something different,
so the repo's history keeps every version a run saw. Report files carry a new name for each
version, so each is downloaded once and never replaced.

Each file is downloaded on its own and written under a temporary name, then renamed once complete,
so a download that stops partway never replaces a saved file. A file that fails doesn't stop the
others; the next run tries it again.

With --scheduled, it pulls only what your schedule calls for at this hour (the workflow runs it every
hour), from the current time and its tracking files:
  - Election days come from Idaho Code 34-106(1), the third Tuesday in May and the Tuesday following
    the first Monday in November, every year, and from the electionDate of every election the site
    lists, which adds special and runoff elections. Each run saves the site's list first.
  - From poll close on election day (9 PM Mountain, America/Boise time) for 72 hours: that election,
    every hour. For the first 24 hours, the hourly run keeps going and pulls it every 5 minutes with
    --every-5-minutes, which pulls only an election within 24 hours of poll close; --in-first-day
    exits 0 while one is, so the workflow knows whether to keep going.
  - After that: that election once a day, from the 15:00 UTC run (a later run that day tries again
    until one pulls it without a failure; OUTDIR/results_daily.txt keeps the day), until its saved status says
    isOfficialResults and a run has pulled all its files after that, or 45 days after poll close,
    whichever comes first. The run that does writes the election to OUTDIR/results_official.txt.
  - Every month, from the 15:00 UTC run on the 1st: every election the site lists. The run that pulls
    all of it without a failure writes the month to OUTDIR/results_monthly.txt; until one does, each
    hourly run tries again, so a late or dropped run on the 1st doesn't skip the month.
Without --scheduled, it pulls every election the site lists.

  python3 download_results.py OUTDIR [--scheduled | --every-5-minutes | --in-first-day]
"""
import calendar, datetime as dt, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request, zoneinfo

SITE = 'https://results.voteidaho.gov'
ELECTIONS = SITE + '/results/public/api/jurisdictions/id'
STATUS = SITE + '/results/public/api/elections/id/{election}'
EXPORT = SITE + '/cdn/results/id/export-{election}.json'


def fetch(url, tries=3):
    """The body, or None after printing why. A 429 or 5xx answer or a dropped connection is tried again."""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'idaho-election-data'})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
                if r.status != 200 or not body:
                    print(f'FAILED {url}: HTTP {r.status}, {len(body)} bytes', flush=True)
                    return None
                return body
        except urllib.error.HTTPError as e:
            if (e.code < 500 and e.code != 429) or attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        except Exception as e:
            if attempt == tries - 1:
                print(f'FAILED {url}: {e}', flush=True)
                return None
        time.sleep(15 * (attempt + 1))


def path_for(out, url):
    """The file under OUTDIR that mirrors url. A path that would leave OUTDIR/<host> is refused."""
    p = urllib.parse.urlsplit(url)
    base = os.path.realpath(os.path.join(out, p.netloc))
    path = os.path.realpath(os.path.join(base, urllib.parse.unquote(p.path).strip('/')))
    if not path.startswith(base + os.sep):
        raise ValueError(f'{url} would be saved outside {base}')
    return path


def save(out, url, body):
    """Write body to the file that mirrors url, unless that file already holds exactly this. True if written."""
    path = path_for(out, url)
    if os.path.isfile(path):
        with open(path, 'rb') as f:
            if f.read() == body:
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
    """The address of every report file the election's status lists; None for a listed name that isn't a plain file name."""
    folder = status.get('jurisdictionId')
    for cat in status.get('publicReportCategories') or []:
        for rep in cat.get('reports') or []:
            for f in [rep] + (rep.get('versions') or []):
                name = f.get('blobName')
                if not folder or not name:
                    continue
                if '/' in name or '\\' in name or name in ('.', '..') or '/' in folder or '..' in folder:
                    print(f'FAILED report {name!r} in folder {folder!r}: not a plain file name', flush=True)
                    yield None
                    continue
                yield f'{SITE}/cdn/results/{folder}/{urllib.parse.quote(name)}'


HOURLY_DAYS, DAILY_HOUR, MAX_DAYS, FIVE_MINUTE_HOURS = 3, 15, 45, 24
BOISE, POLLS_CLOSE = zoneinfo.ZoneInfo('America/Boise'), 21   # 9 PM Mountain
MONTHLY, OFFICIAL, DAILY = 'results_monthly.txt', 'results_official.txt', 'results_daily.txt'
MON = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']


def election_days(year):
    """Idaho Code 34-106(1): the third Tuesday in May; the Tuesday following the first Monday in November."""
    def nth(month, weekday, n):
        first = dt.date(year, month, 1)
        return first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    return [nth(5, calendar.TUESDAY, 3), nth(11, calendar.MONDAY, 1) + dt.timedelta(days=1)]


def daily_done(out):
    """The day each election's daily pull last finished without a failure, from OUTDIR/results_daily.txt."""
    try:
        with open(os.path.join(out, DAILY)) as f:
            return dict(line.split() for line in f if len(line.split()) == 2)
    except OSError:
        return {}


def official_done(out):
    """The elections a run has pulled in full after their status said isOfficialResults."""
    try:
        with open(os.path.join(out, OFFICIAL)) as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


def monthly_due(out, now):
    if now.day == 1 and now.hour < DAILY_HOUR:
        return False
    try:
        with open(os.path.join(out, MONTHLY)) as f:
            done = f.read().strip()
    except OSError:
        done = ''
    return done != f'{now:%Y-%m}'


def election_days_listed(out, now):
    """(election, day) for each election day: the statute's May and November days for this year and last,
    named the way the site names them (nov2026), and every election date in the site's list as last saved,
    which adds special and runoff elections the statute doesn't fix."""
    found = {f'{MON[d.month - 1]}{d.year}': d for d in election_days(now.year - 1) + election_days(now.year)}
    try:
        with open(path_for(out, ELECTIONS)) as f:
            site = json.load(f)
    except (OSError, ValueError):
        site = None
    for e in (site.get('elections') if isinstance(site, dict) else None) or []:
        if isinstance(e, dict) and e.get('publicElectionId') and isinstance(e.get('electionDate'), str):
            try:
                found[e['publicElectionId']] = dt.date.fromisoformat(e['electionDate'][:10])
            except ValueError:
                print(f"Skipped {e['publicElectionId']}'s electionDate {e['electionDate']!r}: not a date", flush=True)
    return list(found.items())


def poll_close(day):
    return dt.datetime(day.year, day.month, day.day, POLLS_CLOSE, tzinfo=BOISE).astimezone(dt.timezone.utc)


def daily_phase(out, election, now):
    """True when election is past its 72 hourly hours and inside its 45 days."""
    for name, day in election_days_listed(out, now):
        if name == election:
            return dt.timedelta(days=HOURLY_DAYS) <= now - poll_close(day) < dt.timedelta(days=MAX_DAYS)
    return False


def window(out, now):
    """The elections in an election-day window at this hour: hourly for 72 hours from poll close, then
    the 15:00 UTC run each day until the saved status says official, or 45 days after poll close."""
    found, done, daily = [], official_done(out), daily_done(out)
    for election, day in election_days_listed(out, now):
        age = now - poll_close(day)
        if dt.timedelta(0) <= age < dt.timedelta(days=HOURLY_DAYS):
            found.append(election)
        elif dt.timedelta(days=HOURLY_DAYS) <= age < dt.timedelta(days=MAX_DAYS) and now.hour >= DAILY_HOUR \
                and election not in done and daily.get(election) != f'{now:%Y-%m-%d}':
            found.append(election)
    return found


def first_day(out, now):
    """The elections within 24 hours of poll close, which the 5-minute run pulls."""
    return [e for e, day in election_days_listed(out, now)
            if dt.timedelta(0) <= now - poll_close(day) < dt.timedelta(hours=FIVE_MINUTE_HOURS)]


def main(out, scheduled=False, now=None, every_5=False):
    now = now or dt.datetime.now(dt.timezone.utc)
    if every_5:
        scheduled = True
    monthly = scheduled and not every_5 and monthly_due(out, now)
    failed = 0
    site = get_json(out, ELECTIONS)   # saved first, so a newly listed election's date counts this run
    wanted = (first_day(out, now) if every_5 else window(out, now)) if scheduled else []
    if scheduled and not monthly and not wanted:
        print(f'Nothing due at {now:%Y-%m-%d %H:%M} UTC.', flush=True)
        return 0
    if site is None:
        print('The site did not serve its list of elections. Nothing downloaded; run again later.', flush=True)
        return 1
    listed = site.get('elections') if isinstance(site, dict) else None
    elections = [e['publicElectionId'] for e in listed or [] if isinstance(e, dict) and e.get('publicElectionId')]
    print(f'{len(elections)} elections listed: {", ".join(elections)}', flush=True)
    if not elections:
        print('The site listed no elections. Counted as a failure; run again later.', flush=True)
        return 1
    if scheduled and not monthly:
        missing = [e for e in wanted if e not in elections]
        if missing:
            print(f'In its election window but not listed by the site: {", ".join(missing)}', flush=True)
        elections = [e for e in elections if e in wanted]
        print(f'Due this hour: {", ".join(elections) or "none the site lists"}', flush=True)
    for election in elections:
        before = failed
        status = get_json(out, STATUS.format(election=election))
        if not isinstance(status, dict):
            if status is not None:
                print(f'FAILED {election}: status is not a JSON object', flush=True)
            failed += 1
        if get_json(out, EXPORT.format(election=election)) is None:
            failed += 1
        for url in reports(status if isinstance(status, dict) else {}):
            if url is None:
                failed += 1
                continue
            if os.path.isfile(path_for(out, url)):
                continue
            body = fetch(url)
            if body is None:
                failed += 1
            elif not body.startswith((b'%PDF', b'PK', b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')):
                print(f'FAILED {url}: not a PDF or Excel file ({body[:60]!r})', flush=True)
                failed += 1
            else:
                save(out, url, body)
        if scheduled and failed == before and daily_phase(out, election, now):
            daily = daily_done(out)
            daily[election] = f'{now:%Y-%m-%d}'
            with open(os.path.join(out, DAILY), 'w') as f:
                f.writelines(f'{e} {d}\n' for e, d in sorted(daily.items()))
        if isinstance(status, dict) and status.get('isOfficialResults') and failed == before and election not in official_done(out):
            with open(os.path.join(out, OFFICIAL), 'a') as f:
                f.write(f'{election}\n')
            print(f'{election}: official, all files pulled.', flush=True)
    if monthly and not failed:
        with open(os.path.join(out, MONTHLY), 'w') as f:
            f.write(f'{now:%Y-%m}\n')
        print(f'Monthly pull for {now:%Y-%m} done.', flush=True)
    print(f'Done, {failed} failed.', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    if {'-h', '--help'} & set(sys.argv[1:]):
        print(__doc__)
        sys.exit(0)
    flags = {'--scheduled', '--every-5-minutes', '--in-first-day'}
    args = [a for a in sys.argv[1:] if a not in flags]
    if len(args) != 1 or len(flags & set(sys.argv[1:])) > 1:
        sys.exit(__doc__)
    if '--in-first-day' in sys.argv[1:]:
        sys.exit(0 if first_day(args[0], dt.datetime.now(dt.timezone.utc)) else 1)
    sys.exit(main(args[0], scheduled='--scheduled' in sys.argv[1:], every_5='--every-5-minutes' in sys.argv[1:]))
