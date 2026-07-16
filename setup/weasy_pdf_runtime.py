#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''Internal WeasyPrint dependency layer for the Talebook Calibre runtime.'''

import os
import shutil
import stat
import subprocess
from pathlib import Path

import build_standalone_ebook_convert_linux_local as base


WEASY_SITE_PACKAGES = frozenset({
    '_cffi_backend.cpython-313-aarch64-linux-gnu.so',
    '_cffi_backend.cpython-312-aarch64-linux-gnu.so',
    '_cffi_backend.cpython-311-aarch64-linux-gnu.so',
    '_cffi_backend.cpython-310-aarch64-linux-gnu.so',
    '_cffi_backend.cpython-39-aarch64-linux-gnu.so',
    '_cffi_backend.cpython-313-x86_64-linux-gnu.so',
    '_cffi_backend.cpython-312-x86_64-linux-gnu.so',
    '_cffi_backend.cpython-311-x86_64-linux-gnu.so',
    '_cffi_backend.cpython-310-x86_64-linux-gnu.so',
    '_cffi_backend.cpython-39-x86_64-linux-gnu.so',
    'cffi',
    'cssselect2',
    'fontTools',
    'fonttools',
    'hyphen',
    'ply',
    'pydyf',
    'pycparser',
    'pyphen',
    'tinycss2',
    'tinyhtml5',
    'weasyprint',
    'zopfli',
})

WEASY_NATIVE_LIBRARY_NAMES = (
    'pango-1.0',
    'pangocairo-1.0',
    'pangoft2-1.0',
    'gobject-2.0',
    'glib-2.0',
    'gio-2.0',
    'gmodule-2.0',
    'gdk_pixbuf-2.0',
    'cairo',
    'fontconfig',
    'freetype',
    'harfbuzz',
    'fribidi',
    'thai',
    'datrie',
    'ffi',
)

WEASY_OVERLAY_FILES = (
    'calibre/ebooks/conversion/weasy_pdf.py',
)


def copy_weasy_site_packages(dest):
    dest.mkdir(parents=True, exist_ok=True)
    for root in base.PYTHON_PACKAGE_ROOTS:
        if not root.exists():
            continue
        for item in root.iterdir():
            name = item.name
            if name not in WEASY_SITE_PACKAGES:
                continue
            if name.endswith(('.dist-info', '.egg-info')):
                continue
            target = dest / name
            if target.exists():
                continue
            if item.is_dir():
                base.copytree(item, target, ignore=base.ignore_pycache)
            elif item.suffix in {'.py', '.so'} or item.name.startswith('_cffi_backend.'):
                shutil.copy2(item, target)


def copy_hyphen_data(dest):
    src = Path('/usr/share/hyphen')
    if not src.exists():
        raise SystemExit('Missing /usr/share/hyphen. Install python3-pyphen and its hyphen dictionaries.')
    target = dest / 'hyphen'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(src, target, symlinks=False)
    init = target / '__init__.py'
    if not init.exists():
        init.write_text('# Hyphenation dictionaries packaged for standalone pyphen.\n', encoding='utf-8')


def overlay_weasy_files(package):
    site_packages = package / 'lib' / 'python' / 'site-packages'
    for rel in WEASY_OVERLAY_FILES:
        src = base.ROOT / 'src' / rel
        if not src.exists():
            raise SystemExit(f'Missing WeasyPrint overlay file: {src}')
        dest = site_packages / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def prune_broken_symlinks(package):
    for path in package.rglob('*'):
        if path.is_symlink() and not path.exists():
            path.unlink()


def ldconfig_library_map():
    ret = subprocess.run(('ldconfig', '-p'), text=True, capture_output=True)
    if ret.returncode != 0:
        return {}
    ans = {}
    for raw in ret.stdout.splitlines():
        line = raw.strip()
        if '=>' not in line:
            continue
        name, _sep, path = line.partition('=>')
        soname = name.split(' ', 1)[0].strip()
        path = path.strip()
        if path.startswith('/'):
            ans.setdefault(soname, Path(path))
    return ans


def copy_initial_native_library(libdir, soname, src):
    real_src = src.resolve()
    dest = libdir / real_src.name
    if not dest.exists():
        shutil.copy2(real_src, dest)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IWRITE)
    alias = libdir / soname
    if soname != dest.name and not alias.exists():
        alias.symlink_to(dest.name)
    return dest


def copy_weasy_native_libraries(package):
    libdir = package / 'lib'
    available = ldconfig_library_map()
    copied = []
    missing = []
    for name in WEASY_NATIVE_LIBRARY_NAMES:
        candidates = [
            soname for soname in sorted(available)
            if soname == f'lib{name}.so' or soname.startswith(f'lib{name}.so.')
        ]
        if not candidates:
            missing.append(name)
            continue
        # Prefer the ABI soname over a linker-only libfoo.so entry.
        soname = sorted(candidates, key=lambda x: (x.endswith('.so'), len(x)))[0]
        copied.append(copy_initial_native_library(libdir, soname, available[soname]))
    if missing:
        raise SystemExit(
            'Missing WeasyPrint native libraries. Install python3-weasyprint and its dependencies first: '
            + ', '.join(missing)
        )
    base.copy_binary_dependencies(package)
    return copied


def copy_fontconfig(package):
    dest = package / 'etc' / 'fonts'
    dest.mkdir(parents=True, exist_ok=True)
    src = Path('/etc/fonts')
    if src.exists():
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest, symlinks=True, ignore=base.ignore_pycache)
    (dest / 'fonts.conf').write_text('''\
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <dir prefix="relative">../../resources/fonts</dir>
  <dir>/usr/share/fonts</dir>
  <cachedir>/tmp/talebook-weasy-pdf-fontconfig-cache</cachedir>
  <config></config>
</fontconfig>
''', encoding='utf-8')
