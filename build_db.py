"""Build results.sqlite from the saved canvass site contest files, without changing them.

usage: python3 build_db.py [SITE_FOLDER] [DATABASE]
defaults: canvass.sos.idaho.gov results.sqlite

Each saved file is
  canvass.sos.idaho.gov/eng/{tab}/download/{number}/show_granularity_dt_id:{G}/.csv/{name}.csv
with one row per place and one column per candidate. The database has one row per
place and candidate, exactly as the file presents it.

Tables:
  files    one row per saved file: tab, number, breakdown, file name, path
  places     file_id, row_number, county (the county row the place sits under, if the
             file lists counties), place (the row's first cell as written), is_county
  candidates file_id, column_number, candidate (the column heading's first line)
  votes      file_id, row_number, column_number, votes (the cell as a number;
             '-' and blank are NULL)
  totals     file_id, column_number, votes: the file's own Totals row
  results    a view joining all of the above, one row per place and candidate:
             tab, number, breakdown, file, county, place, is_county, candidate, votes, path

After building it prints the check: for every file and candidate, the county rows
(or the place rows, for a file with no county rows) must add up to the file's own
Totals row, and the place rows under each county must add up to that county's row.
Every mismatch is printed and saved to the table check_mismatches.
"""
import csv
import glob
import os
import re
import sqlite3
import sys

csv.field_size_limit(10**9)
BREAKDOWN = {'1': 'city', '3': 'county', '7': 'precinct', '80': 'precinct committee district'}
COUNTIES = {'Ada', 'Adams', 'Bannock', 'Bear Lake', 'Benewah', 'Bingham', 'Blaine', 'Boise', 'Bonner',
            'Bonneville', 'Boundary', 'Butte', 'Camas', 'Canyon', 'Caribou', 'Cassia', 'Clark', 'Clearwater',
            'Custer', 'Elmore', 'Franklin', 'Fremont', 'Gem', 'Gooding', 'Idaho', 'Jefferson', 'Jerome',
            'Kootenai', 'Latah', 'Lemhi', 'Lewis', 'Lincoln', 'Madison', 'Minidoka', 'Nez Perce', 'Oneida',
            'Owyhee', 'Payette', 'Power', 'Shoshone', 'Teton', 'Twin Falls', 'Valley', 'Washington'}


def number(text):
    t = text.replace(',', '').strip()
    if t in ('', '-'):
        return None
    try:
        return int(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return None


def main(site, out):
    if os.path.exists(out):
        os.remove(out)
    db = sqlite3.connect(out)
    db.executescript('''
        CREATE TABLE files (id INTEGER PRIMARY KEY, tab TEXT, number INTEGER, breakdown TEXT,
                            breakdown_id INTEGER, name TEXT, path TEXT);
        CREATE TABLE places (file_id INTEGER, row_number INTEGER, county TEXT, place TEXT, is_county INTEGER,
                             PRIMARY KEY (file_id, row_number)) WITHOUT ROWID;
        CREATE TABLE candidates (file_id INTEGER, column_number INTEGER, candidate TEXT,
                                 PRIMARY KEY (file_id, column_number)) WITHOUT ROWID;
        CREATE TABLE votes (file_id INTEGER, row_number INTEGER, column_number INTEGER, votes NUMERIC,
                            PRIMARY KEY (file_id, row_number, column_number)) WITHOUT ROWID;
        CREATE TABLE totals (file_id INTEGER, column_number INTEGER, votes NUMERIC,
                             PRIMARY KEY (file_id, column_number)) WITHOUT ROWID;
    ''')
    paths = sorted(glob.glob(os.path.join(site, 'eng', '*', 'download', '*', 'show_granularity_dt_id:*', '.csv', '*.csv')))
    for fid, path in enumerate(paths, 1):
        parts = path.split(os.sep)
        tab, num, g = parts[-6], parts[-4], parts[-3].split(':')[1]
        name = os.path.splitext(parts[-1])[0]
        db.execute('INSERT INTO files VALUES (?,?,?,?,?,?,?)',
                   (fid, tab, int(num), BREAKDOWN.get(g, g), int(g), name, os.path.relpath(path, site)))
        rows = [r for r in csv.reader(open(path, newline='', encoding='utf-8')) if r]
        if not rows:
            continue
        cands = [h.split('\n')[0].strip() for h in rows[0][1:]]
        db.executemany('INSERT INTO candidates VALUES (?,?,?)', [(fid, j, c) for j, c in enumerate(cands, 1)])
        lists_counties = rows[0][0].strip() == 'County'
        county = None
        got_totals = False
        pl, vo, tot = [], [], []
        for i, r in enumerate(rows[1:], 2):
            place = r[0]
            if place == 'Totals':
                if not got_totals:  # some files repeat the Totals row; the copies are identical
                    tot += [(fid, j, number(v)) for j, v in enumerate(r[1:len(cands) + 1], 1)]
                    got_totals = True
                continue
            is_county = lists_counties and place.strip() in COUNTIES
            if is_county:
                county = place.strip()
            pl.append((fid, i, county, place, int(is_county)))
            vo += [(fid, i, j, number(v)) for j, v in enumerate(r[1:len(cands) + 1], 1)]
        db.executemany('INSERT INTO places VALUES (?,?,?,?,?)', pl)
        db.executemany('INSERT INTO votes VALUES (?,?,?,?)', vo)
        db.executemany('INSERT INTO totals VALUES (?,?,?)', tot)
    db.executescript('''
        CREATE INDEX files_number ON files(number);
        CREATE VIEW results AS
            SELECT f.tab, f.number, f.breakdown, f.name AS file, p.county, p.place, p.is_county,
                   c.candidate, v.votes, f.path
            FROM votes v JOIN files f ON f.id = v.file_id
            JOIN places p ON p.file_id = v.file_id AND p.row_number = v.row_number
            JOIN candidates c ON c.file_id = v.file_id AND c.column_number = v.column_number;
    ''')
    db.commit()
    check(db)
    db.commit()
    db.execute('VACUUM')
    db.close()


def check(db):
    """The same check every build: sums against the file's own Totals and county rows."""
    db.executescript('''
        DROP TABLE IF EXISTS check_mismatches;
        CREATE TABLE check_mismatches (file_id INTEGER, kind TEXT, county TEXT, candidate TEXT,
                                       file_says NUMERIC, rows_add_up_to NUMERIC);
        -- counties (or places, where a file lists no counties) against the Totals row
        INSERT INTO check_mismatches
        SELECT t.file_id, 'Totals row', NULL, c.candidate, t.votes, s.total
        FROM totals t JOIN candidates c ON c.file_id = t.file_id AND c.column_number = t.column_number
        JOIN (SELECT v.file_id, v.column_number, SUM(COALESCE(v.votes, 0)) AS total
              FROM votes v JOIN places p ON p.file_id = v.file_id AND p.row_number = v.row_number
              WHERE p.is_county = 1 OR v.file_id NOT IN (SELECT file_id FROM places WHERE is_county = 1)
              GROUP BY v.file_id, v.column_number) s
          ON s.file_id = t.file_id AND s.column_number = t.column_number
        WHERE COALESCE(t.votes, 0) <> s.total;
        -- places under each county against that county's row
        INSERT INTO check_mismatches
        SELECT cv.file_id, 'County row', cp.county, c.candidate, cv.votes, s.total
        FROM votes cv JOIN places cp ON cp.file_id = cv.file_id AND cp.row_number = cv.row_number AND cp.is_county = 1
        JOIN candidates c ON c.file_id = cv.file_id AND c.column_number = cv.column_number
        JOIN (SELECT v.file_id, p.county, v.column_number, SUM(COALESCE(v.votes, 0)) AS total
              FROM votes v JOIN places p ON p.file_id = v.file_id AND p.row_number = v.row_number
              WHERE p.is_county = 0 AND p.county IS NOT NULL
              GROUP BY v.file_id, p.county, v.column_number) s
          ON s.file_id = cv.file_id AND s.county = cp.county AND s.column_number = cv.column_number
        WHERE COALESCE(cv.votes, 0) <> s.total;
    ''')
    n_files = db.execute('SELECT COUNT(*) FROM files').fetchone()[0]
    n_rows = db.execute('SELECT COUNT(*) FROM votes').fetchone()[0]
    n_tot = db.execute('SELECT COUNT(DISTINCT file_id) FROM totals').fetchone()[0]
    bad = db.execute('''SELECT f.tab, f.number, f.breakdown, m.kind, m.county, m.candidate, m.file_says, m.rows_add_up_to
                        FROM check_mismatches m JOIN files f ON f.id = m.file_id ORDER BY f.number, f.breakdown_id''').fetchall()
    print(f'{n_files:,} files, {n_rows:,} numbers, {n_tot:,} files with a Totals row')
    print(f'{len(bad):,} sums that do not match the file\'s own Totals or county row')
    for b in bad:
        print(' | '.join('' if x is None else str(x) for x in b))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'canvass.sos.idaho.gov',
         sys.argv[2] if len(sys.argv) > 2 else 'results.sqlite')
