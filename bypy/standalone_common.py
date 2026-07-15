#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Constants and helpers shared by the Linux and macOS standalone ebook-convert
package builders. The repository bypy/ directory is not an importable package
(the bypy build tool provides the bypy.* modules), so the platform
__main__.py scripts load this file by path.
'''

import glob
import os
import shutil


def is_standalone_build():
    return 'ebook-convert' in (
        os.environ.get('CALIBRE_LINUX_BINARY_FLAVOR', ''),
        os.environ.get('CALIBRE_MACOS_BINARY_FLAVOR', ''),
    )


STANDALONE_NO_QT_PACKAGES = {'PyQt6', 'PyQt6_sip', 'PyQt6_WebEngine', 'qt'}
STANDALONE_FORBIDDEN_QT_ARTIFACTS = {
    'qt', 'PyQt6', 'PyQt6_sip', 'PyQt6_WebEngine', 'QtWebEngineProcess',
    'qtwebengine_locales',
}
STANDALONE_CALIBRE_DROP_DIRS = {
    'ai', 'devices', 'gui2', 'headless', 'scraper', 'srv', 'web',
}
STANDALONE_RESOURCE_KEEP = frozenset({
    'calibre-ebook-root-CA.crt',
    'common-english-words.txt',
    'default_tweaks.py',
    'fonts',
    'localization',
    'mime.types',
    'pdf-preprint.js',
    'templates',
})
STANDALONE_QT_NAMED_PYTHON_FILES = {
    ('PIL', 'ImageQt.py'),
}
STANDALONE_CALIBRE_EXTENSIONS = {
    'cPalmdoc', 'fast_css_transform', 'fast_html_entities', 'freetype',
    'html_as_json', 'hyphen', 'icu', 'matcher', 'podofo', 'speedup',
    'translator', 'uchardet', 'unicode_names',
}


def is_forbidden_qt_artifact(name):
    return name in STANDALONE_FORBIDDEN_QT_ARTIFACTS or (
        name.startswith(('Qt', 'libQt')) and name.endswith(('.so', '.dylib', '.framework'))
    )


def validate_no_qt_artifacts(root, what='package'):
    for base, dirs, files in os.walk(root):
        bad = sorted(x for x in set(dirs) | set(files) if is_forbidden_qt_artifact(x))
        if bad:
            raise SystemExit(f'Unexpected Qt artifacts in standalone {what} under {base}: {bad}')


def prune_standalone_resources(resources):
    if not is_standalone_build():
        return
    for name in os.listdir(resources):
        path = os.path.join(resources, name)
        if name not in STANDALONE_RESOURCE_KEEP:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)


def copy_standalone_cjk_font(resources, candidates, error_hint):
    if not is_standalone_build():
        return
    fonts = os.path.join(resources, 'fonts')
    os.makedirs(fonts, exist_ok=True)
    for candidate in (os.environ.get('CALIBRE_STANDALONE_CJK_FONT'), *candidates):
        if candidate and os.path.exists(candidate):
            _base, ext = os.path.splitext(candidate)
            shutil.copyfile(candidate, os.path.join(fonts, 'standalone-cjk' + (ext or '.ttf')))
            return
    raise SystemExit(f'Missing CJK font for standalone PDF output. {error_hint}')


def filter_standalone_calibre_extensions(dest, ext_map):
    if not is_standalone_build():
        return ext_map
    for path in glob.glob(os.path.join(dest, '*.so')):
        name = os.path.basename(path).partition('.')[0]
        if name not in STANDALONE_CALIBRE_EXTENSIONS:
            os.remove(path)
    ans = {}
    for key, path in ext_map.items():
        name = os.path.basename(path).partition('.')[0]
        key_name = str(key).rpartition('.')[-1]
        if name in STANDALONE_CALIBRE_EXTENSIONS or key_name in STANDALONE_CALIBRE_EXTENSIONS:
            ans[key] = path
    return ans
