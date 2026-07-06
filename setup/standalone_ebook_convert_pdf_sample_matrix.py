#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


SUPPORTED_INPUT_FORMATS = frozenset({
    'azw', 'azw3', 'docx', 'epub', 'mobi', 'original_epub',
    'pdf', 'prc', 'txt', 'zip',
})
CJK_RE = re.compile(r'[\u3400-\u9fff]')


def safe_name(path):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', path.stem).strip('._-')
    return stem or 'book'


def sample_files(samples_dir):
    for path in sorted(samples_dir.rglob('*')):
        if path.is_file() and path.name != 'manifest.tsv' and not path.name.startswith('.'):
            yield path


def package_root_for_converter(converter):
    q = os.path.dirname(os.path.abspath(converter))
    if os.path.basename(q) == 'bin':
        return os.path.dirname(q)
    return q


def helper_for_converter(converter, name):
    candidate = os.path.join(package_root_for_converter(converter), 'bin', name)
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    q = shutil.which(name)
    if q:
        return q
    raise SystemExit(f'Cannot validate PDF: {name} not found')


def env_for_converter(converter):
    root = package_root_for_converter(converter)
    env = os.environ.copy()
    lib = os.path.join(root, 'lib')
    env['LD_LIBRARY_PATH'] = lib + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    return env


def run_cmd(cmd, timeout, env=None):
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, env=env)
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as err:
        out = err.stdout.decode('utf-8', 'replace') if isinstance(err.stdout, bytes) else (err.stdout or '')
        return 'timeout', out


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ''


def pdf_page_count(pdfinfo_output):
    for line in pdfinfo_output.splitlines():
        if line.startswith('Pages:'):
            try:
                return int(line.split(':', 1)[1].strip())
            except ValueError:
                return 0
    return 0


def validate_pdf(converter, output, timeout):
    pdfinfo = helper_for_converter(converter, 'pdfinfo')
    pdftotext = helper_for_converter(converter, 'pdftotext')
    env = env_for_converter(converter)
    info_rc, info_out = run_cmd([pdfinfo, str(output)], timeout, env=env)
    if info_rc != 0:
        return False, {'pages': 0, 'chars': 0, 'cjk': 0, 'questions': 0, 'message': first_line(info_out)}
    pages = pdf_page_count(info_out)
    if pages < 1:
        return False, {'pages': pages, 'chars': 0, 'cjk': 0, 'questions': 0, 'message': 'pdf has no pages'}
    text_rc, text_out = run_cmd([pdftotext, str(output), '-'], timeout, env=env)
    text = text_out if text_rc == 0 else ''
    return True, {
        'pages': pages,
        'chars': len(re.sub(r'\s+', '', text)),
        'cjk': len(CJK_RE.findall(text)),
        'questions': text.count('?'),
        'message': 'valid pdf',
    }


def run_case(converter, sample, output_dir, timeout):
    ext = sample.suffix[1:].lower()
    expected = 'success' if ext in SUPPORTED_INPUT_FORMATS else 'reject'
    rel = sample.parent.name + '/' + sample.name
    output = output_dir / sample.parent.name / f'{safe_name(sample)}.pdf'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    rc, log = run_cmd([converter, str(sample), str(output)], timeout)
    output_size = output.stat().st_size if output.exists() else 0
    if expected == 'reject':
        ok = rc != 0 and output_size == 0
        stats = {'pages': 0, 'chars': 0, 'cjk': 0, 'questions': 0, 'message': first_line(log)}
    else:
        ok = rc == 0 and output_size > 0
        stats = {'pages': 0, 'chars': 0, 'cjk': 0, 'questions': 0, 'message': first_line(log)}
        if ok:
            ok, stats = validate_pdf(converter, output, timeout)
    return {
        'sample': rel,
        'input_ext': ext,
        'expected': expected,
        'returncode': rc,
        'output_size': output_size,
        'status': 'ok' if ok else 'fail',
        **stats,
    }


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(description='Verify standalone ebook-convert-pdf against a sample corpus')
    parser.add_argument('converter')
    parser.add_argument('samples_dir')
    parser.add_argument('output_dir')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args(argv[1:])

    converter = os.path.abspath(args.converter)
    samples_dir = Path(args.samples_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [run_case(converter, sample, output_dir, args.timeout) for sample in sample_files(samples_dir)]
    report = output_dir / 'pdf-sample-results.tsv'
    headers = (
        'status', 'expected', 'returncode', 'input_ext', 'output_size',
        'pages', 'chars', 'cjk', 'questions', 'sample', 'message',
    )
    with report.open('w', encoding='utf-8') as f:
        f.write('\t'.join(headers) + '\n')
        for row in rows:
            f.write('\t'.join(str(row[x]).replace('\t', ' ') for x in headers) + '\n')
    total = len(rows)
    ok = sum(1 for x in rows if x['status'] == 'ok')
    print(f'PDF sample matrix: {ok}/{total} ok')
    print(f'Report: {report}')
    bad = [x for x in rows if x['status'] != 'ok']
    if bad:
        for row in bad:
            print(f"FAIL {row['sample']}: expected={row['expected']} rc={row['returncode']} size={row['output_size']} {row['message']}")
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
