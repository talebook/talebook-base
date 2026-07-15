#!/bin/sh
set -eu

RUNTIME="${TALEBOOK_CALIBRE_PRIVATE_RUNTIME:-/usr/lib/talebook-calibre-runtime}"
SITE_PACKAGES="$RUNTIME/lib/python/site-packages"
PY_VER="$(python3 - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"

test -d "$SITE_PACKAGES"
test -d "$RUNTIME/resources"

ln -sfn "$SITE_PACKAGES" /usr/lib/calibre
ln -sfn "$RUNTIME/resources" /usr/share/calibre

for root in /usr/lib/python3/dist-packages /usr/local/lib/python"$PY_VER"/dist-packages /usr/local/lib/python"$PY_VER"/site-packages; do
    test -d "$root" || continue
    cp -a "$root"/apsw* "$SITE_PACKAGES"/ 2>/dev/null || true
    cp -a "$root"/xxhash* "$SITE_PACKAGES"/ 2>/dev/null || true
done

python3 - <<'PY'
import apsw
import xxhash

assert apsw
assert xxhash
PY

chmod 0755 /usr/bin/ebook-convert /usr/bin/ebook-convert-pdf /usr/bin/calibredb

if find "$RUNTIME" \( ! -user root -o ! -group root \) -print -quit | grep -q .; then
    echo "runtime contains non-root-owned files" >&2
    exit 1
fi
