# Standalone ebook-convert-pdf

`ebook-convert-pdf` is a separate PDF-focused standalone tool. It keeps the
small no-Qt `ebook-convert` package lightweight, while providing a heavier
WeasyPrint based PDF output path.

## Design

The tool does not reimplement ebook input parsing. It uses calibre's conversion
pipeline to normalize supported inputs into an OEB directory, then renders that
OEB with WeasyPrint.

Pipeline:

1. `ebook-convert-pdf INPUT OUTPUT.pdf`
2. calibre input plugin converts `INPUT` to a temporary OEB directory.
3. `weasy_pdf_binary.py` reads the generated OPF manifest and spine.
4. Spine XHTML files are combined into one HTML document.
5. Resource links are rewritten relative to the OEB root.
6. WeasyPrint renders the combined HTML to `OUTPUT.pdf`.

Supported input formats match the standalone converter input surface:

```text
azw, azw3, docx, epub, mobi, original_epub, pdf, prc, txt, zip
```

The only output format is `pdf`.

Unsupported formats are rejected intentionally, including `doc`, `ebk3`, `png`
and `wps`.

## Packaging

Builder:

```bash
setup/build_standalone_ebook_convert_pdf_linux_local.py
```

The Linux package includes:

- the trimmed Python runtime
- trimmed calibre input pipeline and OEB output plugin
- WeasyPrint 62.3 from Debian 13
- CFFI/Pyphen/Pydyf/TinyCSS2/CSSSelect2/Ply dependencies
- Pango/Cairo/Fontconfig/FreeType/HarfBuzz/GDK-Pixbuf native libraries
- Poppler helper binaries: `pdftohtml`, `pdfinfo`, `pdftoppm`, `pdftotext`
- WQY Microhei CJK font copied as `resources/fonts/standalone-cjk.ttc`
- packaged hyphen dictionaries for `pyphen`

The launcher sets:

- `PYTHONHOME`
- `PYTHONPATH`
- `LD_LIBRARY_PATH`
- `FONTCONFIG_PATH`
- `FONTCONFIG_FILE`
- `PATH` with package `bin` first, so PDF input can find bundled `pdftohtml`

## Build Result

Local build image:

```text
talebook/ebook-convert-pdf-build:weasy
```

Output:

```text
/private/tmp/calibre-weasy-build-output/calibre-ebook-convert-pdf-weasy-linux-arm64.tgz
dist/calibre-ebook-convert-pdf-weasy-linux-arm64.tgz
```

Size and hash:

```text
archive size: 75.44 MB
sha256: 2f914d09dfde7415ace67d7f56a05547e28323e2f8da6557faf111035755207b
```

Uncompressed package size:

```text
217 MB
```

## Validation

Clean Debian smoke:

```text
input txt -> pdf: ok
pdftotext contains Chinese text: ok
```

Sample matrix on `samples/ca-format-samples`:

```text
PDF sample matrix: 23/23 ok
```

Notable rows:

- `azw/azw3/docx/epub/mobi/original_epub/pdf/prc/txt/zip -> pdf`: success
- `doc/ebk3/png/wps -> pdf`: rejected as unsupported
- `MOBI/54...mobi -> pdf`: success, but very slow; output has 6939 pages
- `PDF/183...pdf -> pdf`: success, 254 pages, 99,268 CJK chars
- `PDF/187...pdf -> pdf`: success, 250 pages, 88,851 CJK chars

Talebook reference comparison against `/usr/bin/ebook-convert`:

```text
Reference comparison: ok=15, same_fail=5
```

Command excluded the known pathological `MOBI/54-*` sample because the full
reference comparison stayed stuck on that case for more than 30 minutes. The
sample matrix verified that `ebook-convert-pdf` itself can convert that sample.

Manual PDF input comparison:

- talebook original `ebook-convert PDF -> PDF` fails for both PDF samples with
  `lxml.etree.XMLSyntaxError: Input is not proper UTF-8`.
- `ebook-convert-pdf` succeeds for both because standalone PDF input defaults
  to the bundled `pdftohtml` path.

## Known Limits

- This is not a QtWebEngine pixel-parity renderer. It uses WeasyPrint's HTML/CSS
  paged-media engine.
- Large books can be slow, especially large MOBI/PRC inputs.
- Some extracted-text similarity scores are low even when length/CJK counts
  match, because WeasyPrint and QtWebEngine can emit PDF text in different
  internal order.
- For scanned/image-page sources, text extraction can be empty while the PDF is
  still valid.
