#!/bin/sh
set -eu

OUTPUT="${1:-/opt/talebook-system-root}"
REFERENCE_ROOT="${2:-}"
STAGING="/tmp/talebook-calibre-build"

rm -rf "$OUTPUT" "$STAGING"

python3 setup/build_standalone_ebook_convert_combined_linux_local.py \
    --output "$STAGING" \
    --no-archive

mkdir -p \
    "$OUTPUT/usr/lib/calibre" \
    "$OUTPUT/usr/lib/talebook-calibre/lib" \
    "$OUTPUT/usr/lib/talebook-calibre/bin" \
    "$OUTPUT/usr/share/calibre" \
    "$OUTPUT/etc/talebook-calibre/fonts"

cp -a "$STAGING/lib/python/site-packages/." "$OUTPUT/usr/lib/calibre/"
cp -a "$STAGING/resources/." "$OUTPUT/usr/share/calibre/"

for helper in pdftohtml pdfinfo pdftoppm pdftotext; do
    cp -a "$STAGING/bin/$helper" "$OUTPUT/usr/lib/talebook-calibre/bin/$helper"
done

for library in "$STAGING"/lib/*.so*; do
    test -e "$library" || continue
    cp -a "$library" "$OUTPUT/usr/lib/talebook-calibre/lib/"
done

pruned=0
if test -n "$REFERENCE_ROOT" && test -d "$REFERENCE_ROOT"; then
    for library in "$OUTPUT"/usr/lib/talebook-calibre/lib/*.so*; do
        test -f "$library" || continue
        test ! -L "$library" || continue
        match="$(
            find "$REFERENCE_ROOT" -type f -name "$(basename "$library")" \
                -exec cmp -s "$library" {} \; -print -quit
        )"
        test -n "$match" || continue

        canonical="$(readlink -f "$library")"
        for candidate in "$OUTPUT"/usr/lib/talebook-calibre/lib/*.so*; do
            test -L "$candidate" || continue
            if test "$(readlink -f "$candidate")" = "$canonical"; then
                rm -f "$candidate"
            fi
        done
        rm -f "$library"
        pruned=$((pruned + 1))
    done
fi
echo "Pruned exact system library copies: $pruned"

if test -d "$STAGING/etc/fonts"; then
    cp -a "$STAGING/etc/fonts/." "$OUTPUT/etc/talebook-calibre/fonts/"
    sed -i \
        's#<dir prefix="relative">../../resources/fonts</dir>#<dir>/usr/share/calibre/fonts</dir>#' \
        "$OUTPUT/etc/talebook-calibre/fonts/fonts.conf"
fi

test ! -e "$OUTPUT/usr/lib/talebook-calibre-runtime"
test ! -e "$OUTPUT/usr/bin/python3"
test -f "$OUTPUT/usr/lib/calibre/calibre/__init__.py"
test -x "$OUTPUT/usr/lib/talebook-calibre/bin/pdftotext"

if find "$OUTPUT" \( -name 'PyQt6' -o -name 'qt' -o -name 'libQt*' -o -name 'Qt*' \) -print -quit | grep -q .; then
    echo "system runtime contains Qt artifacts" >&2
    exit 1
fi

du -sh "$OUTPUT"
rm -rf "$STAGING"
