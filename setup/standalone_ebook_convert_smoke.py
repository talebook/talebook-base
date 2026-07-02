#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

import argparse
import importlib.util
import os
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import types


FORMATS = ('epub', 'mobi', 'pdf', 'txt')
CJK_SENTINEL = '这是中文测试'
MACHO_MAGICS = {
    b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca',
    b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
}
ELF_MAGIC = b'\x7fELF'
PACKAGE_ROOT_ITEMS = {'bin', 'ebook-convert', 'lib', 'libexec', 'plugins', 'resources', 'share', 'translations'}
FORBIDDEN_CALIBRE_COMMANDS = frozenset({
    'calibre',
    'calibre-complete',
    'calibre-customize',
    'calibre-debug',
    'calibre-parallel',
    'calibre-postinstall',
    'calibre_postinstall',
    'calibre-server',
    'calibre-smtp',
    'calibredb',
    'ebook-device',
    'ebook-edit',
    'ebook-meta',
    'ebook-polish',
    'ebook-viewer',
    'fetch-ebook-metadata',
    'lrf2lrs',
    'lrfviewer',
    'lrs2lrf',
    'markdown-calibre',
    'web2disk',
})
FORBIDDEN_QT_ARTIFACT_MARKERS = frozenset({
    'qt',
    'PyQt6',
    'PyQt6_sip',
    'PyQt6_WebEngine',
    'QtWebEngineProcess',
    'qtwebengine_locales',
})
FORBIDDEN_STANDALONE_CALIBRE_DIRS = frozenset({
    'ai',
    'devices',
    'gui2',
    'headless',
    'scraper',
    'srv',
    'web',
})
FORBIDDEN_QT_NAMED_PYTHON_FILES = frozenset({
    ('PIL', 'ImageQt.py'),
})


def is_forbidden_qt_name(name):
    return name in FORBIDDEN_QT_ARTIFACT_MARKERS or (
        name.startswith(('Qt', 'libQt')) and (
            name.endswith('.framework') or name.endswith('.so') or name.endswith('.dylib')
        )
    )


def is_forbidden_qt_dependency_name(name):
    return name in FORBIDDEN_QT_ARTIFACT_MARKERS or name.startswith(('Qt', 'libQt'))


def binary_magic(path):
    try:
        with open(path, 'rb') as f:
            return f.read(4)
    except OSError:
        return b''


def parse_otool_deps(raw):
    for line in raw.splitlines()[1:]:
        line = line.strip()
        if not line or 'compatibility version' not in line:
            continue
        yield line.split(' (', 1)[0]


def parse_readelf_deps(raw):
    for line in raw.splitlines():
        if '(NEEDED)' not in line:
            continue
        before, sep, after = line.partition('[')
        if sep:
            yield after.partition(']')[0]


def iter_binary_dependencies(path):
    magic = binary_magic(path)
    if magic in MACHO_MAGICS and shutil.which('otool'):
        ret = subprocess.run(('otool', '-L', path), text=True, capture_output=True)
        if ret.returncode == 0:
            yield from parse_otool_deps(ret.stdout)
    elif magic == ELF_MAGIC and shutil.which('readelf'):
        ret = subprocess.run(('readelf', '-d', path), text=True, capture_output=True)
        if ret.returncode == 0:
            yield from parse_readelf_deps(ret.stdout)


def validate_no_qt_artifacts(root):
    for base, dirs, files in os.walk(root):
        names = set(dirs) | set(files)
        bad = names.intersection(FORBIDDEN_QT_ARTIFACT_MARKERS)
        bad.update(x for x in names if is_forbidden_qt_name(x))
        if bad:
            raise SystemExit(f'Unexpected Qt artifacts in standalone package under {base}: {sorted(bad)}')


def validate_standalone_code_surface(root):
    bad = []
    for base, dirs, files in os.walk(root):
        if os.path.basename(base) == 'calibre':
            bad.extend(os.path.join(base, x) for x in dirs if x in FORBIDDEN_STANDALONE_CALIBRE_DIRS)
        for package, filename in FORBIDDEN_QT_NAMED_PYTHON_FILES:
            if os.path.basename(base) == package and filename in files:
                bad.append(os.path.join(base, filename))
    if bad:
        raise SystemExit('Unexpected non-standalone code in package:\n' + '\n'.join(sorted(bad[:50])))


def validate_no_qt_dependencies(root):
    bad = []
    for base, _, files in os.walk(root):
        for name in files:
            path = os.path.join(base, name)
            for dep in iter_binary_dependencies(path):
                dep_name = os.path.basename(dep)
                if is_forbidden_qt_dependency_name(dep_name):
                    bad.append(f'{path}: {dep}')
    if bad:
        raise SystemExit('Unexpected Qt dynamic dependencies:\n' + '\n'.join(bad[:50]))


def file_size(path):
    if os.path.isdir(path):
        total = 0
        for base, _, files in os.walk(path):
            for name in files:
                f = os.path.join(base, name)
                try:
                    stat_result = os.lstat(f) if os.path.islink(f) else os.stat(f)
                    total += stat_result.st_size
                except OSError:
                    pass
        return total
    return os.path.getsize(path)


def validate_max_size(path, max_mb, label):
    if max_mb is None:
        return
    actual = file_size(path) / (1024 ** 2)
    if actual > max_mb:
        raise SystemExit(f'{label} is too large: {actual:.2f} MB > {max_mb:.2f} MB')


def run(cmd):
    print('+', ' '.join(cmd))
    subprocess.check_call(cmd)


def run_failure(cmd):
    print('+', ' '.join(cmd))
    ret = subprocess.run(cmd).returncode
    if ret == 0:
        raise SystemExit(f'Command unexpectedly succeeded: {cmd!r}')


def validate_package_root(package_root):
    if package_root.endswith('.app'):
        validate_macos_app(package_root)
        return
    validate_no_qt_artifacts(package_root)
    validate_standalone_code_surface(package_root)
    validate_no_qt_dependencies(package_root)
    found = set(os.listdir(package_root))
    unexpected = found - PACKAGE_ROOT_ITEMS
    missing = {'bin', 'ebook-convert', 'lib', 'resources'} - found
    if unexpected or missing:
        raise SystemExit(f'Unexpected package surface. Unexpected: {sorted(unexpected)}, missing: {sorted(missing)}')
    exposed = found | set(os.listdir(os.path.join(package_root, 'bin')))
    extra_commands = exposed.intersection(FORBIDDEN_CALIBRE_COMMANDS)
    if extra_commands:
        raise SystemExit(f'Unexpected calibre commands in standalone package: {sorted(extra_commands)}')
    for path in (os.path.join(package_root, 'ebook-convert'), os.path.join(package_root, 'bin', 'ebook-convert')):
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            raise SystemExit(f'Missing executable: {path}')


def validate_macos_app(app_path):
    validate_no_qt_artifacts(app_path)
    validate_standalone_code_surface(app_path)
    validate_no_qt_dependencies(app_path)
    contents = os.path.join(app_path, 'Contents')
    macos = os.path.join(contents, 'MacOS')
    if not os.path.isdir(macos):
        raise SystemExit(f'Missing MacOS directory: {macos}')
    found = set(os.listdir(macos))
    extra_commands = found.intersection(FORBIDDEN_CALIBRE_COMMANDS)
    if extra_commands:
        raise SystemExit(f'Unexpected calibre commands in standalone macOS app: {sorted(extra_commands)}')
    path = os.path.join(macos, 'ebook-convert')
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        raise SystemExit(f'Missing executable: {path}')
    plist_path = os.path.join(contents, 'Info.plist')
    if os.path.exists(plist_path):
        with open(plist_path, 'rb') as f:
            plist = plistlib.load(f)
        if plist.get('CFBundleExecutable') != 'ebook-convert':
            raise SystemExit(f'Unexpected CFBundleExecutable in standalone macOS app: {plist.get("CFBundleExecutable")!r}')


def normalized_member_names(members):
    names = tuple(x.name for x in members if x.name and not x.name.startswith('/'))
    top_level = {x.split('/', 1)[0] for x in names}
    if len(top_level) == 1 and not (top_level & PACKAGE_ROOT_ITEMS):
        prefix = next(iter(top_level)) + '/'
        return tuple(x[len(prefix):] for x in names if x.startswith(prefix) and x != prefix), next(iter(top_level))
    return names, None


def validate_archive_member(member):
    name = member.name
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
        raise SystemExit(f'Archive contains an unsupported member type: {name}')
    if os.path.isabs(name):
        raise SystemExit(f'Archive contains an absolute path: {name}')
    normalized = os.path.normpath(name)
    if normalized == '..' or normalized.startswith('../') or '/../' in normalized:
        raise SystemExit(f'Archive contains an unsafe path: {name}')
    if member.issym() or member.islnk():
        linkname = member.linkname
        if os.path.isabs(linkname):
            raise SystemExit(f'Archive contains an absolute link target: {name} -> {linkname}')
        target = os.path.normpath(os.path.join(os.path.dirname(normalized), linkname))
        if target == '..' or target.startswith('../') or '/../' in target:
            raise SystemExit(f'Archive contains an unsafe link target: {name} -> {linkname}')


def validate_archive_surface(members):
    names, _top_dir = normalized_member_names(members)
    qt_artifacts = []
    for member in names:
        name = os.path.basename(member)
        if is_forbidden_qt_name(name):
            qt_artifacts.append(member)
    if qt_artifacts:
        raise SystemExit(f'Unexpected Qt artifacts in standalone archive: {sorted(qt_artifacts)}')
    found = {x.split('/', 1)[0] for x in names}
    unexpected = found - PACKAGE_ROOT_ITEMS
    missing = {'bin', 'ebook-convert', 'lib', 'resources'} - found
    if unexpected or missing:
        raise SystemExit(f'Unexpected archive surface. Unexpected: {sorted(unexpected)}, missing: {sorted(missing)}')
    exposed = found | {x.split('/', 2)[1] for x in names if x.startswith('bin/') and '/' in x}
    extra_commands = exposed.intersection(FORBIDDEN_CALIBRE_COMMANDS)
    if extra_commands:
        raise SystemExit(f'Unexpected calibre commands in standalone archive: {sorted(extra_commands)}')


def extract_archive_for_validation(archive_path):
    tdir = tempfile.mkdtemp(prefix='standalone-ebook-convert-archive-')
    with tarfile.open(archive_path, mode='r:*') as tf:
        members = tuple(tf.getmembers())
        for member in members:
            validate_archive_member(member)
        validate_archive_surface(members)
        tf.extractall(tdir, members)
    _names, top_dir = normalized_member_names(members)
    return os.path.join(tdir, top_dir) if top_dir else tdir, tdir


def validate_archive(archive_path):
    package_root, tdir = extract_archive_for_validation(archive_path)
    try:
        validate_package_root(package_root)
    finally:
        shutil.rmtree(tdir)


def inferred_package_root(converter_arg, converter):
    if os.path.basename(converter_arg) == converter_arg:
        return None
    q = os.path.dirname(os.path.abspath(converter))
    if os.path.basename(q) == 'MacOS' and os.path.basename(os.path.dirname(q)) == 'Contents':
        return os.path.dirname(os.path.dirname(q))
    if os.path.basename(q) == 'bin':
        q = os.path.dirname(q)
    return q


def create_seed_txt(path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(
            '# Standalone ebook-convert smoke test\n\n'
            f'{CJK_SENTINEL}，用于确认 PDF 输出不会丢失非 Latin-1 字符。\n\n'
            'This file is generated during package verification.\n\n'
            'It intentionally contains enough structure to exercise the conversion pipeline.\n'
        )


def load_standalone_binary_module():
    class Log:
        def error(self, *args):
            pass

    modules = {
        'calibre': types.ModuleType('calibre'),
        'calibre.utils': types.ModuleType('calibre.utils'),
        'calibre.utils.logging': types.ModuleType('calibre.utils.logging'),
        'calibre.ebooks': types.ModuleType('calibre.ebooks'),
        'calibre.ebooks.conversion': types.ModuleType('calibre.ebooks.conversion'),
        'calibre.ebooks.conversion.cli': types.ModuleType('calibre.ebooks.conversion.cli'),
    }
    modules['calibre.utils.logging'].Log = Log
    modules['calibre.ebooks.conversion.cli'].main = lambda args: 0
    old_modules = {k: sys.modules.get(k) for k in modules}
    sys.modules.update(modules)
    try:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'src', 'calibre', 'ebooks', 'conversion', 'standalone_binary.py')
        spec = importlib.util.spec_from_file_location('standalone_binary_under_test', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        for name, old in old_modules.items():
            if old is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = old


def write_executable(path):
    with open(path, 'w', encoding='utf-8') as f:
        f.write('#!/bin/sh\n')
    os.chmod(path, 0o700)


def create_fake_package_root():
    tdir = tempfile.mkdtemp(prefix='standalone-ebook-convert-package-')
    for name in ('bin', 'lib', 'resources'):
        os.mkdir(os.path.join(tdir, name))
    write_executable(os.path.join(tdir, 'ebook-convert'))
    write_executable(os.path.join(tdir, 'bin', 'ebook-convert'))
    write_executable(os.path.join(tdir, 'bin', 'pdftohtml'))
    return tdir


def create_fake_macos_app():
    tdir = tempfile.mkdtemp(prefix='standalone-ebook-convert-macos-')
    contents = os.path.join(tdir, 'ebook-convert.app', 'Contents')
    macos = os.path.join(contents, 'MacOS')
    os.makedirs(macos)
    write_executable(os.path.join(macos, 'ebook-convert'))
    with open(os.path.join(contents, 'Info.plist'), 'wb') as f:
        plistlib.dump({'CFBundleExecutable': 'ebook-convert'}, f)
    return os.path.join(tdir, 'ebook-convert.app'), tdir


def archive_package_root(package_root, with_top_level_dir=False):
    archive = os.path.join(tempfile.gettempdir(), 'standalone-ebook-convert-self-test.txz')
    try:
        os.remove(archive)
    except FileNotFoundError:
        pass
    with tarfile.open(archive, 'w:xz') as tf:
        if with_top_level_dir:
            tf.add(package_root, arcname='ebook-convert-standalone')
            return archive
        cwd = os.getcwd()
        os.chdir(package_root)
        try:
            for x in os.listdir('.'):
                tf.add(x)
        finally:
            os.chdir(cwd)
    return archive


def create_unsafe_archive():
    archive = os.path.join(tempfile.gettempdir(), 'standalone-ebook-convert-unsafe-self-test.txz')
    try:
        os.remove(archive)
    except FileNotFoundError:
        pass
    info = tarfile.TarInfo('../escape')
    info.size = 1
    with tarfile.open(archive, 'w:xz') as tf:
        tf.addfile(info, fileobj=types.SimpleNamespace(read=lambda n=-1: b'x'))
    return archive


def self_test():
    mod = load_standalone_binary_module()
    assert mod.path_format('book.epub') == 'epub'
    assert mod.path_format('.mobi') == 'mobi'
    assert mod.validate_args(['ebook-convert', 'a.epub', 'b.pdf'])
    assert mod.validate_args(['ebook-convert', 'a.epub', 'b.pdf', '-h'])
    assert mod.validate_args(['ebook-convert', '-h'])
    assert mod.validate_args(['ebook-convert', 'a.docx', 'b.epub', '--version'])
    assert not mod.validate_args(['ebook-convert', 'a.docx', 'b.epub'])
    assert not mod.validate_args(['ebook-convert', 'a.docx', 'b.epub', '-h'])
    assert not mod.validate_args(['ebook-convert', 'a.epub', 'b.docx'])
    assert not mod.validate_args(['ebook-convert', '--list-recipes'])
    assert tuple(parse_otool_deps('x:\n\t@rpath/QtCore.framework/Versions/A/QtCore (compatibility version 1.0.0, current version 1.0.0)\n')) == (
        '@rpath/QtCore.framework/Versions/A/QtCore',
    )
    assert tuple(parse_readelf_deps(' 0x0000000000000001 (NEEDED)             Shared library: [libQt6Core.so.6]\n')) == (
        'libQt6Core.so.6',
    )
    tiny = tempfile.mkdtemp(prefix='standalone-ebook-convert-size-')
    try:
        with open(os.path.join(tiny, 'x'), 'wb') as f:
            f.write(b'x' * 1024)
        validate_max_size(tiny, 1, 'test package')
        try:
            validate_max_size(tiny, 0.0001, 'test package')
        except SystemExit:
            pass
        else:
            raise AssertionError('oversized package was accepted')
    finally:
        shutil.rmtree(tiny)
    assert inferred_package_root('/tmp/pkg/bin/ebook-convert', '/tmp/pkg/bin/ebook-convert') == '/tmp/pkg'
    assert inferred_package_root(
        '/tmp/ebook-convert.app/Contents/MacOS/ebook-convert',
        '/tmp/ebook-convert.app/Contents/MacOS/ebook-convert',
    ) == '/tmp/ebook-convert.app'

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    standalone_builtins = open(os.path.join(root, 'src', 'calibre', 'customize', 'standalone_builtins.py'), encoding='utf-8').read()
    standalone_binary = open(os.path.join(root, 'src', 'calibre', 'ebooks', 'conversion', 'standalone_binary.py'), encoding='utf-8').read()
    for name in ('HTMLInput', 'OEBOutput'):
        assert name in standalone_builtins
    assert 'CALIBRE_STANDALONE_FORBID_QT' in standalone_binary

    package_root = create_fake_package_root()
    try:
        validate_package_root(package_root)
        archive = archive_package_root(package_root)
        validate_archive(archive)
        archive = archive_package_root(package_root, with_top_level_dir=True)
        validate_archive(archive)
        archive = create_unsafe_archive()
        try:
            validate_archive(archive)
        except SystemExit:
            pass
        else:
            raise AssertionError('unsafe archive path was accepted')
        os.mkdir(os.path.join(package_root, 'lib', 'PyQt6'))
        try:
            validate_package_root(package_root)
        except SystemExit:
            pass
        else:
            raise AssertionError('Qt artifacts were accepted in standalone package')
        shutil.rmtree(os.path.join(package_root, 'lib', 'PyQt6'))
        open(os.path.join(package_root, 'lib', 'libQt6Core.so'), 'wb').close()
        try:
            validate_package_root(package_root)
        except SystemExit:
            pass
        else:
            raise AssertionError('libQt artifacts were accepted in standalone package')
        os.remove(os.path.join(package_root, 'lib', 'libQt6Core.so'))
        os.makedirs(os.path.join(package_root, 'lib', 'python', 'calibre', 'gui2'))
        try:
            validate_package_root(package_root)
        except SystemExit:
            pass
        else:
            raise AssertionError('non-standalone calibre code was accepted')
        shutil.rmtree(os.path.join(package_root, 'lib', 'python'))
        write_executable(os.path.join(package_root, 'bin', 'calibre_postinstall'))
        try:
            validate_package_root(package_root)
        except SystemExit:
            pass
        else:
            raise AssertionError('forbidden calibre command was accepted')
    finally:
        shutil.rmtree(package_root)
    app_path, app_root = create_fake_macos_app()
    try:
        validate_package_root(app_path)
        with open(os.path.join(app_path, 'Contents', 'Info.plist'), 'wb') as f:
            plistlib.dump({'CFBundleExecutable': 'calibre'}, f)
        try:
            validate_package_root(app_path)
        except SystemExit:
            pass
        else:
            raise AssertionError('wrong macOS bundle executable was accepted')
        with open(os.path.join(app_path, 'Contents', 'Info.plist'), 'wb') as f:
            plistlib.dump({'CFBundleExecutable': 'ebook-convert'}, f)
        os.makedirs(os.path.join(app_path, 'Contents', 'Frameworks', 'QtCore.framework'))
        try:
            validate_package_root(app_path)
        except SystemExit:
            pass
        else:
            raise AssertionError('Qt framework was accepted in standalone macOS app')
        shutil.rmtree(os.path.join(app_path, 'Contents', 'Frameworks'))
        write_executable(os.path.join(app_path, 'Contents', 'MacOS', 'calibre-debug'))
        try:
            validate_package_root(app_path)
        except SystemExit:
            pass
        else:
            raise AssertionError('forbidden macOS calibre command was accepted')
    finally:
        shutil.rmtree(app_root)
    print('standalone ebook-convert self-test ok')


def smoke_test(converter, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    sources = {'txt': os.path.join(work_dir, 'seed.txt')}
    create_seed_txt(sources['txt'])

    for fmt in FORMATS:
        if fmt == 'txt':
            continue
        path = os.path.join(work_dir, f'seed.{fmt}')
        run([converter, sources['txt'], path])
        if fmt == 'pdf':
            assert_pdf_contains(converter, path, CJK_SENTINEL)
        sources[fmt] = path

    for input_fmt, input_path in sources.items():
        for output_fmt in FORMATS:
            if input_fmt == output_fmt:
                continue
            output_path = os.path.join(work_dir, f'{input_fmt}-to-{output_fmt}.{output_fmt}')
            run([converter, input_path, output_path])
            if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                raise SystemExit(f'Conversion produced no output: {input_fmt} -> {output_fmt}')
            if output_fmt == 'pdf':
                assert_pdf_contains(converter, output_path, CJK_SENTINEL)

    run_failure([converter, sources['txt'], os.path.join(work_dir, 'unsupported.docx')])
    run_failure([converter, os.path.join(work_dir, 'unsupported.docx'), os.path.join(work_dir, 'unsupported.epub')])
    run_failure([converter, os.path.join(work_dir, 'unsupported.docx'), os.path.join(work_dir, 'unsupported.epub'), '-h'])
    run_failure([converter, '--list-recipes'])


def pdftotext_for_converter(converter):
    package_root = inferred_package_root(converter, converter)
    if package_root:
        candidate = os.path.join(package_root, 'bin', 'pdftotext')
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    q = shutil.which('pdftotext')
    if q:
        return q
    raise SystemExit('Cannot validate PDF text: pdftotext not found')


def assert_pdf_contains(converter, pdf_path, text):
    exe = pdftotext_for_converter(converter)
    ret = subprocess.run((exe, pdf_path, '-'), text=True, capture_output=True)
    if ret.returncode != 0:
        raise SystemExit(f'pdftotext failed for {pdf_path}:\n{ret.stderr}')
    extracted = ret.stdout
    if text not in extracted:
        sample = extracted[:500].replace('\n', ' ')
        raise SystemExit(f'PDF text validation failed for {pdf_path}: missing {text!r}; got {sample!r}')


def main(argv=sys.argv):
    parser = argparse.ArgumentParser(description='Smoke test a standalone ebook-convert binary package.')
    parser.add_argument('converter', nargs='?', help='Path to the ebook-convert binary to test')
    parser.add_argument('--archive', help='Standalone package archive to validate')
    parser.add_argument('--package-root', help='Extracted package root to validate. Inferred when converter is a package path.')
    parser.add_argument('--work-dir', help='Directory for generated test books')
    parser.add_argument('--keep', action='store_true', help='Keep generated files')
    parser.add_argument('--forbid-qt-imports', action='store_true', help='Fail if the standalone converter imports qt/PyQt6 during smoke tests')
    parser.add_argument('--max-archive-mb', type=float, help='Fail if --archive is larger than this many MiB')
    parser.add_argument('--max-package-mb', type=float, help='Fail if the extracted package root is larger than this many MiB')
    parser.add_argument('--self-test', action='store_true', help='Run smoke-test helper unit checks without requiring ebook-convert')
    args = parser.parse_args(argv[1:])

    if args.self_test:
        self_test()
        return 0
    if args.forbid_qt_imports:
        os.environ['CALIBRE_STANDALONE_FORBID_QT'] = '1'

    if args.archive:
        archive = os.path.abspath(args.archive)
        validate_archive(archive)
        validate_max_size(archive, args.max_archive_mb, 'archive')
    if args.package_root:
        package_root = os.path.abspath(args.package_root)
        validate_package_root(package_root)
        validate_max_size(package_root, args.max_package_mb, 'package')
    if args.converter is None and (args.archive or args.package_root):
        return 0

    converter_arg = args.converter or 'ebook-convert'
    converter = shutil.which(converter_arg) if os.path.basename(converter_arg) == converter_arg else converter_arg
    if not converter:
        raise SystemExit(f'Cannot find converter binary: {converter_arg}')
    package_root = inferred_package_root(converter_arg, converter)
    if package_root:
        validate_package_root(package_root)
        validate_max_size(package_root, args.max_package_mb, 'package')

    if args.work_dir:
        smoke_test(converter, os.path.abspath(args.work_dir))
        return 0

    work_dir = tempfile.mkdtemp(prefix='standalone-ebook-convert-')
    try:
        smoke_test(converter, work_dir)
    finally:
        if args.keep:
            print('Generated files kept in:', work_dir)
        else:
            shutil.rmtree(work_dir)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
