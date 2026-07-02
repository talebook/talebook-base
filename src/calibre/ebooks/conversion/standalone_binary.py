__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

'''
Restricted ebook-convert entry point for standalone converter packages.
'''

import os
import sys

os.environ.setdefault('CALIBRE_STANDALONE_CONVERTER', '1')


def install_qt_import_guard():
    import importlib.abc

    class BlockQt(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'qt' or fullname.startswith('qt.') or fullname == 'PyQt6' or fullname.startswith('PyQt6.'):
                raise ImportError(f'Qt import blocked in standalone ebook-convert: {fullname}')
            return None

    sys.meta_path.insert(0, BlockQt())


if os.environ.get('CALIBRE_STANDALONE_FORBID_QT') == '1':
    install_qt_import_guard()

from calibre.utils.logging import Log

from calibre.ebooks.conversion.cli import main as ebook_convert_main

SUPPORTED_USER_FORMATS = frozenset({'epub', 'mobi', 'pdf', 'txt'})


def path_format(path):
    if path.startswith('.') and path[:2] not in {'..', '.'} and '/' not in path and '\\' not in path:
        ext = path[1:]
    else:
        ext = os.path.splitext(path)[1][1:]
    return ext.lower()


def validate_args(args, log=None):
    log = log or Log()
    if '--version' in args:
        return True
    if '--list-recipes' in args:
        log.error('Builtin recipe conversion is not included in this standalone binary')
        return False
    if len(args) < 3:
        return True
    input_fmt = path_format(args[1])
    output_fmt = path_format(args[2])
    bad = []
    if input_fmt not in SUPPORTED_USER_FORMATS:
        bad.append(('input', input_fmt or 'open ebook/folder'))
    if output_fmt not in SUPPORTED_USER_FORMATS:
        bad.append(('output', output_fmt or 'open ebook/folder'))
    if bad:
        allowed = ', '.join(sorted(SUPPORTED_USER_FORMATS))
        for which, fmt in bad:
            log.error(f'Unsupported {which} format for this standalone binary: {fmt}')
        log.error(f'This standalone binary supports only these formats: {allowed}')
        return False
    return True


def main(args=sys.argv):
    if not validate_args(args):
        return 2
    return ebook_convert_main(args)
