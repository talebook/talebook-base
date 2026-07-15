#!/bin/sh
set -eu

OUTPUT="${1:-/usr/lib/talebook-calibre-runtime}"

command -v python3 >/dev/null
test -d /usr/lib/calibre
test -d /usr/share/calibre

python3 setup/build_standalone_ebook_convert_combined_linux_local.py \
    --output "$OUTPUT" \
    --no-archive
