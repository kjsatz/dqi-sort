"""Refuse data files in this public repo.

    python3 scripts/check_no_data.py            # check every tracked file (used in CI)
    python3 scripts/check_no_data.py --staged   # check files staged for commit (pre-commit hook)

Fails on data-like file types (tables, JSON, arrays, spreadsheets, documents, archives, HTML pages)
and on any file over the size limit. Made-up test data under tests/fixtures/ is allowed.
"""
import os, subprocess, sys

BLOCKED = {'.csv', '.tsv', '.jsonl', '.json', '.npz', '.npy', '.pkl', '.parquet', '.xlsx', '.xls', '.xlsm',
           '.docx', '.pdf', '.zip', '.gz', '.html', '.htm'}
ALLOWED_DIRS = ('tests/fixtures/',)
ALLOWED_FILES = {'prototype/scripts/map_template.html'}   # template only; data is injected outside the repo
MAX_BYTES = 300_000


def files(staged):
    if staged:
        cmd = ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']
    else:
        cmd = ['git', 'ls-files', '-z']
    return [f for f in subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.split('\0') if f]


def size(path, staged):
    if staged:
        r = subprocess.run(['git', 'cat-file', '-s', f':{path}'], capture_output=True, text=True)
        return int(r.stdout) if r.returncode == 0 else 0
    return os.path.getsize(path) if os.path.exists(path) else 0


def main():
    staged = '--staged' in sys.argv
    bad = []
    for f in files(staged):
        if f.startswith(ALLOWED_DIRS) or f in ALLOWED_FILES:
            continue
        if os.path.splitext(f)[1].lower() in BLOCKED:
            bad.append(f'{f}: data file type')
        elif size(f, staged) > MAX_BYTES:
            bad.append(f'{f}: larger than {MAX_BYTES // 1000} kB')
    if bad:
        print('This repo is public and must not hold conference data. Refusing:', *bad, sep='\n  ')
        print('Data belongs in the private data repo. Made-up test data can go under tests/fixtures/.')
        sys.exit(1)
    print(f'check_no_data: OK ({"staged" if staged else "tracked"} files)')


if __name__ == '__main__':
    main()
