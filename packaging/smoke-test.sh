#!/bin/sh
set -eu

CALIBRE_ROOT="${TALEBOOK_CALIBRE_RUNTIME:-/usr/lib/calibre}"
RUNTIME_ROOT="/usr/lib/talebook-calibre"
HELPER_ROOT="${TALEBOOK_CALIBRE_BIN:-$RUNTIME_ROOT/bin}"
FIXTURE="${1:-resources/quick_start/eng.epub}"
MAX_USR_MIB="${TALEBOOK_MAX_USR_MIB:-400}"

test -d "$CALIBRE_ROOT"
test -d "$RUNTIME_ROOT/lib"
test ! -e /usr/lib/talebook-calibre-runtime
test -f "$FIXTURE"

usr_mib="$(du -smx /usr | awk '{print $1}')"
if test "$usr_mib" -gt "$MAX_USR_MIB"; then
    echo "runtime /usr size ${usr_mib} MiB exceeds ${MAX_USR_MIB} MiB budget" >&2
    exit 1
fi

command -v ebook-convert
command -v ebook-convert-pdf
command -v calibredb
python3 -m pip --version
python3 -m pip install --dry-run --no-index quickjs setuptools

is_installed() {
    dpkg-query -W -f='${Status}\n' "$1" 2>/dev/null | grep -qx 'install ok installed'
}

if is_installed calibre; then
    echo "Debian calibre package must not be installed in the final image" >&2
    exit 1
fi

for package in build-essential python3-dev python3-venv; do
    if is_installed "$package"; then
        echo "$package must not be installed in the final image" >&2
        exit 1
    fi
done
if command -v gcc >/dev/null 2>&1; then
    echo "gcc must not be installed in the final image" >&2
    exit 1
fi

test ! -L /usr/lib/calibre
test ! -L /usr/share/calibre
test -x "$HELPER_ROOT/pdftotext"
test ! -e "$CALIBRE_ROOT/calibre/ebooks/conversion/plugins/standalone_pdf_output.py"

if find "$CALIBRE_ROOT" "$RUNTIME_ROOT" /usr/share/calibre \( ! -user root -o ! -group root \) -print -quit | grep -q .; then
    echo "runtime contains non-root-owned files" >&2
    exit 1
fi

if python3 -c "import PyQt6" >/tmp/pyqt.out 2>/tmp/pyqt.err; then
    echo "PyQt6 should not be installed in talebook-base slim runtime" >&2
    exit 1
fi

find "$CALIBRE_ROOT" "$RUNTIME_ROOT" -type f \( -name '*.so' -o -perm -0100 \) | while IFS= read -r binary; do
    dependencies="$(ldd "$binary" 2>/dev/null || true)"
    if printf '%s\n' "$dependencies" | grep -q 'not found'; then
        echo "runtime binary has missing dependencies: $binary" >&2
        printf '%s\n' "$dependencies" >&2
        exit 1
    fi
    if printf '%s\n' "$dependencies" | grep -Eiq '(^|[/[:space:]])(lib)?Qt[0-9A-Za-z_.-]*'; then
        echo "runtime binary links Qt: $binary" >&2
        printf '%s\n' "$dependencies" >&2
        exit 1
    fi
done

python3 - <<'PY'
import sys

import calibre
import quickjs
from calibre import gui2
from calibre.db.cli.main import main as calibredb_main
from calibre.db.legacy import LibraryDatabase
from calibre.ebooks.conversion.standalone_binary import SUPPORTED_OUTPUT_FORMATS

assert calibre.__file__.startswith("/usr/lib/calibre/")
assert gui2.must_use_qt() is None
assert callable(calibredb_main)
assert callable(quickjs.Context)
assert LibraryDatabase.__name__ == "LibraryDatabase"
assert SUPPORTED_OUTPUT_FORMATS == frozenset({"azw3", "epub", "mobi", "txt"})
assert sys.resources_location == "/usr/share/calibre"
assert sys.extensions_location == "/usr/lib/calibre/calibre/plugins"
assert sys.executables_location == "/usr/lib/talebook-calibre/bin"
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
"$HELPER_ROOT/pdftotext" /tmp/convert-test-cjk.pdf /tmp/convert-test-cjk-extracted.txt
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
