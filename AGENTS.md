# Project Guide

## Repository scope

This repository is based on calibre and the active work is on the
`only-ebook-convert` branch. The branch builds a no-Qt Calibre runtime for
Talebook instead of a full desktop calibre distribution.

The current delivery target is a slim `talebook/talebook-base` Linux image based
on `debian:13-slim`. It uses Debian's system Python and three public commands:

- `ebook-convert`: the compatibility entry point; PDF output is routed to the
  WeasyPrint renderer and other supported output formats use the lightweight
  standalone converter.
- `ebook-convert-pdf`: the WeasyPrint-based PDF converter.
- `calibredb`: direct access to the retained Calibre database CLI.

The standalone input surface is `azw`, `azw3`, `docx`, `epub`, `mobi`,
`original_epub`, `pdf`, `prc`, `txt`, and `zip`. The lightweight converter
currently exposes `azw3`, `epub`, `mobi`, and `txt` outputs. Public PDF output is
not a lightweight Calibre plugin: the `ebook-convert` router sends `.pdf`
outputs to `weasy_pdf_binary.py`. Unsupported formats are rejected intentionally
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
- `src/calibre/ebooks/conversion/weasy_pdf_binary.py`: WeasyPrint PDF entry.
- `src/calibre/customize/standalone_builtins.py`: allowed standalone plugins.
- `docs/standalone-ebook-convert*.md`: design, validation history, and known
  limitations.

## Validation workflow

Use the smallest relevant check first, then validate the image:

```sh
python3 setup/standalone_ebook_convert_smoke.py --self-test
git diff --check
make test
```

`make test` builds `Dockerfile.base` and runs `packaging/smoke-test.sh` in the
resulting image. The image smoke must verify all three public commands, the
absence of PyQt/Qt, Calibre database creation/listing, and EPUB conversion to
MOBI, AZW3, and PDF, including CJK PDF text extraction.

When changing supported formats or PDF behavior, update the corresponding
sample matrix and both standalone design documents. The PDF sample matrix also
contains a synthetic image-only EPUB regression case.

## Runtime constraints

- Do not add PyQt, Qt, QtWebEngine, GUI applications, device drivers, content
  server code, or unrelated calibre commands to the final runtime.
- Keep the final image on Debian's `/usr/bin/python3`; do not add a private
  interpreter, `PYTHONHOME`, or `/usr/lib/talebook-calibre-runtime`.
- Keep selected Python modules in `/usr/lib/calibre`, resources in
  `/usr/share/calibre`, native libraries in `/usr/lib/talebook-calibre/lib`, and
  Poppler helpers in `/usr/lib/talebook-calibre/bin`.
- The package pool stage may use `apt-get --download-only`, but must not install
  Calibre or Qt. `packaging/extract-debian-packages.sh` extracts `.deb` files and
  rejects Qt/PyQt packages before the allowlist/ELF-closure build runs.
- The Debian local builder patches the packaged Debian calibre tree; do not
  assume every current-source file can replace its Debian counterpart without
  API compatibility checks.
- Preserve CJK font embedding, non-BMP Unicode extraction, PDF input through
  bundled Poppler helpers, and public PDF output through WeasyPrint.

## Git and artifact hygiene

- Do not merge, rebase, or pull `origin/master` unless the user explicitly asks
  for it. Current test/CI work must stay on `only-ebook-convert`.
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
