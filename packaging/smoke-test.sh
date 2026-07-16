#!/bin/sh
set -eu

CALIBRE_ROOT="${TALEBOOK_CALIBRE_RUNTIME:-/usr/lib/calibre}"
RUNTIME_ROOT="/usr/lib/talebook-calibre"
HELPER_ROOT="${TALEBOOK_CALIBRE_BIN:-$RUNTIME_ROOT/bin}"
FIXTURE="${1:-resources/quick_start/eng.epub}"
MAX_USR_MIB="${TALEBOOK_MAX_USR_MIB:-400}"
export FIXTURE

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
command -v calibredb
if command -v ebook-convert-pdf >/dev/null 2>&1; then
    echo "temporary ebook-convert-pdf command must not be exposed" >&2
    exit 1
fi
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
test ! -e "$CALIBRE_ROOT/calibre/srv"
test -x "$HELPER_ROOT/pdftotext"
test ! -e "$CALIBRE_ROOT/calibre/ebooks/conversion/plugins/standalone_pdf_output.py"
test -s /usr/share/calibre/talebook-debian-package-version
grep -E '^8\.5\.0([+~-]|$)' /usr/share/calibre/talebook-debian-package-version
python3 -c "from calibre.constants import __version__; assert __version__ == '8.5.0', __version__"

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
from io import BytesIO

import _cffi_backend
import calibre
import quickjs
from PIL import Image
from calibre import gui2
from calibre.db.cli.main import main as calibredb_main
from calibre.db.legacy import LibraryDatabase
from calibre.ebooks.conversion.standalone_binary import SUPPORTED_OUTPUT_FORMATS
from calibre.utils.img import (
    gif_data_to_png_data,
    image_and_format_from_data,
    image_to_data,
    png_data_to_gif_data,
    resize_to_fit,
    save_cover_data_to,
    scale_image,
)
from calibre.utils.magick.draw import thumbnail

assert calibre.__file__.startswith("/usr/lib/calibre/")
assert gui2.must_use_qt() is None
assert callable(calibredb_main)
assert callable(quickjs.Context)
assert LibraryDatabase.__name__ == "LibraryDatabase"
assert SUPPORTED_OUTPUT_FORMATS == frozenset({"azw3", "epub", "mobi", "txt"})
assert sys.resources_location == "/usr/share/calibre"
assert sys.extensions_location == "/usr/lib/calibre/calibre/plugins"
assert sys.executables_location == "/usr/lib/talebook-calibre/bin"

source = BytesIO()
Image.new("RGBA", (160, 80), (20, 80, 140, 128)).save(source, "PNG")
source_raw = source.getvalue()

wrapped, source_format = image_and_format_from_data(source_raw)
assert source_format == "png"
assert (wrapped.width(), wrapped.height()) == (160, 80)
jpeg_raw = image_to_data(wrapped, fmt="JPEG", bgcolor="#ffffff")
assert Image.open(BytesIO(jpeg_raw)).format == "JPEG"

resized, resized_image = resize_to_fit(source_raw, 80, 80)
assert resized is True
assert (resized_image.width(), resized_image.height()) == (80, 40)
width, height, scaled_raw = scale_image(source_raw, width=40, height=40)
assert (width, height) == (40, 20)
assert Image.open(BytesIO(scaled_raw)).format == "JPEG"

saved_raw = save_cover_data_to(source_raw, resize_to=(32, 16), data_fmt="png")
saved = Image.open(BytesIO(saved_raw))
saved.load()
assert saved.format == "PNG"
assert saved.size == (32, 16)
gif_raw = png_data_to_gif_data(source_raw)
assert Image.open(BytesIO(gif_raw)).format == "GIF"
roundtrip_png = gif_data_to_png_data(gif_raw)
assert Image.open(BytesIO(roundtrip_png)).format == "PNG"

width, height, raw = thumbnail(source_raw, width=80, height=80)
assert (width, height) == (80, 40)
result = Image.open(BytesIO(raw))
result.load()
assert result.format == "JPEG"
assert result.size == (80, 40)
PY

calibredb --version
rm -rf /tmp/talebook-calibre-lib /tmp/talebook-calibredb-cli-lib /tmp/convert-test.* /tmp/convert-test-*
calibredb add --library-path /tmp/talebook-calibredb-cli-lib "$FIXTURE"
calibredb list --library-path /tmp/talebook-calibredb-cli-lib > /tmp/talebook-calibredb-list.txt
grep -F 'Quick Start Guide' /tmp/talebook-calibredb-list.txt
calibredb set_metadata --library-path /tmp/talebook-calibredb-cli-lib --field title:'Talebook CLI smoke' 1
calibredb show_metadata --library-path /tmp/talebook-calibredb-cli-lib 1 > /tmp/talebook-calibredb-metadata.txt
grep -F 'Talebook CLI smoke' /tmp/talebook-calibredb-metadata.txt
printf '%s\n' 'Talebook calibredb format smoke' > /tmp/talebook-calibredb-format.txt
calibredb add_format --library-path /tmp/talebook-calibredb-cli-lib 1 /tmp/talebook-calibredb-format.txt
calibredb list --library-path /tmp/talebook-calibredb-cli-lib --fields id,title,formats > /tmp/talebook-calibredb-formats.txt
grep -F '.txt' /tmp/talebook-calibredb-formats.txt
calibredb remove_format --library-path /tmp/talebook-calibredb-cli-lib 1 TXT
calibredb list --library-path /tmp/talebook-calibredb-cli-lib --fields id,title,formats > /tmp/talebook-calibredb-formats-after-remove.txt
if grep -F '.txt' /tmp/talebook-calibredb-formats-after-remove.txt; then
    echo "calibredb remove_format left the TXT format in the library" >&2
    exit 1
fi
calibredb saved_searches --library-path /tmp/talebook-calibredb-cli-lib add cli-smoke 'title:"Talebook CLI smoke"'
calibredb saved_searches --library-path /tmp/talebook-calibredb-cli-lib list > /tmp/talebook-calibredb-searches.txt
grep -F 'Name: cli-smoke' /tmp/talebook-calibredb-searches.txt
calibredb saved_searches --library-path /tmp/talebook-calibredb-cli-lib remove cli-smoke
calibredb add_custom_column --library-path /tmp/talebook-calibredb-cli-lib cli_smoke 'CLI Smoke' text
calibredb set_custom --library-path /tmp/talebook-calibredb-cli-lib cli_smoke 1 passed
calibredb show_metadata --library-path /tmp/talebook-calibredb-cli-lib 1 > /tmp/talebook-calibredb-custom.txt
grep -F 'passed' /tmp/talebook-calibredb-custom.txt
calibredb embed_metadata --library-path /tmp/talebook-calibredb-cli-lib 1 > /tmp/talebook-calibredb-embed.txt
grep -F 'Talebook CLI smoke' /tmp/talebook-calibredb-embed.txt
calibredb remove --library-path /tmp/talebook-calibredb-cli-lib 1
calibredb list --library-path /tmp/talebook-calibredb-cli-lib > /tmp/talebook-calibredb-after-remove.txt
if grep -F 'Talebook CLI smoke' /tmp/talebook-calibredb-after-remove.txt; then
    echo "calibredb remove left the book in the library" >&2
    exit 1
fi
python3 - <<'PY'
from calibre.db.legacy import LibraryDatabase

LibraryDatabase("/tmp/talebook-calibre-lib")
PY
calibredb list --library-path /tmp/talebook-calibre-lib
python3 - <<'PY'
import os
from io import BytesIO

from PIL import Image
from calibre.db.legacy import LibraryDatabase
from calibre.ebooks.metadata.book.base import Metadata

db = LibraryDatabase("/tmp/talebook-calibre-lib")
book_id = db.import_book(Metadata("Talebook image smoke", ["Talebook"]), [os.environ["FIXTURE"]])
assert list(db.all_ids()) == [book_id]

source = BytesIO()
Image.new("RGBA", (96, 144), (120, 30, 200, 128)).save(source, "PNG")
source_raw = source.getvalue()

db.set_cover(book_id, source_raw)
cover = db.cover(book_id, index_is_id=True)
saved = Image.open(BytesIO(cover))
saved.load()
assert saved.format == "JPEG"
assert saved.size == (96, 144)

metadata = db.get_metadata(book_id, index_is_id=True)
metadata.cover_data = ("png", source_raw)
db.set_metadata(book_id, metadata)
cover = db.cover(book_id, index_is_id=True)
assert Image.open(BytesIO(cover)).format == "JPEG"
PY

ebook-convert "$FIXTURE" /tmp/convert-test.mobi
ebook-convert "$FIXTURE" /tmp/convert-test.azw3
ebook-convert "$FIXTURE" /tmp/convert-test.pdf \
    --paper-size=a5 \
    --pdf-page-margin-left=15 \
    --pdf-page-margin-top=15 \
    --pdf-page-margin-right=15 \
    --pdf-page-margin-bottom=15
printf '%s\n' 'Talebook standalone PDF 这是中文测试 😀' > /tmp/convert-test-cjk.txt
ebook-convert /tmp/convert-test-cjk.txt /tmp/convert-test-cjk.pdf
"$HELPER_ROOT/pdftotext" /tmp/convert-test-cjk.pdf /tmp/convert-test-cjk-extracted.txt
grep -F '这是中文测试' /tmp/convert-test-cjk-extracted.txt

test -s /tmp/convert-test.mobi
test -s /tmp/convert-test.azw3
test -s /tmp/convert-test.pdf
test -s /tmp/convert-test-cjk.pdf
ls -lh \
    /tmp/convert-test.mobi \
    /tmp/convert-test.azw3 \
    /tmp/convert-test.pdf \
    /tmp/convert-test-cjk.pdf
