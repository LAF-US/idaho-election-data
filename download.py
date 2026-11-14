#!/usr/bin/env python3
"""Download every file canvass.sos.idaho.gov links to, as the site serves it.

Starts at the site's home page and follows every link on the site. Web pages are only read for
their links; everything else (CSV and any other file) is saved byte for byte. Each file goes in a
folder that mirrors its address on the site, under the name the site gives it.

  python3 download.py OUTDIR
"""
import html.parser, os, re, sys, time, urllib.error, urllib.parse, urllib.request
from collections import deque

START = 'https://canvass.sos.idaho.gov/'
HOST = urllib.parse.urlsplit(START).netloc
PAUSE = 0.5  # seconds between requests, to go easy on the site


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
        return r.headers, r.read()


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


def main(out):
    queue, seen = deque([START]), {START}
    pages = saved = failed = 0
    while queue:
        url = queue.popleft()
        try:
            headers, body = fetch(url)
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
            d = os.path.join(out, folder)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), 'wb') as f:
                f.write(body)
            saved += 1
            print(f'saved {os.path.join(folder, name)} ({len(body)} bytes) from {url}', flush=True)
        if (pages + saved + failed) % 100 == 0:
            print(f'-- {pages} pages read, {saved} files saved, {failed} failed, {len(queue)} links left', flush=True)
    print(f'Done: {pages} pages read, {saved} files saved, {failed} failed.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
