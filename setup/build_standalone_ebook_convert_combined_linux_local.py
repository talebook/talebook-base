#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Build the shared Linux Calibre runtime used by talebook-base. It combines the
restricted converter with the internal WeasyPrint PDF backend in one filesystem
tree. Public commands are installed later by Dockerfile.base; this staging
package does not expose a separate PDF command.

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
import weasy_pdf_runtime as pdf


def validate_package(package):
    base.validate_no_qt(package)
    base.validate_standalone_code_surface(package)
    base.validate_no_qt_dependencies(package)
    required = [package / 'bin' / x for x in base.HELPER_BINS]
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
