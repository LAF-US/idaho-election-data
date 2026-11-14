#!/usr/bin/env python3
"""Download every file canvass.sos.idaho.gov links to, as the site serves it.

Starts at the site's home page and follows every link on the site. Web pages are only read for
their links; everything else (CSV and any other file) is saved byte for byte. Each file goes in a
folder that mirrors its address on the site, under the name the site gives it.

A file already saved in OUTDIR by an earlier run is not downloaded again. Pages are always read
again, since they carry the links. With MINUTES set, the script stops after that many minutes and
exits with code 3 if links were left, so the next run can pick up the rest.

  python3 download.py OUTDIR
"""
import html.parser, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import deque

START = 'https://canvass.sos.idaho.gov/'
HOST = urllib.parse.urlsplit(START).netloc
PAUSE = 0.5  # seconds between requests, to go easy on the site
UNFINISHED = 3  # exit code when time ran out with links left


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = []

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k == 'href' and v:
                self.found.append(v)


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'canvass-download'})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.geturl(), r.headers, r.read()


def filename(url, headers):
    parts = urllib.parse.urlsplit(url)
    name = None
    cd = headers.get('Content-Disposition', '')
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd)
    if m:
        name = urllib.parse.unquote(m.group(1))
    path = parts.path.strip('/')
    folder, _, last = path.rpartition('/') if name is None else (path, '', '')
    name = name or last or 'index'
    if parts.query:
        name += '?' + parts.query
    return folder, os.path.basename(name)


def already_saved(out, url):
    """True if an earlier run saved this address: either the file named after it, or a folder
    named after it holding just one file, the one the site named."""
    parts = urllib.parse.urlsplit(url)
    path = parts.path.strip('/')
    folder, _, last = path.rpartition('/')
    name = (last or 'index') + ('?' + parts.query if parts.query else '')
    if os.path.isfile(os.path.join(out, folder, name)):
        return True
    d = os.path.join(out, path)
    if not path or parts.query or not os.path.isdir(d):
        return False
    inside = os.listdir(d)
    return len(inside) == 1 and os.path.isfile(os.path.join(d, inside[0]))


def main(out, minutes=None):
    queue, seen = deque([START]), {START}
    pages = saved = skipped = failed = 0
    stop_at = time.time() + minutes * 60 if minutes else None
    while queue:
        if stop_at and time.time() > stop_at:
            print(f'Out of time: {pages} pages read, {saved} files saved, {skipped} already saved, '
                  f'{failed} failed, {len(queue)} links left.')
            return UNFINISHED
        url = queue.popleft()
        if already_saved(out, url):
            skipped += 1
            continue
        try:
            url, headers, body = fetch(url)  # url becomes the address after any redirect
        except Exception as e:
            failed += 1
            print(f'FAILED {url}: {e}', flush=True)
            time.sleep(PAUSE)
            continue
        time.sleep(PAUSE)
        if headers.get_content_type() == 'text/html':
            pages += 1
            p = Links()
            p.feed(body.decode('utf-8', 'replace'))
            for href in p.found:
                link = urllib.parse.urljoin(url, href).split('#')[0]
                if urllib.parse.urlsplit(link).netloc == HOST and link.startswith('http') and link not in seen:
                    seen.add(link)
                    queue.append(link)
        else:
            folder, name = filename(url, headers)
            try:
                d = os.path.join(out, folder)
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, name), 'wb') as f:
                    f.write(body)
            except OSError as e:
                failed += 1
                print(f'FAILED to save {url}: {e}', flush=True)
            else:
                saved += 1
                print(f'saved {os.path.join(folder, name)} ({len(body)} bytes) from {url}', flush=True)
        if (pages + saved + failed) % 100 == 0:
            print(f'-- {pages} pages read, {saved} files saved, {skipped} already saved, {failed} failed, '
                  f'{len(queue)} links left', flush=True)
    print(f'Done: {pages} pages read, {saved} files saved, {skipped} already saved, {failed} failed.')
    return 0


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    minutes = float(os.environ['MINUTES']) if os.environ.get('MINUTES') else None
    sys.exit(main(sys.argv[1], minutes))
