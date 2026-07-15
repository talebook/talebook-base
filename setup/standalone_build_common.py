#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Kovid Goyal <kovid at kovidgoyal.net>

'''
Constants shared by the local standalone ebook-convert build scripts
(build_standalone_ebook_convert_local.py and
build_standalone_ebook_convert_linux_local.py). Platform specific lists
(CJK fonts, resource keep lists, ...) stay in the per-platform scripts.
'''

NO_QT_NAMES = {'qt', 'PyQt6', 'PyQt6_sip', 'PyQt6_WebEngine'}
FORBIDDEN_STANDALONE_CALIBRE_DIRS = frozenset({
    'ai',
    'devices',
    'gui2',
    'headless',
    'scraper',
    'srv',
    'web',
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
QT_NAMED_PYTHON_FILES = (
    ('PIL', 'ImageQt.py'),
)
HELPER_BINS = ('pdftohtml', 'pdfinfo', 'pdftoppm', 'pdftotext')
PYTHON_DYNLOAD_DROP_PREFIXES = ('_test', '_xxtest')
PYTHON_DYNLOAD_DROP_NAMES = {
    '_ctypes_test',
    'xxlimited',
    'xxlimited_35',
}
