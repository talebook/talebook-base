#!/bin/sh
set -eu

ARCHIVE_DIR="${1:-/var/cache/apt/archives}"
OUTPUT="${2:-/opt/debian-root}"

rm -rf "$OUTPUT"
mkdir -p "$OUTPUT"

found=0
for archive in "$ARCHIVE_DIR"/*.deb; do
    test -f "$archive" || continue
    found=1
    package="$(dpkg-deb -f "$archive" Package)"
    case "$package" in
        libqt5*|libqt6*|pyqt5*|pyqt6*|python3-pyqt5*|python3-pyqt6*|qt5-*|qt6-*|qtwayland5|qtwayland6)
            echo "Skipping Qt package: $package"
            continue
            ;;
    esac
    dpkg-deb -x "$archive" "$OUTPUT"
done

test "$found" = 1
test -d "$OUTPUT/usr/lib/calibre"
test -d "$OUTPUT/usr/share/calibre"
test -x "$OUTPUT/usr/bin/python3"
test -x "$OUTPUT/usr/bin/pdftotext"
