#!/usr/bin/env python3
"""Route the classic ebook-convert CLI to the standalone conversion binaries."""

from __future__ import annotations

import os
import sys

from talebook_calibre_env import RUNTIME_ROOT


EBOOK_CONVERT = os.path.join(RUNTIME_ROOT, "ebook-convert")
EBOOK_CONVERT_PDF = os.path.join(RUNTIME_ROOT, "ebook-convert-pdf")

PDF_DROP_OPTIONS = {
    "--no-chapters-in-toc",
}
PDF_DROP_VALUE_OPTIONS = {
    "--base-font-size",
    "--filter-css",
    "--pdf-sans-family",
    "--pdf-serif-family",
}
PDF_MARGIN_OPTIONS = {
    "--pdf-page-margin-left",
    "--pdf-page-margin-top",
    "--pdf-page-margin-right",
    "--pdf-page-margin-bottom",
}


def split_option(arg: str) -> tuple[str, str | None, bool]:
    if "=" in arg:
        name, value = arg.split("=", 1)
        return name, value, True
    return arg, None, False


def output_path(argv: list[str]) -> str:
    positional = [arg for arg in argv if arg == "-" or not arg.startswith("-")]
    return positional[1] if len(positional) > 1 else ""


def translate_pdf_args(argv: list[str]) -> list[str]:
    input_path, target_output_path = argv[0], argv[1]
    rest = argv[2:]
    page_size = "A4"
    margin = None
    passthrough = []
    i = 0
    while i < len(rest):
        arg = rest[i]
        name, value, inline = split_option(arg)
        if name == "--paper-size":
            if value is None and i + 1 < len(rest):
                value = rest[i + 1]
                i += 1
            if value:
                page_size = value.upper()
        elif name in PDF_MARGIN_OPTIONS:
            if value is None and i + 1 < len(rest):
                value = rest[i + 1]
                i += 1
            if value and margin is None:
                margin = value if any(ch.isalpha() for ch in value) else f"{value}pt"
        elif name in PDF_DROP_OPTIONS:
            pass
        elif name in PDF_DROP_VALUE_OPTIONS:
            if not inline and i + 1 < len(rest):
                i += 1
        else:
            passthrough.append(arg)
        i += 1
    args = [input_path, target_output_path, "--weasy-page-size", page_size]
    if margin:
        args += ["--weasy-margin", margin]
    if passthrough:
        args += ["--", *passthrough]
    return args


def main(argv: list[str]) -> None:
    if output_path(argv).lower().endswith(".pdf") and len(argv) >= 2:
        target = EBOOK_CONVERT_PDF
        args = translate_pdf_args(argv)
    else:
        target = EBOOK_CONVERT
        args = argv
    os.execv(target, [target, *args])


if __name__ == "__main__":
    main(sys.argv[1:])
