#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Build a local Linux standalone ebook-convert-pdf package.

This package is separate from the small no-Qt ebook-convert build. It includes
WeasyPrint and the native text/layout libraries needed for higher quality PDF
output, while still reusing calibre input plugins to support the same input
formats as the standalone converter.
'''

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tarfile
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
    'calibre/ebooks/conversion/weasy_pdf_binary.py',
)


def copy_weasy_site_packages(dest):
    dest.mkdir(parents=True, exist_ok=True)
    for item in base.DEBIAN_DIST_PACKAGES.iterdir():
        name = item.name
        if name not in WEASY_SITE_PACKAGES:
            continue
        if name.endswith(('.dist-info', '.egg-info')):
            continue
        target = dest / name
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
  <cachedir>/tmp/calibre-ebook-convert-pdf-fontconfig-cache</cachedir>
  <config></config>
</fontconfig>
''', encoding='utf-8')


def write_launchers(package):
    runner = package / 'lib' / 'python' / 'run_ebook_convert_pdf.py'
    runner.write_text('''\
import os
import sys
import tempfile

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
site_packages = os.path.join(root, "lib", "python", "site-packages")
state_root = os.path.join(tempfile.gettempdir(), "calibre-ebook-convert-pdf-standalone")
os.environ.setdefault("CALIBRE_CONFIG_DIRECTORY", os.path.join(state_root, "config"))
os.environ.setdefault("CALIBRE_CACHE_DIRECTORY", os.path.join(state_root, "cache"))
os.environ["CALIBRE_STANDALONE_CONVERTER"] = "1"
os.environ.setdefault("CALIBRE_STANDALONE_FORBID_QT", "1")
os.environ.setdefault("FONTCONFIG_PATH", os.path.join(root, "etc", "fonts"))
os.environ.setdefault("FONTCONFIG_FILE", os.path.join(root, "etc", "fonts", "fonts.conf"))
os.environ["PATH"] = os.path.join(root, "bin") + os.pathsep + os.environ.get("PATH", "")
sys.path[:0] = [site_packages]
sys.extensions_location = os.path.join(site_packages, "calibre", "plugins")
sys.resources_location = os.path.join(root, "resources")
sys.executables_location = os.path.join(root, "bin")
sys.system_plugins_location = None
sys.frozen = False
sys.calibre_basename = "ebook-convert-pdf"

from calibre.ebooks.conversion.weasy_pdf_binary import main

raise SystemExit(main(["ebook-convert-pdf", *sys.argv[1:]]))
''', encoding='utf-8')
    launcher = package / 'ebook-convert-pdf'
    launcher.write_text(f'''\
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONHOME="$HERE"
export PYTHONPATH="$HERE/lib/python/site-packages"
export LD_LIBRARY_PATH="$HERE/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
export FONTCONFIG_PATH="$HERE/etc/fonts"
export FONTCONFIG_FILE="$HERE/etc/fonts/fonts.conf"
export PATH="$HERE/bin:$PATH"
exec "$HERE/bin/python3" "$HERE/lib/python/run_ebook_convert_pdf.py" "$@"
''', encoding='utf-8')
    launcher.chmod(0o755)
    bindir_launcher = package / 'bin' / 'ebook-convert-pdf'
    if bindir_launcher.exists() or bindir_launcher.is_symlink():
        bindir_launcher.unlink()
    bindir_launcher.symlink_to('../ebook-convert-pdf')


def validate_package(package):
    base.validate_no_qt(package)
    base.validate_standalone_code_surface(package)
    base.validate_no_qt_dependencies(package)
    required = [package / 'ebook-convert-pdf', package / 'bin' / 'ebook-convert-pdf']
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
    parser = argparse.ArgumentParser(description='Build a local Linux standalone ebook-convert-pdf package')
    parser.add_argument('--output', default='/out/calibre-ebook-convert-pdf-weasy-linux')
    parser.add_argument('--python', default=f'/usr/bin/python{base.PY_VER}')
    parser.add_argument('--no-strip', action='store_true')
    parser.add_argument('--no-archive', action='store_true')
    args = parser.parse_args(argv)

    package = Path(args.output).resolve()
    if package.exists():
        shutil.rmtree(package)
    (package / 'bin').mkdir(parents=True)
    (package / 'lib').mkdir()
    base.copy_python(package, Path(args.python).resolve())
    base.copy_site_packages(package / 'lib' / 'python' / 'site-packages')
    copy_weasy_site_packages(package / 'lib' / 'python' / 'site-packages')
    copy_hyphen_data(package / 'lib' / 'python' / 'site-packages')
    base.copy_calibre_from_debian(package)
    overlay_weasy_files(package)
    base.copy_resources(package)
    base.copy_helper_bins(package)
    copy_fontconfig(package)
    write_launchers(package)
    copy_weasy_native_libraries(package)
    prune_broken_symlinks(package)
    validate_package(package)
    if not args.no_strip:
        base.strip_elfs(package)
        prune_broken_symlinks(package)
        validate_package(package)
    print('Package:', package)
    subprocess.check_call(['du', '-sh', str(package)])
    if not args.no_archive:
        create_archive(package)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
