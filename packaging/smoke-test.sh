#!/bin/sh
set -eu

RUNTIME="${TALEBOOK_CALIBRE_PRIVATE_RUNTIME:-/usr/lib/talebook-calibre-runtime}"
FIXTURE="${1:-resources/quick_start/eng.epub}"

test -d "$RUNTIME"
test -f "$FIXTURE"
command -v ebook-convert
command -v ebook-convert-pdf
command -v calibredb

test "$(readlink /usr/lib/calibre)" = "$RUNTIME/lib/python/site-packages"
test "$(readlink /usr/share/calibre)" = "$RUNTIME/resources"

if find "$RUNTIME" \( ! -user root -o ! -group root \) -print -quit | grep -q .; then
    echo "runtime contains non-root-owned files" >&2
    exit 1
fi

if python3 -c "import PyQt6" >/tmp/pyqt.out 2>/tmp/pyqt.err; then
    echo "PyQt6 should not be installed in talebook-base slim runtime" >&2
    exit 1
fi

python3 - <<'PY'
import sys

import calibre
from calibre import gui2
from calibre.db.cli.main import main as calibredb_main
from calibre.db.legacy import LibraryDatabase

assert calibre.__file__.startswith("/usr/lib/calibre/")
assert gui2.must_use_qt() is None
assert callable(calibredb_main)
assert LibraryDatabase.__name__ == "LibraryDatabase"
assert sys.resources_location == "/usr/share/calibre"
assert sys.extensions_location == "/usr/lib/calibre/calibre/plugins"
assert sys.executables_location == "/usr/bin"
PY

calibredb --version
rm -rf /tmp/talebook-calibre-lib /tmp/convert-test.* /tmp/convert-test-*
python3 - <<'PY'
from calibre.db.legacy import LibraryDatabase

LibraryDatabase("/tmp/talebook-calibre-lib")
PY
calibredb list --library-path /tmp/talebook-calibre-lib

ebook-convert "$FIXTURE" /tmp/convert-test.mobi
ebook-convert "$FIXTURE" /tmp/convert-test.azw3
ebook-convert "$FIXTURE" /tmp/convert-test.pdf \
    --paper-size=a5 \
    --pdf-page-margin-left=15 \
    --pdf-page-margin-top=15 \
    --pdf-page-margin-right=15 \
    --pdf-page-margin-bottom=15
ebook-convert-pdf "$FIXTURE" /tmp/convert-test-direct.pdf \
    --weasy-page-size A5 \
    --weasy-margin 15pt

printf '%s\n' 'Talebook standalone PDF 这是中文测试 😀' > /tmp/convert-test-cjk.txt
ebook-convert /tmp/convert-test-cjk.txt /tmp/convert-test-cjk.pdf
"$RUNTIME/bin/pdftotext" /tmp/convert-test-cjk.pdf /tmp/convert-test-cjk-extracted.txt
grep -F '这是中文测试' /tmp/convert-test-cjk-extracted.txt

test -s /tmp/convert-test.mobi
test -s /tmp/convert-test.azw3
test -s /tmp/convert-test.pdf
test -s /tmp/convert-test-direct.pdf
test -s /tmp/convert-test-cjk.pdf
ls -lh \
    /tmp/convert-test.mobi \
    /tmp/convert-test.azw3 \
    /tmp/convert-test.pdf \
    /tmp/convert-test-direct.pdf \
    /tmp/convert-test-cjk.pdf
