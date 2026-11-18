"""Download saved canvass files again and compare them with the saved copies. Prints results only."""
import csv, hashlib, io, json, time, urllib.request

def fetch(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'canvass-download'})
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.read()
        except Exception as e:
            err = e
            time.sleep(15 * (attempt + 1))
    print(f'FAILED {url}: {err}', flush=True)
    return None

items = json.load(open('saved_sample.json'))
first = {}
print('TEST 1: same download again, compared with the saved copy', flush=True)
for it in items:
    b = fetch(it['url'])
    first[it['url']] = b
    if b is not None:
        same = hashlib.sha256(b).hexdigest() == it['sha256']
        print(f"{'SAME' if same else 'DIFFERENT'} as saved {it['saved']}: {it['url']}", flush=True)
time.sleep(60)
print('TEST 2: same download twice, a minute apart', flush=True)
for it in items:
    b = fetch(it['url'])
    a = first[it['url']]
    if a is not None and b is not None:
        print(f"{'SAME' if a == b else 'DIFFERENT'} both times: {it['url']}", flush=True)

print('TEST 3: Arco 1 in contest 20485, year export and contest file, fetched now', flush=True)
exp = first['https://canvass.sos.idaho.gov/eng/contests/search/year_from:2024/year_to:2024/show_granularity_dt_id:7/.csv']
own = first['https://canvass.sos.idaho.gov/eng/contests/download/20485/show_granularity_dt_id:7/.csv']
if exp:
    for r in csv.reader(io.StringIO(exp.decode('utf-8', 'replace'))):
        if r and r[0] == '20485' and r[-2] in ('Arco 1',):
            print('year export:', r[12], r[-4] if len(r) > 23 else '', r[-2], r[-1], flush=True)
if own:
    rows = list(csv.reader(io.StringIO(own.decode('utf-8', 'replace'))))
    print('contest file header:', [h.split(chr(10))[0] for h in rows[0]], flush=True)
    for r in rows:
        if r and r[0].strip() in ('Butte', 'Precinct Arco 1'):
            print('contest file:', r, flush=True)
