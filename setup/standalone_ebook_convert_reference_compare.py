#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import hashlib
import os
import re
import subprocess
import sys
from difflib import SequenceMatcher
from fnmatch import fnmatch
from pathlib import Path


DEFAULT_TARGETS = ('epub', 'mobi', 'pdf', 'txt')
CJK_RE = re.compile(r'[\u3400-\u9fff]')
SPACE_RE = re.compile(r'\s+')


def safe_name(path):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', path.stem).strip('._-')
    return stem or 'book'


def sample_files(samples_dir, exclude_patterns=()):
    for path in sorted(samples_dir.rglob('*')):
        if not path.is_file() or path.name in {'manifest.tsv', '.DS_Store'}:
            continue
        rel = path.relative_to(samples_dir).as_posix()
        if any(fnmatch(rel, pat) for pat in exclude_patterns):
            continue
        yield path


def ext(path):
    return path.suffix[1:].lower()


def run_cmd(cmd, timeout):
    try:
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as err:
        out = err.stdout.decode('utf-8', 'replace') if isinstance(err.stdout, bytes) else (err.stdout or '')
        return 'timeout', out


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ''


def normalize_text(text):
    return SPACE_RE.sub('', text)


def text_stats(text):
    normalized = normalize_text(text)
    cjk = len(CJK_RE.findall(normalized))
    return {
        'chars': len(normalized),
        'cjk': cjk,
        'questions': normalized.count('?'),
        'sha256': hashlib.sha256(normalized.encode('utf-8', 'replace')).hexdigest() if normalized else '',
        'text': normalized,
    }


def extract_text(path, reference_converter, pdftotext, out_dir, timeout):
    fmt = ext(path)
    if fmt == 'txt':
        try:
            return 0, path.read_text(encoding='utf-8', errors='replace'), ''
        except OSError as err:
            return 1, '', str(err)
    if fmt == 'pdf':
        rc, out = run_cmd([pdftotext, str(path), '-'], timeout)
        return rc, out if rc == 0 else '', first_line(out)
    if fmt in {'epub', 'mobi'}:
        txt_path = out_dir / (path.name + '.txt')
        rc, out = run_cmd([reference_converter, str(path), str(txt_path)], timeout)
        if rc == 0 and txt_path.exists():
            return 0, txt_path.read_text(encoding='utf-8', errors='replace'), first_line(out)
        return rc, '', first_line(out)
    return 'skip', '', f'no text extractor for {fmt}'


def similarity(a, b):
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    if len(a) > 200000 or len(b) > 200000:
        step_a = max(1, len(a) // 100000)
        step_b = max(1, len(b) // 100000)
        a = a[::step_a]
        b = b[::step_b]
    return SequenceMatcher(None, a, b, autojunk=True).ratio()


def compare_text(ref_text, standalone_text, target_ext=''):
    ref = text_stats(ref_text)
    got = text_stats(standalone_text)
    len_ratio = min(ref['chars'], got['chars']) / max(ref['chars'], got['chars'], 1)
    cjk_ratio = min(ref['cjk'], got['cjk']) / max(ref['cjk'], got['cjk'], 1)
    sim = similarity(ref['text'], got['text'])
    if target_ext == 'pdf':
        ok = ref['sha256'] == got['sha256'] or (len_ratio >= 0.98 and cjk_ratio >= 0.98)
    else:
        ok = (
            ref['sha256'] == got['sha256'] or
            (len_ratio >= 0.90 and cjk_ratio >= 0.90 and sim >= 0.80)
        )
    if ref['cjk'] >= 10 and got['questions'] > max(20, got['cjk'] // 2):
        ok = False
    return ok, {
        'ref_chars': ref['chars'],
        'got_chars': got['chars'],
        'ref_cjk': ref['cjk'],
        'got_cjk': got['cjk'],
        'got_questions': got['questions'],
        'len_ratio': f'{len_ratio:.4f}',
        'cjk_ratio': f'{cjk_ratio:.4f}',
        'similarity': f'{sim:.4f}',
        'same_text_sha': str(ref['sha256'] == got['sha256']).lower(),
    }


def run_conversion(converter, sample, target, out_dir, timeout):
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / sample.parent.name / f'{safe_name(sample)}.{target}'
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    rc, log = run_cmd([converter, str(sample), str(output)], timeout)
    size = output.stat().st_size if output.exists() else 0
    return rc, output, size, first_line(log)


def classify(ref_rc, ref_size, got_rc, got_size, text_ok):
    ref_ok = ref_rc == 0 and ref_size > 0
    got_ok = got_rc == 0 and got_size > 0
    if ref_ok and got_ok:
        return 'ok' if text_ok else 'content_diff'
    if not ref_ok and not got_ok:
        return 'same_fail'
    if ref_ok and not got_ok:
        return 'standalone_missing'
    return 'standalone_extra'


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(description='Compare standalone ebook-convert against a reference converter on sample files.')
    parser.add_argument('--reference', default='/usr/bin/ebook-convert')
    parser.add_argument('--standalone', required=True)
    parser.add_argument('--samples-dir', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--pdftotext', default='pdftotext')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--targets', default=','.join(DEFAULT_TARGETS))
    parser.add_argument('--exclude-sample', action='append', default=[], help='Glob of sample path relative to samples-dir to skip')
    args = parser.parse_args(argv[1:])

    samples_dir = Path(args.samples_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    targets = tuple(x.strip().lower() for x in args.targets.split(',') if x.strip())
    rows = []

    for sample in sample_files(samples_dir, args.exclude_sample):
        input_ext = ext(sample)
        for target in targets:
            if input_ext == target:
                continue
            ref_rc, ref_out, ref_size, ref_log = run_conversion(args.reference, sample, target, output_dir / 'reference', args.timeout)
            got_rc, got_out, got_size, got_log = run_conversion(args.standalone, sample, target, output_dir / 'standalone', args.timeout)
            text_ok = ''
            stats = {}
            ref_ok = ref_rc == 0 and ref_size > 0
            got_ok = got_rc == 0 and got_size > 0
            if ref_ok and got_ok:
                ref_text_rc, ref_text, ref_text_log = extract_text(ref_out, args.reference, args.pdftotext, output_dir / 'text' / 'reference', args.timeout)
                got_text_rc, got_text, got_text_log = extract_text(got_out, args.reference, args.pdftotext, output_dir / 'text' / 'standalone', args.timeout)
                if ref_text_rc == 0 and got_text_rc == 0:
                    text_ok, stats = compare_text(ref_text, got_text, target)
                    text_ok = 'true' if text_ok else 'false'
                else:
                    text_ok = 'extract_fail'
                    stats = {'ref_extract': ref_text_log, 'got_extract': got_text_log}
            status = classify(ref_rc, ref_size, got_rc, got_size, text_ok == 'true')
            row = {
                'status': status,
                'sample': sample.parent.name + '/' + sample.name,
                'input_ext': input_ext,
                'target_ext': target,
                'ref_rc': ref_rc,
                'standalone_rc': got_rc,
                'ref_size': ref_size,
                'standalone_size': got_size,
                'text_ok': text_ok,
                'ref_log': ref_log,
                'standalone_log': got_log,
            }
            row.update(stats)
            rows.append(row)

    headers = (
        'status', 'sample', 'input_ext', 'target_ext', 'ref_rc', 'standalone_rc',
        'ref_size', 'standalone_size', 'text_ok', 'ref_chars', 'got_chars',
        'ref_cjk', 'got_cjk', 'got_questions', 'len_ratio', 'cjk_ratio',
        'similarity', 'same_text_sha', 'ref_log', 'standalone_log',
    )
    report = output_dir / 'reference-compare.tsv'
    with report.open('w', encoding='utf-8') as f:
        f.write('\t'.join(headers) + '\n')
        for row in rows:
            f.write('\t'.join(str(row.get(h, '')).replace('\t', ' ') for h in headers) + '\n')

    counts = {}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    print('Reference comparison:', ', '.join(f'{k}={counts[k]}' for k in sorted(counts)))
    print('Report:', report)
    bad = [x for x in rows if x['status'] in {'standalone_missing', 'standalone_extra', 'content_diff'}]
    if bad:
        for row in bad[:80]:
            print(
                f"{row['status']} {row['sample']} -> {row['target_ext']} "
                f"ref_rc={row['ref_rc']} standalone_rc={row['standalone_rc']} "
                f"text_ok={row.get('text_ok', '')} ref_size={row['ref_size']} standalone_size={row['standalone_size']}"
            )
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
