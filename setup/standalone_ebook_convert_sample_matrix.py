#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SUPPORTED_TARGETS = {
    'epub': ('mobi', 'pdf'),
    'mobi': ('epub', 'pdf'),
    'pdf': ('txt',),
    'txt': ('epub', 'pdf'),
}
CJK_RE = re.compile(r'[\u3400-\u9fff]')


def safe_name(path):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', path.stem).strip('._-')
    return stem or 'book'


def sample_files(samples_dir):
    for path in sorted(samples_dir.rglob('*')):
        if path.is_file() and path.name != 'manifest.tsv':
            yield path


def package_root_for_converter(converter):
    q = os.path.dirname(os.path.abspath(converter))
    if os.path.basename(q) == 'bin':
        return os.path.dirname(q)
    return q


def pdftotext_for_converter(converter):
    candidate = os.path.join(package_root_for_converter(converter), 'bin', 'pdftotext')
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    q = shutil.which('pdftotext')
    if q:
        return q
    raise SystemExit('Cannot validate PDF text: pdftotext not found')


def validate_pdf_text(converter, output):
    exe = pdftotext_for_converter(converter)
    proc = subprocess.run([exe, str(output), '-'], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        return False, 'pdftotext failed: ' + proc.stderr.strip()
    text = proc.stdout
    cjk_count = len(CJK_RE.findall(text))
    question_count = text.count('?')
    if cjk_count < 10:
        return False, f'pdf text has too few CJK chars: {cjk_count}'
    if question_count > max(20, cjk_count // 2):
        return False, f'pdf text has too many question marks: {question_count}, cjk={cjk_count}'
    return True, f'pdf text CJK chars: {cjk_count}'


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
    pdf_message = ''
    if ok and expected == 'success' and target_ext == 'pdf':
        ok, pdf_message = validate_pdf_text(converter, output)
    first_log_line = ''
    for line in stdout.splitlines():
        if line.strip():
            first_log_line = line.strip()
            break
    if pdf_message:
        first_log_line = (first_log_line + ' | ' + pdf_message).strip(' |')
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
