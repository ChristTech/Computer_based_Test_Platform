import os
import sqlite3
import csv
import json
import io
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB = os.path.join(BASE_DIR, 'cbt.db')

# optional XLSX support
try:
    import pandas as pd
except Exception:
    pd = None

def _sanitize_filename(s):
    s = (s or '').strip()
    keep = ''.join(c if c.isalnum() or c in '-._ ' else '_' for c in s)
    return '_'.join(keep.split()).lower() or 'unknown'

def fetch_all_results():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('''
        SELECT r.token, r.name, r.score, r.total, r.submitted_at, r.answers_detail,
               e.id AS exam_id, COALESCE(t.subject,'') AS subject, COALESCE(e.tag,'') AS tag
        FROM results r
        JOIN sessions s ON r.token = s.token
        LEFT JOIN exams e ON s.exam_id = e.id
        LEFT JOIN teachers t ON e.teacher_id = t.id
        ORDER BY r.submitted_at DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return rows

def build_groups(rows):
    groups = {}
    for r in rows:
        subject = (r['subject'] or '').strip()
        tag = (r['tag'] or '').strip()
        exam_id = r['exam_id'] or ''
        # prefer subject, then tag, then exam_id
        key = subject or tag or exam_id or 'unknown'
        label = _sanitize_filename(key)
        try:
            answers = json.loads(r['answers_detail'] or '[]')
        except Exception:
            answers = r['answers_detail'] or ''
        submitted = ''
        try:
            submitted = datetime.fromtimestamp(r['submitted_at']).isoformat() if r['submitted_at'] else ''
        except Exception:
            submitted = ''
        row = {
            'exam_id': exam_id,
            'token': r['token'],
            'name': r['name'] or '',
            'score': r['score'],
            'total': r['total'] if 'total' in r.keys() else '',
            'submitted_at': submitted,
            'answers_detail': json.dumps(answers, ensure_ascii=False)
        }
        groups.setdefault(label, []).append(row)
    return groups

def write_group_files(groups):
    for label, rows in groups.items():
        csv_path = os.path.join(BASE_DIR, f'results_{label}.csv')
        xlsx_path = os.path.join(BASE_DIR, f'results_{label}.xlsx') if pd else None

        # write CSV
        fieldnames = ['exam_id','token','name','score','total','submitted_at','answers_detail']
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        print(f'Wrote {csv_path} ({len(rows)} rows)')

        # write XLSX if available
        if pd and xlsx_path:
            try:
                df = pd.DataFrame(rows)
                df.to_excel(xlsx_path, index=False, sheet_name='results')
                print(f'Wrote {xlsx_path} ({len(rows)} rows)')
            except Exception as e:
                print('Failed to write xlsx for', label, e)

def main():
    rows = fetch_all_results()
    if not rows:
        print('No results found in DB.')
        return
    groups = build_groups(rows)
    write_group_files(groups)
    print('Done. You can now download results_<subject>.csv/xlsx from the project folder.')

if __name__ == '__main__':
    main()