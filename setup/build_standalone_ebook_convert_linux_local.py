#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Build a local Linux no-Qt standalone ebook-convert package from the Debian
calibre package installed in the current container, with the standalone
converter glue overlaid from this checkout.

This is a developer/test packager for validating the standalone Linux surface.
It is intentionally separate from the release bypy pipeline.
'''

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from standalone_build_common import (
    FORBIDDEN_STANDALONE_CALIBRE_DIRS,
    HELPER_BINS,
    NO_QT_NAMES,
    PYTHON_DYNLOAD_DROP_NAMES,
    PYTHON_DYNLOAD_DROP_PREFIXES,
    PYTHON_STDLIB_DROP_FILES,
    QT_NAMED_PYTHON_FILES,
)

ROOT = Path(__file__).resolve().parent.parent
PY_VER = f'{sys.version_info.major}.{sys.version_info.minor}'
ELF_MAGIC = b'\x7fELF'
CALIBRE_CODE_ROOT = Path(os.environ.get('CALIBRE_STANDALONE_CODE_ROOT', '/usr/lib/calibre'))
CALIBRE_RESOURCE_ROOT = Path(os.environ.get('CALIBRE_STANDALONE_RESOURCE_ROOT', '/usr/share/calibre'))
CALIBRE_PLUGIN_ROOT = Path(os.environ.get('CALIBRE_STANDALONE_PLUGIN_ROOT', CALIBRE_CODE_ROOT / 'calibre' / 'plugins'))
DEBIAN_DIST_PACKAGES = Path('/usr/lib/python3/dist-packages')
PYTHON_PACKAGE_ROOTS = tuple(
    Path(x) for x in os.environ.get(
        'CALIBRE_STANDALONE_PYTHON_PACKAGE_ROOTS',
        os.pathsep.join((
            str(DEBIAN_DIST_PACKAGES),
            f'/usr/local/lib/python{PY_VER}/dist-packages',
            f'/usr/local/lib/python{PY_VER}/site-packages',
        )),
    ).split(os.pathsep) if x
)
CALIBRE_DROP_DIRS = {
    'ai', 'devices', 'gui2', 'headless', 'plugins', 'scraper', 'srv', 'web',
}
CALIBRE_DROP_RUNTIME_NAMES = {'tests', '__pycache__'}
RESOURCE_KEEP = frozenset({
    'calibre-ebook-root-CA.crt',
    'catalog',
    'common-english-words.txt',
    'default_tweaks.py',
    'fonts',
    'fts_sqlite.sql',
    'fts_triggers.sql',
    'jacket',
    'localization',
    'metadata_sqlite.sql',
    'mime.types',
    'notes_sqlite.sql',
    'pdf-preprint.js',
    'templates',
    'user-agent-data.json',
})
PYTHON_STDLIB_DROP_DIRS = frozenset({
    '__phello__',
    'curses',
    'dbm',
    'ensurepip',
    'idlelib',
    'lib2to3',
    'pydoc_data',
    'test',
    'tkinter',
    'turtledemo',
    'venv',
    'wsgiref',
    'xmlrpc',
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
    'webencodings',
})
CALIBRE_TOP_LEVEL_PACKAGES = ('calibre', 'polyglot', 'css_selectors', 'tinycss', 'odf')
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
    'sqlite_custom.so',
    'sqlite_extension.so',
    'uchardet.so',
    'unicode_names.so',
})
CJK_FONT_CANDIDATES = (
    '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
)
CORE_SYSTEM_LIB_PREFIXES = (
    'ld-linux',
    'libBrokenLocale.so',
    'libanl.so',
    'libc.so',
    'libdl.so',
    'libm.so',
    'libpthread.so',
    'libresolv.so',
    'librt.so',
    'libthread_db.so',
    'libutil.so',
)
STANDALONE_OVERLAY_FILES = (
    'calibre/customize/standalone_builtins.py',
    'calibre/ebooks/docx/images.py',
    'calibre/ebooks/conversion/standalone_common.py',
    'calibre/ebooks/conversion/standalone_binary.py',
    'calibre/utils/img_shim.py',
    'calibre/utils/safe_atexit.py',
    'calibre/utils/standalone_img.py',
)


def run(*cmd, check=True):
    return subprocess.run(tuple(map(str, cmd)), text=True, capture_output=True, check=check)


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
    ans.update(x for x in names if x in CALIBRE_DROP_RUNTIME_NAMES)
    if Path(root).name == 'calibre':
        ans.update(x for x in names if x in CALIBRE_DROP_DIRS)
    return ans


def ignore_stdlib(root, names):
    ans = set(ignore_pycache(root, names))
    ans.update(x for x in names if x in PYTHON_STDLIB_DROP_DIRS or x in PYTHON_STDLIB_DROP_FILES)
    ans.update(x for x in names if x.endswith(('.a', '.la')))
    return ans


def copy_site_packages(dest):
    dest.mkdir(parents=True, exist_ok=True)
    for root in PYTHON_PACKAGE_ROOTS:
        if not root.exists():
            continue
        for item in root.iterdir():
            name = item.name
            if name not in SITE_PACKAGES_ALLOWLIST:
                continue
            if name in NO_QT_NAMES or name == '__pycache__' or name == 'pip' or name.startswith('pip-'):
                continue
            if name.endswith(('.dist-info', '.egg-info')):
                continue
            target = dest / name
            if target.exists():
                continue
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


def copy_calibre_from_debian(package):
    site_packages = package / 'lib' / 'python' / 'site-packages'
    site_packages.mkdir(parents=True, exist_ok=True)
    for name in CALIBRE_TOP_LEVEL_PACKAGES:
        src = CALIBRE_CODE_ROOT / name
        if not src.exists():
            continue
        if name == 'calibre':
            copytree(src, site_packages / name, ignore=ignore_calibre)
        else:
            copytree(src, site_packages / name, ignore=ignore_pycache)

    plugins_dest = site_packages / 'calibre' / 'plugins'
    plugins_dest.mkdir()
    for name in sorted(PLUGIN_ALLOWLIST):
        src = CALIBRE_PLUGIN_ROOT / name
        if not src.exists():
            raise SystemExit(f'Missing required native plugin: {src}')
        shutil.copy2(src, plugins_dest / name)

    for rel in STANDALONE_OVERLAY_FILES:
        src = ROOT / 'src' / rel
        if not src.exists():
            raise SystemExit(f'Missing standalone overlay file: {src}')
        dest = site_packages / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    patch_debian_ui(site_packages / 'calibre' / 'customize' / 'ui.py')
    patch_debian_img(site_packages / 'calibre' / 'utils' / 'img.py')
    patch_debian_mobi_files(site_packages)
    write_talebook_runtime_overlays(site_packages)


def patch_debian_ui(path):
    raw = path.read_text(encoding='utf-8')
    raw = raw.replace(
        'from calibre.customize.builtins import plugins as builtin_plugins',
        "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
        '    from calibre.customize.standalone_builtins import plugins as builtin_plugins\n'
        'else:\n'
        '    from calibre.customize.builtins import plugins as builtin_plugins',
    )
    raw = raw.replace(
        'from calibre.devices.interface import DevicePlugin',
        "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
        '    class DevicePlugin:\n'
        '        pass\n'
        'else:\n'
        '    from calibre.devices.interface import DevicePlugin',
    )
    path.write_text(raw, encoding='utf-8')


def write_talebook_runtime_overlays(site_packages):
    (site_packages / 'sitecustomize.py').write_text('''\
import os
import sys

os.environ.setdefault("CALIBRE_STANDALONE_CONVERTER", "1")
os.environ.setdefault("CALIBRE_STANDALONE_FORBID_QT", "1")
sys.resources_location = os.environ.get("TALEBOOK_CALIBRE_RESOURCES", "/usr/share/calibre")
sys.extensions_location = os.environ.get("TALEBOOK_CALIBRE_PLUGINS", "/usr/lib/calibre/calibre/plugins")
sys.executables_location = os.environ.get("TALEBOOK_CALIBRE_BIN", "/usr/lib/talebook-calibre/bin")
sys.system_plugins_location = None
sys.frozen = False
''', encoding='utf-8')

    gui2 = site_packages / 'calibre' / 'gui2'
    if gui2.exists():
        shutil.rmtree(gui2)
    gui2.mkdir()
    (gui2 / '__init__.py').write_text('''\
def must_use_qt(headless=True):
    return None
''', encoding='utf-8')


QT_CORE_IMPORT = (
    'from qt.core import QBuffer, QByteArray, QColor, QImage, QImageReader, '
    'QImageWriter, QIODevice, QPixmap, Qt, QTransform, qRgba'
)
IMAGEOPS_IMPORT = 'from calibre_extensions import imageops'
STANDALONE_IMG_OVERRIDE = (
    "\n\nif os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
    '    # No-Qt runtime: route Qt-backed image operations through the PIL-based backend.\n'
    '    from calibre.utils.standalone_img import (  # noqa: E402,F401\n'
    '        AnimatedGIF, NotImage, gif_data_to_png_data, image_and_format_from_data,\n'
    '        image_from_data, image_to_data, png_data_to_gif_data, resize_image,\n'
    '        resize_to_fit, save_cover_data_to, scale_image,\n'
    '    )\n'
)


def patch_debian_img(path):
    '''Make calibre.utils.img importable without Qt.

    img.py unconditionally imports qt.core and the native imageops extension at
    module load, so every ``from calibre.utils.img import ...`` explodes in the
    no-Qt runtime. Only the standalone converter's own conversion paths were
    patched to avoid it; talebook's webserver reaches many more sites (metadata
    read/write, cover handling). Guard the two module-level imports so the module
    loads, then override the Qt-backed public helpers with the PIL-based
    standalone_img implementations. The remaining functions (optimize_jpeg /
    encode_jpeg / optimize_png) are already Qt-free (they shell out) and degrade
    gracefully when their helper binaries are absent.
    '''
    raw = path.read_text(encoding='utf-8')
    if QT_CORE_IMPORT not in raw:
        raise SystemExit(f'Cannot patch {path}: missing qt.core import')
    if IMAGEOPS_IMPORT not in raw:
        raise SystemExit(f'Cannot patch {path}: missing imageops import')
    names = QT_CORE_IMPORT.split('import', 1)[1].strip()
    raw = raw.replace(
        QT_CORE_IMPORT,
        "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
        f'    {" = ".join(n.strip() for n in names.split(","))} = None\n'
        'else:\n'
        f'    {QT_CORE_IMPORT}',
    )
    raw = raw.replace(
        IMAGEOPS_IMPORT,
        "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
        '    imageops = None\n'
        'else:\n'
        f'    {IMAGEOPS_IMPORT}',
    )
    raw += STANDALONE_IMG_OVERRIDE
    path.write_text(raw, encoding='utf-8')


def patch_text(path, replacements):
    raw = path.read_text(encoding='utf-8')
    for old, new in replacements:
        if old not in raw:
            raise SystemExit(f'Cannot patch {path}: missing expected text: {old!r}')
        raw = raw.replace(old, new)
    path.write_text(raw, encoding='utf-8')


def patch_debian_mobi_files(site_packages):
    patch_text(site_packages / 'calibre' / 'ebooks' / 'conversion' / 'plugins' / 'mobi_output.py', (
        (
            "__docformat__ = 'restructuredtext en'\n",
            "__docformat__ = 'restructuredtext en'\n\nimport os\n",
        ),
        (
            '        from calibre.ebooks.oeb.transforms.rasterize import SVGRasterizer, Unavailable\n',
            "        if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
            '            class Unavailable(Exception):\n'
            '                pass\n\n'
            '            class SVGRasterizer:\n'
            '                def __init__(self):\n'
            '                    raise Unavailable()\n'
            '        else:\n'
            '            from calibre.ebooks.oeb.transforms.rasterize import SVGRasterizer, Unavailable\n',
        ),
    ))
    patch_text(site_packages / 'calibre' / 'ebooks' / 'mobi' / 'reader' / 'mobi6.py', (
        (
            'from calibre.utils.img import AnimatedGIF, gif_data_to_png_data, save_cover_data_to\n',
            "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
            '    from calibre.utils.standalone_img import AnimatedGIF, gif_data_to_png_data, save_cover_data_to\n'
            'else:\n'
            '    from calibre.utils.img import AnimatedGIF, gif_data_to_png_data, save_cover_data_to\n',
        ),
    ))
    patch_text(site_packages / 'calibre' / 'ebooks' / 'mobi' / 'utils.py', (
        (
            'from calibre.utils.img import image_from_data, image_to_data, png_data_to_gif_data, resize_image, save_cover_data_to, scale_image\n',
            "if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
            '    from calibre.utils.standalone_img import image_from_data, image_to_data, png_data_to_gif_data, resize_image, save_cover_data_to, scale_image\n'
            'else:\n'
            '    from calibre.utils.img import image_from_data, image_to_data, png_data_to_gif_data, resize_image, save_cover_data_to, scale_image\n',
        ),
    ))
    patch_text(site_packages / 'calibre' / 'ebooks' / 'mobi' / 'writer2' / 'resources.py', (
        (
            '                from calibre.utils.img import optimize_png\n',
            "                if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
            '                    from calibre.utils.standalone_img import optimize_png\n'
            '                else:\n'
            '                    from calibre.utils.img import optimize_png\n',
        ),
        (
            '        from calibre.utils.img import image_and_format_from_data, image_to_data\n',
            "        if os.environ.get('CALIBRE_STANDALONE_CONVERTER') == '1':\n"
            '            from calibre.utils.standalone_img import image_and_format_from_data, image_to_data\n'
            '        else:\n'
            '            from calibre.utils.img import image_and_format_from_data, image_to_data\n',
        ),
    ))


def copy_resources(package):
    resources = package / 'resources'
    if resources.exists():
        shutil.rmtree(resources)
    shutil.copytree(CALIBRE_RESOURCE_ROOT, resources, symlinks=False, ignore=ignore_pycache)
    for item in resources.iterdir():
        if item.name not in RESOURCE_KEEP:
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    copy_standalone_cjk_font(resources)


def copy_standalone_cjk_font(resources):
    fonts = resources / 'fonts'
    fonts.mkdir(parents=True, exist_ok=True)
    candidates = [os.environ.get('CALIBRE_STANDALONE_CJK_FONT'), *CJK_FONT_CANDIDATES]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            suffix = Path(candidate).suffix.lower() or '.ttf'
            shutil.copyfile(candidate, fonts / f'standalone-cjk{suffix}')
            return
    raise SystemExit('Missing CJK font for standalone PDF output. Install fonts-wqy-microhei or set CALIBRE_STANDALONE_CJK_FONT.')


def copy_python(package, python_exe):
    pybin = package / 'bin' / 'python3'
    shutil.copy2(python_exe, pybin)
    os.chmod(pybin, 0o755)
    stdlib_src = Path(f'/usr/lib/python{PY_VER}')
    stdlib_dest = package / 'lib' / f'python{PY_VER}'
    if stdlib_dest.exists():
        shutil.rmtree(stdlib_dest)
    shutil.copytree(stdlib_src, stdlib_dest, symlinks=False, ignore=ignore_stdlib)
    for item in stdlib_dest.glob('config-*'):
        if item.is_dir():
            shutil.rmtree(item)
    dynload = stdlib_dest / 'lib-dynload'
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
    runner.write_text('''\
import os
import sys
import tempfile

root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
site_packages = os.path.join(root, "lib", "python", "site-packages")
state_root = os.path.join(tempfile.gettempdir(), "calibre-ebook-convert-standalone")
os.environ.setdefault("CALIBRE_CONFIG_DIRECTORY", os.path.join(state_root, "config"))
os.environ.setdefault("CALIBRE_CACHE_DIRECTORY", os.path.join(state_root, "cache"))
os.environ["CALIBRE_STANDALONE_CONVERTER"] = "1"
os.environ.setdefault("CALIBRE_STANDALONE_FORBID_QT", "1")
sys.path[:0] = [site_packages]
sys.extensions_location = os.path.join(site_packages, "calibre", "plugins")
sys.resources_location = os.path.join(root, "resources")
sys.executables_location = os.path.join(root, "bin")
sys.system_plugins_location = None
sys.frozen = False
sys.calibre_basename = "ebook-convert"

from calibre.ebooks.conversion.standalone_binary import main

raise SystemExit(main(["ebook-convert", *sys.argv[1:]]))
''', encoding='utf-8')
    launcher = package / 'ebook-convert'
    launcher.write_text(f'''\
#!/bin/sh
HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PYTHONHOME="$HERE"
export PYTHONPATH="$HERE/lib/python/site-packages"
export LD_LIBRARY_PATH="$HERE/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
exec "$HERE/bin/python3" "$HERE/lib/python/run_ebook_convert.py" "$@"
''', encoding='utf-8')
    launcher.chmod(0o755)
    bindir_launcher = package / 'bin' / 'ebook-convert'
    if bindir_launcher.exists() or bindir_launcher.is_symlink():
        bindir_launcher.unlink()
    bindir_launcher.symlink_to('../ebook-convert')


def is_elf(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4) == ELF_MAGIC
    except OSError:
        return False


def should_scan_binary(path):
    if path.is_symlink() or not path.is_file():
        return False
    if path.suffix == '.so' or '.so.' in path.name or path.parent.name == 'bin':
        return is_elf(path)
    return False


def parse_ldd(path):
    ret = subprocess.run(('ldd', str(path)), text=True, capture_output=True)
    if ret.returncode != 0:
        return []
    ans = []
    for raw_line in ret.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if '=>' in line:
            before, _sep, after = line.partition('=>')
            soname = before.strip()
            lib = after.strip().split(' ', 1)[0]
            if lib.startswith('/'):
                ans.append((soname, Path(lib)))
        elif line.startswith('/'):
            lib = line.split(' ', 1)[0]
            ans.append((Path(lib).name, Path(lib)))
    return ans


def is_core_system_lib(name):
    return name.startswith(CORE_SYSTEM_LIB_PREFIXES)


def copy_library_dependency(src, soname, libdir):
    if soname.startswith(('Qt', 'libQt')):
        raise SystemExit(f'Unexpected Qt dependency while collecting libraries: {soname} from {src}')
    if is_core_system_lib(soname):
        return None
    real_src = src.resolve()
    dest = libdir / real_src.name
    if not dest.exists():
        shutil.copy2(real_src, dest)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IWRITE)
    alias = libdir / soname
    if soname != dest.name and not alias.exists():
        alias.symlink_to(dest.name)
    return dest


def copy_binary_dependencies(package):
    libdir = package / 'lib'
    queue = []
    for base in (package / 'bin', package / 'lib' / f'python{PY_VER}', package / 'lib' / 'python' / 'site-packages'):
        if not base.exists():
            continue
        for path in base.rglob('*'):
            if should_scan_binary(path):
                queue.append(path)
    seen = set()
    while queue:
        path = queue.pop()
        for soname, src in parse_ldd(path):
            if (soname, src.resolve()) in seen:
                continue
            seen.add((soname, src.resolve()))
            dest = copy_library_dependency(src, soname, libdir)
            if dest and should_scan_binary(dest):
                queue.append(dest)


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


def validate_standalone_code_surface(package):
    bad = []
    for path in package.rglob('*'):
        if not path.exists():
            continue
        if path.parent.name == 'calibre' and path.name == 'gui2' and is_gui2_stub(path):
            continue
        if path.parent.name == 'calibre' and path.name in FORBIDDEN_STANDALONE_CALIBRE_DIRS:
            bad.append(path)
        elif path.name == 'ImageQt.py' and path.parent.name == 'PIL':
            bad.append(path)
    if bad:
        raise SystemExit('Unexpected non-standalone code in package:\n' + '\n'.join(map(str, bad[:50])))


def is_gui2_stub(path):
    if not path.is_dir():
        return False
    entries = [x.name for x in path.iterdir()]
    return entries == ['__init__.py']


def validate_no_qt_dependencies(package):
    bad = []
    for path in package.rglob('*'):
        if should_scan_binary(path):
            for soname, _src in parse_ldd(path):
                if soname.startswith(('Qt', 'libQt')) or soname in NO_QT_NAMES:
                    bad.append(f'{path}: {soname}')
    if bad:
        raise SystemExit('Unexpected Qt dynamic dependencies:\n' + '\n'.join(bad[:50]))


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


def strip_elfs(package):
    count = 0
    for path in package.rglob('*'):
        if not should_scan_binary(path):
            continue
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
        ret = subprocess.run(('strip', '--strip-unneeded', str(path)), text=True, capture_output=True)
        if ret.returncode != 0:
            raise SystemExit(f'Failed to strip {path}:\n{ret.stderr}')
        count += 1
    print('Stripped ELF files:', count)


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
    parser = argparse.ArgumentParser(description='Build a local Linux no-Qt standalone ebook-convert package')
    parser.add_argument('--output', default='/out/calibre-ebook-convert-noqt-linux')
    parser.add_argument('--python', default=f'/usr/bin/python{PY_VER}')
    parser.add_argument('--no-strip', action='store_true')
    parser.add_argument('--no-archive', action='store_true')
    args = parser.parse_args(argv)

    package = Path(args.output).resolve()
    if package.exists():
        shutil.rmtree(package)
    (package / 'bin').mkdir(parents=True)
    (package / 'lib').mkdir()
    copy_python(package, Path(args.python).resolve())
    copy_site_packages(package / 'lib' / 'python' / 'site-packages')
    copy_calibre_from_debian(package)
    copy_resources(package)
    copy_helper_bins(package)
    write_launchers(package)
    copy_binary_dependencies(package)
    validate_package(package)
    if not args.no_strip:
        strip_elfs(package)
        validate_package(package)
    print('Package:', package)
    subprocess.check_call(['du', '-sh', str(package)])
    if not args.no_archive:
        create_archive(package)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
