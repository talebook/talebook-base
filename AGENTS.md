# Project Guide

## Repository scope

This repository is based on calibre and the active work is on the
`slim-v8.5.0` branch. The branch builds a no-Qt Calibre runtime for
Talebook instead of a full desktop calibre distribution.

The compatibility baseline is the highest Calibre package available from the
target Debian repository, not the newest release or `master` commit in the
official Calibre repository. For `debian:13-slim`, the verified candidate on
2026-07-16 is `8.5.0+ds-1+deb13u3`; source/API adaptations therefore target
Calibre `v8.5.0`. Open a separate `slim-vX.Y.Z` branch only after the target
Debian repository provides that higher Calibre version.

The current delivery target is a slim `talebook/talebook-base` Linux image based
on `debian:13-slim`. It uses Debian's system Python and two public Calibre commands:

- `ebook-convert`: the compatibility entry point; PDF output is routed to the
  WeasyPrint renderer and other supported output formats use the lightweight
  standalone converter.
- `calibredb`: direct access to the retained Calibre database CLI.

The standalone input surface is `azw`, `azw3`, `docx`, `epub`, `mobi`,
`original_epub`, `pdf`, `prc`, `txt`, and `zip`. The lightweight converter
currently exposes `azw3`, `epub`, `mobi`, and `txt` outputs. Public PDF output is
not a lightweight Calibre plugin: the `ebook-convert` router sends `.pdf`
outputs to the internal `weasy_pdf.py` backend. Unsupported formats are rejected intentionally
to keep Qt, GUI, device, server, and scraper dependencies out of the runtime.

## Important paths

- `Dockerfile.base`: multi-stage slim base-image build.
- `Makefile`: local `build-base`, `test`, and `push-base` entry points.
- `packaging/`: Debian package extraction, system-runtime assembly, public
  launchers, CLI routing, and image-level smoke tests.
- `setup/build_standalone_ebook_convert_*`: developer standalone builders.
- `setup/standalone_ebook_convert_*`: smoke, sample-matrix, and reference
  comparison tools.
- `src/calibre/ebooks/conversion/standalone_binary.py`: lightweight CLI entry.
- `src/calibre/ebooks/conversion/weasy_pdf.py`: internal WeasyPrint PDF backend.
- `src/calibre/customize/standalone_builtins.py`: allowed standalone plugins.
- `docs/standalone-ebook-convert.md`: design, validation history, and known
  limitations for the unified public converter.

## Validation workflow

Use the smallest relevant check first, then validate the image:

```sh
python3 setup/standalone_ebook_convert_smoke.py --self-test
git diff --check
make test
```

`make test` builds `Dockerfile.base` and runs `packaging/smoke-test.sh` in the
resulting image. The image smoke must verify both public Calibre commands, the
absence of the temporary `ebook-convert-pdf` command and PyQt/Qt, Calibre database creation/listing, and EPUB conversion to
MOBI, AZW3, and PDF, including CJK PDF text extraction. It must also import the
prebuilt QuickJS module, reject missing/Qt-linked native dependencies, prove
that no compiler toolchain remains, and keep `/usr` at or below 400 MiB. Image
coverage must include the public `calibre.utils.magick.draw.thumbnail` API,
PNG/JPEG/GIF Pillow-shim operations, and database cover writes through both
`LibraryDatabase.set_cover` and `set_metadata`.

When changing supported formats, update the standalone sample matrix. When
changing PDF routing or rendering, update `packaging/smoke-test.sh`, the unified
standalone design document, and the active architecture note in `design/`.

## Runtime constraints

- Do not add PyQt, Qt, QtWebEngine, GUI applications, device drivers, content
  server code, or unrelated calibre commands to the final runtime.
- Keep the final image on Debian's `/usr/bin/python3`; do not add a private
  interpreter, `PYTHONHOME`, or `/usr/lib/talebook-calibre-runtime`.
- Keep selected Python modules in `/usr/lib/calibre`, resources in
  `/usr/share/calibre`, native libraries in `/usr/lib/talebook-calibre/lib`, and
  Poppler helpers in `/usr/lib/talebook-calibre/bin`.
- Build QuickJS in the `python-wheel-build` stage and install the wheel into the
  final system Python. Do not install `build-essential`, `python3-dev`,
  `python3-venv`, or `gcc` in the published image.
- Prune native libraries from the Calibre closure only when an exact byte copy
  exists in the final Debian system layer; the final `ldd` scan is the safety
  net for this de-duplication.
- The package pool stage may use `apt-get --download-only`, but must not install
  Calibre or Qt. `packaging/extract-debian-packages.sh` extracts `.deb` files and
  rejects Qt/PyQt packages before the allowlist/ELF-closure build runs.
- Keep `CALIBRE_UPSTREAM_VERSION` aligned with the `slim-vX.Y.Z` branch name.
  Debian packaging/security revisions may advance, but a different upstream
  Calibre version must fail the build and be handled on a new branch.
- The Debian local builder patches the packaged Debian calibre tree; do not
  assume every current-source file can replace its Debian counterpart without
  API compatibility checks.
- Preserve CJK font embedding, non-BMP Unicode extraction, PDF input through
  bundled Poppler helpers, and public PDF output through WeasyPrint.
- Preserve Talebook's historical `calibre.utils.magick.draw.thumbnail` call.
  In standalone mode it must route to Pillow without constructing `QImage`;
  full Calibre mode must retain the original Qt implementation.

## Git and artifact hygiene

- Do not merge, rebase, or pull `origin/master` unless the user explicitly asks
  for it. Current test/CI work must stay on `slim-v8.5.0`.
- Select future Calibre baselines from the target Debian package candidate;
  upstream Calibre tags and `master` are only source references, not the
  version-selection authority.
- The worktree may contain user-owned staged, unstaged, and untracked work.
  Preserve unrelated changes and do not use destructive Git commands.
- `samples/` contains a large local validation corpus. Do not add the corpus or
  generated archives to Git unless explicitly requested.
- Build products belong under ignored `build/`, `dist/`, `.build/`, or temporary
  directories, not in source commits.

## CI expectations

The base-image workflow should validate the Docker build and smoke test before
publishing. Publishing must be limited to explicit release events or manual
dispatch, use the repository's configured registry credentials, and build the
requested target architectures without silently weakening the local smoke
coverage.

The arm64 reference built on 2026-07-16 is 356,153,818 bytes (about 340 MiB),
with `/usr` using 346 MiB. CI explicitly passes the 400 MiB `/usr` budget to the
smoke test. Treat this as a regression limit, not a target to consume or relax
without a measured explanation.
