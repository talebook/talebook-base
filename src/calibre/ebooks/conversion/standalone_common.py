__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid@kovidgoyal.net>'

'''
Shared helpers for the standalone ebook-convert backends.

Entry points import this before installing the Qt import guard, so nothing
here may import Qt or anything that dispatches on CALIBRE_STANDALONE_CONVERTER.
'''

import os
import sys

SUPPORTED_INPUT_FORMATS = frozenset({
    'azw', 'azw3', 'docx', 'epub', 'mobi', 'original_epub',
    'pdf', 'prc', 'txt', 'zip',
})


def extension_of(path):
    if path.startswith('.') and path[:2] not in {'..', '.'} and '/' not in path and '\\' not in path:
        ext = path[1:]
    else:
        ext = os.path.splitext(path)[1][1:]
    return ext.lower()


def install_qt_import_guard(binary_name):
    import importlib.abc

    class BlockQt(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'qt' or fullname.startswith('qt.') or fullname == 'PyQt6' or fullname.startswith('PyQt6.'):
                raise ImportError(f'Qt import blocked in standalone {binary_name}: {fullname}')
            return None

    sys.meta_path.insert(0, BlockQt())
