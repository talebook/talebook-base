#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


SUPPORTED_TARGETS = {
    'azw': ('epub',),
    'azw3': ('epub',),
    'docx': ('epub',),
    'epub': ('mobi',),
    'mobi': ('epub',),
    'original_epub': ('epub',),
    'pdf': ('txt',),
    'prc': ('epub',),
    'txt': ('epub',),
    'zip': ('epub',),
}
def safe_name(path):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', path.stem).strip('._-')
    return stem or 'book'


def sample_files(samples_dir):
    for path in sorted(samples_dir.rglob('*')):
        if path.is_file() and path.name != 'manifest.tsv' and not path.name.startswith('.'):
            yield path


def run_case(converter, sample, output_dir, timeout, target_ext):
    ext = sample.suffix[1:].lower()
    expected = 'success' if ext in SUPPORTED_TARGETS else 'reject'
    rel = sample.parent.name + '/' + sample.name
    output = output_dir / sample.parent.name / f'{safe_name(sample)}.{target_ext}'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    timed_out = False
    try:
        proc = subprocess.run(
            [converter, str(sample), str(output)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        returncode = proc.returncode
        stdout = proc.stdout
    except subprocess.TimeoutExpired as err:
        timed_out = True
        returncode = 'timeout'
        stdout = err.stdout.decode('utf-8', 'replace') if isinstance(err.stdout, bytes) else (err.stdout or '')
    output_size = output.stat().st_size if output.exists() else 0
    ok = False if timed_out else ((returncode == 0 and output_size > 0) if expected == 'success' else (returncode == 2 and output_size == 0))
    first_log_line = ''
    for line in stdout.splitlines():
        if line.strip():
            first_log_line = line.strip()
            break
    return {
        'sample': rel,
        'input_ext': ext,
        'target_ext': target_ext,
        'expected': expected,
        'returncode': returncode,
        'output_size': output_size,
        'status': 'ok' if ok else 'fail',
        'message': first_log_line,
    }


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(description='Verify standalone ebook-convert against a sample corpus')
    parser.add_argument('converter')
    parser.add_argument('samples_dir')
    parser.add_argument('output_dir')
    parser.add_argument('--timeout', type=int, default=240)
    args = parser.parse_args(argv[1:])

    converter = os.path.abspath(args.converter)
    samples_dir = Path(args.samples_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for sample in sample_files(samples_dir):
        ext = sample.suffix[1:].lower()
        targets = SUPPORTED_TARGETS.get(ext, ('epub',))
        for target_ext in targets:
            rows.append(run_case(converter, sample, output_dir, args.timeout, target_ext))
    report = output_dir / 'sample-results.tsv'
    headers = ('status', 'expected', 'returncode', 'input_ext', 'target_ext', 'output_size', 'sample', 'message')
    with report.open('w', encoding='utf-8') as f:
        f.write('\t'.join(headers) + '\n')
        for row in rows:
            f.write('\t'.join(str(row[x]).replace('\t', ' ') for x in headers) + '\n')
    total = len(rows)
    ok = sum(1 for x in rows if x['status'] == 'ok')
    print(f'Sample matrix: {ok}/{total} ok')
    print(f'Report: {report}')
    bad = [x for x in rows if x['status'] != 'ok']
    if bad:
        for row in bad:
            print(f"FAIL {row['sample']}: expected={row['expected']} rc={row['returncode']} size={row['output_size']} {row['message']}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
