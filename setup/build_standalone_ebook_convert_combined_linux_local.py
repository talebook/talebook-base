#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Build a single combined Linux standalone Calibre runtime that ships one shared
runtime (Python interpreter, calibre code, resources, native libraries) with two
entry points:

    ebook-convert      -> the no-Qt standalone converter
    ebook-convert-pdf  -> the WeasyPrint based high quality PDF converter

The WeasyPrint PDF package is already a superset of the small no-Qt package: it
reuses the exact same base runtime and only adds WeasyPrint plus its native
stack on top. Rather than shipping two archives that each carry a full copy of
the ~70MB base runtime, this packager assembles that runtime once and writes
both launchers against it, halving the shipped size.

This is a developer/test packager, intentionally separate from the release bypy
pipeline. It composes the two existing local packagers instead of duplicating
their logic.
'''

import argparse
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import build_standalone_ebook_convert_linux_local as base
import build_standalone_ebook_convert_pdf_linux_local as pdf


def write_launchers(package):
    # Both launchers target the same shared runtime tree. base.write_launchers
    # writes the ebook-convert launcher (+ run_ebook_convert.py + bin symlink);
    # pdf.write_launchers writes the ebook-convert-pdf launcher. They touch
    # disjoint files, so composing them yields both entry points.
    base.write_launchers(package)
    pdf.write_launchers(package)


def validate_package(package):
    base.validate_no_qt(package)
    base.validate_standalone_code_surface(package)
    base.validate_no_qt_dependencies(package)
    required = [
        package / 'ebook-convert', package / 'bin' / 'ebook-convert',
        package / 'ebook-convert-pdf', package / 'bin' / 'ebook-convert-pdf',
    ]
    required += [package / 'bin' / x for x in base.HELPER_BINS]
    for path in required:
        if not path.exists():
            raise SystemExit(f'Missing required package file: {path}')
        if not os.access(path, os.X_OK):
            raise SystemExit(f'Package file is not executable: {path}')
    broken = [x for x in package.rglob('*') if x.is_symlink() and not x.exists()]
    if broken:
        raise SystemExit('Broken symlinks in package:\n' + '\n'.join(map(str, broken[:50])))


def create_archive(package):
    archive = package.with_suffix('.tgz')
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, 'w:gz') as tf:
        tf.add(package, arcname=package.name)
    print('Archive:', archive)
    print('Archive size: %.2f MB' % (archive.stat().st_size / (1024 ** 2)))
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a single combined Linux standalone Calibre runtime')
    parser.add_argument('--output', default='/out/calibre-runtime-linux')
    parser.add_argument('--python', default=f'/usr/bin/python{base.PY_VER}')
    parser.add_argument('--no-strip', action='store_true')
    parser.add_argument('--no-archive', action='store_true')
    args = parser.parse_args(argv)

    package = Path(args.output).resolve()
    if package.exists():
        shutil.rmtree(package)
    (package / 'bin').mkdir(parents=True)
    (package / 'lib').mkdir()

    python_exe = Path(args.python).resolve()
    # shared base runtime, built once
    base.copy_python(package, python_exe)
    base.copy_site_packages(package / 'lib' / 'python' / 'site-packages')
    # WeasyPrint additions layered onto the same runtime
    pdf.copy_weasy_site_packages(package / 'lib' / 'python' / 'site-packages')
    pdf.copy_hyphen_data(package / 'lib' / 'python' / 'site-packages')
    base.copy_calibre_from_debian(package)
    pdf.overlay_weasy_files(package)
    base.copy_resources(package)
    base.copy_helper_bins(package)
    pdf.copy_fontconfig(package)
    # both entry points against the one shared tree
    write_launchers(package)
    # pulls in the WeasyPrint native stack and then all transitive deps
    pdf.copy_weasy_native_libraries(package)
    pdf.prune_broken_symlinks(package)

    validate_package(package)
    if not args.no_strip:
        base.strip_elfs(package)
        pdf.prune_broken_symlinks(package)
        validate_package(package)
    print('Package:', package)
    subprocess.check_call(['du', '-sh', str(package)])
    if not args.no_archive:
        create_archive(package)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
