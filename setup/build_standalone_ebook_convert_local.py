#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Build a local macOS no-Qt standalone ebook-convert package from an already
built source checkout. This is a developer convenience packager, not the
release bypy pipeline.
'''

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PY_VER = f'{sys.version_info.major}.{sys.version_info.minor}'
MACHO_MAGICS = {
    b'\xca\xfe\xba\xbe',
    b'\xbe\xba\xfe\xca',
    b'\xca\xfe\xba\xbf',
    b'\xbf\xba\xfe\xca',
    b'\xfe\xed\xfa\xce',
    b'\xce\xfa\xed\xfe',
    b'\xfe\xed\xfa\xcf',
    b'\xcf\xfa\xed\xfe',
}
NO_QT_NAMES = {'qt', 'PyQt6', 'PyQt6_sip', 'PyQt6_WebEngine'}
CALIBRE_DROP_DIRS = {
    'ai', 'db', 'devices', 'gui2', 'headless', 'library', 'plugins', 'scraper', 'srv', 'web',
}
FORBIDDEN_STANDALONE_CALIBRE_DIRS = frozenset({
    'ai',
    'devices',
    'gui2',
    'headless',
    'scraper',
    'srv',
    'web',
})
TOP_LEVEL_SRC_PACKAGES = ('calibre', 'polyglot', 'css_selectors', 'tinycss', 'odf')
RESOURCE_KEEP = frozenset({
    'calibre-ebook-root-CA.crt',
    'common-english-words.txt',
    'default_tweaks.py',
    'fonts',
    'localization',
    'mime.types',
    'pdf-preprint.js',
    'templates',
})
PYTHON_STDLIB_DROP_DIRS = frozenset({
    'curses',
    'dbm',
    'pydoc_data',
    'venv',
    'wsgiref',
    'xmlrpc',
})
PYTHON_STDLIB_DROP_FILES = frozenset({
    'antigravity.py',
    'cProfile.py',
    'doctest.py',
    'pdb.py',
    'profile.py',
    'pstats.py',
    'pydoc.py',
    'this.py',
    'turtle.py',
})
SITE_PACKAGES_ALLOWLIST = frozenset({
    'PIL',
    'bs4',
    'chardet',
    'css_parser',
    'dateutil',
    'html2text',
    'html5_parser',
    'html5lib',
    'lxml',
    'lxml_html_clean',
    'mechanize',
    'msgpack',
    'regex',
    'sgmllib.py',
    'six.py',
    'soupsieve',
    'typing_extensions.py',
    'tzdata',
    'tzlocal',
    'webencodings',
})
QT_NAMED_PYTHON_FILES = (
    ('PIL', 'ImageQt.py'),
)
PLUGIN_ALLOWLIST = frozenset({
    'cPalmdoc.so',
    'fast_css_transform.so',
    'fast_html_entities.so',
    'freetype.so',
    'html_as_json.so',
    'hyphen.so',
    'icu.so',
    'matcher.so',
    'podofo.so',
    'speedup.so',
    'translator.so',
    'uchardet.so',
    'unicode_names.so',
})
HELPER_BINS = ('pdftohtml', 'pdfinfo', 'pdftoppm', 'pdftotext')
PYTHON_DYNLOAD_DROP_PREFIXES = ('_test', '_xxtest')
PYTHON_DYNLOAD_DROP_NAMES = {
    '_ctypes_test',
    'xxlimited',
    'xxlimited_35',
}


def run(*cmd, check=True, echo=False):
    if echo or os.environ.get('CALIBRE_STANDALONE_PACKAGER_VERBOSE'):
        print('+', ' '.join(map(str, cmd)))
    return subprocess.run(tuple(map(str, cmd)), check=check, text=True, capture_output=True)


def copytree(src, dest, ignore=None):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True, ignore=ignore)


def ignore_pycache(root, names):
    ans = {'__pycache__'}
    ans.update(x for x in names if x.endswith(('.pyc', '.pyo')))
    return ans


def ignore_calibre(root, names):
    ans = set(ignore_pycache(root, names))
    if Path(root).name == 'calibre':
        ans.update(x for x in names if x in CALIBRE_DROP_DIRS)
    return ans


def copy_site_packages(src, dest):
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        name = item.name
        if name not in SITE_PACKAGES_ALLOWLIST:
            continue
        if name in NO_QT_NAMES or name == '__pycache__' or name == 'pip' or name.startswith('pip-'):
            continue
        if name.endswith(('.dist-info', '.egg-info')):
            continue
        target = dest / name
        if item.is_dir():
            copytree(item, target, ignore=ignore_pycache)
        elif item.suffix in {'.py', '.so'}:
            shutil.copy2(item, target)
    prune_qt_named_python_files(dest)


def prune_qt_named_python_files(site_packages):
    for parts in QT_NAMED_PYTHON_FILES:
        path = site_packages.joinpath(*parts)
        if path.exists():
            path.unlink()


def copy_sources(dest):
    app = dest / 'lib' / 'python' / 'site-packages'
    app.mkdir(parents=True, exist_ok=True)
    for name in TOP_LEVEL_SRC_PACKAGES:
        src = ROOT / 'src' / name
        if not src.exists():
            continue
        if name == 'calibre':
            copytree(src, app / name, ignore=ignore_calibre)
        else:
            copytree(src, app / name, ignore=ignore_pycache)
    plugins_dest = app / 'calibre' / 'plugins'
    plugins_dest.mkdir()
    for name in sorted(PLUGIN_ALLOWLIST):
        src = ROOT / 'src' / 'calibre' / 'plugins' / name
        if not src.exists():
            raise SystemExit(f'Missing required native plugin: {src}')
        shutil.copy2(src, plugins_dest / name)
    library_dest = app / 'calibre' / 'library'
    library_dest.mkdir()
    for name in ('__init__.py', 'comments.py', 'field_metadata.py'):
        shutil.copy2(ROOT / 'src' / 'calibre' / 'library' / name, library_dest / name)
    db_dest = app / 'calibre' / 'db'
    db_dest.mkdir()
    for name in ('__init__.py', 'constants.py'):
        shutil.copy2(ROOT / 'src' / 'calibre' / 'db' / name, db_dest / name)
    copytree(ROOT / 'resources', dest / 'resources', ignore=ignore_pycache)
    prune_resources(dest / 'resources')


def prune_resources(resources):
    for item in resources.iterdir():
        if item.name not in RESOURCE_KEEP:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()


def parse_otool(path):
    if not is_macho(path):
        return []
    try:
        raw = run('otool', '-L', path).stdout
    except subprocess.CalledProcessError:
        return []
    ans = []
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if not line or 'compatibility version' not in line:
            continue
        ans.append(line.split(' (', 1)[0])
    return ans


def find_library(dep):
    if dep.startswith('/usr/lib/') or dep.startswith('/System/'):
        return None
    name = dep.rpartition('/')[-1]
    if name.startswith(('Qt', 'libQt')):
        raise SystemExit(f'Unexpected Qt dependency while collecting libraries: {dep}')
    if dep.startswith('@rpath/'):
        candidates = [
            Path('/opt/homebrew/lib') / name,
            Path('/private/tmp/calibre-podofo/lib') / name,
            Path('/private/tmp/calibre-local-sw/lib') / name,
        ]
        candidates.extend(Path('/opt/homebrew/opt').glob(f'*/lib/{name}'))
        candidates.extend(Path('/opt/homebrew/Cellar').glob(f'*/**/lib/{name}'))
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve()
        return None
    p = Path(dep)
    if p.exists() and ('/opt/homebrew/' in dep or '/private/tmp/calibre-' in dep):
        return p.resolve()
    return None


def add_rpath(path, rpath):
    if not is_macho(path):
        return
    out = run('otool', '-l', path, check=False).stdout
    if rpath in out:
        return
    run('install_name_tool', '-add_rpath', rpath, path, check=False)


def is_macho(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) in MACHO_MAGICS
    except OSError:
        return False


def should_scan_binary(path):
    if path.suffix not in {'.so', '.dylib'} and path.parent.name != 'bin' and path.name not in {'Python'}:
        return False
    return is_macho(path)


def copy_binary_dependencies(package):
    libdir = package / 'lib'
    queue = []
    for base in (package / 'bin', package / 'lib' / 'Python.framework', package / 'lib' / 'python' / 'site-packages'):
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if path.is_file() and should_scan_binary(path):
                queue.append(path)
    seen = set()
    while queue:
        path = queue.pop()
        if package / 'bin' in path.parents:
            add_rpath(path, '@executable_path/../lib')
        else:
            for rpath in ('@loader_path/../lib', '@loader_path/../../lib', '@loader_path/../../../lib', '@loader_path/../../../../lib'):
                add_rpath(path, rpath)
        for dep in parse_otool(path):
            src = find_library(dep)
            if src is None or src in seen:
                continue
            seen.add(src)
            dest = copy_library_dependency(src, dep, libdir)
            add_rpath(dest, '@loader_path')
            queue.append(dest)


def copy_library_dependency(src, dep, libdir):
    real_src = src.resolve()
    dest = libdir / real_src.name
    if not dest.exists():
        shutil.copy2(real_src, dest)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IWRITE)
    dep_name = dep.rpartition('/')[-1]
    alias = libdir / dep_name
    if dep_name != dest.name and not alias.exists():
        alias.symlink_to(dest.name)
    return dest


def copy_python(package, python_exe):
    pybin = package / 'bin' / 'python3.14'
    shutil.copy2(python_exe, pybin)
    os.chmod(pybin, 0o755)
    raw = run('otool', '-L', python_exe).stdout
    old = None
    for line in raw.splitlines():
        q = line.strip().split(' (', 1)[0]
        if q.endswith('/Python.framework/Versions/3.14/Python'):
            old = q
            break
    if old:
        run('install_name_tool', '-change', old, '@executable_path/../lib/Python.framework/Versions/3.14/Python', pybin)
    framework = Path(old).parents[2] if old else Path('/opt/homebrew/Cellar/python@3.14/3.14.3_1/Frameworks/Python.framework')
    copytree(framework, package / 'lib' / 'Python.framework', ignore=ignore_pycache)
    prune_python_framework(package / 'lib' / 'Python.framework')


def prune_python_framework(framework):
    version_root = framework / 'Versions' / PY_VER
    py_lib = version_root / 'lib' / f'python{PY_VER}'
    for path in (
        version_root / 'include',
        version_root / 'share',
        version_root / '_CodeSignature',
        version_root / 'lib' / 'pkgconfig',
        py_lib / 'config-3.14-darwin',
        py_lib / 'ensurepip',
        py_lib / 'idlelib',
        py_lib / 'test',
        py_lib / 'tkinter',
        py_lib / 'turtledemo',
    ):
        if path.exists():
            shutil.rmtree(path)
    for name in PYTHON_STDLIB_DROP_DIRS:
        path = py_lib / name
        if path.exists():
            shutil.rmtree(path)
    for name in PYTHON_STDLIB_DROP_FILES:
        path = py_lib / name
        if path.exists():
            path.unlink()
    for item in (version_root / 'bin').glob('*'):
        if item.name not in {f'python{PY_VER}', 'python3', 'python'}:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    for path in (
        framework / 'Headers',
        version_root / 'Headers',
        py_lib / 'site-packages',
    ):
        if path.is_symlink():
            path.unlink()
    dynload = py_lib / 'lib-dynload'
    if dynload.exists():
        for item in dynload.glob('*.so'):
            stem = item.name.split('.', 1)[0]
            if stem.startswith(PYTHON_DYNLOAD_DROP_PREFIXES) or stem in PYTHON_DYNLOAD_DROP_NAMES:
                item.unlink()


def copy_helper_bins(package):
    for name in HELPER_BINS:
        path = shutil.which(name)
        if not path:
            raise SystemExit(f'Missing required helper binary on PATH: {name}')
        real = Path(path).resolve()
        dest = package / 'bin' / name
        shutil.copy2(real, dest)
        os.chmod(dest, 0o755)


def write_launchers(package):
    runner = package / 'lib' / 'python' / 'run_ebook_convert.py'
    runner.write_text(f'''\
import os
import sys
import tempfile

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
python_root = os.path.join(root, "lib", "python")
site_packages = os.path.join(python_root, "site-packages")
state_root = os.path.join(tempfile.gettempdir(), "calibre-ebook-convert-standalone")
os.environ.setdefault("CALIBRE_CONFIG_DIRECTORY", os.path.join(state_root, "config"))
os.environ.setdefault("CALIBRE_CACHE_DIRECTORY", os.path.join(state_root, "cache"))
os.environ["CALIBRE_STANDALONE_CONVERTER"] = "1"
os.environ.setdefault("CALIBRE_STANDALONE_FORBID_QT", "1")
sys.path[:0] = [site_packages]
sys.extensions_location = os.path.join(site_packages, "calibre", "plugins")
sys.resources_location = os.path.join(root, "resources")
sys.executables_location = os.path.join(root, "bin")
sys.frozen = False
sys.calibre_basename = "ebook-convert"

from calibre.ebooks.conversion.standalone_binary import main

raise SystemExit(main(["ebook-convert", *sys.argv[1:]]))
''', encoding='utf-8')
    launcher = package / 'ebook-convert'
    launcher.write_text(f'''\
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONHOME="$HERE/lib/Python.framework/Versions/3.14"
export PYTHONPATH="$HERE/lib/python/site-packages"
export DYLD_LIBRARY_PATH="$HERE/lib${{DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}}"
exec "$HERE/bin/python3.14" "$HERE/lib/python/run_ebook_convert.py" "$@"
''', encoding='utf-8')
    launcher.chmod(0o755)
    bindir_launcher = package / 'bin' / 'ebook-convert'
    if bindir_launcher.exists():
        bindir_launcher.unlink()
    bindir_launcher.symlink_to('../ebook-convert')


def validate_no_qt(package):
    bad = []
    for path in package.rglob('*'):
        name = path.name
        if name in NO_QT_NAMES or name == 'QtWebEngineProcess' or name == 'qtwebengine_locales':
            bad.append(path)
        elif name.startswith(('Qt', 'libQt')):
            bad.append(path)
    if bad:
        raise SystemExit('Unexpected Qt artifacts:\n' + '\n'.join(map(str, bad[:50])))


def validate_no_qt_dependencies(package):
    bad = []
    for path in package.rglob('*'):
        if not path.is_file() or not is_macho(path):
            continue
        for dep in parse_otool(path):
            name = Path(dep).name
            if name.startswith(('Qt', 'libQt')) or name in NO_QT_NAMES:
                bad.append(f'{path}: {dep}')
    if bad:
        raise SystemExit('Unexpected Qt dynamic dependencies:\n' + '\n'.join(bad[:50]))


def validate_standalone_code_surface(package):
    bad = []
    for path in package.rglob('*'):
        if not path.exists():
            continue
        if path.parent.name == 'calibre' and path.name in FORBIDDEN_STANDALONE_CALIBRE_DIRS:
            bad.append(path)
        elif path.name == 'ImageQt.py' and path.parent.name == 'PIL':
            bad.append(path)
    if bad:
        raise SystemExit('Unexpected non-standalone code in package:\n' + '\n'.join(map(str, bad[:50])))


def validate_package(package):
    validate_no_qt(package)
    validate_standalone_code_surface(package)
    validate_no_qt_dependencies(package)
    required = [package / 'ebook-convert', package / 'bin' / 'ebook-convert']
    required += [package / 'bin' / x for x in HELPER_BINS]
    for path in required:
        if not path.exists():
            raise SystemExit(f'Missing required package file: {path}')
        if not os.access(path, os.X_OK):
            raise SystemExit(f'Package file is not executable: {path}')
    broken = [x for x in package.rglob('*') if x.is_symlink() and not x.exists()]
    if broken:
        raise SystemExit('Broken symlinks in package:\n' + '\n'.join(map(str, broken[:50])))


def strip_machos(package):
    count = 0
    for path in package.rglob('*'):
        if not path.is_file() or not is_macho(path):
            continue
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
        ret = subprocess.run(('/usr/bin/strip', '-x', '-S', str(path)), text=True, capture_output=True)
        if ret.returncode != 0:
            raise SystemExit(f'Failed to strip {path}:\n{ret.stderr}')
        count += 1
    print('Stripped Mach-O files:', count)


def sign_machos(package):
    count = 0
    for path in package.rglob('*'):
        if not path.is_file() or not is_macho(path):
            continue
        subprocess.check_call(
            ['/usr/bin/codesign', '--force', '--sign', '-', str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        count += 1
    print('Ad-hoc signed Mach-O files:', count)


def create_archive(package):
    archive = package.with_suffix('.tar.xz')
    if archive.exists():
        archive.unlink()
    with tarfile.open(archive, 'w:xz') as tf:
        tf.add(package, arcname=package.name)
    print('Archive:', archive)
    print('Archive size: %.2f MB' % (archive.stat().st_size / (1024 ** 2)))
    return archive


def main(argv=None):
    parser = argparse.ArgumentParser(description='Build a local no-Qt standalone ebook-convert package')
    parser.add_argument('--output', default='/private/tmp/calibre-ebook-convert-noqt-macos')
    parser.add_argument('--python', default='/opt/homebrew/opt/python@3.14/bin/python3.14')
    parser.add_argument('--venv', default='/private/tmp/calibre-run-venv')
    parser.add_argument('--no-archive', action='store_true')
    args = parser.parse_args(argv)

    package = Path(args.output).resolve()
    if package.exists():
        shutil.rmtree(package)
    (package / 'bin').mkdir(parents=True)
    (package / 'lib').mkdir()
    copy_python(package, Path(args.python).resolve())
    copy_site_packages(Path(args.venv) / 'lib' / f'python{PY_VER}' / 'site-packages', package / 'lib' / 'python' / 'site-packages')
    copy_sources(package)
    copy_helper_bins(package)
    write_launchers(package)
    copy_binary_dependencies(package)
    validate_package(package)
    strip_machos(package)
    sign_machos(package)
    print('Package:', package)
    subprocess.check_call(['du', '-sh', str(package)])
    if not args.no_archive:
        create_archive(package)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
