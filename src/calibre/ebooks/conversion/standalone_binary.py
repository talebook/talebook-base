__license__ = 'GPL 3'
__copyright__ = '2026, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

'''
Restricted ebook-convert entry point for standalone converter packages.
'''

import os
import sys

os.environ.setdefault('CALIBRE_STANDALONE_CONVERTER', '1')

from calibre.ebooks.conversion.standalone_common import SUPPORTED_INPUT_FORMATS, extension_of, install_qt_import_guard

if os.environ.get('CALIBRE_STANDALONE_FORBID_QT') == '1':
    install_qt_import_guard('ebook-convert')

from calibre.utils.logging import Log

from calibre.ebooks.conversion.cli import main as ebook_convert_main

SUPPORTED_OUTPUT_FORMATS = frozenset({'azw3', 'epub', 'mobi', 'txt'})


def conversion_paths(args):
    '''
    Return the input/output paths for the calibre CLI shape:
    ebook-convert INPUT OUTPUT [options...]

    A few global options may appear before the paths; once two positional paths
    are found, later conversion options are intentionally ignored here.
    '''
    positional = []
    after_separator = False
    for arg in args[1:]:
        if not after_separator and arg == '--':
            after_separator = True
            continue
        if not after_separator and arg.startswith('-'):
            continue
        positional.append(arg)
    for i, first in enumerate(positional[:-1]):
        second = positional[i + 1]
        if extension_of(first) and extension_of(second):
            return first, second
    if len(positional) >= 2:
        return positional[0], positional[1]
    return None, None


def validate_args(args, log=None):
    log = log or Log()
    if '--version' in args:
        return True
    if '--list-recipes' in args:
        log.error('Builtin recipe conversion is not included in this standalone binary')
        return False
    input_path, output_path = conversion_paths(args)
    if not input_path or not output_path:
        return True
    input_fmt = extension_of(input_path)
    output_fmt = extension_of(output_path)
    bad = []
    if input_fmt not in SUPPORTED_INPUT_FORMATS:
        bad.append(('input', input_fmt or 'open ebook/folder'))
    if output_fmt not in SUPPORTED_OUTPUT_FORMATS:
        bad.append(('output', output_fmt or 'open ebook/folder'))
    if bad:
        allowed_input = ', '.join(sorted(SUPPORTED_INPUT_FORMATS))
        allowed_output = ', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))
        for which, fmt in bad:
            log.error(f'Unsupported {which} format for this standalone binary: {fmt}')
        log.error(f'This standalone binary supports these input formats: {allowed_input}')
        log.error(f'This standalone binary supports these output formats: {allowed_output}')
        return False
    return True


def main(args=sys.argv):
    if not validate_args(args):
        return 2
    return ebook_convert_main(args)
